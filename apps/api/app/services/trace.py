from collections.abc import Callable
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.schemas.chat import TraceStep


class TraceRecorder:
    def __init__(self) -> None:
        self.trace_id = f"trace_{uuid4().hex[:12]}"
        self.steps: list[TraceStep] = []
        self.tool_calls = 0

    def add(
        self,
        node_name: str,
        agent_role: str,
        status: str,
        detail: str,
        latency_ms: float = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.steps.append(
            TraceStep(
                node_name=node_name,
                agent_role=agent_role,
                status=status,
                detail=detail,
                latency_ms=round(latency_ms, 2),
                metadata=metadata or {},
            )
        )

    def timed(
        self,
        node_name: str,
        agent_role: str,
        detail: str,
        fn: Callable[[], Any],
    ) -> Any:
        start = perf_counter()
        try:
            result = fn()
        except Exception as exc:
            self.add(
                node_name=node_name,
                agent_role=agent_role,
                status="error",
                detail=str(exc),
                latency_ms=(perf_counter() - start) * 1000,
            )
            raise
        self.add(
            node_name=node_name,
            agent_role=agent_role,
            status="success",
            detail=detail,
            latency_ms=(perf_counter() - start) * 1000,
        )
        return result
