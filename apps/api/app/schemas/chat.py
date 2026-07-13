from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None
    approved: bool = False  # HITL 审批标记：前端批准后重放请求时设为 True


class ApprovalRequest(BaseModel):
    session_id: str
    approved: bool


class Citation(BaseModel):
    doc_id: str
    title: str
    chunk_id: str
    snippet: str
    score: float

    # ── 检索溯源 ──
    retrieval_sources: list[str] = Field(default_factory=list)   # ["dense","bm25"]
    dense_rank: int | None = None                                 # 在 dense 结果中的排名
    sparse_rank: int | None = None                                # 在 bm25 结果中的排名
    rrf_score: float | None = None                                # RRF 融合分
    rerank_score: float | None = None                             # LLM Rerank 分(1-10)
    matched_queries: list[str] = Field(default_factory=list)      # 命中哪些 MQE 变体

    # ── 上下文扩展 ──
    is_neighbor: bool = False                                     # 是否为相邻 chunk
    source_hit: str | None = None                                 # 指向主命中的 chunk_id
    rag_profile: str | None = None                                # RAG Router 选择的检索链路
    router_reason: str | None = None                              # Router 选择原因


class SqlResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    error: str | None = None

# 单个执行步骤的trace信息
class TraceStep(BaseModel):
    node_name: str
    agent_role: str = "system"
    status: str
    detail: str
    latency_ms: float = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str | None = None
    sequence: int = 0
    kind: str = "agent_node"
    started_at: str = ""
    ended_at: str = ""


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
