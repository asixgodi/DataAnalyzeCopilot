import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.core.config import settings  # noqa: E402
from app.schemas.chat import Citation  # noqa: E402
from app.services.chroma_store import query_chroma  # noqa: E402
from app.services.rag import retrieve_docs  # noqa: E402


K = 5


RAG_PROFILES: dict[str, dict[str, object] | None] = {
    "current": None,
    "dense": {
        "rag_enable_router": False,
        "rag_enable_mqe": False,
        "rag_enable_bm25": False,
        "rag_enable_rrf": False,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": False,
    },
    "dense-neighbor": {
        "rag_enable_router": False,
        "rag_enable_mqe": False,
        "rag_enable_bm25": False,
        "rag_enable_rrf": False,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": True,
    },
    "hybrid": {
        "rag_enable_router": False,
        "rag_enable_mqe": False,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": False,
    },
    "hybrid-neighbor": {
        "rag_enable_router": False,
        "rag_enable_mqe": False,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": True,
    },
    "mqe-hybrid": {
        "rag_enable_router": False,
        "rag_enable_mqe": True,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": False,
    },
    "mqe-hybrid-neighbor": {
        "rag_enable_router": False,
        "rag_enable_mqe": True,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": True,
    },
    "rerank-only": {
        "rag_enable_router": False,
        "rag_enable_mqe": False,
        "rag_enable_bm25": False,
        "rag_enable_rrf": False,
        "rag_enable_rerank": True,
        "rag_enable_adjacent_context": False,
    },
    "hybrid-rerank": {
        "rag_enable_router": False,
        "rag_enable_mqe": False,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": True,
        "rag_enable_adjacent_context": False,
    },
    "full": {
        "rag_enable_router": False,
        "rag_enable_mqe": True,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": True,
        "rag_enable_adjacent_context": True,
    },
    "router": {
        "rag_enable_router": True,
        "rag_router_mode": "rule",
        "rag_enable_mqe": True,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": True,
    },
    "llm-router": {
        "rag_enable_router": True,
        "rag_router_mode": "llm",
        "rag_router_confidence_threshold": 0.65,
        "rag_enable_mqe": True,
        "rag_enable_bm25": True,
        "rag_enable_rrf": True,
        "rag_enable_rerank": False,
        "rag_enable_adjacent_context": True,
    },
}


def apply_rag_profile(profile: str) -> dict[str, object]:
    values = RAG_PROFILES[profile]
    if values is not None:
        for key, value in values.items():
            setattr(settings, key, value)
    return {
        "mqe": settings.rag_enable_mqe,
        "bm25": settings.rag_enable_bm25,
        "rrf": settings.rag_enable_rrf,
        "rerank": settings.rag_enable_rerank,
        "adjacent_context": settings.rag_enable_adjacent_context,
        "router": settings.rag_enable_router,
        "router_mode": settings.rag_router_mode,
        "router_confidence_threshold": settings.rag_router_confidence_threshold,
    }


@dataclass(frozen=True)
class GoldenCase:
    question: str
    relevant_doc_ids: set[str]
    relevant_chunk_ids: set[str] | None = None


