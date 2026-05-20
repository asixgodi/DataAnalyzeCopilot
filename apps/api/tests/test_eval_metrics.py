from app.services.eval_runner import run_eval


def test_route_accuracy_in_range():
    result = run_eval()
    assert 0 <= result["route_accuracy"] <= 1


def test_keyword_accuracy_in_range():
    result = run_eval()
    assert 0 <= result["keyword_accuracy"] <= 1


def test_total_is_positive():
    result = run_eval()
    assert result["total"] > 0


def test_metric_fields_present():
    result = run_eval()
    expected_fields = [
        "total", "task_success_rate", "route_accuracy",
        "keyword_accuracy", "tool_call_accuracy",
        "avg_latency_ms", "avg_tool_calls",
    ]
    for field in expected_fields:
        assert field in result, f"Missing field: {field}"
