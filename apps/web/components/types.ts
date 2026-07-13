export type TraceStep = {
  node_name: string;
  agent_role: string;
  status: string;
  detail: string;
  latency_ms: number;
  metadata: Record<string, unknown>;
  trace_id?: string;
  span_id?: string;
  parent_span_id?: string | null;
  sequence?: number;
  kind?: string;
  started_at?: string;
  ended_at?: string;
};

export type Citation = {
  doc_id: string;
  title: string;
  chunk_id: string;
  snippet: string;
  score: number;
  retrieval_sources?: string[];
  dense_rank?: number | null;
  sparse_rank?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
  matched_queries?: string[];
  is_neighbor?: boolean;
  source_hit?: string | null;
  rag_profile?: string | null;
  router_reason?: string | null;
};

export type TraceRun = {
  trace_id: string;
  session_id: string;
  route: string;
  route_confidence: number;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number;
  tool_calls: number;
  citation_count: number;
};

export type TraceRetrieval = Citation & {
  id: number | null;
  trace_id: string;
  span_id: string;
  final_rank: number | null;
  selected_for_context: boolean;
};

export type TraceDetail = {
  run: TraceRun;
  spans: TraceStep[];
  retrievals: TraceRetrieval[];
  metadata: Record<string, unknown>;
};

export type SqlResult = {
  sql: string;
  columns: string[];
  rows: Record<string, string | number | null>[];
  row_count: number;
  error: string | null;
};

export type ChatResponse = {
  answer: string;
  route: "sql" | "rag" | "hybrid" | "clarification";
  trace_id: string;
  steps: TraceStep[];
  citations: Citation[];
  sql_result: SqlResult | null;
  metrics: {
    latency_ms: number;
    tool_calls: number;
    citations: number;
    route_confidence: number;
  };
  memory: {
    session_id: string;
    recent_turns: number;
    conversation_summary: string;
    user_profile: Record<string, unknown>;
  };
  requires_approval?: boolean;
  approval_context?: {
    reason: string;
    sql?: string;
    risk_level: "low" | "medium" | "high";
  };
};

export type Message = {
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  isStreaming?: boolean;
};

export type Session = {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
};

export type AgentGroup = {
  agent_role: string;
  steps: TraceStep[];
};

export const routeLabels: Record<ChatResponse["route"], string> = {
  sql: "SQL 数据查询",
  rag: "RAG 知识检索",
  hybrid: "Hybrid 混合分析",
  clarification: "追问澄清",
};

/** Tracks the in-progress state while an SSE stream is being consumed. */
export type StreamingState = {
  route: string;
  routeReason: string;
  answer: string;
  statusText: string;
  sqlGenerated: boolean;
  sqlExecuting: boolean;
  sqlRowCount: number | null;
  citationCount: number | null;
  steps: TraceStep[];
};

export const initialStreamingState: StreamingState = {
  route: "",
  routeReason: "",
  answer: "",
  statusText: "思考中...",
  sqlGenerated: false,
  sqlExecuting: false,
  sqlRowCount: null,
  citationCount: null,
  steps: [],
};
