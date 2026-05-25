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

import json
import logging
import sqlite3
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

import httpx
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

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
    analyze_sql_risk,
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
        "sql_approved": False,  # HITL 审批标记
        "sql_risk": None,
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
    policy_action_terms = [
        "应该", "应当", "需要", "触发", "进入", "走什么", "什么流程",
        "怎么处理", "如何处理", "如何判断", "怎么判断", "流程", "规则",
        "sop", "处置", "升级", "人工审核", "品控", "质量控制",
    ]
    metric_query_terms = [
        "多少", "几", "统计", "查询", "退款率", "订单数", "退款数", "工单数",
        "金额", "最高", "排行", "排名", "top", "对比", "环比", "同比",
    ]
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
    has_policy_action = any(kw in text for kw in policy_action_terms)
    has_metric_query = any(kw in text for kw in metric_query_terms)
    has_definition_intent = any(kw in text for kw in ["口径", "定义", "规则", "流程", "SOP", "sop"])
    has_time_or_stat_intent = any(
        kw in text for kw in ["3月", "4月", "5月", "2026-", "统计", "查询", "多少", "对比", "环比", "同比"]
    )

    if len(question.strip()) < 4 or any(kw in text for kw in weak):
        return ROUTE_CLARIFY, "问题信息不足，需要先追问分析范围。", 0.72

    if has_policy_action and not has_metric_query:
        return ROUTE_RAG, "问题是在询问业务规则、SOP 或触发流程，优先检索知识库文档。", 0.9

    if has_definition_intent and not has_time_or_stat_intent:
        return ROUTE_RAG, "问题是在询问指标口径、定义、规则或流程，优先检索知识库文档。", 0.9

    if has_data and has_doc:
        return ROUTE_HYBRID, "问题同时需要结构化数据和文档证据。", 0.91

    if has_doc and not has_data:
        return ROUTE_RAG, "问题主要需要检索业务政策、SOP 或指标口径。", 0.84

    if has_data:
        return ROUTE_SQL, "问题主要需要查询结构化售后数据。", 0.86

    return ROUTE_CLARIFY, "暂未识别出明确的数据查询或知识检索意图，需追问。", 0.65


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = next((part for part in parts if "{" in part and "}" in part), cleaned)
        cleaned = cleaned.replace("json", "", 1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("LLM did not return a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM router JSON must be an object")
    return payload


def _should_use_llm_router(question: str, rule_route: str, rule_confidence: float) -> bool:
    mode = settings.agent_router_mode.lower()
    if mode == "rule" or not settings.siliconflow_api_key:
        return False
    if mode == "llm":
        return True
    review_terms = [
        "应该", "触发", "流程", "规则", "SOP", "sop", "SKU", "sku",
        "为什么", "原因", "结合", "判断", "处理", "升级", "质量争议",
    ]
    return rule_confidence < settings.agent_router_confidence_threshold or any(
        term in question for term in review_terms
    )


def _classify_question_with_llm(
    question: str,
    rule_route: str,
    rule_reason: str,
    rule_confidence: float,
) -> tuple[str, str, float]:
    prompt = f"""你是企业售后 Agent 的意图路由器，只负责选择工具链，不直接回答用户。

可选 route：
- sql：需要查询结构化数据库，例如退款率、订单数、退款数、排行榜、具体统计。
- rag：需要查询知识库文档，例如政策、SOP、规则、流程、口径定义、应该触发什么处理。
- hybrid：需要同时查数据库和知识库，例如“结合4月数据和退款政策分析为什么升高”。
- clarification：问题缺少关键条件，需要先追问。

判断要求：
- “应该/触发/流程/规则/怎么处理/如何判断/SOP”通常是 rag，除非用户明确要查真实数据。
- “多少/退款率/订单数/退款数/排名/top/统计/查询”通常是 sql。
- “结合数据和政策/为什么升高/归因分析”通常是 hybrid。
- 只能输出 JSON，不要输出解释文字。

规则路由初判：
route={rule_route}
reason={rule_reason}
confidence={rule_confidence}

用户问题：
{question}

输出格式：
{{"route":"sql|rag|hybrid|clarification","confidence":0.0,"reason":"一句中文原因"}}"""

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 240,
        "response_format": {"type": "json_object"},
    }
    with httpx.Client() as client:
        resp = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=20.0,
        )
        resp.raise_for_status()
        data = _extract_json_object(resp.json()["choices"][0]["message"]["content"])

    route = str(data.get("route", "")).lower()
    if route not in {ROUTE_SQL, ROUTE_RAG, ROUTE_HYBRID, ROUTE_CLARIFY}:
        raise ValueError(f"Unsupported route from LLM router: {route}")
    confidence = float(data.get("confidence", 0.75))
    confidence = max(0.0, min(1.0, confidence))
    reason = str(data.get("reason") or "LLM Router 完成意图分类。")
    return route, f"LLM Router：{reason}", confidence


