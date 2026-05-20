"""
RAG 检索管道对比评估。

对比 3 种配置：
  Baseline: 纯 Dense (Chroma) 检索，无任何优化
  V1:       MQE → Dense → Adjacent → LLM Rerank
  V2:       MQE → Dense + BM25 → RRF → Adjacent → LLM Rerank

工业界标准指标 (k=5):
  Recall@K     — 检索到的相关chunk数 / 所有相关chunk数
  Precision@K  — 检索到的相关chunk数 / K
  MRR          — 第一个相关chunk排名的倒数均值
  Hit Rate     — 至少命中1个相关chunk的问题占比

用法: cd apps/api && python ../../scripts/rag_eval.py
"""

import json
import re
import sys
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

# 确保可以 import app
api_dir = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(api_dir))

from app.services.rag import _mqe_expand_llm, _get_bm25, _rrf_fuse, _expand_adjacent_chunks, _llm_rerank  # noqa: E402
from app.services.chroma_store import query_chroma  # noqa: E402
from app.schemas.chat import Citation  # noqa: E402

# ── 测试集 ───────────────────────────────────────────────────────────

# 从 eval_dataset.jsonl 抽取 RAG 相关用例
EVAL_PATH = api_dir.parents[1] / "data" / "eval_dataset.jsonl"

QUERIES: list[dict[str, Any]] = [
    {"q": "退款率指标口径是什么？", "relevant_docs": ["metric_definitions"], "keywords": ["退款率", "支付订单", "口径"]},
    {"q": "金卡会员的退货期限是多久？", "relevant_docs": ["vip_rules"], "keywords": ["金卡", "30天", "退货"]},
    {"q": "售后处理SOP的归因流程是什么？", "relevant_docs": ["after_sales_sop"], "keywords": ["归因", "订单月份", "退款原因"]},
    {"q": "服装类商品正常退款率预警线是多少？", "relevant_docs": ["product_category_guide", "quality_control"], "keywords": ["预警", "12%", "退款率"]},
    {"q": "客服工单P1级别包含哪些情况？", "relevant_docs": ["ticket_classification"], "keywords": ["P1", "金卡", "投诉"]},
    {"q": "物流延迟导致的退款怎么处理？", "relevant_docs": ["logistics_policy"], "keywords": ["物流", "延迟", "优惠券"]},
    {"q": "退款政策中服装类有什么特殊规定？", "relevant_docs": ["refund_policy"], "keywords": ["服装", "7天", "尺码"]},
    {"q": "Agent输出售后分析时需要包含什么？", "relevant_docs": ["analysis_guidelines"], "keywords": ["数据结果", "文档证据", "建议动作"]},
    {"q": "银卡会员和普通会员的退货政策有什么区别？", "relevant_docs": ["vip_rules"], "keywords": ["银卡", "15天", "普通"]},
    {"q": "FCR低于60%需要触发什么流程？", "relevant_docs": ["quality_control"], "keywords": ["FCR", "60%", "客服话术"]},
    {"q": "4月服装类退款率为什么升高？", "relevant_docs": ["refund_policy", "product_category_guide"], "keywords": ["退款率", "异常", "预警"]},
    {"q": "产品表有哪些字段？", "relevant_docs": ["data_dictionary"], "keywords": ["products", "字段", "INTEGER"]},
    {"q": "钻石会员有什么特殊权益？", "relevant_docs": ["vip_rules"], "keywords": ["钻石", "45天", "极速退款"]},
    {"q": "品控抽检的触发条件是什么？", "relevant_docs": ["quality_control"], "keywords": ["差评率", "15%", "品控"]},
    {"q": "P0紧急工单的定义是什么？", "relevant_docs": ["ticket_classification"], "keywords": ["P0", "批量", "10单"]},
]

K = 5

# ── 指标计算 ─────────────────────────────────────────────────────────


def is_relevant(rec: dict[str, Any], keywords: list[str]) -> bool:
    """判断一个检索结果是否相关：文本包含至少一个关键词。"""
    text = str(rec.get("document", "")).lower()
    return any(kw.lower() in text for kw in keywords)


def compute_metrics(
    results: list[list[dict[str, Any]]],  # 每个 query 的检索结果
    ground_truth: list[list[str]],        # 每个 query 的相关 chunk_id 列表
) -> dict[str, float]:
    recall_vals: list[float] = []
    precision_vals: list[float] = []
    mrr_vals: list[float] = []
    hit_count = 0

    for i, records in enumerate(results):
        retrieved_ids = [str(r["id"]) for r in records[:K]]
        relevant_ids = set(ground_truth[i])

        if not relevant_ids:
            continue

        # Recall@K
        hit_relevant = [rid for rid in retrieved_ids if rid in relevant_ids]
        recall = len(hit_relevant) / len(relevant_ids) if relevant_ids else 0
        recall_vals.append(recall)

        # Precision@K
        precision = len(hit_relevant) / K
        precision_vals.append(precision)

        # MRR
        for rank, rid in enumerate(retrieved_ids, start=1):
            if rid in relevant_ids:
                mrr_vals.append(1.0 / rank)
                break
        else:
            mrr_vals.append(0.0)

        # Hit Rate
        if any(rid in relevant_ids for rid in retrieved_ids):
            hit_count += 1

    n = len(results)
    return {
        "Recall@K": round(mean(recall_vals), 3) if recall_vals else 0,
        "Precision@K": round(mean(precision_vals), 3) if precision_vals else 0,
        "MRR": round(mean(mrr_vals), 3) if mrr_vals else 0,
        "Hit Rate": round(hit_count / n, 3) if n else 0,
    }


