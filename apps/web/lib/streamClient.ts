// SSE event types matching the backend
export interface RouteEvent {
  route: string;
  reason: string;
  confidence: number;
}

export interface SqlResultEvent {
  sql: string;
  columns: string[];
  row_count: number;
}

export interface RetrievalEvent {
  citation_count: number;
  profile: string;
}

export interface MetricsEvent {
  latency_ms: number;
  tool_calls: number;
  citations: number;
  route_confidence: number;
}

export interface DoneEvent {
  trace_id: string;
  session_id: string;
}

export interface StreamCallbacks {
  onRoute: (data: RouteEvent) => void;
  onSqlGenerated: (data: { sql: string }) => void;
  onSqlResult: (data: SqlResultEvent) => void;
  onRetrieval: (data: RetrievalEvent) => void;
  onAnswerDelta: (delta: string) => void;
  onTrace: (step: any) => void;
  onMetrics: (data: MetricsEvent) => void;
  onDone: (data: DoneEvent) => void;
  onError: (error: string) => void;
  onStart?: () => void;
}

// 解析 SSE 事件的辅助函数
function parseSSEEvent(raw: string): { event: string; data: any } | null {
  let eventType = "message";
  let dataStr = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      dataStr = line.slice(6);
    }
  }
  if (!dataStr) return null;
  try {
    return { event: eventType, data: JSON.parse(dataStr) };
  } catch {
    return null;
  }
}

export async function streamChat(
  apiBaseUrl: string,
  request: { message: string; session_id?: string; approved?: boolean },
  callbacks: StreamCallbacks
): Promise<AbortController> {
  const controller = new AbortController();

  try {
    const response = await fetch(`${apiBaseUrl}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    if (!response.ok) {
      callbacks.onError(`HTTP ${response.status}`);
      return controller;
    }

    callbacks.onStart?.();

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const parsed = parseSSEEvent(part);
        if (!parsed) continue;

        switch (parsed.event) {
          case "route":
            callbacks.onRoute(parsed.data);
            break;
          case "sql_generated":
            callbacks.onSqlGenerated(parsed.data);
            break;
          case "sql_result":
            callbacks.onSqlResult(parsed.data);
            break;
          case "retrieval":
            callbacks.onRetrieval(parsed.data);
            break;
          case "answer_delta":
            callbacks.onAnswerDelta(parsed.data.delta || "");
            break;
          case "trace":
            callbacks.onTrace(parsed.data);
            break;
          case "metrics":
            callbacks.onMetrics(parsed.data);
            break;
          case "done":
            callbacks.onDone(parsed.data);
            break;
          case "error":
            callbacks.onError(parsed.data.message || "Unknown error");
            break;
        }
      }
    }
  } catch (err: any) {
    if (err.name !== "AbortError") {
      callbacks.onError(err.message || "Stream failed");
    }
  }

  return controller;
}
