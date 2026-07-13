import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.schemas.chat import TraceStep
from app.schemas.trace import TraceRun
from app.services.trace_store import TraceStore, get_trace_store


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SpanHandle:
    span_id: str
    node_name: str
    agent_role: str
    kind: str
    parent_span_id: str | None
    sequence: int
    started_at: datetime
    started_perf: float
    metadata: dict[str, Any]


class TraceRecorder:
    """Request-scoped recorder that persists the same spans exposed to clients."""

    def __init__(
        self,
        *,
        session_id: str = "unknown",
        question_summary: str = "",
        request_id: str = "",
        store: TraceStore | None = None,
    ) -> None:
        self.trace_id = f"trace_{uuid4().hex[:12]}"
        self.steps: list[TraceStep] = []
        self.tool_calls = 0
        self._sequence = 0
        self._started_perf = perf_counter()
        self._started_at = _utc_now()
        self._finished = False
        self.store = store or get_trace_store()
        self.run = TraceRun(
            trace_id=self.trace_id,
            session_id=session_id,
            request_id=request_id,
            question_summary=question_summary.strip()[:500],
            started_at=self._started_at.isoformat(),
        )
        try:
            self.store.create_run(self.run)
        except Exception:
            logger.exception("Failed to create trace run %s", self.trace_id)

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def add(
        self,
        node_name: str,
        agent_role: str,
        status: str,
        detail: str,
        latency_ms: float = 0,
        metadata: dict[str, Any] | None = None,
        *,
        kind: str = "agent_node",
        parent_span_id: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> TraceStep:
        ended_at = _utc_now()
        safe_latency = max(float(latency_ms or 0), 0)
        started_at = ended_at - timedelta(milliseconds=safe_latency)
        step = TraceStep(
            node_name=node_name,
            agent_role=agent_role,
            status=status,
            detail=detail,
            latency_ms=round(safe_latency, 2),
            metadata=metadata or {},
            trace_id=self.trace_id,
            span_id=f"span_{uuid4().hex[:12]}",
            parent_span_id=parent_span_id,
            sequence=self._next_sequence(),
            kind=kind,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
        )
        self.steps.append(step)
        try:
            self.store.save_span(
                step,
                error_type=error_type,
                error_message=error_message,
            )
        except Exception:
            logger.exception("Failed to persist trace span %s", step.span_id)
        return step

    def start_span(
        self,
        node_name: str,
        agent_role: str,
        *,
        kind: str = "agent_node",
        parent_span_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpanHandle:
        return SpanHandle(
            span_id=f"span_{uuid4().hex[:12]}",
            node_name=node_name,
            agent_role=agent_role,
            kind=kind,
            parent_span_id=parent_span_id,
            sequence=self._next_sequence(),
            started_at=_utc_now(),
            started_perf=perf_counter(),
            metadata=metadata or {},
        )

    def finish_span(
        self,
        handle: SpanHandle,
        *,
        status: str = "success",
        detail: str = "",
        metadata: dict[str, Any] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> TraceStep:
        ended_at = _utc_now()
        merged_metadata = dict(handle.metadata)
        if metadata:
            merged_metadata.update(metadata)
        step = TraceStep(
            node_name=handle.node_name,
            agent_role=handle.agent_role,
            status=status,
            detail=detail,
            latency_ms=round((perf_counter() - handle.started_perf) * 1000, 2),
            metadata=merged_metadata,
            trace_id=self.trace_id,
            span_id=handle.span_id,
            parent_span_id=handle.parent_span_id,
            sequence=handle.sequence,
            kind=handle.kind,
            started_at=handle.started_at.isoformat(),
            ended_at=ended_at.isoformat(),
        )
        self.steps.append(step)
        try:
            self.store.save_span(
                step,
                error_type=error_type,
                error_message=error_message,
            )
        except Exception:
            logger.exception("Failed to persist trace span %s", step.span_id)
        return step

    def timed(
        self,
        node_name: str,
        agent_role: str,
        detail: str,
        fn: Callable[[], Any],
    ) -> Any:
        handle = self.start_span(node_name, agent_role)
        try:
            result = fn()
        except Exception as exc:
            self.finish_span(
                handle,
                status="error",
                detail=str(exc),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        self.finish_span(handle, status="success", detail=detail)
        return result

    def save_retrievals(
        self,
        span_id: str,
        citations: Iterable[dict[str, Any]],
    ) -> None:
        try:
            self.store.save_retrievals(self.trace_id, span_id, citations)
        except Exception:
            logger.exception("Failed to persist trace retrievals for %s", self.trace_id)

    def finish_run(
        self,
        *,
        status: str,
        route: str = "",
        route_confidence: float = 0,
        citation_count: int = 0,
        error: Exception | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        ended_at = _utc_now()
        duration_ms = round((perf_counter() - self._started_perf) * 1000, 2)
        self.run.status = status
        self.run.route = route
        self.run.route_confidence = route_confidence
        self.run.ended_at = ended_at.isoformat()
        self.run.duration_ms = duration_ms
        self.run.tool_calls = self.tool_calls
        self.run.citation_count = citation_count
        if error is not None:
            self.run.error_type = type(error).__name__
            self.run.error_message = str(error)[:1000]
        try:
            self.store.finish_run(
                self.trace_id,
                status=status,
                ended_at=self.run.ended_at,
                duration_ms=duration_ms,
                route=route,
                route_confidence=route_confidence,
                tool_calls=self.tool_calls,
                citation_count=citation_count,
                error_type=self.run.error_type,
                error_message=self.run.error_message,
            )
        except Exception:
            logger.exception("Failed to finish trace run %s", self.trace_id)
