"use client";

import { useMemo, useState } from "react";
import type { ChatResponse, Message, TraceStep, AgentGroup } from "./types";

type TracePanelProps = {
  response: ChatResponse | null;
  messages: Message[];
  selectedIndex: number;
  onSelectMessage: (index: number) => void;
};

const agentColorMap: Record<string, string> = {
  RouterAgent: "#3b82f6",
  SQLAgent: "#0f766e",
  RAGAgent: "#f59e0b",
  MemoryAgent: "#8b5cf6",
  EvaluatorAgent: "#10b981",
};

function groupSteps(steps: TraceStep[]): AgentGroup[] {
  const map = new Map<string, TraceStep[]>();
  for (const step of steps) {
    const existing = map.get(step.agent_role);
    if (existing) {
      existing.push(step);
    } else {
      map.set(step.agent_role, [step]);
    }
  }
  return Array.from(map.entries()).map(([agent_role, steps]) => ({
    agent_role,
    steps,
  }));
}

export function TracePanel({
  response,
  messages,
  selectedIndex,
  onSelectMessage,
}: TracePanelProps) {
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  function toggleNode(nodeKey: string) {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeKey)) {
        next.delete(nodeKey);
      } else {
        next.add(nodeKey);
      }
      return next;
    });
  }

  const groups = useMemo(
    () => (response ? groupSteps(response.steps) : []),
    [response],
  );

  const assistantIndices = useMemo(
    () =>
      messages
        .map((msg, idx) =>
          msg.role === "assistant" && msg.response ? idx : -1,
        )
        .filter((idx) => idx >= 0),
    [messages],
  );

  const effectiveSelectedIndex =
    selectedIndex < 0 && assistantIndices.length > 0
      ? assistantIndices[assistantIndices.length - 1]
      : selectedIndex;

  return (
    <aside className="tracePanel">
      <div className="sectionTitle">
        <span className="buttonIcon" aria-hidden="true">
          ◎
        </span>
        <h2>执行链路</h2>
      </div>

      {response ? (
        <>
          <div className="traceMeta">
            <span>Trace ID</span>
            <strong>{response.trace_id}</strong>
          </div>

          {assistantIndices.length > 1 ? (
            <div className="traceMessageSelector">
              <span className="traceSelectorLabel">选择消息</span>
              <div className="traceSelectorItems">
                {assistantIndices.map((idx) => (
                  <button
                    key={idx}
                    type="button"
                    className={`traceSelectorItem ${idx === effectiveSelectedIndex ? "active" : ""}`}
                    onClick={() => onSelectMessage(idx)}
                  >
                    #{idx + 1}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div className="traceGroups">
            {groups.map((group) => {
              const color =
                agentColorMap[group.agent_role] ?? "#6b7280";
              return (
                <div key={group.agent_role} className="traceGroup">
                  <div className="traceGroupHeader">
                    <span
                      className="traceGroupDot"
                      style={{ background: color }}
                      aria-hidden="true"
                    />
                    <strong>{group.agent_role}</strong>
                    <span className="traceGroupCount">
                      {group.steps.length} 步
                    </span>
                  </div>
                  <div className="traceTimeline">
                    {group.steps.map((step, idx) => {
                      const nodeKey = `${group.agent_role}-${idx}`;
                      const isExpanded = expandedNodes.has(nodeKey);
                      const totalSteps = group.steps.length;
                      return (
                        <div key={nodeKey} className="traceNode">
                          <div className="traceNodeLine">
                            <span
                              className="traceNodeDot"
                              style={{ borderColor: color }}
                              aria-hidden="true"
                            />
                            {idx < totalSteps - 1 ? (
                              <span
                                className="traceNodeConnector"
                                aria-hidden="true"
                              />
                            ) : null}
                          </div>
                          <div className="traceNodeContent">
                            <button
                              type="button"
                              className="traceNodeHeader"
                              onClick={() => toggleNode(nodeKey)}
                            >
                              <div className="traceNodeInfo">
                                <h4>{step.node_name}</h4>
                                <span
                                  className={`traceNodeStatus ${step.status}`}
                                >
                                  {step.status}
                                </span>
                              </div>
                              <div className="traceNodeMeta">
                                <span className="traceNodeLatency">
                                  {step.latency_ms}ms
                                </span>
                                <span
                                  className={`collapseArrow ${isExpanded ? "open" : ""}`}
                                  aria-hidden="true"
                                >
                                  ▾
                                </span>
                              </div>
                            </button>
                            {step.detail ? (
                              <p className="traceNodeDetail">
                                {step.detail}
                              </p>
                            ) : null}
                            {isExpanded ? (
                              <div className="traceNodeExpanded">
                                <pre className="metadataJson">
                                  {JSON.stringify(step.metadata, null, 2)}
                                </pre>
                              </div>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          <div className="memoryBox">
            <span>Memory</span>
            <p>
              {response.memory.conversation_summary || "暂无会话摘要"}
            </p>
          </div>
        </>
      ) : (
        <p className="muted">
          完成一次提问后，这里会展示 Router、SQL、RAG、Memory、Evaluator
          的执行过程。
        </p>
      )}
    </aside>
  );
}
