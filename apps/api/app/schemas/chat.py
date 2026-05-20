from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class ApprovalRequest(BaseModel):
    session_id: str
    approved: bool


class Citation(BaseModel):
    doc_id: str
    title: str
    chunk_id: str
    snippet: str
    score: float


class SqlResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    error: str | None = None


class TraceStep(BaseModel):
    node_name: str
    agent_role: str = "system"
    status: str
    detail: str
    latency_ms: float = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalContext(BaseModel):
    reason: str
    sql: str | None = None
    risk_level: str = "low"


class Metrics(BaseModel):
    latency_ms: float
    tool_calls: int
    citations: int
    route_confidence: float


class MemoryInfo(BaseModel):
    session_id: str
    recent_turns: int
    conversation_summary: str
    user_profile: dict[str, str]


class ChatResponse(BaseModel):
    answer: str
    route: str
    trace_id: str
    steps: list[TraceStep]
    citations: list[Citation] = Field(default_factory=list)
    sql_result: SqlResult | None = None
    metrics: Metrics
    memory: MemoryInfo
    requires_approval: bool = False
    approval_context: ApprovalContext | None = None
