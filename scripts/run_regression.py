"""
快速回归测试 — 使用 regression_cases.jsonl 跑核心 case，5 分钟内出结果。

用法：
    python scripts/run_regression.py                          # 默认
    python scripts/run_regression.py --cases data/regression_cases.jsonl
    python scripts/run_regression.py --save-baseline         # 保存为 baseline
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CASES = DATA_DIR / "regression_cases.jsonl"
BASELINE_PATH = DATA_DIR / "baseline.json"


def main():
    parser = argparse.ArgumentParser(description="Agent 快速回归测试")
    parser.add_argument("--cases", type=str, default=str(DEFAULT_CASES))
    parser.add_argument("--save-baseline", action="store_true", help="将本次结果保存为 baseline")
    args = parser.parse_args()

    sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

    from app.services.agent import run_agent
    from app.schemas.chat import ChatRequest

    cases_path = Path(args.cases)
    cases = []
    with open(cases_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    print(f"\n═══ Agent 回归测试 ═══")
    print(f"测试集：{cases_path.name} ({len(cases)} 条)")
    print(f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    route_correct = 0
    keyword_correct = 0
    sql_success = 0
    sql_total = 0
    citation_hits = 0
    citation_total = 0
    total_latency = 0
    errors = 0

    results = []

    for i, case in enumerate(cases):
        q = case["question"]
        print(f"  [{i+1:2d}/{len(cases)}] {q[:50]:50s}", end=" ")

        start = time.time()
        try:
            resp = run_agent(ChatRequest(
                message=q,
                session_id=f"reg_{case['id']}",
            ))
            latency_ms = (time.time() - start) * 1000
            total_latency += latency_ms

            # 路由
            route_ok = resp.route == case["expected_route"]
            if route_ok:
                route_correct += 1

            # 关键词
            kw_ok = all(kw in resp.answer for kw in case.get("expected_keywords", []))
            if kw_ok:
                keyword_correct += 1

            # SQL
            if case["expected_route"] in ("sql", "hybrid"):
                sql_total += 1
                if resp.sql_result and not resp.sql_result.error:
                    sql_success += 1

            # 引用
            if case["expected_route"] in ("rag", "hybrid"):
                citation_total += 1
                if resp.citations:
                    citation_hits += 1

            tag = "OK" if route_ok else "ROUTE_MISS"
            print(f"[{tag:12s}] {latency_ms:6.0f}ms  route={resp.route}")

            results.append({
                "id": case["id"],
                "question": q,
                "expected_route": case["expected_route"],
                "actual_route": resp.route,
                "route_correct": route_ok,
                "keyword_correct": kw_ok,
                "latency_ms": round(latency_ms, 2),
                "answer_preview": resp.answer[:120],
            })

        except Exception as exc:
            errors += 1
            print(f"[ERROR] {exc}")
            results.append({"id": case["id"], "question": q, "error": str(exc)})

    # 汇总
    n = len(cases)
    print(f"\n─── 汇总 ───")
    print(f"  路由准确率：          {route_correct}/{n} = {route_correct/n:.2%}")
    print(f"  关键词命中率：        {keyword_correct}/{n} = {keyword_correct/n:.2%}")
    print(f"  SQL 执行成功率：      {sql_success}/{sql_total} = {sql_success/sql_total:.2%}" if sql_total else "  SQL 执行成功率：      N/A")
    print(f"  引用命中率：          {citation_hits}/{citation_total} = {citation_hits/citation_total:.2%}" if citation_total else "  引用命中率：          N/A")
    print(f"  平均延迟：            {total_latency/n:.0f}ms")
    print(f"  错误数：              {errors}")

    summary = {
        "timestamp": datetime.now().isoformat(),
        "cases_file": str(cases_path),
        "total": n,
        "metrics": {
            "route_accuracy": round(route_correct / n, 4) if n else 0,
            "keyword_accuracy": round(keyword_correct / n, 4) if n else 0,
            "sql_execution_success_rate": round(sql_success / sql_total, 4) if sql_total else 1.0,
            "citation_hit_rate": round(citation_hits / citation_total, 4) if citation_total else 1.0,
            "avg_latency_ms": round(total_latency / n, 2) if n else 0,
        },
        "errors": errors,
        "results": results,
    }

    # 保存结果
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = DATA_DIR / "eval_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"regression_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至 {out_path}")

    if args.save_baseline:
        with open(BASELINE_PATH, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"已更新 baseline → {BASELINE_PATH}")


if __name__ == "__main__":
    main()
