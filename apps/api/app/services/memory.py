"""
四层记忆系统 — 电商售后分析 Copilot（SQLite 持久化）

┌─ ① system prompt：Agent 角色定义
├─ ② 业务指令：分析规范 + 输出格式要求（从 Markdown 文件加载）
├─ ③ 长期记忆 (memory)：用户画像 — 动态提取关注类目/指标/偏好
├─ ④ 最近对话 (conversation)：recent_turns 滑动窗口历史轮次
└─ ⑤ 摘要记忆：LLM 压缩长对话为结构化摘要

持久化策略：
  sessions 表 — session_id, user_profile(JSON), summary, updated_at
  messages 表 — id, session_id, role, content, created_at
  SessionMemory 作为内存缓存层，加载时从 DB 恢复，更新时同步写 DB。

企业实践对标：
  SQLite → 单用户嵌入式场景的标准选择（Chrome/WhatsApp/Slack 客户端同理）
  生产扩展 → 换 PostgreSQL 只需改 _get_conn() 和 SQL 方言适配器
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import httpx

from app.core.config import settings

# ── 数据库层 ──────────────────────────────────────────────────────────

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        data_dir = settings.resolve_api_path("../../data")
        data_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = data_dir / "memory.db"
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_tables() -> None:
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                user_profile TEXT NOT NULL DEFAULT '{}',
                summary      TEXT NOT NULL DEFAULT '',
                updated_at   TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT NOT NULL,
                role         TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content      TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, created_at);
        """)
        conn.commit()
    finally:
        conn.close()


# ── 数据结构 ──────────────────────────────────────────────────────────


@dataclass
class SessionMemory:
    """单会话的四层记忆状态（内存缓存 + DB 持久化）。"""

    recent_turns: list[dict[str, str]] = field(default_factory=list)
    conversation_summary: str = ""
    user_profile: dict[str, str] = field(default_factory=dict)

    _dirty_summary: bool = field(default=False, repr=False)
    _dirty_profile: bool = field(default=False, repr=False)
    _session_id: str = field(default="", repr=False)


class PromptContext(TypedDict):
    system_prompt: str
    business_instructions: str
    user_profile_text: str
    summary_text: str
    recent_turns: list[dict[str, str]]


# ── 内存缓存层（避免每次请求都查 DB）──────────────────────────────────

_mem_cache: dict[str, SessionMemory] = {}


def _load_from_db(session_id: str) -> SessionMemory | None:
    """从 DB 恢复会话记忆。"""
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT user_profile, summary FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row is None:
            return None

        mem = SessionMemory(
            user_profile=json.loads(row["user_profile"]),
            conversation_summary=row["summary"],
            _session_id=session_id,
        )

        # 恢复最近 10 条消息
        msg_rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE session_id = ? ORDER BY created_at DESC LIMIT 20",
            (session_id,),
        ).fetchall()

        # 按 user/assistant 成对重建 recent_turns
        turns: list[dict[str, str]] = []
        pending_user: str | None = None
        for msg in reversed(msg_rows):
            if msg["role"] == "user":
                pending_user = msg["content"]
            elif msg["role"] == "assistant" and pending_user is not None:
                turns.append({"user": pending_user, "assistant": msg["content"]})
                pending_user = None
        if turns:
            mem.recent_turns = turns[-10:]

        return mem
    finally:
        conn.close()


