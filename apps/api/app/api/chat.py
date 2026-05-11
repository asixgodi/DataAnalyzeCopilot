from fastapi import APIRouter

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.mock_agent import run_mock_agent

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    return run_mock_agent(request)
