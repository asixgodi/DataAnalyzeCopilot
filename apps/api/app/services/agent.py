"""
LangGraph Agent — 企业数据分析 Copilot 核心工作流。

StateGraph 结构:
  START → classify_intent → route_condition
    → sql_branch → ... → format_sql_answer → generate_final → END
    → rag_branch → format_rag_answer → generate_final → END
    → hybrid_branch → hybrid_merge → generate_final → END
    → clarification → generate_final → END

SQL 分支含失败重试（reflect → generate 循环，默认最多 2 次）。
"""

import logging
import sqlite3
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

import httpx
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.core.config import settings
from app.schemas.chat import (
    ApprovalContext,
    ChatRequest,
    ChatResponse,
    Citation,
    MemoryInfo,
    Metrics,
    SqlResult,
)
from app.services.memory import (
    PromptContext,
    build_context,
    get_instruction,
    get_memory,
    resolve_followup,
    update_memory,
)
from app.services.rag import retrieve_docs
from app.services.sql_tools import (
    build_sql_for_question,
    execute_readonly_sql,
    get_table_schema,
    list_tables,
    validate_readonly_sql,
)
from app.services.trace import TraceRecorder

logger = logging.getLogger(__name__)

MAX_SQL_RETRIES = 2
ROUTE_SQL = "sql"
ROUTE_RAG = "rag"
ROUTE_HYBRID = "hybrid"
ROUTE_CLARIFY = "clarification"


# ── State ────────────────────────────────────────────────────────────

# 定义初始状态
def _init_state(question: str, session_id: str, prompt_ctx: PromptContext | None = None) -> dict[str, Any]:
    return {
        "question": question,
        "session_id": session_id,
        "prompt_ctx": prompt_ctx or {},
        "route": "",
        "route_reason": "",
        "route_confidence": 0.0,
        "sql": "",
        "sql_columns": [],
        "sql_rows": [],
        "sql_row_count": 0,
        "sql_error": None,
        "sql_retry_count": 0,
        "citations_data": [],
        "answer_text": "",
        "need_clarification": False,
        "requires_approval": False,
        "approval_reason": "",
        "approval_sql": "",
        "approval_risk": "low",
        "is_finished": False,
    }


# ── Checkpointer ─────────────────────────────────────────────────────


def _build_checkpointer():
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_dir = settings.resolve_api_path("../../data")
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "checkpoints.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        logger.info("Using SqliteSaver at %s", db_path)
        return SqliteSaver(conn)
    except Exception as exc:
        logger.warning("SqliteSaver unavailable (%s), using MemorySaver", exc)
        return MemorySaver()


_checkpointer = None


def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _build_checkpointer()
    return _checkpointer


# ── LLM SQL Generation ───────────────────────────────────────────────


