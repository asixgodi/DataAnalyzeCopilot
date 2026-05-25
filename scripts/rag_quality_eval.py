"""
RAG 检索质量对比评估（LLM-as-Judge）

方法：对同一组问题，跑两种检索配置，用 LLM 逐条判断相关性（1-5 分），
       输出配置间的质量对比。

用法：cd apps/api && python ../../scripts/rag_quality_eval.py

输出示例：
  指标              Baseline  Optimized  提升
  Avg Relevance      3.2       4.1       +28%
  Hit Rate@3         0.60      0.87      +45%
  Top-1 Relevance    2.8       4.3       +54%
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

api_dir = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(api_dir))

from app.services.rag import _mqe_expand_llm, _get_bm25, _rrf_fuse, _expand_adjacent_chunks, _llm_rerank  # noqa: E402
from app.services.chroma_store import query_chroma  # noqa: E402
from app.core.config import settings  # noqa: E402

# ── 测试问题 ─────────────────────────────────────────────────────────

QUESTIONS = [
    "退款率指标口径是什么？",
    "金卡会员的退货期限是多久？",
    "售后处理SOP的归因流程是什么？",
    "服装类商品正常退款率预警线是多少？",
    "客服工单P1级别包含哪些情况？",
    "物流延迟导致的退款怎么处理？",
    "退款政策中服装类有什么特殊规定？",
    "银卡会员和普通会员的退货政策有什么区别？",
    "FCR低于60%需要触发什么流程？",
    "品控抽检的触发条件是什么？",
    "P0紧急工单的定义是什么？",
    "钻石会员有什么特殊权益？",
    "商品表中category字段的含义是什么？",
    "4月服装类退款率为什么升高？",
    "Agent输出售后分析时需要包含什么？",
]

# ── 两种检索配置 ─────────────────────────────────────────────────────


def baseline_retrieve(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Baseline: 纯 Chroma Dense，无任何优化。"""
    return query_chroma(query, top_k=top_k)