def _classify_question(question: str) -> tuple[str, str, float]:
    rule_route, rule_reason, rule_confidence = route_question(question)
    if not _should_use_llm_router(question, rule_route, rule_confidence):
        return rule_route, rule_reason, rule_confidence
    try:
        return _classify_question_with_llm(question, rule_route, rule_reason, rule_confidence)
    except Exception as exc:
        logger.warning("LLM Router failed (%s), using rule route", exc)
        return rule_route, f"{rule_reason}（LLM Router 失败，已回退规则路由）", rule_confidence


def _is_policy_or_flow_question(question: str) -> bool:
    policy_terms = [
        "应该", "应当", "触发", "进入", "什么流程", "怎么处理", "如何处理",
        "如何判断", "规则", "SOP", "sop", "处置", "升级", "质量控制",
    ]
    metric_terms = ["多少", "统计", "查询", "退款率", "订单数", "退款数", "金额", "排名", "top"]
    return any(term in question for term in policy_terms) and not any(
        term in question for term in metric_terms
    )


def _citation_dict(citation: Any) -> dict[str, Any]:
    return {
        "doc_id": citation.doc_id,
        "title": citation.title,
        "chunk_id": citation.chunk_id,
        "snippet": citation.snippet,
        "score": citation.score,
        "retrieval_sources": citation.retrieval_sources,
        "dense_rank": citation.dense_rank,
        "sparse_rank": citation.sparse_rank,
        "rrf_score": citation.rrf_score,
        "rerank_score": citation.rerank_score,
        "matched_queries": citation.matched_queries,
        "is_neighbor": citation.is_neighbor,
        "source_hit": citation.source_hit,
        "rag_profile": citation.rag_profile,
        "router_reason": citation.router_reason,
    }


