from typing import Any

from pydantic import BaseModel, Field

from app.schemas.chat import TraceStep

# 一次请求的trace记录信息
class TraceRun(BaseModel):
    trace_id: str
    session_id: str
    request_id: str = ""
    question_summary: str = ""
    route: str = ""
    route_confidence: float = 0
    status: str = "running"
    started_at: str
    ended_at: str | None = None
    duration_ms: float = 0
    tool_calls: int = 0
    citation_count: int = 0
    error_type: str | None = None
    error_message: str | None = None
    app_version: str = "0.1.0"

# 检索的trace
class TraceRetrieval(BaseModel):
    id: int | None = None
    trace_id: str
    span_id: str
    doc_id: str
    doc_version: str | None = None
    chunk_id: str
    content_hash: str | None = None
    title: str = ""
    snippet: str = ""
    score: float = 0
    retrieval_sources: list[str] = Field(default_factory=list)
    dense_rank: int | None = None
    dense_score: float | None = None
    sparse_rank: int | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    final_rank: int | None = None
    selected_for_context: bool = True
    is_neighbor: bool = False
    source_hit: str | None = None
    matched_queries: list[str] = Field(default_factory=list)
    rag_profile: str | None = None
    router_reason: str | None = None


class TraceDetail(BaseModel):
    run: TraceRun
    spans: list[TraceStep] = Field(default_factory=list)
    retrievals: list[TraceRetrieval] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
