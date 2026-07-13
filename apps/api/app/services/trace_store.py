import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings
from app.schemas.chat import TraceStep
from app.schemas.trace import TraceDetail, TraceRetrieval, TraceRun


class TraceStore:
    """SQLite-backed authoritative storage for trace runs and spans."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or settings.resolve_api_path(settings.trace_database_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trace_runs (
                    trace_id          TEXT PRIMARY KEY,
                    session_id        TEXT NOT NULL,
                    request_id        TEXT NOT NULL DEFAULT '',
                    question_summary  TEXT NOT NULL DEFAULT '',
                    route             TEXT NOT NULL DEFAULT '',
                    route_confidence  REAL NOT NULL DEFAULT 0,
                    status            TEXT NOT NULL,
                    started_at        TEXT NOT NULL,
                    ended_at          TEXT,
                    duration_ms       REAL NOT NULL DEFAULT 0,
                    tool_calls        INTEGER NOT NULL DEFAULT 0,
                    citation_count    INTEGER NOT NULL DEFAULT 0,
                    error_type        TEXT,
                    error_message     TEXT,
                    app_version       TEXT NOT NULL DEFAULT '0.1.0'
                );

                CREATE TABLE IF NOT EXISTS trace_spans (
                    span_id           TEXT PRIMARY KEY,
                    trace_id          TEXT NOT NULL,
                    parent_span_id    TEXT,
                    sequence          INTEGER NOT NULL,
                    node_name         TEXT NOT NULL,
                    kind              TEXT NOT NULL,
                    agent_role        TEXT NOT NULL,
                    status            TEXT NOT NULL,
                    started_at        TEXT NOT NULL,
                    ended_at          TEXT NOT NULL,
                    duration_ms       REAL NOT NULL DEFAULT 0,
                    detail            TEXT NOT NULL DEFAULT '',
                    metadata_json     TEXT NOT NULL DEFAULT '{}',
                    error_type        TEXT,
                    error_message     TEXT,
                    FOREIGN KEY(trace_id) REFERENCES trace_runs(trace_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS trace_retrievals (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id             TEXT NOT NULL,
                    span_id              TEXT NOT NULL,
                    doc_id               TEXT NOT NULL,
                    doc_version          TEXT,
                    chunk_id             TEXT NOT NULL,
                    content_hash         TEXT,
                    title                TEXT NOT NULL DEFAULT '',
                    snippet              TEXT NOT NULL DEFAULT '',
                    score                REAL NOT NULL DEFAULT 0,
                    retrieval_sources    TEXT NOT NULL DEFAULT '[]',
                    dense_rank            INTEGER,
                    dense_score           REAL,
                    sparse_rank           INTEGER,
                    bm25_score            REAL,
                    rrf_score             REAL,
                    rerank_score          REAL,
                    final_rank            INTEGER,
                    selected_for_context  INTEGER NOT NULL DEFAULT 1,
                    is_neighbor           INTEGER NOT NULL DEFAULT 0,
                    source_hit            TEXT,
                    matched_queries       TEXT NOT NULL DEFAULT '[]',
                    rag_profile           TEXT,
                    router_reason         TEXT,
                    FOREIGN KEY(trace_id) REFERENCES trace_runs(trace_id) ON DELETE CASCADE,
                    FOREIGN KEY(span_id) REFERENCES trace_spans(span_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_trace_runs_session_started
                    ON trace_runs(session_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_trace_spans_trace_sequence
                    ON trace_spans(trace_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_trace_retrievals_trace
                    ON trace_retrievals(trace_id, final_rank);
                """
            )

    def create_run(self, run: TraceRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_runs (
                    trace_id, session_id, request_id, question_summary, route,
                    route_confidence, status, started_at, ended_at, duration_ms,
                    tool_calls, citation_count, error_type, error_message, app_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.trace_id, run.session_id, run.request_id, run.question_summary,
                    run.route, run.route_confidence, run.status, run.started_at,
                    run.ended_at, run.duration_ms, run.tool_calls, run.citation_count,
                    run.error_type, run.error_message, run.app_version,
                ),
            )

    def save_span(
        self,
        step: TraceStep,
        *,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_spans (
                    span_id, trace_id, parent_span_id, sequence, node_name, kind,
                    agent_role, status, started_at, ended_at, duration_ms, detail,
                    metadata_json, error_type, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.span_id, step.trace_id, step.parent_span_id, step.sequence,
                    step.node_name, step.kind, step.agent_role, step.status,
                    step.started_at, step.ended_at, step.latency_ms, step.detail,
                    json.dumps(step.metadata, ensure_ascii=False, default=str),
                    error_type, error_message,
                ),
            )

    def finish_run(
        self,
        trace_id: str,
        *,
        status: str,
        ended_at: str,
        duration_ms: float,
        route: str = "",
        route_confidence: float = 0,
        tool_calls: int = 0,
        citation_count: int = 0,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trace_runs
                SET status = ?, ended_at = ?, duration_ms = ?, route = ?,
                    route_confidence = ?, tool_calls = ?, citation_count = ?,
                    error_type = ?, error_message = ?
                WHERE trace_id = ?
                """,
                (
                    status, ended_at, duration_ms, route, route_confidence,
                    tool_calls, citation_count, error_type, error_message, trace_id,
                ),
            )

    def save_retrievals(
        self,
        trace_id: str,
        span_id: str,
        citations: Iterable[dict[str, Any]],
    ) -> None:
        rows = []
        for final_rank, citation in enumerate(citations, start=1):
            rows.append(
                (
                    trace_id, span_id, str(citation.get("doc_id", "unknown")),
                    citation.get("doc_version"), str(citation.get("chunk_id", "")),
                    citation.get("content_hash"), str(citation.get("title", "")),
                    str(citation.get("snippet", ""))[:500], float(citation.get("score", 0) or 0),
                    json.dumps(citation.get("retrieval_sources", []), ensure_ascii=False),
                    citation.get("dense_rank"), citation.get("dense_score"),
                    citation.get("sparse_rank"), citation.get("bm25_score"),
                    citation.get("rrf_score"), citation.get("rerank_score"),
                    final_rank, 1, int(bool(citation.get("is_neighbor", False))),
                    citation.get("source_hit"),
                    json.dumps(citation.get("matched_queries", []), ensure_ascii=False),
                    citation.get("rag_profile"), citation.get("router_reason"),
                )
            )
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO trace_retrievals (
                    trace_id, span_id, doc_id, doc_version, chunk_id, content_hash,
                    title, snippet, score, retrieval_sources, dense_rank, dense_score,
                    sparse_rank, bm25_score, rrf_score, rerank_score, final_rank,
                    selected_for_context, is_neighbor, source_hit, matched_queries,
                    rag_profile, router_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_trace(self, trace_id: str) -> TraceDetail | None:
        with self._connect() as conn:
            run_row = conn.execute(
                "SELECT * FROM trace_runs WHERE trace_id = ?", (trace_id,)
            ).fetchone()
            if run_row is None:
                return None
            span_rows = conn.execute(
                "SELECT * FROM trace_spans WHERE trace_id = ? ORDER BY sequence",
                (trace_id,),
            ).fetchall()
            retrieval_rows = conn.execute(
                "SELECT * FROM trace_retrievals WHERE trace_id = ? ORDER BY final_rank, id",
                (trace_id,),
            ).fetchall()

        run = TraceRun(**dict(run_row))
        spans = [
            TraceStep(
                node_name=row["node_name"],
                agent_role=row["agent_role"],
                status=row["status"],
                detail=row["detail"],
                latency_ms=row["duration_ms"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                trace_id=row["trace_id"],
                span_id=row["span_id"],
                parent_span_id=row["parent_span_id"],
                sequence=row["sequence"],
                kind=row["kind"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
            )
            for row in span_rows
        ]
        retrievals = [
            TraceRetrieval(
                **{
                    **dict(row),
                    "retrieval_sources": json.loads(row["retrieval_sources"] or "[]"),
                    "matched_queries": json.loads(row["matched_queries"] or "[]"),
                    "selected_for_context": bool(row["selected_for_context"]),
                    "is_neighbor": bool(row["is_neighbor"]),
                }
            )
            for row in retrieval_rows
        ]
        return TraceDetail(run=run, spans=spans, retrievals=retrievals)


@lru_cache(maxsize=1)
def get_trace_store() -> TraceStore:
    return TraceStore()