# ── 检索配置 ─────────────────────────────────────────────────────────


def baseline_retrieve(query: str, top_k: int) -> list[dict[str, Any]]:
    """Baseline: 纯 Chroma Dense 检索，无任何优化。"""
    return query_chroma(query, top_k=top_k)


def v1_retrieve(query: str, top_k: int) -> list[dict[str, Any]]:
    """V1: MQE → Dense → Adjacent → LLM Rerank（优化前）。"""
    variants = _mqe_expand_llm(query)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        for rec in query_chroma(variant, top_k=8):
            rid = str(rec["id"])
            if rid not in seen:
                seen.add(rid)
                records.append(rec)

    records.sort(key=lambda r: r["score"], reverse=True)
    records = _expand_adjacent_chunks(records)
    records = _llm_rerank(query, records, top_k)
    return records[:top_k]


def v2_retrieve(query: str, top_k: int) -> list[dict[str, Any]]:
    """V2: MQE → Dense + BM25 → RRF → Adjacent → LLM Rerank（完整优化）。"""
    variants = _mqe_expand_llm(query)
    bm25 = _get_bm25()

    dense_records: list[dict[str, Any]] = []
    sparse_records: list[dict[str, Any]] = []
    dense_seen: set[str] = set()
    sparse_seen: set[str] = set()

    for variant in variants:
        for rec in query_chroma(variant, top_k=8):
            rid = str(rec["id"])
            if rid not in dense_seen:
                dense_seen.add(rid)
                rec["source"] = "dense"
                dense_records.append(rec)
        for rec in bm25.search(variant, top_k=8):
            rid = str(rec["id"])
            if rid not in sparse_seen:
                sparse_seen.add(rid)
                sparse_records.append(rec)

    records = _rrf_fuse(dense_records, sparse_records)
    records = _expand_adjacent_chunks(records)
    records = _llm_rerank(query, records, top_k)
    return records[:top_k]


# ── 运行 ─────────────────────────────────────────────────────────────


def run():
    configs = [
        ("Baseline (纯Dense)", baseline_retrieve),
        ("V1 (MQE+Dense+Adjacent+Rerank)", v1_retrieve),
        ("V2 (MQE+Dense+BM25+RRF+Adjacent+Rerank)", v2_retrieve),
    ]

    # 构建 ground truth：对每个 query，找出哪些 chunk 包含期望关键词
    bm25 = _get_bm25()
    ground_truth: list[list[str]] = []
    for case in QUERIES:
        keywords = case["keywords"]
        relevant_ids = []
        for rec in bm25.search(case["q"], top_k=30):
            if is_relevant(rec, keywords):
                relevant_ids.append(str(rec["id"]))
        ground_truth.append(relevant_ids)

    print(f"{'配置':<50} {'Recall@5':>9} {'Precision@5':>11} {'MRR':>7} {'Hit Rate':>9} {'Latency':>9}")
    print("-" * 100)

    for name, retrieve_fn in configs:
        results: list[list[dict[str, Any]]] = []
        latencies: list[float] = []

        for case in QUERIES:
            started = perf_counter()
            records = retrieve_fn(case["q"], K)
            latencies.append((perf_counter() - started) * 1000)
            results.append(records)

        metrics = compute_metrics(results, ground_truth)
        avg_latency = round(mean(latencies), 0)
        print(
            f"{name:<50} "
            f"{metrics['Recall@K']:>9.3f} "
            f"{metrics['Precision@K']:>11.3f} "
            f"{metrics['MRR']:>7.3f} "
            f"{metrics['Hit Rate']:>9.3f} "
            f"{avg_latency:>6.0f}ms"
        )

    # 提升幅度
    print()
    print("--- V2 vs Baseline 提升 ---")
    # Re-run V2 results for proper delta calculation
    v2_results = [v2_retrieve(c["q"], K) for c in QUERIES]
    v2_metrics = compute_metrics(v2_results, ground_truth)
    baseline_results = [baseline_retrieve(c["q"], K) for c in QUERIES]
    baseline_metrics = compute_metrics(baseline_results, ground_truth)

    for metric in ["Recall@K", "Precision@K", "MRR", "Hit Rate"]:
        before = baseline_metrics[metric]
        after = v2_metrics[metric]
        delta = after - before
        pct = (delta / before * 100) if before > 0 else 0
        print(f"  {metric}: {before:.3f} → {after:.3f}  (Δ={delta:+.3f}, {pct:+.0f}%)")


if __name__ == "__main__":
    run()
