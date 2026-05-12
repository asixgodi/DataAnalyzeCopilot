"use client";

import { FormEvent, useMemo, useState } from "react";
import { getApiBaseUrl } from "@/lib/api";

type TraceStep = {
  node_name: string;
  agent_role: string;
  status: string;
  detail: string;
  latency_ms: number;
  metadata: Record<string, unknown>;
};

type Citation = {
  doc_id: string;
  title: string;
  chunk_id: string;
  snippet: string;
  score: number;
};

type SqlResult = {
  sql: string;
  columns: string[];
  rows: Record<string, string | number | null>[];
  row_count: number;
  error: string | null;
};

type ChatResponse = {
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
};

const examples = [
  "4月服装类商品退款率是多少？",
  "退款率指标口径是什么？",
  "4月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。",
  "那鞋靴类呢？",
  "随便看看"
];

const routeLabels: Record<ChatResponse["route"], string> = {
  sql: "SQL 数据查询",
  rag: "RAG 知识检索",
  hybrid: "Hybrid 混合分析",
  clarification: "追问澄清"
};

export default function HomePage() {
  const apiBaseUrl = useMemo(() => getApiBaseUrl(), []);
  const [message, setMessage] = useState(examples[0]);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState("demo-session");

  async function submit(nextMessage = message) {
    const content = nextMessage.trim();
    if (!content || isLoading) return;

    setMessage(content);
    setIsLoading(true);
    setError("");

    try {
      const response = await fetch(`${apiBaseUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: content,
          session_id: sessionId
        })
      });

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      const data = (await response.json()) as ChatResponse;
      setResult(data);
      setSessionId(data.memory.session_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "请求失败，请检查后端服务是否启动。");
    } finally {
      setIsLoading(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark" aria-hidden="true">DB</span>
          <div>
            <strong>售后分析 Copilot</strong>
            <span>Agent + SQL + RAG</span>
          </div>
        </div>

        <form className="queryBox" onSubmit={onSubmit}>
          <label htmlFor="message">自然语言问题</label>
          <textarea
            id="message"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={7}
            placeholder="输入要分析的售后问题"
          />
          <button type="submit" disabled={isLoading}>
            <span className={isLoading ? "spin buttonIcon" : "buttonIcon"} aria-hidden="true">
              {isLoading ? "◌" : "↗"}
            </span>
            发送
          </button>
        </form>

        <section className="exampleList" aria-label="示例问题">
          {examples.map((item) => (
            <button key={item} type="button" onClick={() => void submit(item)}>
              <span className="buttonIcon" aria-hidden="true">▶</span>
              <span>{item}</span>
            </button>
          ))}
        </section>

        <div className="apiBox">
          <span>API</span>
          <strong>{apiBaseUrl}</strong>
        </div>
      </aside>

      <section className="workspace">
        {error ? (
          <div className="notice errorNotice">
            <span className="buttonIcon" aria-hidden="true">!</span>
            <span>{error}</span>
          </div>
        ) : null}

        <div className="answerPanel">
          {!result && !isLoading ? (
            <div className="emptyState">
              <span className="emptyIcon" aria-hidden="true">↔</span>
              <h1>把问题路由到 SQL、RAG 或混合分析链路</h1>
              <p>左侧选择一个示例，就能看到回答、SQL、文档证据、执行链路和指标。</p>
            </div>
          ) : null}

          {isLoading ? (
            <div className="emptyState">
              <span className="emptyIcon spin" aria-hidden="true">◌</span>
              <h1>Agent 正在执行</h1>
              <p>正在完成路由、工具调用、结果校验和 trace 记录。</p>
            </div>
          ) : null}

          {result ? (
            <>
              <div className="resultHeader">
                <div>
                  <span className={`routeBadge ${result.route}`}>{routeLabels[result.route]}</span>
                  <h1>分析结果</h1>
                </div>
                <dl className="metrics">
                  <div>
                    <dt>耗时</dt>
                    <dd>{result.metrics.latency_ms} ms</dd>
                  </div>
                  <div>
                    <dt>工具调用</dt>
                    <dd>{result.metrics.tool_calls}</dd>
                  </div>
                  <div>
                    <dt>置信度</dt>
                    <dd>{Math.round(result.metrics.route_confidence * 100)}%</dd>
                  </div>
                </dl>
              </div>

              <article className="answerText">{result.answer}</article>

              {result.sql_result ? (
                <section className="dataSection">
                  <div className="sectionTitle">
                    <span className="buttonIcon" aria-hidden="true">DB</span>
                    <h2>SQL 执行结果</h2>
                  </div>
                  <pre className="sqlBlock">{result.sql_result.sql}</pre>
                  {result.sql_result.error ? (
                    <p className="inlineError">{result.sql_result.error}</p>
                  ) : (
                    <div className="tableWrap">
                      <table>
                        <thead>
                          <tr>
                            {result.sql_result.columns.map((column) => (
                              <th key={column}>{column}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {result.sql_result.rows.map((row, index) => (
                            <tr key={index}>
                              {result.sql_result?.columns.map((column) => (
                                <td key={column}>{String(row[column] ?? "")}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              ) : null}

              {result.citations.length ? (
                <section className="dataSection">
                  <div className="sectionTitle">
                    <span className="buttonIcon" aria-hidden="true">§</span>
                    <h2>文档证据</h2>
                  </div>
                  <div className="citationGrid">
                    {result.citations.map((citation) => (
                      <article className="citation" key={citation.chunk_id}>
                        <div>
                          <strong>{citation.title}</strong>
                          <span>{Math.round(citation.score * 100)} 分</span>
                        </div>
                        <p>{citation.snippet}</p>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </div>
      </section>

      <aside className="tracePanel">
        <div className="sectionTitle">
          <span className="buttonIcon" aria-hidden="true">◎</span>
          <h2>执行链路</h2>
        </div>

        {result ? (
          <>
            <div className="traceMeta">
              <span>Trace ID</span>
              <strong>{result.trace_id}</strong>
            </div>
            <ol className="traceList">
              {result.steps.map((step, index) => (
                <li key={`${step.node_name}-${index}`}>
                  <div>
                    <strong>{step.agent_role}</strong>
                    <span>{step.status}</span>
                  </div>
                  <h3>{step.node_name}</h3>
                  <p>{step.detail}</p>
                </li>
              ))}
            </ol>
            <div className="memoryBox">
              <span>Memory</span>
              <p>{result.memory.conversation_summary || "暂无会话摘要"}</p>
            </div>
          </>
        ) : (
          <p className="muted">完成一次提问后，这里会展示 Router、SQL、RAG、Memory、Evaluator 的执行过程。</p>
        )}
      </aside>
    </main>
  );
}