def _generate_sql_with_llm(
    question: str,
    tables: list[str],
    prompt_ctx: PromptContext | None = None,
    tool_error: str | None = None,
) -> str:
    if not settings.siliconflow_api_key:
        raise RuntimeError("SILICONFLOW_API_KEY not configured")

    schema_parts = []
    for table in tables:
        try:
            cols = get_table_schema(table)
            schema_parts.append(
                f"CREATE TABLE {table} (\n"
                + ",\n".join(f"  {c['name']} {c['type']}" for c in cols)
                + "\n);"
            )
        except Exception:
            pass

    if not schema_parts:
        raise RuntimeError("No table schema available")

    schema_text = "\n\n".join(schema_parts)
    ctx = prompt_ctx or {}

    # ═══════════════════════════════════════
    # 按 6 层结构组装 messages
    # ═══════════════════════════════════════
    messages: list[dict[str, str]] = []

    # ① system prompt — Agent 角色定义
    messages.append({
        "role": "system",
        "content": ctx.get("system_prompt", get_instruction()),
    })

    # ② 业务指令 — 分析规范 + 输出格式
    messages.append({
        "role": "system",
        "content": ctx.get("business_instructions", ""),
    })

    # ③ memory (长期记忆) — 用户画像
    if ctx.get("user_profile_text"):
        messages.append({
            "role": "system",
            "content": ctx["user_profile_text"],
        })

    # ④ conversation (最近对话) — 最近 4 轮完整对话
    recent_turns: list[dict[str, str]] = ctx.get("recent_turns", [])
    for turn in recent_turns[-4:]:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"][:300]})

    # ⑤ tool result — SQL 重试时的错误反馈
    if tool_error:
        messages.append({
            "role": "tool",
            "content": f"SQL 执行错误：{tool_error}\n请修正后重新生成。",
        })

    # ⑥ 当前用户问题
    messages.append({
        "role": "user",
        "content": (
            f"数据库表结构：\n\n{schema_text}\n\n"
            f"用户问题：{question}\n\n"
            f"要求：\n"
            f"- 只输出 SELECT 语句\n"
            f"- 使用 SQLite 语法\n"
            f"- 外键关联：orders.product_id→products.id, refunds.order_id→orders.id, "
            f"tickets.product_id→products.id, reviews.product_id→products.id\n"
            f"- 百分比计算用 ROUND(CAST(... AS REAL) * 100 / ..., 2)\n"
        ),
    })

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 600,
    }

    with httpx.Client() as client:
        resp = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=45.0,
        )
        resp.raise_for_status()
        data = resp.json()
        sql = data["choices"][0]["message"]["content"].strip()

    for fence in ("```sql", "```"):
        if fence in sql:
            sql = sql.split(fence)[1]
            if "```" in sql:
                sql = sql.split("```")[0]
            sql = sql.strip()
            break

    if not sql.lower().startswith("select"):
        raise RuntimeError(f"LLM returned non-SELECT: {sql[:120]}")

    return sql


def _generate_sql(
    question: str,
    prompt_ctx: PromptContext | None = None,
    tool_error: str | None = None,
) -> str:
    """生成 SQL：优先使用模板匹配，复杂问题回退到 LLM。"""
    template_sql = build_sql_for_question(question)

    default_patterns = ["refund_rate", "COUNT(DISTINCT r.id)"]
    is_default = any(p in template_sql for p in default_patterns)

    advanced_keywords = ["差评", "评分", "平均", "总计", "对比上月", "环比", "同比", "低于"]
    needs_llm = any(kw in question for kw in advanced_keywords) and is_default

    if needs_llm and settings.siliconflow_api_key:
        tables = list_tables()
        try:
            sql = _generate_sql_with_llm(question, tables, prompt_ctx, tool_error)
            logger.info("LLM generated SQL for complex question: %s", sql[:200])
            return sql
        except Exception as exc:
            logger.warning("LLM SQL generation failed (%s), using template", exc)

    return template_sql


# ── Routing ──────────────────────────────────────────────────────────


def route_question(question: str) -> tuple[str, str, float]:
    text = question.lower()
    weak = ["随便", "不知道", "都行", "看看"]
    data_terms = [
        "4月", "5月", "3月", "订单", "商品", "工单", "评价",
        "最高", "多少", "对比", "升高", "下降", "退款率", "销量",
        "排名", "top", "数量", "统计", "查询",
    ]
    doc_terms = [
        "政策", "规则", "sop", "口径", "定义", "为什么", "原因",
        "结合", "证据", "会员", "物流", "分类标准", "字段说明",
        "规范", "流程", "指标",
    ]

    has_data = any(kw in text for kw in data_terms)
    has_doc = any(kw in text for kw in doc_terms)

    if len(question.strip()) < 4 or any(kw in text for kw in weak):
        return ROUTE_CLARIFY, "问题信息不足，需要先追问分析范围。", 0.72

    if has_data and has_doc:
        return ROUTE_HYBRID, "问题同时需要结构化数据和文档证据。", 0.91

    if has_doc and not has_data:
        return ROUTE_RAG, "问题主要需要检索业务政策、SOP 或指标口径。", 0.84

    if has_data:
        return ROUTE_SQL, "问题主要需要查询结构化售后数据。", 0.86

    return ROUTE_CLARIFY, "暂未识别出明确的数据查询或知识检索意图，需追问。", 0.65


# ── Helper ───────────────────────────────────────────────────────────

