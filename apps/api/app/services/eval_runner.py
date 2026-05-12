from app.schemas.chat import ChatRequest
from app.services.agent import run_agent


EVAL_CASES = [
    {
        "question": "4月服装类商品退款率是多少？",
        "expected_route": "sql",
        "expected_keywords": ["退款率"],
    },
    {
        "question": "退款率指标口径是什么？",
        "expected_route": "rag",
        "expected_keywords": ["知识库", "依据"],
    },
    {
        "question": "4月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。",
        "expected_route": "hybrid",
        "expected_keywords": ["退款率", "知识库"],
    },
    {
        "question": "随便看看",
        "expected_route": "clarification",
        "expected_keywords": ["补充"],
    },
]


def run_eval() -> dict[str, object]:
    results = []
    route_hits = 0
    keyword_hits = 0
    for index, case in enumerate(EVAL_CASES, start=1):
        response = run_agent(ChatRequest(message=case["question"], session_id=f"eval_{index}"))
        route_ok = response.route == case["expected_route"]
        keyword_ok = all(keyword in response.answer for keyword in case["expected_keywords"])
        route_hits += int(route_ok)
        keyword_hits += int(keyword_ok)
        results.append(
            {
                "question": case["question"],
                "expected_route": case["expected_route"],
                "actual_route": response.route,
                "route_ok": route_ok,
                "keyword_ok": keyword_ok,
                "latency_ms": response.metrics.latency_ms,
            }
        )
    total = len(EVAL_CASES)
    return {
        "total": total,
        "route_accuracy": round(route_hits / total, 3),
        "answer_keyword_accuracy": round(keyword_hits / total, 3),
        "results": results,
    }
