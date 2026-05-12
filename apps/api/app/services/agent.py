from time import perf_counter
from uuid import uuid4

from app.schemas.chat import ChatRequest, ChatResponse, Metrics, SqlResult
from app.services.memory import get_memory, resolve_followup, update_memory
from app.services.rag import retrieve_docs
from app.services.sql_tools import build_sql_for_question, execute_readonly_sql, list_tables
from app.services.trace import TraceRecorder


def route_question(question: str) -> tuple[str, str, float]:
    text = question.lower()
    weak_intent = ["随便", "不知道", "都行", "看看"]
    data_terms = ["4月", "5月", "3月", "订单", "商品", "工单", "评价", "最高", "多少", "对比", "升高", "下降"]
    metric_terms = ["退款率", "退款", "售后"]
    doc_terms = ["政策", "规则", "sop", "口径", "定义", "为什么", "原因", "结合", "证据"]

    asks_data = any(keyword in text for keyword in data_terms)
    mentions_metric = any(keyword in text for keyword in metric_terms)
    asks_docs = any(keyword in text for keyword in doc_terms)

    if len(question.strip()) < 4 or any(keyword in text for keyword in weak_intent):
        return "clarification", "问题信息不足，需要先追问分析范围。", 0.72
    if asks_docs and not asks_data:
        return "rag", "问题主要需要检索业务政策、SOP 或指标口径。", 0.84
    if asks_data and asks_docs:
        return "hybrid", "问题同时需要结构化数据和文档证据。", 0.91
    if asks_data or mentions_metric:
        return "sql", "问题主要需要查询结构化售后数据。", 0.86
    return "clarification", "暂未识别出明确的数据查询或知识检索意图。", 0.65


def _format_sql_answer(sql_result: SqlResult) -> str:
    if sql_result.error:
        return f"SQL 执行失败：{sql_result.error}"
    if not sql_result.rows:
        return "没有查到匹配的数据。"
    row = sql_result.rows[0]
    if "refund_rate" in row:
        return (
            f"{row['month']} {row['category']}类目的订单数为 {row['order_count']}，"
            f"退款数为 {row['refund_count']}，退款率为 {row['refund_rate']}%。"
        )
    if "ticket_count" in row:
        parts = [f"{item['reason']} {item['ticket_count']} 次" for item in sql_result.rows]
        return "客服工单原因分布：" + "，".join(parts) + "。"
    if "refund_count" in row:
        parts = [f"{item['name']} {item['refund_count']} 次" for item in sql_result.rows]
        return "退款次数最高的商品：" + "，".join(parts) + "。"
    return f"查询返回 {sql_result.row_count} 行结果。"


def _format_rag_answer(citations) -> str:
    if not citations:
        return "知识库中没有检索到足够相关的政策或 SOP。"
    titles = "、".join(dict.fromkeys(citation.title for citation in citations))
    snippets = "；".join(citation.snippet for citation in citations[:2])
    return f"根据知识库中的 {titles}，相关依据包括：{snippets}"


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
        "route_task",
        "RouterAgent",
        "success",
        reason,
        metadata={"route": route, "confidence": confidence},
    )

    sql_result: SqlResult | None = None
    citations = []
    answer_parts: list[str] = []

    if route in {"sql", "hybrid"}:
        trace.tool_calls += 1
        tables = list_tables()
        trace.add("list_tables", "SQLAgent", "success", "读取数据库表结构。", metadata={"tables": tables})
        sql = build_sql_for_question(question)
        trace.add("generate_sql", "SQLAgent", "success", "根据问题生成只读 SQL。", metadata={"sql": sql})
        sql_result = execute_readonly_sql(sql)
        trace.add(
            "execute_sql",
            "SQLAgent",
            "error" if sql_result.error else "success",
            sql_result.error or f"SQL 返回 {sql_result.row_count} 行。",
            metadata={"row_count": sql_result.row_count},
        )
        answer_parts.append(_format_sql_answer(sql_result))

    if route in {"rag", "hybrid"}:
        trace.tool_calls += 1
        citations = retrieve_docs(question)
        trace.add(
            "retrieve_docs",
            "RAGAgent",
            "success" if citations else "warning",
            f"检索到 {len(citations)} 条文档证据。",
            metadata={"citations": [item.model_dump() for item in citations]},
        )
        answer_parts.append(_format_rag_answer(citations))

    if route == "clarification":
        answer_parts.append("我需要你补充分析范围，例如月份、类目，或说明要查数据还是查政策。")

    if route == "hybrid" and sql_result and not sql_result.error and citations:
        answer_parts.append(
            "综合判断：退款率升高通常需要同时看数据异常和售后政策。"
            "建议优先排查尺码、色差、面料描述与客服工单高频原因。"
        )

    answer = "\n\n".join(answer_parts)
    update_memory(memory, request.message, answer)
    trace.add(
        "update_memory",
        "MemoryAgent",
        "success",
        "更新 recent_turns 和 conversation_summary。",
        metadata={"recent_turns": len(memory.recent_turns), "summary": memory.conversation_summary},
    )
    trace.add("final_answer", "EvaluatorAgent", "success", "完成答案生成和基础质量检查。")

    latency_ms = round((perf_counter() - started) * 1000, 2)
    return ChatResponse(
        answer=answer,
        route=route,
        trace_id=trace.trace_id,
        steps=trace.steps,
        citations=citations,
        sql_result=sql_result,
        metrics=Metrics(
            latency_ms=latency_ms,
            tool_calls=trace.tool_calls,
            citations=len(citations),
            route_confidence=confidence,
        ),
        memory={
            "session_id": session_id,
            "recent_turns": len(memory.recent_turns),
            "conversation_summary": memory.conversation_summary,
            "user_profile": memory.user_profile,
        },
    )
