from app.services.guards import OutputGuard


def test_hybrid_guard_accepts_numbers_grounded_in_citations():
    result = OutputGuard().check(
        answer=(
            "4月退款率为 10%。政策规定可在 7 天内申请，"
            "客服应在 48 小时内响应，共分 3 个处理步骤、2 个审核条件和 1 次回访。"
        ),
        route="hybrid",
        sql_rows=[{"refund_rate": 10.0}],
        citations=[{"snippet": "消费者可在 7 天内申请退款；客服 SLA 为 48 小时；流程共 3 步、2 个审核条件、1 次回访。"}],
    )

    assert result.passed


def test_hybrid_guard_still_blocks_many_ungrounded_numbers():
    result = OutputGuard().check(
        answer="退款率为 10%，并且出现 11、12、13、14、15、16 六项额外指标。",
        route="hybrid",
        sql_rows=[{"refund_rate": 10.0}],
        citations=[{"snippet": "政策规定 7 天内可申请退款。"}],
    )

    assert not result.passed
    assert result.guard_name == "number_hallucination"