def _save_to_db(memory: SessionMemory) -> None:
    """将内存状态持久化到 DB。"""
    if not memory._session_id:
        return
    memory.user_profile = _stringify_profile(memory.user_profile)
    _ensure_tables()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sessions (session_id, user_profile, summary, updated_at)
               VALUES (?, ?, ?, ?)""",
            (
                memory._session_id,
                json.dumps(memory.user_profile, ensure_ascii=False),
                memory.conversation_summary,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        # 只存最近 20 条消息（user+assistant 各一条 = 最近 10 轮）
        conn.execute("DELETE FROM messages WHERE session_id = ?", (memory._session_id,))
        for turn in memory.recent_turns:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (memory._session_id, "user", turn["user"], now),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (memory._session_id, "assistant", turn["assistant"], now),
            )

        conn.commit()
    finally:
        conn.close()


# ── ① system prompt ──────────────────────────────────────────────────


def get_system_prompt() -> str:
    return (
        "你是一个电商售后数据分析助手。你的职责是：\n"
        "1. 理解用户的自然语言问题，判断需要查数据库、查知识库还是两者都查。\n"
        "2. 生成安全的只读 SQL 查询结构化数据。\n"
        "3. 检索业务政策、SOP、指标口径等非结构化文档。\n"
        "4. 融合数据结果和文档证据，给出有依据的分析结论。"
    )


# ── ② 业务指令 ────────────────────────────────────────────────────────


def get_business_instructions() -> str:
    guidelines_path = _resolve_documents_dir() / "analysis_guidelines.md"
    guidelines_text = (
        guidelines_path.read_text(encoding="utf-8")
        if guidelines_path.exists()
        else ""
    )
    return (
        "回答要求：\n"
        "- 数据结论需要有具体的数字和来源（SQL 语句）。\n"
        "- 引用政策或规则时需要标明出自哪个文档。\n"
        "- 如果信息不足无法给出确切结论，主动追问而不是猜测。\n"
        "- 对混合分析问题，按「数据结果 → 文档依据 → 综合分析 → 建议动作」的结构输出。\n"
        "\n" + guidelines_text
    )


def get_instruction() -> str:
    return get_system_prompt() + "\n\n" + get_business_instructions()


# ── ② 会话记忆：滑动窗口 + DB 持久化 ─────────────────────────────────


def get_memory(session_id: str) -> SessionMemory:
    """
    获取会话记忆。先查内存缓存，未命中则从 DB 加载。
    首次访问的 session 创建默认记忆并写入 DB。
    """
    if session_id in _mem_cache:
        return _mem_cache[session_id]

    mem = _load_from_db(session_id)

    if mem is None:
        # 全新会话：创建默认记忆
        mem = SessionMemory(
            user_profile={
                "role": "after_sales_operator",
                "focus": "退换货分析和客诉归因",
                "preferred_categories": "",
                "preferred_metrics": "",
                "interaction_count": "0",
            },
            _session_id=session_id,
        )
        _save_to_db(mem)

    _mem_cache[session_id] = mem
    return mem


def _stringify_profile(profile: dict[str, object]) -> dict[str, str]:
    return {str(key): "" if value is None else str(value) for key, value in profile.items()}


_FOLLOWUP_ACTION_TERMS = [
    "那", "呢", "这个", "这些", "上面", "前面", "刚才", "继续", "接着", "往下",
    "按这个", "照这个", "就查", "查一下", "补一下", "补充", "第一个", "第二个",
    "第三个", "第四个", "1", "2", "3", "4",
]


def _is_followup_action(message: str) -> bool:
    normalized = message.strip()
    if len(normalized) <= 12 and any(term in normalized for term in ["查", "继续", "接着", "补", "按"]):
        return True
    return any(term in normalized for term in _FOLLOWUP_ACTION_TERMS)


def _extract_context_text(previous: dict[str, str]) -> str:
    return f"{previous.get('user', '')}\n{previous.get('assistant', '')}"


def _infer_month(text: str) -> str:
    match = re.search(r"(20\d{2})[-年/ ]?(0?[1-9]|1[0-2])月?", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"([1-9]|1[0-2])月", text)
    if match:
        return f"2026-{int(match.group(1)):02d}"
    return "2026-04"


def _infer_category(text: str) -> str:
    category_map = {
        "服装": "服装",
        "衣服": "服装",
        "鞋靴": "鞋靴",
        "鞋": "鞋靴",
        "数码": "数码",
        "耳机": "数码",
        "手表": "数码",
    }
    return next((cat for kw, cat in category_map.items() if kw in text), "服装")


def _infer_metric(text: str) -> str:
    if any(keyword in text for keyword in ["退款率", "整体退款率", "预警线", "环比"]):
        return "refund_rate"
    if any(keyword in text for keyword in ["工单", "原因", "原因分布", "尺码", "色差", "面料"]):
        return "ticket_reason"
    if any(keyword in text for keyword in ["最高", "top", "排行", "排名", "SKU", "sku", "商品", "款式"]):
        return "top_refund_products"
    return ""


def _extract_suggested_items(answer: str) -> list[str]:
    lines = [line.strip(" -\t") for line in answer.splitlines()]
    items: list[str] = []
    capture = False
    section_keywords = ["下一步", "缺少", "缺失", "需补充", "补充查询", "建议查询", "关键数据"]

    for line in lines:
        if not line:
            continue
        if any(keyword in line for keyword in section_keywords):
            capture = True
            cleaned = re.sub(r"^[\d一二三四五六七八九十]+[、.．)]\s*", "", line).strip()
            if cleaned and not any(keyword in cleaned for keyword in section_keywords):
                items.append(cleaned)
            continue
        if capture:
            if re.match(r"^(数据异常判断|可能原因|文档依据|综合分析|DB|SQL|文档引用)", line):
                capture = False
                continue
            cleaned = re.sub(r"^[\d一二三四五六七八九十]+[、.．)]\s*", "", line).strip()
            if cleaned:
                items.append(cleaned)

    return list(dict.fromkeys(items))[:8]


def _select_suggested_item(message: str, items: list[str]) -> str | None:
    if not items:
        return None

    ordinal_map = {
        "第一个": 0, "第一": 0, "1": 0, "一": 0,
        "第二个": 1, "第二": 1, "2": 1, "二": 1,
        "第三个": 2, "第三": 2, "3": 2, "三": 2,
        "第四个": 3, "第四": 3, "4": 3, "四": 3,
    }
    for key, index in ordinal_map.items():
        if key in message and index < len(items):
            return items[index]

    target_keywords = [
        ("sku", ["sku", "SKU", "商品", "款式", "同款"]),
        ("原因", ["原因", "分布", "尺码", "色差", "面料", "工单"]),
        ("退款率", ["退款率", "整体", "环比", "上月", "3月", "4月", "预警线"]),
        ("渠道", ["渠道", "活动", "促销", "直播", "清仓"]),
        ("物流", ["物流", "配送", "签收"]),
        ("批次", ["批次", "品控", "质量"]),
    ]
    for _, keywords in target_keywords:
        if any(keyword in message for keyword in keywords):
            matched = next((item for item in items if any(keyword in item for keyword in keywords)), None)
            if matched:
                return matched

    return items[0]


def _build_explicit_followup_query(message: str, previous: dict[str, str]) -> str | None:
    context = _extract_context_text(previous)
    items = _extract_suggested_items(previous.get("assistant", ""))
    selected = _select_suggested_item(message, items)
    month = _infer_month(message + "\n" + context)
    category = _infer_category(message + "\n" + context)

    if selected:
        return (
            f"用户在上一轮分析后要求继续补充查询。"
            f"上一轮问题：{previous.get('user', '')}。"
            f"本轮追问：{message}。"
            f"请把本轮问题具体化为：{selected}。"
            f"如果需要默认条件，使用月份 {month}，类目 {category}。"
        )

    if any(keyword in message for keyword in ["原因", "分布", "工单", "尺码", "色差", "面料"]):
        return f"查询 {month} {category}类目客服工单/退款原因分布，重点关注尺码、色差、面料等原因。"
    if any(keyword in message for keyword in ["sku", "SKU", "商品", "款式", "同款"]):
        return f"查询 {month} {category}类目退款次数最高的商品或 SKU，并返回退款次数和退款金额。"
    if any(keyword in message for keyword in ["退款率", "整体", "环比", "上月", "预警"]):
        return f"查询 {month} {category}类目整体退款率，并用于判断是否超过预警线。"
    if any(keyword in message for keyword in ["渠道", "活动", "促销", "直播", "清仓"]):
        return f"查询 {month} {category}类目按活动渠道或销售渠道拆分的退款情况。"

    return None


def resolve_followup(message: str, memory: SessionMemory) -> str:
    if not memory.recent_turns or not _is_followup_action(message):
        return message

    previous = memory.recent_turns[-1]
    explicit_query = _build_explicit_followup_query(message, previous)
    if explicit_query:
        return explicit_query

    category_map = {"服装": "服装", "衣服": "服装", "鞋": "鞋靴", "鞋靴": "鞋靴", "数码": "数码", "耳机": "数码"}
    matched = next((cat for kw, cat in category_map.items() if kw in message), None)

    if matched:
        context = _extract_context_text(previous)
        month = _infer_month(message + "\n" + context)
        metric = _infer_metric(message + "\n" + previous.get("user", ""))
        if metric == "refund_rate":
            return f"查询 {month} {matched}类目整体退款率，并返回订单数、退款数和退款率。"
        if metric == "ticket_reason":
            return f"查询 {month} {matched}类目客服工单/退款原因分布。"
        if metric == "top_refund_products":
            return f"查询 {month} {matched}类目退款次数最高的商品或 SKU，并返回退款次数和退款金额。"
        return f"查询 {month} {matched}类目的同一指标。上一轮问题是：{previous['user']}"
    return (
        f"上一轮问题：{previous['user']}，回答：{previous['assistant'][:500]}。"
        f"现在用户追问：{message}"
    )


# ── ③ 摘要记忆：LLM 压缩 ──────────────────────────────────────────────


_SUMMARY_PROMPT = """你是一个对话摘要生成器。根据以下对话历史，生成一个结构化摘要。