GOLDEN_CASES = [
    GoldenCase("退款率指标口径是什么？", {"metric_definitions"}, {"metric_definitions-0"}),
    GoldenCase("售后处理 SOP 的归因流程是什么？", {"after_sales_sop"}, {"after_sales_sop-1"}),
    GoldenCase("退款政策中服装类商品有什么特殊规定？", {"refund_policy"}),
    GoldenCase("Agent 输出售后分析时需要包含哪些内容？", {"after_sales_sop", "analysis_guidelines"}),
    GoldenCase("反欺诈规则中哪些退款行为需要重点关注？", {"anti_fraud_rules"}),
    GoldenCase("客服工单 P1 级别包括哪些情况？", {"ticket_classification", "after_sales_sop"}),
    GoldenCase("金卡会员的退货期限和售后权益是什么？", {"vip_rules"}),
    GoldenCase("物流延迟导致退款应该如何处理？", {"logistics_policy"}),
    GoldenCase("商品质量异常监控的触发条件是什么？", {"quality_control"}),
    GoldenCase("退换货政策中普通退货和换货有什么区别？", {"return_exchange_policy"}),
    GoldenCase("退款审核流程有哪些关键节点？", {"refund_review_process"}),
    GoldenCase("商品评价管理中差评应该如何处理？", {"review_management"}),
    GoldenCase("供应商质量问题应该如何追责和整改？", {"supplier_quality"}),
    GoldenCase("仓储物流 SOP 中发货异常如何处理？", {"warehouse_logistics_sop"}),
    GoldenCase("促销活动后的售后问题应该如何复盘？", {"promotion_after_sales"}),
    GoldenCase("投诉处理流程中高优先级投诉如何升级？", {"complaint_handling"}),
    GoldenCase("客服话术模板如何处理用户退款咨询？", {"cs_script_templates"}),
    GoldenCase("数据字典中 orders 表包含哪些字段？", {"data_dictionary"}),
    GoldenCase("售后数据报告需要包含哪些核心模块？", {"data_report_spec"}),
    GoldenCase("隐私和安全 SOP 对用户数据有什么要求？", {"security_and_privacy_sop"}),
    GoldenCase("服装类和鞋靴类售后特点有什么差异？", {"product_category_guide"}),
    GoldenCase("FCR 低于阈值时需要触发什么优化流程？", {"quality_control"}),
    GoldenCase("物流破损签收应该如何补偿和记录？", {"logistics_policy", "warehouse_logistics_sop"}),
    GoldenCase("会员等级会如何影响退款处理时效？", {"vip_rules", "refund_review_process"}),
    GoldenCase("当分析信息不足时 Agent 应该如何处理？", {"analysis_guidelines"}),
]


GOLDEN_CASES.extend([
    GoldenCase("金卡会员命中高频退款风险时，还能直接走快速退款吗？", {"policy_conflict_resolution", "refund_exception_matrix", "vip_rules", "anti_fraud_rules"}),
    GoldenCase("满减活动订单只退一件商品时，退款金额应该按什么规则计算？", {"refund_exception_matrix", "policy_conflict_resolution", "promotion_after_sales"}),
    GoldenCase("用户说显示签收但没收到，这属于什么售后意图，应该查哪些规则？", {"customer_intent_dictionary", "logistics_policy", "complaint_handling"}),
    GoldenCase("收到商品外包装破损且同 SKU 最近也有质量投诉时，应该先判断物流责任还是质量责任？", {"policy_conflict_resolution", "refund_exception_matrix", "quality_control", "warehouse_logistics_sop"}),
    GoldenCase("退款审核 SLA 超时可能由哪些原因造成？", {"metric_diagnosis_playbook", "refund_review_process", "anti_fraud_rules"}),
    GoldenCase("FCR 下降同时投诉升级增加，应该优先检查哪些知识库规则？", {"metric_diagnosis_playbook", "cs_script_templates", "complaint_handling", "quality_control"}),
    GoldenCase("用户说钱什么时候到账，这个口语问题应该映射到哪个业务流程？", {"customer_intent_dictionary", "refund_review_process"}),
    GoldenCase("退货很多这种模糊表达，应该关联哪些指标口径和诊断维度？", {"customer_intent_dictionary", "metric_definitions", "metric_diagnosis_playbook"}),
    GoldenCase("为什么简单定义类问题不应该默认启用 MQE 和 LLM Rerank？", {"rag_query_routing_strategy"}),
    GoldenCase("包含 P1、FCR、SLA、SKU 这类明确术语的问题适合走哪种检索链路？", {"rag_query_routing_strategy", "customer_intent_dictionary"}),
    GoldenCase("多文档综合类问题为什么适合 MQE 加 Hybrid Retrieval？", {"rag_query_routing_strategy"}),
    GoldenCase("如果 Rerank 导致 MRR 或 NDCG 下降，系统应该如何回退？", {"rag_query_routing_strategy"}),
    GoldenCase("促销退款、会员权益和风控规则同时命中时，售后规则优先级是什么？", {"policy_conflict_resolution", "refund_exception_matrix"}),
    GoldenCase("用户说我要投诉并要求主管处理，应该对应哪个意图和哪个工单流程？", {"customer_intent_dictionary", "complaint_handling", "ticket_classification"}),
    GoldenCase("同一 SKU 7 天内多起质量争议时，应该触发什么流程？", {"refund_exception_matrix", "metric_diagnosis_playbook", "quality_control"}),
])