def _format_rag_answer_from_citations(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "知识库中没有检索到足够相关的政策或 SOP。"
    titles = "、".join(dict.fromkeys(c["title"] for c in citations))
    snippets = "；".join(c["snippet"] for c in citations[:3])
    return f"根据知识库中的 {titles}，相关依据包括：{snippets}"


def _answer_guard_and_repair(
    question: str,
    result: dict[str, Any],
    trace: TraceRecorder,
) -> dict[str, Any]:
    if not settings.agent_enable_answer_guard:
        return result

    expected_route, expected_reason, expected_confidence = route_question(question)
    sql_columns = set(result.get("sql_columns", []))
    sql_looks_like_top_refund = "refund_count" in sql_columns and "refund_rate" not in sql_columns
    should_be_docs = (
        expected_route == ROUTE_RAG
        or _is_policy_or_flow_question(question)
        or (result.get("route") == ROUTE_SQL and sql_looks_like_top_refund and "流程" in question)
    )

    if result.get("route") == ROUTE_SQL and should_be_docs:
        citations = [_citation_dict(c) for c in retrieve_docs(question)]
        repaired = _update(
            result,
            route=ROUTE_RAG,
            route_reason=f"Answer Guard 回退：{expected_reason}",
            route_confidence=max(expected_confidence, 0.82),
            citations_data=citations,
            answer_text=_format_rag_answer_from_citations(citations),
            sql="",
            sql_columns=[],
            sql_rows=[],
            sql_row_count=0,
            sql_error=None,
        )
        trace.add(
            "answer_guard",
            "EvaluatorAgent",
            "warning",
            "检测到 SQL 结果与用户流程/规则意图不匹配，已回退到 RAG 知识库检索。",
            metadata={
                "original_route": result.get("route"),
                "repaired_route": ROUTE_RAG,
                "expected_route": expected_route,
                "sql_columns": list(sql_columns),
            },
        )
        return repaired

    trace.add(
        "answer_guard",
        "EvaluatorAgent",
        "success",
        "答案链路与用户问题意图匹配。",
        metadata={
            "route": result.get("route"),
            "expected_route": expected_route,
            "expected_confidence": expected_confidence,
        },
    )
    return result


# ── Helper ───────────────────────────────────────────────────────────

# 数据的不可变性对于 StateGraph 来说非常重要，因为它依赖于状态的纯函数转换和条件分支。这个 _update 函数确保我们每次都返回一个新的状态副本，而不是修改原有状态，从而避免了潜在的副作用和难以追踪的状态变更。
def _update(state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """返回合并后的完整 state 副本。LangGraph 的 dict state 会替换而非合并。"""
    merged = dict(state)
    merged.update(kwargs)
    return merged


def _stringify_user_profile(profile: dict[str, Any]) -> dict[str, str]:
    return {str(key): "" if value is None else str(value) for key, value in profile.items()}


# ── Nodes ────────────────────────────────────────────────────────────


def classify_intent_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("route"):
        return state
    route, reason, confidence = _classify_question(state["question"])
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


def sql_risk_check_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    SQL 执行前风险分析——真正 HITL（LangGraph interrupt）。

    - blocked  → 拒绝执行，记录错误
    - dangerous → interrupt() 挂起图，等待用户审批后再继续
    - warning │ safe → 直接放行

    这是「图暂停」而非「条件路由」——
    图状态在 checkpointer 中完整保留，恢复后从 interrupt 下一行继续执行。
    """
    if state.get("sql_approved"):
        return _update(state, sql_risk="approved")

    sql = state.get("sql", "")
    risk = analyze_sql_risk(sql)

    if risk["level"] == "blocked":
        return _update(state, sql_error=f"SQL 被拒绝：{risk['reason']}", sql_risk=risk)

    if risk["level"] == "dangerous":
        # ── 真正挂起：图在这里暂停 ──
        decision = interrupt({
            "type": "sql_approval",
            "reason": risk["reason"],
            "sql": sql,
            "risk": risk["risk"],
        })
        # ── 恢复后从这里继续执行 ──
        if decision.get("approved"):
            return _update(state, sql_risk=risk)
        else:
            return _update(state, sql_error="用户拒绝执行此 SQL")

    return _update(state, sql_risk=risk)


def risk_check_condition(
    state: dict[str, Any],
) -> Literal["execute", "format"]:
    """风险检查后的路由（只有两条路：执行或报错）。"""
    if state.get("sql_error"):
        return "format"
    return "execute"


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
            "retrieval_sources": c.retrieval_sources,
            "dense_rank": c.dense_rank,
            "sparse_rank": c.sparse_rank,
            "rrf_score": c.rrf_score,
            "rerank_score": c.rerank_score,
            "matched_queries": c.matched_queries,
            "is_neighbor": c.is_neighbor,
            "source_hit": c.source_hit,
            "rag_profile": c.rag_profile,
            "router_reason": c.router_reason,
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
            "retrieval_sources": c.retrieval_sources,
            "dense_rank": c.dense_rank,
            "sparse_rank": c.sparse_rank,
            "rrf_score": c.rrf_score,
            "rerank_score": c.rerank_score,
            "matched_queries": c.matched_queries,
            "is_neighbor": c.is_neighbor,
            "source_hit": c.source_hit,
            "rag_profile": c.rag_profile,
            "router_reason": c.router_reason,
        }
        for c in citations
    ]
    return _update(state, **updates)


def _build_hybrid_evidence(state: dict[str, Any]) -> tuple[list[str], str, str]:
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
        snippets = "；".join(c["snippet"] for c in citations[:3])
        parts.append(f"文档依据（{titles}）：{snippets}")

    sql_evidence = json.dumps(
        {
            "sql": state.get("sql", ""),
            "columns": state.get("sql_columns", []),
            "rows": rows[:8],
            "row_count": state.get("sql_row_count", 0),
            "error": error,
        },
        ensure_ascii=False,
        indent=2,
    )
    doc_evidence = json.dumps(citations[:5], ensure_ascii=False, indent=2)
    return parts, sql_evidence, doc_evidence


def _generate_hybrid_answer_with_llm(state: dict[str, Any], sql_evidence: str, doc_evidence: str) -> str:
    if not settings.siliconflow_api_key:
        raise RuntimeError("SILICONFLOW_API_KEY not configured")

    prompt = f"""你是企业售后数据分析 Agent。请基于用户问题、SQL 查询结果和知识库文档证据，生成中文综合分析。

要求：
- 只能使用给定的 SQL 结果和文档证据，不要编造额外数据。
- 如果 SQL 结果没有退款原因分布、SKU 分布、活动渠道等信息，必须明确说明“当前数据不足，不能直接断定具体原因”。
- 回答要包含：数据异常判断、可能原因、文档依据、还缺少哪些数据、下一步建议。
- 不要输出 JSON，不要输出 Markdown 表格。

用户问题：
{state.get("question", "")}

SQL 结果：
{sql_evidence}

文档证据：
{doc_evidence}
"""

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 900,
    }

    with httpx.Client() as client:
        resp = client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=45.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def hybrid_merge_node(state: dict[str, Any]) -> dict[str, Any]:
    evidence_parts, sql_evidence, doc_evidence = _build_hybrid_evidence(state)
    try:
        answer = _generate_hybrid_answer_with_llm(state, sql_evidence, doc_evidence)
        return _update(state, answer_text=answer)
    except Exception as exc:
        logger.warning("Hybrid answer synthesis failed (%s), using template fallback", exc)

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
    # 意图识别
    workflow.add_node("classify_intent", classify_intent_node) 
    # 获取表结构
    workflow.add_node("sql_retrieve_schema", sql_retrieve_schema_node)
    workflow.add_node("sql_generate", sql_generate_node)
    workflow.add_node("sql_validate", sql_validate_node)
    # 风险检查、触发 HITL 挂起（真正 interrupt）
    workflow.add_node("sql_risk_check", sql_risk_check_node)
    workflow.add_node("sql_execute", sql_execute_node)
    workflow.add_node("sql_reflect", sql_reflect_node)
    workflow.add_node("format_sql_answer", format_sql_answer_node)
    # RAG分支
    workflow.add_node("rag_retrieve", rag_retrieve_node)
    workflow.add_node("format_rag_answer", format_rag_answer_node)
    workflow.add_node("hybrid_run", hybrid_run_node)
    workflow.add_node("hybrid_merge", hybrid_merge_node)
    # 当 classify_intent 判断问题信息不足时，生成追问提示
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
    workflow.add_edge("sql_validate", "sql_risk_check")
    workflow.add_conditional_edges(
        "sql_risk_check",
        risk_check_condition,
        {
            "execute": "sql_execute",
            "format": "format_sql_answer",
        },
    )
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


def _build_approval_response(
    result: dict[str, Any],
    interrupt_info: dict[str, Any],
    trace: TraceRecorder,
    started: float,
    memory: Any,
) -> ChatResponse:
    """图被 interrupt() 挂起时，构建审批请求响应返回前端。"""
    trace.add(
        "hitl_interrupted",
        "EvaluatorAgent",
        "success",
        "图已挂起，等待用户审批。",
        metadata={"interrupt": interrupt_info},
    )
    trace.add(
        "final_answer",
        "EvaluatorAgent",
        "success",
        "审批挂起中，返回审批请求。",
    )

    latency_ms = round((perf_counter() - started) * 1000, 2)
    return ChatResponse(
        answer=f"SQL 需要审批后才能执行。\n\n原因：{interrupt_info.get('reason', '需要人工审批')}\n\n待审批 SQL：\n{interrupt_info.get('sql', '')}\n\n请在前端点击「批准」或「拒绝」。",
        route=result.get("route", "sql"),
        trace_id=trace.trace_id,
        steps=trace.steps,
        citations=[],
        sql_result=None,
        metrics=Metrics(
            latency_ms=latency_ms,
            tool_calls=trace.tool_calls,
            citations=0,
            route_confidence=result.get("route_confidence", 0),
        ),
        memory=MemoryInfo(
            session_id=result.get("session_id", ""),
            recent_turns=len(memory.recent_turns),
            conversation_summary=memory.conversation_summary,
            user_profile=_stringify_user_profile(memory.user_profile),
        ),
        requires_approval=True,
        approval_context=ApprovalContext(
            reason=interrupt_info.get("reason", "需要人工审批"),
            sql=interrupt_info.get("sql"),
            risk_level=interrupt_info.get("risk", "dangerous"),
        ),
    )


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

    route, reason, confidence = _classify_question(question)
    trace.add(
        "classify_intent",
        "RouterAgent",
        "success",
        reason,
        metadata={"route": route, "confidence": confidence},
    )

    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}}

    # 构建结构化 PromptContext
    prompt_ctx = build_context(memory)

    # ═══════════════════════════════════════
    # 真正 HITL：区分首次 invoke 和恢复 invoke
    # ═══════════════════════════════════════
    if request.approved:
        # 恢复被 interrupt() 挂起的图
        trace.add(
            "approval_received",
            "EvaluatorAgent",
            "success",
            "用户已批准 SQL 执行，恢复挂起的 Graph。",
        )
        result = graph.invoke(Command(resume={"approved": True}), config)
        # 如果 thread 没有挂起过，resume 可能返回 None
        if result is None:
            initial = _init_state(question, session_id, prompt_ctx)
            initial["route"] = route
            initial["route_reason"] = reason
            initial["route_confidence"] = confidence
            initial["sql_approved"] = True
            result = graph.invoke(initial, config)
    else:
        initial = _init_state(question, session_id, prompt_ctx)
        initial["route"] = route
        initial["route_reason"] = reason
        initial["route_confidence"] = confidence
        result = graph.invoke(initial, config)

    # 检查图是否被 interrupt() 挂起
    interrupt_info = result.get("__interrupt__") if result else None
    if interrupt_info:
        # 图挂起了 → 返回审批请求给前端
        return _build_approval_response(
            result=result,
            interrupt_info=interrupt_info[0] if isinstance(interrupt_info, list) else interrupt_info,
            trace=trace,
            started=started,
            memory=memory,
        )

    result = _answer_guard_and_repair(question, result, trace)

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

    # HITL：interrupt 机制在前面的 __interrupt__ 检查中已处理。
    # 到达这里说明图正常完成（没有被挂起），不需要审批。
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
            user_profile=_stringify_user_profile(memory.user_profile),
        ),
        requires_approval=False,
        approval_context=None,
    )