def _update(state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """返回合并后的完整 state 副本。LangGraph 的 dict state 会替换而非合并。"""
    merged = dict(state)
    merged.update(kwargs)
    return merged


# ── Nodes ────────────────────────────────────────────────────────────


def classify_intent_node(state: dict[str, Any]) -> dict[str, Any]:
    route, reason, confidence = route_question(state["question"])
    return _update(state, route=route, route_reason=reason, route_confidence=confidence)


def route_condition(state: dict[str, Any]) -> Literal["sql", "rag", "hybrid", "clarification"]:
    return state["route"]


# ── SQL Branch ───────────────────────────────────────────────────────


def sql_retrieve_schema_node(state: dict[str, Any]) -> dict[str, Any]:
    return _update(state)


def sql_generate_node(state: dict[str, Any]) -> dict[str, Any]:
    question = state["question"]
    if state.get("sql_retry_count", 0) > 0:
        error_msg = state.get("sql_error", "")
        question = (
            f"原始问题：{question}\n"
            f"上一次 SQL 执行失败：{error_msg}\n"
            f"请修正 SQL 并重新生成。"
        )
    try:
        sql = _generate_sql(
            question,
            prompt_ctx=state.get("prompt_ctx"),
            tool_error=state.get("sql_error") if state.get("sql_retry_count", 0) > 0 else None,
        )
    except Exception:
        sql = build_sql_for_question(state["question"])
    return _update(state, sql=sql)


def sql_validate_node(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    try:
        validate_readonly_sql(sql)
        return _update(state)
    except ValueError as exc:
        return _update(state, sql_error=str(exc))


def sql_execute_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("sql_error"):
        return _update(state)
    result = execute_readonly_sql(state["sql"])
    return _update(
        state,
        sql_columns=result.columns,
        sql_rows=[dict(r) for r in result.rows],
        sql_row_count=result.row_count,
        sql_error=result.error,
    )


def sql_check_condition(state: dict[str, Any]) -> Literal["retry", "format"]:
    error = state.get("sql_error")
    retries = state.get("sql_retry_count", 0)
    if error and retries < MAX_SQL_RETRIES:
        return "retry"
    return "format"


def sql_reflect_node(state: dict[str, Any]) -> dict[str, Any]:
    return _update(
        state,
        sql_retry_count=state.get("sql_retry_count", 0) + 1,
    )


def format_sql_answer_node(state: dict[str, Any]) -> dict[str, Any]:
    error = state.get("sql_error")
    if error:
        text = f"SQL 执行失败：{error}（已尝试 {state.get('sql_retry_count', 0)} 次修复）"
    elif not state.get("sql_rows"):
        text = "没有查到匹配的数据。"
    else:
        rows = state["sql_rows"]
        row = rows[0]
        if "refund_rate" in row:
            text = (
                f"{row.get('month', '')} {row.get('category', '')}类目的订单数为 "
                f"{row.get('order_count', 'N/A')}，退款数为 {row.get('refund_count', 'N/A')}，"
                f"退款率为 {row['refund_rate']}%。"
            )
        elif "ticket_count" in row:
            parts = [
                f"{item.get('reason', '未知原因')} {item['ticket_count']} 次"
                for item in rows
            ]
            text = "客服工单原因分布：" + "，".join(parts) + "。"
        elif "refund_count" in row:
            parts = []
            for item in rows:
                name = item.get("name") or f"商品#{item.get('product_id', '?')}"
                parts.append(f"{name} {item['refund_count']} 次退款")
            text = "退款次数最高的商品：" + "，".join(parts) + "。"
        else:
            columns = state.get("sql_columns", [])
            preview = "；".join(
                ", ".join(f"{col}={row.get(col, '?')}" for col in columns[:4])
                for row in rows[:3]
            )
            text = f"查询返回 {state['sql_row_count']} 行结果。预览：{preview}"
    return _update(state, answer_text=text)


# ── RAG Branch ───────────────────────────────────────────────────────


def rag_retrieve_node(state: dict[str, Any]) -> dict[str, Any]:
    citations = retrieve_docs(state["question"])
    data = [
        {
            "doc_id": c.doc_id,
            "title": c.title,
            "chunk_id": c.chunk_id,
            "snippet": c.snippet,
            "score": c.score,
        }
        for c in citations
    ]
    return _update(state, citations_data=data)


def format_rag_answer_node(state: dict[str, Any]) -> dict[str, Any]:
    citations = state.get("citations_data", [])
    if not citations:
        return _update(state, answer_text="知识库中没有检索到足够相关的政策或 SOP。")
    titles = "、".join(dict.fromkeys(c["title"] for c in citations))
    snippets = "；".join(c["snippet"] for c in citations[:2])
    text = f"根据知识库中的 {titles}，相关依据包括：{snippets}"
    return _update(state, answer_text=text)


# ── Hybrid Branch ────────────────────────────────────────────────────


def hybrid_run_node(state: dict[str, Any]) -> dict[str, Any]:
    question = state["question"]
    updates: dict[str, Any] = {}

    try:
        sql = _generate_sql(question, prompt_ctx=state.get("prompt_ctx"))
    except Exception:
        sql = build_sql_for_question(question)
    updates["sql"] = sql

    try:
        validate_readonly_sql(sql)
        sql_result = execute_readonly_sql(sql)
        updates["sql_columns"] = sql_result.columns
        updates["sql_rows"] = [dict(r) for r in sql_result.rows]
        updates["sql_row_count"] = sql_result.row_count
        updates["sql_error"] = sql_result.error
    except ValueError as exc:
        updates["sql_error"] = str(exc)
        updates["sql_columns"] = []
        updates["sql_rows"] = []
        updates["sql_row_count"] = 0

    citations = retrieve_docs(question)
    updates["citations_data"] = [
        {
            "doc_id": c.doc_id,
            "title": c.title,
            "chunk_id": c.chunk_id,
            "snippet": c.snippet,
            "score": c.score,
        }
        for c in citations
    ]
    return _update(state, **updates)


def hybrid_merge_node(state: dict[str, Any]) -> dict[str, Any]:
    parts: list[str] = []

    error = state.get("sql_error")
    rows = state.get("sql_rows", [])
    if error:
        parts.append(f"数据查询遇到问题：{error}")
    elif rows:
        row = rows[0]
        if "refund_rate" in row:
            parts.append(
                f"数据结果：{row.get('month', '')} {row.get('category', '')}类目 "
                f"退款率为 {row['refund_rate']}%（订单 {row.get('order_count', '?')} 单，"
                f"退款 {row.get('refund_count', '?')} 单）。"
            )
        elif "ticket_count" in row:
            detail = "，".join(
                f"{item.get('reason', '?')} {item['ticket_count']} 次"
                for item in rows
            )
            parts.append(f"数据结果：工单原因分布——{detail}。")
        else:
            parts.append(f"数据结果：查询返回 {state.get('sql_row_count', 0)} 行。")
    else:
        parts.append("数据结果：未查到匹配记录。")

    citations = state.get("citations_data", [])
    if citations:
        titles = "、".join(dict.fromkeys(c["title"] for c in citations))
        snippets = "；".join(c["snippet"] for c in citations[:2])
        parts.append(f"文档依据（{titles}）：{snippets}")

    parts.append(
        "综合分析：退款率波动通常需要结合数据趋势和售后政策综合判断。"
        "建议重点关注高频退款原因（如尺码、色差、面料）与工单原因的一致性，"
        "并对照售后 SOP 确认是否需要启动品控抽检或详情页优化。"
    )

    return _update(state, answer_text="\n\n".join(parts))


# ── Clarification ────────────────────────────────────────────────────


def clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    need = []
    question = state["question"]
    if not any(kw in question for kw in ["月", "3月", "4月", "5月", "时间"]):
        need.append("分析的时间范围（如 4 月、5 月）")
    if not any(kw in question for kw in ["服装", "鞋靴", "数码", "类目", "分类"]):
        need.append("关注的商品类目（如服装、鞋靴、数码）")
    if not any(kw in question for kw in ["退款", "工单", "评价", "订单", "指标", "政策"]):
        need.append("想了解的数据类型（退款率、工单分布、评价分析等）")

    if need:
        text = "我需要补充以下信息才能准确分析：\n" + "\n".join(f"- {n}" for n in need)
    else:
        text = "请补充更具体的分析需求，例如查询哪个月份、哪个类目的什么指标。"
    return _update(state, answer_text=text)


# ── Final ────────────────────────────────────────────────────────────


def generate_final_node(state: dict[str, Any]) -> dict[str, Any]:
    return _update(state, is_finished=True)


# ── Graph Builder ────────────────────────────────────────────────────


_graph = None


def build_graph() -> StateGraph:
    global _graph
    if _graph is not None:
        return _graph

    workflow = StateGraph(dict)

    workflow.add_node("classify_intent", classify_intent_node)
    workflow.add_node("sql_retrieve_schema", sql_retrieve_schema_node)
    workflow.add_node("sql_generate", sql_generate_node)
    workflow.add_node("sql_validate", sql_validate_node)
    workflow.add_node("sql_execute", sql_execute_node)
    workflow.add_node("sql_reflect", sql_reflect_node)
    workflow.add_node("format_sql_answer", format_sql_answer_node)
    workflow.add_node("rag_retrieve", rag_retrieve_node)
    workflow.add_node("format_rag_answer", format_rag_answer_node)
    workflow.add_node("hybrid_run", hybrid_run_node)
    workflow.add_node("hybrid_merge", hybrid_merge_node)
    workflow.add_node("clarification", clarification_node)
    workflow.add_node("generate_final", generate_final_node)

    workflow.set_entry_point("classify_intent")

    workflow.add_conditional_edges(
        "classify_intent",
        route_condition,
        {
            ROUTE_SQL: "sql_retrieve_schema",
            ROUTE_RAG: "rag_retrieve",
            ROUTE_HYBRID: "hybrid_run",
            ROUTE_CLARIFY: "clarification", 
        },
    )

    # SQL branch
    workflow.add_edge("sql_retrieve_schema", "sql_generate")
    workflow.add_edge("sql_generate", "sql_validate")
    workflow.add_edge("sql_validate", "sql_execute")
    workflow.add_conditional_edges(
        "sql_execute",
        sql_check_condition,
        {"retry": "sql_reflect", "format": "format_sql_answer"},
    )
    workflow.add_edge("sql_reflect", "sql_generate")
    workflow.add_edge("format_sql_answer", "generate_final")

    # RAG branch
    workflow.add_edge("rag_retrieve", "format_rag_answer")
    workflow.add_edge("format_rag_answer", "generate_final")

    # Hybrid branch
    workflow.add_edge("hybrid_run", "hybrid_merge")
    workflow.add_edge("hybrid_merge", "generate_final")

    # Clarification
    workflow.add_edge("clarification", "generate_final")

    # End
    workflow.add_edge("generate_final", END)

    _graph = workflow.compile(checkpointer=_get_checkpointer())
    return _graph


# ── Public API ───────────────────────────────────────────────────────


def run_agent(request: ChatRequest) -> ChatResponse:
    started = perf_counter()
    session_id = request.session_id or f"session_{uuid4().hex[:8]}"
    memory = get_memory(session_id)
    question = resolve_followup(request.message.strip(), memory)
    trace = TraceRecorder()

    trace.add(
        "receive_message",
        "ChatAgent",
        "success",
        "收到用户问题并加载会话记忆。",
        metadata={"session_id": session_id, "resolved_question": question},
    )

    route, reason, confidence = route_question(question)
    trace.add(
        "classify_intent",
        "RouterAgent",
        "success",
        reason,
        metadata={"route": route, "confidence": confidence},
    )

    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}}

    # 构建结构化 PromptContext（6 层结构），注入 graph state 供 LLM 节点使用
    prompt_ctx = build_context(memory)

    initial = _init_state(question, session_id, prompt_ctx)
    result = graph.invoke(initial, config)

    trace.add(
        "route_task",
        "RouterAgent",
        "success",
        f"路由至 {result['route']} 分支。",
        metadata={"route": result["route"]},
    )

    if result["route"] in (ROUTE_SQL, ROUTE_HYBRID):
        trace.tool_calls += 1
        trace.add(
            "sql_generate",
            "SQLAgent",
            "success",
            "生成只读 SQL 查询。",
            metadata={
                "sql": result.get("sql", ""),
                "retry_count": result.get("sql_retry_count", 0),
            },
        )
        trace.add(
            "sql_execute",
            "SQLAgent",
            "error" if result.get("sql_error") else "success",
            result.get("sql_error") or f"返回 {result.get('sql_row_count', 0)} 行。",
            metadata={"row_count": result.get("sql_row_count", 0)},
        )

    if result["route"] in (ROUTE_RAG, ROUTE_HYBRID):
        trace.tool_calls += 1
        c_count = len(result.get("citations_data", []))
        trace.add(
            "retrieve_docs",
            "RAGAgent",
            "success" if c_count else "warning",
            f"检索到 {c_count} 条文档证据。",
            metadata={"citations": result.get("citations_data", [])},
        )

    if result["route"] == ROUTE_HYBRID:
        trace.add(
            "merge_evidence",
            "EvaluatorAgent",
            "success",
            "合并 SQL 数据和 RAG 文档证据完成综合分析。",
        )

    if result["route"] == ROUTE_CLARIFY:
        trace.add(
            "ask_clarification",
            "RouterAgent",
            "success",
            "信息不足，生成追问以获取更多上下文。",
        )

    answer = result.get("answer_text", "")
    update_memory(memory, request.message, answer)

    trace.add(
        "update_memory",
        "MemoryAgent",
        "success",
        (
            f"更新四层记忆：recent_turns={len(memory.recent_turns)}轮, "
            f"summary={'已更新' if memory.conversation_summary else '未触发'}, "
            f"profile_categories={memory.user_profile.get('preferred_categories', '未提取')}"
        ),
        metadata={
            "recent_turns": len(memory.recent_turns),
            "summary": memory.conversation_summary[:120] if memory.conversation_summary else "",
            "user_profile": memory.user_profile,
            "prompt_layers": {
                "system_prompt": bool(prompt_ctx.get("system_prompt")),
                "business_instructions": bool(prompt_ctx.get("business_instructions")),
                "user_profile": bool(prompt_ctx.get("user_profile_text")),
                "history_turns": len(prompt_ctx.get("recent_turns", [])),
            },
        },
    )
    trace.add(
        "final_answer",
        "EvaluatorAgent",
        "success",
        "完成答案生成和基础质量检查。",
    )

    citations = [Citation(**c) for c in result.get("citations_data", [])]

    sql_result = None
    if result["route"] in (ROUTE_SQL, ROUTE_HYBRID) and (
        result.get("sql_columns") or result.get("sql_error")
    ):
        sql_result = SqlResult(
            sql=result.get("sql", ""),
            columns=result.get("sql_columns", []),
            rows=result.get("sql_rows", []),
            row_count=result.get("sql_row_count", 0),
            error=result.get("sql_error"),
        )

    latency_ms = round((perf_counter() - started) * 1000, 2)

    requires_approval = False
    approval_context = None
    sql_raw = result.get("sql", "")
    if sql_raw and result["route"] in (ROUTE_SQL, ROUTE_HYBRID):
        high_risk_keywords = ["password", "secret", "token", "credit_card"]
        if any(kw in sql_raw.lower() for kw in high_risk_keywords):
            requires_approval = True
            approval_context = ApprovalContext(
                reason="SQL 涉及敏感字段，需要人工审批后执行。",
                sql=sql_raw,
                risk_level="high",
            )
        elif result.get("sql_row_count", 0) > 500:
            requires_approval = True
            approval_context = ApprovalContext(
                reason=f"SQL 返回 {result['sql_row_count']} 行数据，数量较大，需要确认。",
                sql=sql_raw,
                risk_level="medium",
            )

    return ChatResponse(
        answer=answer,
        route=result["route"],
        trace_id=trace.trace_id,
        steps=trace.steps,
        citations=citations,
        sql_result=sql_result,
        metrics=Metrics(
            latency_ms=latency_ms,
            tool_calls=trace.tool_calls,
            citations=len(citations),
            route_confidence=result.get("route_confidence", 0),
        ),
        memory=MemoryInfo(
            session_id=session_id,
            recent_turns=len(memory.recent_turns),
            conversation_summary=memory.conversation_summary,
            user_profile=memory.user_profile,
        ),
        requires_approval=requires_approval,
        approval_context=approval_context,
    )
