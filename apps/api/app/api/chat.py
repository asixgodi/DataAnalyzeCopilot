from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent import run_agent
from app.services.eval_runner import run_eval

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return run_agent(request)


@router.post("/eval/run")
def eval_run() -> dict[str, object]:
    return run_eval()
