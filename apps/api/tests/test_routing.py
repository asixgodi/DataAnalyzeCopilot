from app.services.agent import route_question


def test_route_sql_question():
    route, reason, confidence = route_question("4月服装类退款率是多少？")
    assert route == "sql"
    assert 0 <= confidence <= 1


def test_route_rag_question():
    route, reason, confidence = route_question("售后处理SOP的归因流程是什么？")
    assert route == "rag"


def test_route_hybrid_question():
    route, reason, confidence = route_question(
        "4月服装类退款率为什么升高？请结合数据和退款政策给出分析。"
    )
    assert route == "hybrid"


def test_route_clarification_question():
    route, reason, confidence = route_question("随便看看")
    assert route == "clarification"


def test_route_sql_with_metric_only():
    route, reason, confidence = route_question("售后工单数量是多少？")
    assert route == "sql"


def test_route_confidence_range():
    questions = [
        "4月服装类退款率是多少？",
        "退款率指标口径是什么？",
        "4月服装类退款率为什么升高？请结合数据和退款政策给出分析。",
        "随便看看",
        "5月鞋靴类退货最多的商品是哪个？",
    ]
    for q in questions:
        route, reason, confidence = route_question(q)
        assert 0 <= confidence <= 1
        assert isinstance(reason, str)
        assert len(reason) > 0
