"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getApiBaseUrl } from "@/lib/api";
import { streamChat } from "@/lib/streamClient";
import { ChatBubble } from "@/components/ChatBubble";
import { TracePanel } from "@/components/TracePanel";
import type { ChatResponse, Message, Session, TraceStep, StreamingState } from "@/components/types";
import { initialStreamingState, routeLabels } from "@/components/types";

const examples = [
  "4月服装类商品退款率是多少？",
  "退款率指标口径是什么？",
  "4月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。",
  "那鞋靴类呢？",
  "随便看看",
];

const STORAGE_KEY = "copilot-sessions";

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function loadSessions(): Session[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session[]) : [];
  } catch {
    return [];
  }
}

function saveSessions(sessions: Session[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  } catch {
    // quota exceeded or private browsing
  }
}

// 显示当前流转中的中间状态
function StreamingBubble({ state }: { state: StreamingState }) {
  const route = state.route as ChatResponse["route"];
  const label = route ? (routeLabels[route] ?? state.route) : null;

  return (
    <div className="chatBubble assistant">
      <div className="bubbleContent assistantContent">
        {label ? (
          <div className="bubbleHeader">
            <span className={`routeBadge ${route}`}>{label}</span>
          </div>
        ) : null}

        {state.answer ? (
          <div className="bubbleAnswer">
            {state.answer}
            <span className="streamingCursor" aria-hidden="true">
              |
            </span>
          </div>
        ) : (
          <div className="loadingDots">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </div>
        )}

        <div className="bubbleFooter">
          <span>{state.statusText}</span>
        </div>
      </div>
    </div>
  );
}

