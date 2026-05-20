"""
四层记忆系统 — 电商售后分析 Copilot

┌─ ① system prompt：Agent 角色定义
├─ ② 业务指令：分析规范 + 输出格式要求（从 Markdown 文件加载）
├─ ③ 长期记忆 (memory)：用户画像 — 动态提取关注类目/指标/偏好
├─ ④ 最近对话 (conversation)：recent_turns 滑动窗口历史轮次
└─ ⑤ 摘要记忆：LLM 压缩长对话为结构化摘要

企业实践对标：
  system prompt  ── OpenAI Assistants API 的 Instructions 字段
  业务指令        ── 企业中 Prompt Engineer 维护的独立 prompt 模板
  memory         ── Anthropic 的 memory files (user_profile.md)
  conversation   ── OpenAI 的 Thread messages / LangChain 的 ChatHistory
  摘要            ── LangChain ConversationSummaryBufferMemory
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

import httpx

from app.core.config import settings

# ── 数据结构 ──────────────────────────────────────────────────────────


@dataclass
class SessionMemory:
    """单会话的四层记忆状态。"""

    recent_turns: list[dict[str, str]] = field(default_factory=list)
    conversation_summary: str = ""
    user_profile: dict[str, str] = field(default_factory=dict)

    _dirty_summary: bool = field(default=False, repr=False)
    _dirty_profile: bool = field(default=False, repr=False)


_STORE: dict[str, SessionMemory] = {}


class PromptContext(TypedDict):
    """
    Agent 发往 LLM 时的完整 prompt 结构：

    ┌─ system_prompt         → role:"system"  #1
    ├─ business_instructions  → role:"system"  #2
    ├─ user_profile_text      → role:"system"  #3 (可选)
    ├─ summary_text           → role:"system"  #4 (可选)
    ├─ recent_turns           → 展开为 role:"user" + role:"assistant" 历史轮次
    ├─ tool_result            → role:"tool" (SQL 重试时)
    └─ current_question       → role:"user" (最后一条)
    """

    system_prompt: str
    business_instructions: str
    user_profile_text: str
    summary_text: str
    recent_turns: list[dict[str, str]]


# ── ① system prompt：Agent 角色定义 ────────────────────────────────────


def get_system_prompt() -> str:
    """纯角色定义——这个 Agent 是谁，做什么。"""
    return (
        "你是一个电商售后数据分析助手。你的职责是：\n"
        "1. 理解用户的自然语言问题，判断需要查数据库、查知识库还是两者都查。\n"
        "2. 生成安全的只读 SQL 查询结构化数据。\n"
        "3. 检索业务政策、SOP、指标口径等非结构化文档。\n"
        "4. 融合数据结果和文档证据，给出有依据的分析结论。"
    )


# ── ② 业务指令：分析规范 + 输出格式 ────────────────────────────────────


def get_business_instructions() -> str:
    """从知识库加载分析规范，作为业务指令独立注入。"""
    guidelines_path = _resolve_documents_dir() / "analysis_guidelines.md"
    if guidelines_path.exists():
        guidelines_text = guidelines_path.read_text(encoding="utf-8")
    else:
        guidelines_text = ""

    return (
        "回答要求：\n"
        "- 数据结论需要有具体的数字和来源（SQL 语句）。\n"
        "- 引用政策或规则时需要标明出自哪个文档。\n"
        "- 如果信息不足无法给出确切结论，主动追问而不是猜测。\n"
        "- 对混合分析问题，按「数据结果 → 文档依据 → 综合分析 → 建议动作」的结构输出。\n"
        "\n"
        + guidelines_text
    )


# ── 向后兼容 ──────────────────────────────────────────────────────────


def get_instruction() -> str:
    """旧接口兼容：合并 system prompt + 业务指令。"""
    return get_system_prompt() + "\n\n" + get_business_instructions()


# ── 会话记忆：滑动窗口 ─────────────────────────────────────────────────


def get_memory(session_id: str) -> SessionMemory:
    if session_id not in _STORE:
        _STORE[session_id] = SessionMemory(
            user_profile={
                "role": "after_sales_operator",
                "focus": "退换货分析和客诉归因",
                "preferred_categories": "",
                "preferred_metrics": "",
                "interaction_count": "0",
            }
        )
    return _STORE[session_id]


def resolve_followup(message: str, memory: SessionMemory) -> str:
    """
    指代消解 + 上下文补全。
    当 recent_turns 作为独立 history messages 注入后，
    这个函数负责当前问题的补全——把「那鞋靴类呢？」扩展为完整语义。

    注意：这里的补全是「问题级」补全，和 messages 数组里的历史轮次互补。
    """
    followup_markers = ["那", "这个", "这两个", "对比", "呢", "也", "再", "继续"]
    if not memory.recent_turns or not any(marker in message for marker in followup_markers):
        return message

    previous = memory.recent_turns[-1]

    category_map = {"鞋": "鞋靴", "鞋靴": "鞋靴", "数码": "数码", "耳机": "数码"}
    matched_category = None
    for keyword, category in category_map.items():
        if keyword in message:
            matched_category = category
            break

    if matched_category:
        return (
            f"上一轮问题：{previous['user']}，回答：{previous['assistant'][:200]}。"
            f"现在用户追问：把分析类目换成{matched_category}，{message}"
        )

    return (
        f"上一轮问题：{previous['user']}，回答：{previous['assistant'][:200]}。"
        f"现在用户追问：{message}"
    )


# ── 摘要记忆：LLM 压缩 ────────────────────────────────────────────────


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
    if len(memory.recent_turns) < 6:
        return
    if not memory._dirty_summary:
        return
    if not settings.siliconflow_api_key:
        memory.conversation_summary = "；".join(
            turn["user"] for turn in memory.recent_turns[-4:]
        )
        memory._dirty_summary = False
        return

    history_lines: list[str] = []
    for turn in memory.recent_turns:
        history_lines.append(f"用户：{turn['user']}")
        history_lines.append(f"助手：{turn['assistant'][:200]}")

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "user",
                "content": _SUMMARY_PROMPT.format(history="\n".join(history_lines)),
            },
        ],
        "temperature": 0.3,
        "max_tokens": 250,
    }

    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=20.0,
            )
            resp.raise_for_status()
            summary = resp.json()["choices"][0]["message"]["content"].strip()
            memory.conversation_summary = summary
    except Exception:
        memory.conversation_summary = "；".join(
            turn["user"] for turn in memory.recent_turns[-4:]
        )

    memory._dirty_summary = False


# ── 用户档案：动态提取 ─────────────────────────────────────────────────


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
    if len(memory.recent_turns) < 3:
        return
    if not memory._dirty_profile:
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

    history_lines: list[str] = []
    for turn in memory.recent_turns[-5:]:
        history_lines.append(f"用户：{turn['user']}")
        history_lines.append(f"助手摘要：{turn['assistant'][:150]}")

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [
            {
                "role": "user",
                "content": _PROFILE_PROMPT.format(history="\n".join(history_lines)),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=20.0,
            )
            resp.raise_for_status()
            import json

            profile_update = json.loads(
                resp.json()["choices"][0]["message"]["content"].strip()
            )
            memory.user_profile.update(profile_update)
    except Exception:
        memory.user_profile["interaction_count"] = str(len(memory.recent_turns))

    memory._dirty_profile = False


# ── 统一更新入口 ──────────────────────────────────────────────────────


def update_memory(
    memory: SessionMemory, user_message: str, assistant_answer: str
) -> None:
    memory.recent_turns.append(
        {"user": user_message, "assistant": assistant_answer[:300]}
    )
    if len(memory.recent_turns) > 10:
        memory.recent_turns = memory.recent_turns[-10:]
    if len(memory.recent_turns) >= 6:
        memory._dirty_summary = True
    if len(memory.recent_turns) % 5 == 0:
        memory._dirty_profile = True
    _maybe_summarize(memory)
    _maybe_update_profile(memory)


# ── 构建上下文（结构化 PromptContext）──────────────────────────────────


def build_context(memory: SessionMemory) -> PromptContext:
    """
    构建发往 LLM 的完整 prompt 结构。

    返回 PromptContext，由调用方组装为 messages 数组：
      system_prompt  → role:"system"
      business_instructions → role:"system"
      user_profile_text     → role:"system" (可选)
      summary_text          → role:"system" (可选)
      recent_turns          → 展开为 user/assistant 历史轮次
      [+ tool_result]       → role:"tool" (由 agent.py 在重试时注入)
      [+ current_question]  → role:"user" (由 agent.py 注入)
    """

    # ③ 长期记忆 — 用户画像
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

    # ⑤ 摘要记忆
    summary_text = ""
    if memory.conversation_summary:
        summary_text = "## 对话历史摘要\n" + memory.conversation_summary

    return PromptContext(
        system_prompt=get_system_prompt(),
        business_instructions=get_business_instructions(),
        user_profile_text=profile_text,
        summary_text=summary_text,
        recent_turns=list(memory.recent_turns),  # 拷贝一份
    )


# ── 辅助 ─────────────────────────────────────────────────────────────


def _resolve_documents_dir() -> Path:
    return settings.resolve_api_path(settings.documents_dir)
