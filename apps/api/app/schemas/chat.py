from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class TraceStep(BaseModel):
    node_name: str
    status: str
    detail: str


class ChatResponse(BaseModel):
    answer: str
    route: str
    trace_id: str
    steps: list[TraceStep]
