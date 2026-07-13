"""
JSON 结构化日志 — 为 Agent 可观测性提供标准化的日志格式。

每条日志都包含：
  - trace_id: 关联到一次完整的 Agent 执行
  - span_id: 关联到一个具体的 Node / 工具调用
  - timestamp: ISO 8601 UTC 时间
  - level: info / warning / error
  - event: 事件名称（如 route_decided, llm_call, sql_executed）
  - data: 事件相关数据

集成方式：在 agent.py 的关键节点调用 slog.info / slog.warning / slog.error。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class StructuredLogger:
    """
    结构化 JSON 日志器。

    用法：
        slog = StructuredLogger("agent")
        slog.set_trace("trace_abc123")
        slog.start_span("classify_intent")
        slog.info("route_decided", route="sql", confidence=0.92, latency_ms=15)
        slog.end_span()
    """

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
        self._trace_id: str = "none"
        self._span_stack: list[str] = []

    def set_trace(self, trace_id: str) -> None:
        self._trace_id = trace_id

    def start_span(self, span_name: str) -> str:
        span_id = f"{span_name}_{uuid4().hex[:6]}"
        self._span_stack.append(span_id)
        return span_id

    def end_span(self) -> None:
        if self._span_stack:
            self._span_stack.pop()

    @property
    def current_span(self) -> str:
        return self._span_stack[-1] if self._span_stack else "root"

    def _emit(self, level: str, event: str, data: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "trace_id": self._trace_id,
            "span_id": self.current_span,
            "event": event,
        }
        if data:
            record["data"] = data
        log_fn = getattr(self._logger, level.lower(), self._logger.info)
        log_fn(json.dumps(record, ensure_ascii=False))

    def info(self, event: str, **data: Any) -> None:
        self._emit("info", event, data)

    def warning(self, event: str, **data: Any) -> None:
        self._emit("warning", event, data)

    def error(self, event: str, **data: Any) -> None:
        self._emit("error", event, data)


# ── 全局实例 ─────────────────────────────────────────────────────────

slog = StructuredLogger("agent")
