"use client";

import { useState } from "react";
import type { ChatResponse, Message } from "./types";
import { routeLabels } from "./types";

type ChatBubbleProps = {
  message: Message;
  messageIndex: number;
  isSelected: boolean;
  onSelect: () => void;
  onApprove: (approved: boolean) => void;
};

export function ChatBubble({
  message,
  isSelected,
  onSelect,
  onApprove,
}: ChatBubbleProps) {
  const [sqlExpanded, setSqlExpanded] = useState(true);
  const [citationsExpanded, setCitationsExpanded] = useState(true);

  if (message.role === "user") {
    return (
      <div className="chatBubble user">
        <div className="bubbleContent userContent">
          <p className="userText">{message.content}</p>
        </div>
      </div>
    );
  }

  const response = message.response;

  return (
    <div
      className={`chatBubble assistant ${isSelected ? "selected" : ""}`}
      onClick={onSelect}
    >
      <div className="bubbleContent assistantContent">
        {response ? (
          <>
            <div className="bubbleHeader">
              <span className={`routeBadge ${response.route}`}>
                {routeLabels[response.route]}
              </span>
              <span className="bubbleLatency">
                {response.metrics.latency_ms}ms
              </span>
            </div>

            <div className="bubbleAnswer">{response.answer}</div>

            {response.sql_result ? (
              <div className="collapsibleSection">
                <button
                  type="button"
                  className="collapsibleHeader"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSqlExpanded((v) => !v);
                  }}
                >
                  <span className="buttonIcon" aria-hidden="true">
                    DB
                  </span>
                  <span>SQL 执行结果</span>
                  <span
                    className={`collapseArrow ${sqlExpanded ? "open" : ""}`}
                    aria-hidden="true"
                  >
                    ▾
                  </span>
                </button>
                {sqlExpanded ? (
                  <div className="collapsibleContent">
                    <pre className="sqlBlock">{response.sql_result.sql}</pre>
                    {response.sql_result.error ? (
                      <p className="inlineError">
                        {response.sql_result.error}
                      </p>
                    ) : (
                      <div className="tableWrap">
                        <table>
                          <thead>
                            <tr>
                              {response.sql_result.columns.map((column) => (
                                <th key={column}>{column}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {response.sql_result.rows.map((row, index) => (
                              <tr key={index}>
                                {response.sql_result!.columns.map((column) => (
                                  <td key={column}>
                                    {String(row[column] ?? "")}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
            ) : null}

            {response.citations.length > 0 ? (
              <div className="collapsibleSection">
                <button
                  type="button"
                  className="collapsibleHeader"
                  onClick={(e) => {
                    e.stopPropagation();
                    setCitationsExpanded((v) => !v);
                  }}
                >
                  <span className="buttonIcon" aria-hidden="true">
                    §
                  </span>
                  <span>文档引用 ({response.citations.length})</span>
                  <span
                    className={`collapseArrow ${citationsExpanded ? "open" : ""}`}
                    aria-hidden="true"
                  >
                    ▾
                  </span>
                </button>
                {citationsExpanded ? (
                  <div className="collapsibleContent">
                    <div className="citationGrid">
                      {response.citations.map((citation) => (
                        <article
                          className="citation"
                          key={citation.chunk_id}
                        >
                          <div>
                            <strong>{citation.title}</strong>
                            <span>
                              {Math.round(citation.score * 100)} 分
                            </span>
                          </div>
                          <p>{citation.snippet}</p>
                        </article>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}

            {response.requires_approval ? (
              <div
                className="approvalCard"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="approvalHeader">
                  <span className="approvalIcon" aria-hidden="true">
                    !
                  </span>
                  <div>
                    <strong>需要审批</strong>
                    <span
                      className={`riskBadge ${response.approval_context?.risk_level ?? "low"}`}
                    >
                      {response.approval_context?.risk_level ?? "low"} 风险
                    </span>
                  </div>
                </div>
                {response.approval_context ? (
                  <div className="approvalContext">
                    <p className="approvalReason">
                      {response.approval_context.reason}
                    </p>
                    {response.approval_context.sql ? (
                      <pre className="sqlBlock approvalSql">
                        {response.approval_context.sql}
                      </pre>
                    ) : null}
                  </div>
                ) : null}
                <div className="approvalActions">
                  <button
                    type="button"
                    className="approveBtn"
                    onClick={() => onApprove(true)}
                  >
                    批准
                  </button>
                  <button
                    type="button"
                    className="rejectBtn"
                    onClick={() => onApprove(false)}
                  >
                    拒绝
                  </button>
                </div>
              </div>
            ) : null}

            <div className="bubbleFooter">
              <span>工具调用 {response.metrics.tool_calls}</span>
              <span>
                置信度 {Math.round(response.metrics.route_confidence * 100)}%
              </span>
            </div>
          </>
        ) : (
          <div className="bubbleAnswer">{message.content}</div>
        )}
      </div>
    </div>
  );
}