def baseline_retrieve(question: str, top_k: int) -> list[Citation]:
    """优化前：只使用 Chroma Dense Retrieval，不做 MQE/BM25/RRF/Rerank。"""
    citations: list[Citation] = []
    for rec in query_chroma(question, top_k=top_k):
        metadata = rec.get("metadata", {})
        citations.append(
            Citation(
                doc_id=str(metadata.get("doc_id", "unknown")),
                title=str(metadata.get("title", "未知文档")),
                chunk_id=str(rec["id"]),
                snippet=str(rec.get("document", ""))[:260],
                score=float(rec.get("score", 0)),
                retrieval_sources=["dense"],
            )
        )
    return citations


def optimized_retrieve(question: str, top_k: int) -> list[Citation]:
    """优化后：使用当前 retrieve_docs，包含 MQE + Dense/BM25 + RRF + 相邻 chunk + LLM Rerank。"""
    return retrieve_docs(question, top_k=top_k)


def is_relevant(citation: Citation, case: GoldenCase) -> bool:
    if case.relevant_chunk_ids and citation.chunk_id in case.relevant_chunk_ids:
        return True
    return citation.doc_id in case.relevant_doc_ids


def build_counted_relevances(citations: list[Citation], case: GoldenCase) -> list[int]:
    relevances: list[int] = []
    seen_relevant_docs: set[str] = set()
    for citation in citations[:K]:
        if case.relevant_chunk_ids:
            relevances.append(1 if citation.chunk_id in case.relevant_chunk_ids else 0)
            continue

        if citation.doc_id in case.relevant_doc_ids and citation.doc_id not in seen_relevant_docs:
            seen_relevant_docs.add(citation.doc_id)
            relevances.append(1)
        else:
            relevances.append(0)
    return relevances


def average_precision(relevances: list[int]) -> float:
    hit_count = 0
    precisions: list[float] = []
    for index, rel in enumerate(relevances, start=1):
        if rel:
            hit_count += 1
            precisions.append(hit_count / index)
    return mean(precisions) if precisions else 0.0


def reciprocal_rank(relevances: list[int]) -> float:
    for index, rel in enumerate(relevances, start=1):
        if rel:
            return 1 / index
    return 0.0


def dcg(relevances: list[int]) -> float:
    import math

    score = 0.0
    for index, rel in enumerate(relevances, start=1):
        if rel:
            score += rel / math.log2(index + 1)
    return score


def ndcg_at_k(relevances: list[int], total_relevant: int) -> float:
    ideal = [1] * min(total_relevant, len(relevances))
    ideal_score = dcg(ideal)
    if ideal_score == 0:
        return 0.0
    return dcg(relevances) / ideal_score


def evaluate_case(case: GoldenCase, retrieve_fn: Callable[[str, int], list[Citation]]) -> dict[str, object]:
    started = perf_counter()
    citations = retrieve_fn(case.question, K)
    latency_ms = round((perf_counter() - started) * 1000, 2)

    relevances = build_counted_relevances(citations, case)
    hit_count = sum(relevances)
    total_relevant = len(case.relevant_chunk_ids or case.relevant_doc_ids)

    return {
        "question": case.question,
        "expected_docs": sorted(case.relevant_doc_ids),
        "retrieved": [
            {
                "rank": index,
                "doc_id": citation.doc_id,
                "chunk_id": citation.chunk_id,
                "score": citation.score,
                "relevant": is_relevant(citation, case),
                "counted_relevant": bool(relevances[index - 1]),
            }
            for index, citation in enumerate(citations[:K], start=1)
        ],
        "hit": hit_count > 0,
        "recall": hit_count / total_relevant if total_relevant else 0,
        "precision": hit_count / K,
        "mrr": reciprocal_rank(relevances),
        "map": average_precision(relevances),
        "ndcg": ndcg_at_k(relevances, total_relevant),
        "latency_ms": latency_ms,
    }


