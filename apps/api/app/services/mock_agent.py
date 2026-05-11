from uuid import uuid4

from app.schemas.chat import ChatRequest, ChatResponse, TraceStep


def run_mock_agent(request: ChatRequest) -> ChatResponse:
    trace_id = f"trace_{uuid4().hex[:12]}"
    answer = (
        "当前是第 1 天的 mock agent。后续会替换为 LangGraph workflow，"
        "并接入 SQL tools、RAG retrieval、trace logger 和 eval harness。"
    )

    return ChatResponse(
        answer=answer,
        route="mock",
        trace_id=trace_id,
        steps=[
            TraceStep(
                node_name="receive_message",
                status="success",
                detail=f"received: {request.message}",
            ),
            TraceStep(
                node_name="mock_response",
                status="success",
                detail="returned project skeleton response",
            ),
        ],
    )