def optimized_retrieve(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Optimized: 完整管道。"""
    variants = _mqe_expand_llm(query)
    bm25 = _get_bm25()
    variant_weights = [1.0, 0.7, 0.5, 0.3]

    dense_records: list[dict[str, Any]] = []
    sparse_records: list[dict[str, Any]] = []
    dense_seen: set[str] = set()
    sparse_seen: set[str] = set()

    for i, variant in enumerate(variants):
        weight = variant_weights[i] if i < len(variant_weights) else 0.3
        for rec in query_chroma(variant, top_k=8):
            rid = str(rec["id"])
            rec.setdefault("matched_queries", []).append(variant)
            rec["query_weight"] = max(rec.get("query_weight", 0), weight)
            if rid not in dense_seen:
                dense_seen.add(rid)
                rec["source"] = "dense"
                rec["is_neighbor"] = False
                dense_records.append(rec)
        for rec in bm25.search(variant, top_k=8):
            rid = str(rec["id"])
            rec.setdefault("matched_queries", []).append(variant)
            rec["query_weight"] = max(rec.get("query_weight", 0), weight)
            if rid not in sparse_seen:
                sparse_seen.add(rid)
                rec["is_neighbor"] = False
                sparse_records.append(rec)

    records = _rrf_fuse(dense_records, sparse_records)
    records = _expand_adjacent_chunks(records)
    records = _llm_rerank(query, records, top_k)
    return records[:top_k]


# ── LLM-as-Judge 相关性打分 ──────────────────────────────────────────

_JUDGE_PROMPT = """评测问题：{question}

检索结果片段：
{passage}

请仅打分（1-5 数字），不要其他内容：
5 = 完全回答了问题，信息充足
4 = 高度相关，回答了大部分问题
3 = 部分相关，有参考价值但不够完整
2 = 勉强相关，信息不足
1 = 完全不相关

分数："""


def judge_relevance(question: str, passage: str) -> int:
    """LLM 判断单个片段对问题的相关性（1-5 分）。"""
    if not settings.siliconflow_api_key:
        # 无 API Key 时用关键词回退
        keywords = set(question) & set(passage)
        return min(len(keywords) // 3 + 1, 5)

    import httpx
    snippet = passage.strip()[:500].replace("\n", " ")
    try:
        with httpx.Client() as client:
            resp = client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.siliconflow_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": _JUDGE_PROMPT.format(
                        question=question, passage=snippet)}],
                    "temperature": 0.1,
                    "max_tokens": 5,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            score_str = resp.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r"(\d)", score_str)
            return int(match.group(1)) if match else 3
    except Exception:
        return 3


# ── 指标计算 ─────────────────────────────────────────────────────────


def compute_metrics(
    results: list[list[dict[str, Any]]],
    questions: list[str],
) -> dict[str, float]:
    """计算 Top-1 相关性、Top-3 相关性、Hit Rate@3。"""
    relevance_scores = []
    hit_count = 0
    top1_scores = []

    for i, records in enumerate(results):
        scores = []
        for rec in records[:3]:
            score = judge_relevance(questions[i], rec.get("document", ""))
            scores.append(score)
        if scores:
            relevance_scores.extend(scores)
            top1_scores.append(scores[0])
        if any(s >= 3 for s in scores):
            hit_count += 1

    n = len(results)
    return {
        "avg_relevance": round(sum(relevance_scores) / len(relevance_scores), 2) if relevance_scores else 0,
        "top1_relevance": round(sum(top1_scores) / len(top1_scores), 2) if top1_scores else 0,
        "hit_rate": round(hit_count / n, 3) if n else 0,
    }


# ── 运行 ─────────────────────────────────────────────────────────────


def run():
    if not settings.siliconflow_api_key:
        print("需要配置 SILICONFLOW_API_KEY")
        return

    configs = [
        ("Baseline (纯Dense)", baseline_retrieve),
        ("Optimized (完整管道)", optimized_retrieve),
    ]

    print("=" * 70)
    print(f"{'指标':<22} {'Baseline':>12} {'Optimized':>12} {'提升':>12}")
    print("-" * 70)

    all_baseline: list[list[dict[str, Any]]] = []
    all_optimized: list[list[dict[str, Any]]] = []

    for name, fn in configs:
        results = [fn(q) for q in QUESTIONS]
        if name.startswith("Baseline"):
            all_baseline = results
        else:
            all_optimized = results

    base_metrics = compute_metrics(all_baseline, QUESTIONS)
    opt_metrics = compute_metrics(all_optimized, QUESTIONS)

    for metric, label in [
        ("avg_relevance", "Avg Relevance (1-5)"),
        ("top1_relevance", "Top-1 Relevance"),
        ("hit_rate", "Hit Rate@3"),
    ]:
        before = base_metrics[metric]
        after = opt_metrics[metric]
        if metric == "hit_rate":
            delta_pct = f"{(after - before) * 100:+.0f}pp"
            print(f"  {label:<22} {before:>12.3f} {after:>12.3f} {delta_pct:>12}")
        else:
            delta_pct = f"{(after - before) / before * 100:+.0f}%"
            print(f"  {label:<22} {before:>12.2f} {after:>12.2f} {delta_pct:>12}")

    # 逐问题对比
    print()
    print("=" * 70)
    print("逐问题 Top-1 相关性对比")
    print("-" * 70)
    print(f"{'问题':<40} {'Baseline':>8} {'Optimized':>8}")

    for i, q in enumerate(QUESTIONS):
        b_scores = [judge_relevance(q, r.get("document", "")) for r in all_baseline[i][:1]]
        o_scores = [judge_relevance(q, r.get("document", "")) for r in all_optimized[i][:1]]
        b1 = b_scores[0] if b_scores else 0
        o1 = o_scores[0] if o_scores else 0
        marker = " +" if o1 > b1 else (" =" if o1 == b1 else " -")
        print(f"  {q[:38]:<40} {b1:>8} {o1:>8}{marker}")


if __name__ == "__main__":
    run()
