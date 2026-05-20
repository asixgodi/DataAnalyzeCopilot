from fastapi import APIRouter

from app.schemas.chat import ApprovalRequest, ChatRequest, ChatResponse
from app.services.agent import run_agent
from app.services.eval_runner import run_eval

router = APIRouter()


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