export default function HomePage() {
  const apiBaseUrl = useMemo(() => getApiBaseUrl(), []);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [message, setMessage] = useState(examples[0]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedMessageIndex, setSelectedMessageIndex] = useState<number>(-1);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Streaming state
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingState, setStreamingState] = useState<StreamingState>(initialStreamingState);
  const answerRef = useRef("");
  const stepsRef = useRef<any[]>([]);
  const streamStartedRef = useRef(false);
  const routeRef = useRef("");
  const citationCountRef = useRef(0);
  // Capture metrics from the onMetrics SSE event so onDone can use real values
  const metricsRef = useRef({ latency_ms: 0, tool_calls: 0, route_confidence: 0 });

  // Load sessions from localStorage on mount
  useEffect(() => {
    const saved = loadSessions();
    setSessions(saved);
    if (saved.length > 0) {
      setCurrentSessionId(saved[0].id);
    }
  }, []);

  // Persist sessions to localStorage on change
  useEffect(() => {
    if (sessions.length > 0) {
      saveSessions(sessions);
    }
  }, [sessions]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [currentSessionId]);

  // Auto-scroll to bottom when new messages appear (tracking count)
  const currentSession = useMemo(
    () => sessions.find((s) => s.id === currentSessionId) ?? null,
    [sessions, currentSessionId],
  );

  const messages = currentSession?.messages ?? [];
  const messageCount = messages.length;

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messageCount]);

  // Auto-scroll during streaming as answer grows
  useEffect(() => {
    if (isStreaming) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [isStreaming, streamingState.answer]);

  const activeTraceResponse = useMemo(() => {
    if (
      selectedMessageIndex >= 0 &&
      selectedMessageIndex < messages.length
    ) {
      const msg = messages[selectedMessageIndex];
      return msg.role === "assistant" ? (msg.response ?? null) : null;
    }
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].response) {
        return messages[i].response!;
      }
    }
    return null;
  }, [messages, selectedMessageIndex]);

  const createNewSession = useCallback(() => {
    const newSession: Session = {
      id: generateId(),
      title: "新会话",
      messages: [],
      createdAt: Date.now(),
    };
    setSessions((prev) => [newSession, ...prev]);
    setCurrentSessionId(newSession.id);
    setMessage(examples[0]);
    setError("");
    setSelectedMessageIndex(-1);
  }, []);

  const switchSession = useCallback((sessionId: string) => {
    setCurrentSessionId(sessionId);
    setError("");
    setSelectedMessageIndex(-1);
  }, []);

  const deleteSession = useCallback(
    (sessionId: string) => {
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== sessionId);
        if (sessionId === currentSessionId) {
          if (next.length > 0) {
            setCurrentSessionId(next[0].id);
          } else {
            setCurrentSessionId("");
          }
        }
        if (next.length === 0) {
          try {
            localStorage.removeItem(STORAGE_KEY);
          } catch {
            // ignore
          }
        }
        return next;
      });
    },
    [currentSessionId],
  );

  /**
   * Core streaming+fallback chat logic shared by submit() and handleApproval().
   * Tries SSE streaming first; if the endpoint is unavailable, falls back to
   * the regular /api/chat JSON endpoint.
   */
  async function executeChat(
    sessionId: string,
    chatContent: string,
    approved?: boolean,
  ) {
    // Reset streaming accumulators
    answerRef.current = "";
    stepsRef.current = [];
    streamStartedRef.current = false;
    routeRef.current = "";
    citationCountRef.current = 0;
    setStreamingState({ ...initialStreamingState });

    let streamError = "";

    try {
      await streamChat(
        apiBaseUrl,
        {
          message: chatContent,
          session_id: sessionId,
          ...(approved !== undefined ? { approved } : {}),
        },
        {
          onStart: () => {
            streamStartedRef.current = true;
            setIsStreaming(true);
          },
          onRoute: (data) => {
            routeRef.current = data.route;
            setStreamingState((prev) => ({
              ...prev,
              route: data.route,
              routeReason: data.reason,
              statusText: `已路由到 ${data.route}`,
            }));
          },
          onSqlGenerated: (data) => {
            setStreamingState((prev) => ({
              ...prev,
              sqlGenerated: true,
              sqlExecuting: true,
              statusText: "SQL 已生成，正在执行...",
            }));
          },
          onSqlResult: (data) => {
            setStreamingState((prev) => ({
              ...prev,
              sqlExecuting: false,
              sqlRowCount: data.row_count,
              statusText: `查询完成，${data.row_count} 行结果`,
            }));
          },
          onRetrieval: (data) => {
            citationCountRef.current = data.citation_count;
            setStreamingState((prev) => ({
              ...prev,
              citationCount: data.citation_count,
              statusText: `检索到 ${data.citation_count} 条引用`,
            }));
          },
          onAnswerDelta: (delta) => {
            answerRef.current += delta;
            const currentAnswer = answerRef.current;
            setStreamingState((prev) => ({
              ...prev,
              answer: currentAnswer,
              statusText: "生成回答中...",
            }));
          },
          onTrace: (step) => {
            stepsRef.current.push(step);
          },
          onMetrics: (data) => {
            metricsRef.current = {
              latency_ms: data.latency_ms ?? 0,
              tool_calls: data.tool_calls ?? 0,
              route_confidence: data.route_confidence ?? 0,
            };
            setStreamingState((prev) => ({
              ...prev,
              statusText: `延迟 ${data.latency_ms}ms`,
            }));
          },
          onDone: (data) => {
            const m = metricsRef.current;
            const assistantMessage: Message = {
              role: "assistant",
              content: answerRef.current,
              response: {
                answer: answerRef.current,
                route: (routeRef.current || "sql") as ChatResponse["route"],
                trace_id: data.trace_id,
                steps: stepsRef.current as TraceStep[],
                citations: [],
                sql_result: null,
                metrics: {
                  latency_ms: m.latency_ms,
                  tool_calls: m.tool_calls,
                  citations: citationCountRef.current,
                  route_confidence: m.route_confidence,
                },
                memory: {
                  session_id: data.session_id,
                  recent_turns: 0,
                  conversation_summary: "",
                  user_profile: {},
                },
              },
            };

            setSessions((prev) =>
              prev.map((s) => {
                if (s.id !== sessionId) return s;
                return {
                  ...s,
                  messages: [...s.messages, assistantMessage],
                };
              }),
            );

            setIsStreaming(false);
            setSelectedMessageIndex(-1);
          },
          onError: (error) => {
            streamError = error;
          },
        },
      );
    } catch {
      streamError = "stream_exception";
    }

    // If streaming endpoint is unavailable, fall back to non-streaming /api/chat
    if (streamError && !streamStartedRef.current) {
      try {
        const response = await fetch(`${apiBaseUrl}/api/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: chatContent,
            session_id: sessionId,
            ...(approved !== undefined ? { approved } : {}),
          }),
        });

        if (!response.ok) {
          throw new Error(`API returned ${response.status}`);
        }

        const data = (await response.json()) as ChatResponse;

        const assistantMessage: Message = {
          role: "assistant",
          content: data.answer,
          response: data,
        };

        setSessions((prev) =>
          prev.map((s) => {
            if (s.id !== sessionId) return s;
            return {
              ...s,
              messages: [...s.messages, assistantMessage],
            };
          }),
        );

        setSelectedMessageIndex(-1);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "请求失败，请检查后端服务是否启动。",
        );
      }
    }

    setIsLoading(false);
  }

  async function submit(nextMessage?: string) {
    const content = (nextMessage ?? message).trim();
    if (!content || isLoading) return;

    let sessionId = currentSessionId;
    if (!sessionId) {
      const newSession: Session = {
        id: generateId(),
        title:
          content.slice(0, 30) + (content.length > 30 ? "..." : ""),
        messages: [],
        createdAt: Date.now(),
      };
      setSessions((prev) => [newSession, ...prev]);
      sessionId = newSession.id;
      setCurrentSessionId(sessionId);
    }

    setMessage(""); // 请求发送前清空输入框
    setIsLoading(true);
    setError("");

    const userMessage: Message = { role: "user", content };

    setSessions((prev) =>
      prev.map((s) => {
        if (s.id !== sessionId) return s;
        const isFirstMessage = s.messages.length === 0;
        return {
          ...s,
          title: isFirstMessage
            ? content.slice(0, 30) +
            (content.length > 30 ? "..." : "")
            : s.title,
          messages: [...s.messages, userMessage],
        };
      }),
    );

    await executeChat(sessionId, content);
  }

  async function handleApproval(approved: boolean) {
    const sessionId = currentSessionId;
    if (!sessionId) return;

    // 找到最近一条用户消息，作为重放的问题
    const lastUserMsg = [...messages].reverse().find(
      (m) => m.role === "user",
    );
    if (!lastUserMsg && !approved) {
      setError("无法找到待审批的原始问题");
      return;
    }

    if (!approved) {
      // 拒绝：直接追加一条系统消息
      const rejectMsg: Message = {
        role: "assistant",
        content: "SQL 执行已被用户拒绝，Agent 终止当前操作。",
      };
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          return { ...s, messages: [...s.messages, rejectMsg] };
        }),
      );
      return;
    }

    // 批准：用 approved=true 重新发送原问题（走流式接口）
    setIsLoading(true);
    setError("");

    await executeChat(sessionId, lastUserMsg!.content, true);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit();
  }

  return (
    <main className="appShell">
      {/* Left Sidebar */}
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark" aria-hidden="true">
            DB
          </span>
          <div>
            <strong>售后分析 Copilot</strong>
            <span>Agent + SQL + RAG</span>
          </div>
        </div>

        {/* Session List */}
        <div className="sessionSection">
          <div className="sessionHeader">
            <span className="sessionLabel">会话列表</span>
            <button
              type="button"
              className="newSessionBtn"
              onClick={createNewSession}
              title="新建会话"
            >
              +
            </button>
          </div>
          <div className="sessionList">
            {sessions.length === 0 ? (
              <p className="sessionEmpty">暂无会话，点击 + 新建</p>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  className={`sessionItem ${session.id === currentSessionId ? "active" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => switchSession(session.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      switchSession(session.id);
                    }
                  }}
                >
                  <span className="sessionItemTitle">
                    {session.title}
                  </span>
                  <span
                    className="sessionDeleteBtn"
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(session.id);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.stopPropagation();
                        e.preventDefault();
                        deleteSession(session.id);
                      }
                    }}
                    title="删除会话"
                  >
                    x
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Example questions */}
        <section
          className="exampleList"
          aria-label="示例问题"
        >
          {examples.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => void submit(item)}
            >
              <span className="buttonIcon" aria-hidden="true">
                ▶
              </span>
              <span>{item}</span>
            </button>
          ))}
        </section>

        <div className="apiBox">
          <span>API</span>
          <strong>{apiBaseUrl}</strong>
        </div>
      </aside>

      {/* Center: Chat Area */}
      <section className="workspace">
        {error ? (
          <div className="notice errorNotice">
            <span className="buttonIcon" aria-hidden="true">
              !
            </span>
            <span>{error}</span>
          </div>
        ) : null}

        <div className="answerPanel chatPanel">
          {!currentSessionId ? (
            <div className="emptyState">
              <span className="emptyIcon" aria-hidden="true">
                +
              </span>
              <h1>创建或选择一个会话开始分析</h1>
              <p>
                点击左侧 + 按钮新建会话，然后输入你的售后数据问题。
              </p>
            </div>
          ) : messages.length === 0 && !isLoading ? (
            <div className="emptyState">
              <span className="emptyIcon" aria-hidden="true">
                ↔
              </span>
              <h1>把问题路由到 SQL、RAG 或混合分析链路</h1>
              <p>
                在下方输入问题或从左侧选择一个示例，就能看到回答、SQL、文档证据、执行链路和指标。
              </p>
            </div>
          ) : (
            <div className="chatContainer">
              <div className="chatMessages">
                {messages.map((msg, index) => (
                  <ChatBubble
                    key={index}
                    message={msg}
                    messageIndex={index}
                    isSelected={index === selectedMessageIndex}
                    onSelect={() =>
                      setSelectedMessageIndex(index)
                    }
                    onApprove={handleApproval}
                  />
                ))}
                {isLoading &&
                  messages[messages.length - 1]?.role ===
                  "user" ? (
                  isStreaming ? (
                    <StreamingBubble state={streamingState} />
                  ) : (
                    <div className="chatBubble assistant loadingBubble">
                      <div className="bubbleContent assistantContent">
                        <div className="loadingDots">
                          <span>.</span>
                          <span>.</span>
                          <span>.</span>
                        </div>
                      </div>
                    </div>
                  )
                ) : null}
                <div ref={chatEndRef} />
              </div>

              {currentSessionId ? (
                <form
                  className="chatInput"
                  onSubmit={onSubmit}
                >
                  <textarea
                    id="message"
                    value={message}
                    onChange={(event) =>
                      setMessage(event.target.value)
                    }
                    rows={3}
                    placeholder="输入要分析的售后问题"
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey
                      ) {
                        e.preventDefault();
                        void submit();
                      }
                    }}
                  />
                  <button
                    type="submit"
                    disabled={isLoading}
                  >
                    <span
                      className={
                        isLoading
                          ? "spin buttonIcon"
                          : "buttonIcon"
                      }
                      aria-hidden="true"
                    >
                      {isLoading ? "◌" : "↗"}
                    </span>
                    发送
                  </button>
                </form>
              ) : null}
            </div>
          )}
        </div>
      </section>

      {/* Right: Trace Panel */}
      <TracePanel
        response={activeTraceResponse}
        messages={messages}
        selectedIndex={selectedMessageIndex}
        onSelectMessage={setSelectedMessageIndex}
      />
    </main>
  );
}
