import json
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter
# 引入 StreamingResponse 以支持 SSE 流式响应，将数据分块逐步发送给客户端
from fastapi.responses import StreamingResponse

from app.schemas.chat import ApprovalRequest, ChatRequest, ChatResponse
from app.services.agent import (
    InputGuard,
    OutputGuard,
    TraceRecorder,
    _classify_question,
    _init_state,
    build_graph,
    run_agent,
)
from app.services.eval_runner import run_eval
from app.services.memory import (
    build_context,
    get_memory,
    resolve_followup,
    update_memory,
)
from app.services.structured_log import slog

router = APIRouter()


# ── SSE Helper ────────────────────────────────────────────────────────


def _sse_event(event_type: str, data: dict) -> str:
    """格式化一条 SSE 事件。"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── Existing Endpoints (unchanged) ────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """主对话端点：接收自然语言问题，返回分析结果。"""
    return run_agent(request)


@router.post("/chat/approve")
def approve(approval: ApprovalRequest) -> dict[str, object]:
    """人工审批端点：批准或拒绝高风险操作。"""
    return {
        "session_id": approval.session_id,
        "approved": approval.approved,
        "status": "approved" if approval.approved else "rejected",
        "message": (
            "操作已批准，Agent 将继续执行。"
            if approval.approved
            else "操作已拒绝，Agent 将终止当前任务。"
        ),
    }


@router.post("/eval/run")
def eval_run() -> dict[str, object]:
    """触发评估运行，返回指标汇总和逐条结果。"""
    return run_eval()


# ── SSE Streaming Endpoint ────────────────────────────────────────────


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式对话端点 — 逐步推送 Agent 执行事件和答案。"""
    return StreamingResponse(
        _stream_agent_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_agent_events(request: ChatRequest):
    """异步生成器 — 逐步执行 Agent 流水线并逐条推送 SSE 事件。"""
    started = perf_counter()
    session_id = request.session_id or f"session_{uuid4().hex[:8]}"
    trace = TraceRecorder(
        session_id=session_id,
        question_summary=request.message,
    )

    # ── 1. Load memory 
    memory = get_memory(session_id)

    # ── 2. Input Guard 输入安全检查
    input_guard = InputGuard()
    guard_result = input_guard.check(request.message)
    if not guard_result.passed:
        slog.warning("input_guard_rejected", session_id=session_id, reason=guard_result.reason)
        guard_step = trace.add(
            "input_guard",
            "ChatAgent",
            "error",
            guard_result.reason or "输入安全检查未通过。",
            kind="guard",
        )
        trace.finish_run(status="error", route="clarification")
        yield _sse_event("trace", guard_step.model_dump())
        yield _sse_event("error", {
            "message": guard_result.reason or "抱歉，您的输入包含不合规内容，请重新描述您的问题。",
        })
        yield _sse_event("done", {"trace_id": trace.trace_id, "session_id": session_id})
        return

    # 使用经过清理的输入，并进行指代消解
    request_message = guard_result.sanitized_input or request.message
    question = resolve_followup(request_message.strip(), memory)

    slog.set_trace(trace.trace_id)
    receive_step = trace.add(
        "receive_message",
        "ChatAgent",
        "success",
        "收到用户问题并加载会话记忆。",
        metadata={"session_id": session_id, "resolved_question": question},
    )
    yield _sse_event("trace", receive_step.model_dump())

    # ── 3. Classify question & yield "route" event ───────────────────
    prompt_ctx = build_context(memory)
    recent_turns = prompt_ctx.get("recent_turns", [])
    route, reason, confidence = _classify_question(question, recent_turns=recent_turns)

    classify_step = trace.add(
        "classify_intent",
        "RouterAgent",
        "success",
        reason,
        metadata={"route": route, "confidence": confidence},
    )
    yield _sse_event("trace", classify_step.model_dump())

    yield _sse_event("route", {
        "route": route,
        "reason": reason,
        "confidence": confidence,
    })

    # ── 4. Execute graph with stream() ───────────────────────────────
    graph = build_graph()
    config = {"configurable": {"thread_id": session_id}}

    if request.approved:
        approval_step = trace.add(
            "approval_received",
            "EvaluatorAgent",
            "success",
            "用户已批准 SQL 执行，恢复挂起的 Graph。",
        )
        yield _sse_event("trace", approval_step.model_dump())
        from langgraph.types import Command
        stream_iter = graph.stream(Command(resume={"approved": True}), config, stream_mode="updates")
    else:
        initial = _init_state(question, session_id, prompt_ctx)
        initial["route"] = route
        initial["route_reason"] = reason
        initial["route_confidence"] = confidence
        stream_iter = graph.stream(initial, config, stream_mode="updates")

    # Track intermediate data for the metrics event
    final_citations: list[dict] = []
    hitl_interrupted = False
    rag_hit = False
    last_node_event_at = perf_counter()

    for event in stream_iter:
        # ── Handle HITL interrupt ────────────────────────────────────
        if "__interrupt__" in event:
            hitl_interrupted = True
            interrupt_info = event["__interrupt__"]
            if isinstance(interrupt_info, list) and interrupt_info:
                interrupt_info = interrupt_info[0]
            interrupt_value = (
                interrupt_info.value if hasattr(interrupt_info, "value") else interrupt_info
            )

            interrupted_step = trace.add(
                "hitl_interrupted",
                "EvaluatorAgent",
                "success",
                "图已挂起，等待用户审批。",
                metadata={"interrupt": interrupt_value},
            )
            yield _sse_event("trace", interrupted_step.model_dump())

            yield _sse_event("approval_needed", {
                "reason": interrupt_value.get("reason", "需要人工审批"),
                "sql": interrupt_value.get("sql", ""),
                "risk": interrupt_value.get("risk", "dangerous"),
            })
            break

        # ── Process per-node updates ─────────────────────────────────
        for node_name, node_state in event.items():
            if not isinstance(node_state, dict):
                continue

            # Map LangGraph node names to agent roles for the TracePanel
            _node_role_map: dict[str, str] = {
                "classify_intent": "RouterAgent",
                "sql_retrieve_schema": "SQLAgent",
                "sql_generate": "SQLAgent",
                "sql_validate": "SQLAgent",
                "sql_risk_check": "EvaluatorAgent",
                "sql_execute": "SQLAgent",
                "sql_reflect": "SQLAgent",
                "format_sql_answer": "SQLAgent",
                "rag_retrieve": "RAGAgent",
                "format_rag_answer": "RAGAgent",
                "hybrid_run": "EvaluatorAgent",
                "hybrid_merge": "EvaluatorAgent",
                "clarification": "RouterAgent",
                "generate_final": "EvaluatorAgent",
            }

            # Build per-node detail + metadata from node_state
            _node_detail = f"执行节点: {node_name}"
            _node_meta: dict = {}
            _node_status = "success"

            if node_name == "classify_intent":
                if node_state.get("route"):
                    _node_detail = f"路由至 {node_state['route']}"
                    _node_meta = {"route": node_state["route"], "confidence": node_state.get("route_confidence", 0), "reason": node_state.get("route_reason", "")}
            elif node_name == "sql_generate":
                sql = node_state.get("sql", "")
                if sql:
                    _node_detail = "生成 SQL 查询"
                    _node_meta = {
                        "sql": sql[:200],
                        "query_params": node_state.get("query_params", {}),
                    }
            elif node_name == "sql_validate":
                err = node_state.get("sql_error")
                _node_detail = "SQL 校验通过" if not err else f"SQL 校验失败: {err}"
                _node_status = "error" if err else "success"
                if err:
                    _node_meta = {"error": err}
            elif node_name == "sql_risk_check":
                risk_info = node_state.get("sql_risk")
                _node_detail = f"风险评估: {risk_info.get('level', 'low')}" if risk_info else "风险评估通过"
                if risk_info:
                    _node_meta = {"level": risk_info.get("level"), "reason": risk_info.get("reason", "")}
            elif node_name == "sql_execute":
                rows = node_state.get("sql_row_count", 0)
                err = node_state.get("sql_error")
                if err:
                    _node_detail = f"SQL 执行错误: {err[:80]}"
                    _node_status = "error"
                    _node_meta = {"error": err}
                else:
                    _node_detail = f"返回 {rows} 行数据"
                    _node_meta = {
                        "row_count": rows,
                        "columns": node_state.get("sql_columns", []),
                        "metric": node_state.get("query_params", {}).get("metric"),
                    }
            elif node_name == "sql_reflect":
                _node_detail = f"第 {node_state.get('sql_retry_count', 0)} 次重试，分析错误并修正 SQL"
            elif node_name == "format_sql_answer":
                text = node_state.get("answer_text", "")
                _node_detail = "SQL 结果已格式化"
                _node_meta = {"answer_preview": text[:120]}
            elif node_name == "rag_retrieve":
                cites = node_state.get("citations_data", [])
                _node_detail = f"检索到 {len(cites)} 条文档"
                _node_meta = {"citation_count": len(cites)}
            elif node_name == "format_rag_answer":
                _node_detail = "RAG 答案已生成"
            elif node_name == "hybrid_run":
                sql_rows = node_state.get("sql_row_count", 0)
                cites = node_state.get("citations_data", [])
                _node_detail = f"混合查询: SQL {sql_rows} 行 + 检索 {len(cites)} 条"
                _node_meta = {"sql_row_count": sql_rows, "citation_count": len(cites)}
            elif node_name == "hybrid_merge":
                _node_detail = "合并证据生成综合分析"
            elif node_name == "clarification":
                _node_detail = "生成追问"
            elif node_name == "generate_final":
                _node_detail = "完成"

            trace_step = None
            if node_name != "classify_intent":
                node_completed_at = perf_counter()
                node_latency_ms = (node_completed_at - last_node_event_at) * 1000
                last_node_event_at = node_completed_at
                trace_step = trace.add(
                    node_name,
                    _node_role_map.get(node_name, "EvaluatorAgent"),
                    _node_status,
                    _node_detail,
                    latency_ms=node_latency_ms,
                    metadata=_node_meta,
                    kind="langgraph_node",
                    error_type="NodeExecutionError" if _node_status == "error" else None,
                    error_message=_node_detail if _node_status == "error" else None,
                )
                yield _sse_event("trace", trace_step.model_dump())

            # ── route (from classify_intent) ─────────────────────────
            if node_name == "classify_intent" and node_state.get("route"):
                yield _sse_event("route", {
                    "route": node_state["route"],
                    "reason": node_state.get("route_reason", ""),
                    "confidence": node_state.get("route_confidence", 0),
                })

            # ── sql_generated (from sql_generate) ────────────────────
            if node_name == "sql_generate" and node_state.get("sql"):
                trace.tool_calls += 1
                yield _sse_event("sql_generated", {"sql": node_state["sql"]})

            # ── sql_result (from sql_execute) ────────────────────────
            if node_name == "sql_execute":
                cols = node_state.get("sql_columns", [])
                row_count = node_state.get("sql_row_count", 0)
                error = node_state.get("sql_error")
                if cols or row_count or error:
                    payload: dict = {
                        "columns": cols,
                        "row_count": row_count,
                    }
                    if error:
                        payload["error"] = error
                    yield _sse_event("sql_result", payload)

            # ── retrieval (from rag_retrieve / hybrid_run) ───────────
            if node_name in ("rag_retrieve", "hybrid_run") and node_state.get("citations_data"):
                final_citations = node_state["citations_data"]
                rag_hit = True
                if trace_step is not None:
                    trace.save_retrievals(trace_step.span_id, final_citations)
                yield _sse_event("retrieval", {
                    "citation_count": len(final_citations),
                })

    # Count tool calls from node execution
    if rag_hit:
        trace.tool_calls += 1

    # ── If HITL interrupted, emit done and stop ──────────────────────
    if hitl_interrupted:
        trace.finish_run(
            status="interrupted",
            route=route,
            route_confidence=confidence,
        )
        yield _sse_event("done", {
            "trace_id": trace.trace_id,
            "session_id": session_id,
            "status": "interrupted",
            "span_count": len(trace.steps),
        })
        return

    # ── 5. Retrieve final state from the graph ───────────────────────
    final_state = graph.get_state(config).values

    # ── Output Guard ─────────────────────────────────────────────────
    answer = final_state.get("answer_text", "")
    route = final_state.get("route", "sql")
    sql_rows = final_state.get("sql_rows", [])
    citations = final_state.get("citations_data", [])
    output_guard = OutputGuard()
    output_result = output_guard.check(answer=answer, route=route, sql_rows=sql_rows, citations=citations)
    if not output_result.passed:
        slog.warning("output_guard_triggered", session_id=session_id, reason=output_result.reason)
        answer = "抱歉，生成的回复内容需要审核，请稍后重试。"
    output_guard_step = trace.add(
        "output_guard",
        "EvaluatorAgent",
        "success" if output_result.passed else "warning",
        output_result.reason or "输出安全检查通过。",
        kind="guard",
    )
    yield _sse_event("trace", output_guard_step.model_dump())

    # ── Update memory ────────────────────────────────────────────────
    update_memory(memory, request_message, answer)
    memory_step = trace.add(
        "update_memory",
        "MemoryAgent",
        "success",
        "更新会话记忆。",
        metadata={"recent_turns": len(memory.recent_turns)},
        kind="memory",
    )
    yield _sse_event("trace", memory_step.model_dump())

    # ── 6. Stream answer as answer_delta events (~20 chars each) ─────
    chunk_size = 20
    for i in range(0, len(answer), chunk_size):
        chunk = answer[i : i + chunk_size]
        yield _sse_event("answer_delta", {"delta": chunk})

    # ── 7. Yield metrics and done events ─────────────────────────────
    latency_ms = round((perf_counter() - started) * 1000, 2)
    final_step = trace.add(
        "final_answer",
        "EvaluatorAgent",
        "success",
        "完成答案生成并准备结束流式响应。",
        kind="llm",
    )
    yield _sse_event("trace", final_step.model_dump())
    trace.finish_run(
        status="success",
        route=route,
        route_confidence=final_state.get("route_confidence", confidence),
        citation_count=len(final_citations),
    )
    yield _sse_event("metrics", {
        "latency_ms": latency_ms,
        "tool_calls": trace.tool_calls,
        "citations": len(final_citations),
        "route_confidence": final_state.get("route_confidence", confidence),
    })

    yield _sse_event("done", {
        "trace_id": trace.trace_id,
        "session_id": session_id,
        "status": "success",
        "span_count": len(trace.steps),
    })
