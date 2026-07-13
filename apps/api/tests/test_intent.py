import pytest

from app.services.agent import (
    _should_use_llm_router,
    format_sql_answer_node,
    route_question,
    validate_metric_result,
)
from app.services.intent import extract_intent_slots
from app.services.memory import SessionMemory, resolve_followup
from app.services.sql_tools import extract_query_params


@pytest.mark.parametrize(
    ("question", "route", "metric"),
    [
        ("4月服装类商品退款率是多少？", "sql", "refund_rate"),
        ("查一下四月份衣服退款占比", "sql", "refund_rate"),
        ("2026-05鞋靴退货率", "sql", "refund_rate"),
        ("5月哪个鞋子退款最多？", "sql", "top_refund_products"),
        ("查询四月服装退款单数", "sql", "refund_count"),
        ("4月服装退款总金额", "sql", "refund_amount_sum"),
        ("4月数码订单数量是多少", "sql", "order_count"),
        ("4月服装售后工单数量是多少", "sql", "ticket_count"),
        ("4月服装工单原因分布", "sql", "ticket_distribution"),
        ("退款率指标口径是什么？", "rag", "refund_rate"),
        ("商品退款政策是什么？", "rag", None),
        ("售后SOP中色差问题怎么处理？", "rag", None),
        ("退款率超过多少会触发品控审核？", "rag", "refund_rate"),
        ("4月服装退款率为什么升高？", "hybrid", "refund_rate"),
        ("结合5月鞋靴退款数据和政策分析原因", "hybrid", None),
        ("随便看看", "clarification", None),
        ("退款率", "clarification", "refund_rate"),
    ],
)
def test_intent_matrix(question, route, metric):
    slots = extract_intent_slots(question)
    actual_route, _, _ = route_question(question)
    assert actual_route == route
    assert slots.metric == metric


def test_full_question_is_not_rewritten_as_followup():
    memory = SessionMemory()
    memory.recent_turns.append({
        "user": "哪个商品退款最多？",
        "assistant": "建议继续查看商品排行。",
    })
    question = "4月服装类商品退款率是多少？"
    assert resolve_followup(question, memory) == question


def test_short_followup_still_uses_previous_context():
    memory = SessionMemory()
    memory.recent_turns.append({
        "user": "4月服装退款率是多少？",
        "assistant": "4月服装退款率为 12%。",
    })
    resolved = resolve_followup("那鞋靴呢？", memory)
    assert "鞋靴" in resolved
    assert "退款率" in resolved


def test_followup_chinese_month_inherits_only_missing_slots():
    memory = SessionMemory()
    memory.recent_turns.append({
        "user": "4月服装退款率是多少？",
        "assistant": "4月服装退款率为 12%。",
    })
    resolved = resolve_followup("五月份呢？", memory)
    assert "2026-05" in resolved
    assert "服装" in resolved
    assert "退款率" in resolved
    assert "2026-04" not in resolved


def test_strong_sql_route_skips_llm_router():
    route, _, confidence = route_question("4月服装退款率是多少？")
    assert route == "sql"
    assert confidence >= 0.9
    assert _should_use_llm_router("4月服装退款率是多少？", route, confidence) is False


def test_strong_sql_params_skip_llm(monkeypatch):
    def fail_if_called(_question):
        raise AssertionError("LLM parameter extraction should not be called")

    monkeypatch.setattr("app.services.sql_tools._extract_params_with_llm", fail_if_called)
    params = extract_query_params("4月服装退款率是多少？")
    assert params.metric == "refund_rate"
    assert params.time_range == "2026-04"
    assert params.category == "服装"


def test_metric_result_validation_rejects_wrong_columns():
    error = validate_metric_result(
        "refund_rate",
        ["category", "month", "refund_count", "total_amount"],
    )
    assert error is not None
    assert "refund_rate" in error


def test_refund_rate_formatter_uses_metric_not_refund_count_guess():
    state = {
        "query_params": {"metric": "refund_rate"},
        "sql_error": None,
        "sql_rows": [{
            "month": "2026-04",
            "category": "服装",
            "order_count": 310,
            "refund_count": 52,
            "refund_rate": 16.77,
        }],
        "sql_columns": ["month", "category", "order_count", "refund_count", "refund_rate"],
        "sql_row_count": 1,
    }
    result = format_sql_answer_node(state)
    assert "退款率为 16.77%" in result["answer_text"]
    assert "商品#" not in result["answer_text"]


def test_refund_amount_formatter_does_not_claim_product_ranking():
    state = {
        "query_params": {"metric": "refund_amount_sum"},
        "sql_error": None,
        "sql_rows": [{
            "month": "2026-04",
            "category": "服装",
            "refund_count": 52,
            "total_amount": 55971.89,
            "avg_amount": 1076.38,
        }],
        "sql_columns": ["month", "category", "refund_count", "total_amount", "avg_amount"],
        "sql_row_count": 1,
    }
    result = format_sql_answer_node(state)
    assert "退款总金额为 55971.89 元" in result["answer_text"]
    assert "退款次数最高的商品" not in result["answer_text"]
