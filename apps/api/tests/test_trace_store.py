from app.services.trace import TraceRecorder
from app.services.trace_store import TraceStore


def test_trace_recorder_persists_run_and_spans(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    recorder = TraceRecorder(
        session_id="session_test",
        question_summary="退款规则是什么？",
        store=store,
    )

    step = recorder.add(
        "classify_intent",
        "RouterAgent",
        "success",
        "路由至 rag",
        latency_ms=12.5,
        metadata={"route": "rag", "confidence": 0.95},
    )
    recorder.finish_run(
        status="success",
        route="rag",
        route_confidence=0.95,
    )

    trace = store.get_trace(recorder.trace_id)
    assert trace is not None
    assert trace.run.status == "success"
    assert trace.run.route == "rag"
    assert trace.run.session_id == "session_test"
    assert len(trace.spans) == 1
    assert trace.spans[0].span_id == step.span_id
    assert trace.spans[0].sequence == 1
    assert trace.spans[0].metadata["confidence"] == 0.95


def test_trace_recorder_persists_retrievals(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    recorder = TraceRecorder(
        session_id="session_rag",
        question_summary="退款需要哪些条件？",
        store=store,
    )
    step = recorder.add(
        "rag_retrieve",
        "RAGAgent",
        "success",
        "检索到 1 条文档",
        kind="retrieval",
    )
    recorder.save_retrievals(
        step.span_id,
        [
            {
                "doc_id": "refund-policy",
                "title": "退款规则",
                "chunk_id": "refund-policy-12",
                "snippet": "商品满足条件时可以申请退款。",
                "score": 0.91,
                "retrieval_sources": ["dense", "bm25"],
                "dense_rank": 2,
                "sparse_rank": 1,
                "rrf_score": 0.032,
                "matched_queries": ["退款条件"],
                "rag_profile": "hybrid-neighbor",
            }
        ],
    )
    recorder.finish_run(
        status="success",
        route="rag",
        citation_count=1,
    )

    trace = store.get_trace(recorder.trace_id)
    assert trace is not None
    assert trace.run.citation_count == 1
    assert len(trace.retrievals) == 1
    retrieval = trace.retrievals[0]
    assert retrieval.span_id == step.span_id
    assert retrieval.chunk_id == "refund-policy-12"
    assert retrieval.retrieval_sources == ["dense", "bm25"]
    assert retrieval.final_rank == 1


def test_finish_run_is_idempotent(tmp_path):
    store = TraceStore(tmp_path / "traces.db")
    recorder = TraceRecorder(session_id="session_once", store=store)
    recorder.finish_run(status="success", route="sql")
    recorder.finish_run(status="error", route="rag")

    trace = store.get_trace(recorder.trace_id)
    assert trace is not None
    assert trace.run.status == "success"
    assert trace.run.route == "sql"


def test_trace_api_returns_persisted_trace(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    store = TraceStore(tmp_path / "traces.db")
    recorder = TraceRecorder(session_id="session_api", store=store)
    recorder.add("receive_message", "ChatAgent", "success", "收到问题")
    recorder.finish_run(status="success", route="rag")

    monkeypatch.setattr("app.api.traces.get_trace_store", lambda: store)
    response = TestClient(app).get(f"/api/traces/{recorder.trace_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["trace_id"] == recorder.trace_id
    assert payload["spans"][0]["node_name"] == "receive_message"