def evaluate_suite(
    name: str,
    cases: list[GoldenCase],
    retrieve_fn: Callable[[str, int], list[Citation]],
    verbose: bool,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for index, case in enumerate(cases, start=1):
        if verbose:
            print(f"[{name}] {index}/{len(cases)} {case.question}", file=sys.stderr, flush=True)
        results.append(evaluate_case(case, retrieve_fn))
    return {"summary": summarize(results), "results": results}


def summarize(results: list[dict[str, object]]) -> dict[str, float | int]:
    return {
        "cases": len(results),
        f"hit_rate@{K}": round(mean(1 if item["hit"] else 0 for item in results), 3),
        f"recall@{K}": round(mean(float(item["recall"]) for item in results), 3),
        f"precision@{K}": round(mean(float(item["precision"]) for item in results), 3),
        "mrr": round(mean(float(item["mrr"]) for item in results), 3),
        "map": round(mean(float(item["map"]) for item in results), 3),
        f"ndcg@{K}": round(mean(float(item["ndcg"]) for item in results), 3),
        "avg_latency_ms": round(mean(float(item["latency_ms"]) for item in results), 2),
    }


def compare_summaries(baseline: dict[str, float | int], optimized: dict[str, float | int]) -> dict[str, object]:
    deltas: dict[str, object] = {}
    for metric in [f"hit_rate@{K}", f"recall@{K}", f"precision@{K}", "mrr", "map", f"ndcg@{K}"]:
        before = float(baseline[metric])
        after = float(optimized[metric])
        deltas[metric] = {
            "baseline": before,
            "optimized": after,
            "absolute_delta": round(after - before, 3),
            "relative_delta": round((after - before) / before, 3) if before else None,
        }
    deltas["avg_latency_ms"] = {
        "baseline": baseline["avg_latency_ms"],
        "optimized": optimized["avg_latency_ms"],
        "absolute_delta": round(float(optimized["avg_latency_ms"]) - float(baseline["avg_latency_ms"]), 2),
    }
    return deltas


def run() -> int:
    parser = argparse.ArgumentParser(description="评估 RAG Top-K 检索质量，并支持 Baseline 与 Optimized 对比。")
    parser.add_argument("--limit", type=int, default=0, help="只运行前 N 条 case，0 表示全部运行。")
    parser.add_argument(
        "--mode",
        choices=["baseline", "optimized", "compare"],
        default="compare",
        help="baseline=纯 Chroma Dense；optimized=当前优化链路；compare=两者都跑并输出对比。",
    )
    parser.add_argument("--quiet", action="store_true", help="不打印进度，只输出最终 JSON。")
    parser.add_argument(
        "--profile",
        choices=sorted(RAG_PROFILES),
        default="current",
        help="选择 optimized 链路的 RAG 优化组合；current 表示使用 .env 当前配置。",
    )
    args = parser.parse_args()

    active_switches = apply_rag_profile(args.profile)
    cases = GOLDEN_CASES[: args.limit] if args.limit else GOLDEN_CASES
    verbose = not args.quiet
    output: dict[str, object] = {
        "k": K,
        "mode": args.mode,
        "profile": args.profile,
        "switches": active_switches,
        "case_count": len(cases),
    }

    if args.mode in {"baseline", "compare"}:
        output["baseline"] = evaluate_suite("baseline", cases, baseline_retrieve, verbose)
    if args.mode in {"optimized", "compare"}:
        output["optimized"] = evaluate_suite("optimized", cases, optimized_retrieve, verbose)
    if args.mode == "compare":
        baseline_summary = output["baseline"]["summary"]  # type: ignore[index]
        optimized_summary = output["optimized"]["summary"]  # type: ignore[index]
        output["comparison"] = compare_summaries(baseline_summary, optimized_summary)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