要求：
- 不超过 150 字
- 包含：用户最关心的类目、指标、时间段
- 列出已得出的关键数据结论（如退款率数值、TOP 原因）
- 标注尚未解决的用户追问（如果有）

对话历史：
{history}

结构化摘要："""


def _maybe_summarize(memory: SessionMemory) -> None:
    if len(memory.recent_turns) < 6 or not memory._dirty_summary:
        return

    if not settings.siliconflow_api_key:
        memory.conversation_summary = "；".join(
            turn["user"] for turn in memory.recent_turns[-4:]
        )
        memory._dirty_summary = False
        return

    history_lines = [
        f"用户：{t['user']}\n助手：{t['assistant'][:200]}"
        for t in memory.recent_turns
    ]
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": _SUMMARY_PROMPT.format(history="\n".join(history_lines))}],
        "temperature": 0.3,
        "max_tokens": 250,
    }
    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.siliconflow_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=20.0,
            )
            resp.raise_for_status()
            memory.conversation_summary = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        memory.conversation_summary = "；".join(turn["user"] for turn in memory.recent_turns[-4:])
    memory._dirty_summary = False


# ── ④ 用户档案：动态提取 ──────────────────────────────────────────────


_PROFILE_PROMPT = """你是一个用户画像分析器。根据以下对话历史，提取用户的分析偏好。

请严格按 JSON 格式输出（不要其他内容）：
{{"preferred_categories": "最常关注的类目（如服装、鞋靴）",
 "preferred_metrics": "最常查询的指标（如退款率、工单数）",
 "interaction_count": "累计对话轮数",
 "analysis_style": "偏好分析风格（简洁数据/详细报告/原因深挖）"}}

对话历史：
{history}
"""  # noqa: E501


def _maybe_update_profile(memory: SessionMemory) -> None:
    if len(memory.recent_turns) < 3 or not memory._dirty_profile:
        return

    if not settings.siliconflow_api_key:
        memory.user_profile["interaction_count"] = str(len(memory.recent_turns))
        categories = set()
        for turn in memory.recent_turns[-5:]:
            for cat in ["服装", "鞋靴", "数码"]:
                if cat in turn["user"]:
                    categories.add(cat)
        if categories:
            memory.user_profile["preferred_categories"] = "、".join(sorted(categories))
        memory._dirty_profile = False
        return

    history_lines = [
        f"用户：{t['user']}\n助手摘要：{t['assistant'][:150]}"
        for t in memory.recent_turns[-5:]
    ]
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": _PROFILE_PROMPT.format(history="\n".join(history_lines))}],
        "temperature": 0.2,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.siliconflow_api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=20.0,
            )
            resp.raise_for_status()
            profile_update = json.loads(resp.json()["choices"][0]["message"]["content"].strip())
            memory.user_profile.update(_stringify_profile(profile_update))
    except Exception:
        memory.user_profile["interaction_count"] = str(len(memory.recent_turns))
    memory._dirty_profile = False


# ── 统一更新入口 ──────────────────────────────────────────────────────


def update_memory(
    memory: SessionMemory, user_message: str, assistant_answer: str
) -> None:
    """每轮对话后：更新内存 → 触发摘要/画像 → 持久化到 DB。"""
    memory.recent_turns.append(
        {"user": user_message, "assistant": assistant_answer[:2000]}
    )
    if len(memory.recent_turns) > 10:
        memory.recent_turns = memory.recent_turns[-10:]

    if len(memory.recent_turns) >= 6:
        memory._dirty_summary = True
    if len(memory.recent_turns) % 5 == 0:
        memory._dirty_profile = True

    _maybe_summarize(memory)
    _maybe_update_profile(memory)

    # 持久化到 DB
    _save_to_db(memory)


# ── 构建上下文 ────────────────────────────────────────────────────────


def build_context(memory: SessionMemory) -> PromptContext:
    profile_text = ""
    profile = memory.user_profile
    if profile.get("preferred_categories") or profile.get("preferred_metrics"):
        lines = ["## 当前用户画像"]
        if profile.get("preferred_categories"):
            lines.append(f"- 关注类目：{profile['preferred_categories']}")
        if profile.get("preferred_metrics"):
            lines.append(f"- 常用指标：{profile['preferred_metrics']}")
        if profile.get("analysis_style"):
            lines.append(f"- 分析偏好：{profile['analysis_style']}")
        profile_text = "\n".join(lines)

    summary_text = ""
    if memory.conversation_summary:
        summary_text = "## 对话历史摘要\n" + memory.conversation_summary

    return PromptContext(
        system_prompt=get_system_prompt(),
        business_instructions=get_business_instructions(),
        user_profile_text=profile_text,
        summary_text=summary_text,
        recent_turns=list(memory.recent_turns),
    )


# ── 辅助 ─────────────────────────────────────────────────────────────


def _resolve_documents_dir() -> Path:
    return settings.resolve_api_path(settings.documents_dir)
