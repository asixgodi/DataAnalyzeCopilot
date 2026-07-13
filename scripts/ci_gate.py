"""
CI 门禁脚本 — 在 CI 环境中运行回归测试，核心指标不达标则 exit(1)。

用法：
    python scripts/ci_gate.py                      # 使用默认阈值
    python scripts/ci_gate.py --baseline data/baseline.json  # 与 baseline 对比

门禁阈值（可在下方 GATE_THRESHOLDS 中调整）：
  - route_accuracy >= 0.85
  - sql_execution_success_rate >= 0.90
  - task_success_rate >= 0.80
  - citation_hit_rate >= 0.75
  - avg_latency_ms <= 15000
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
REGRESSION_PATH = DATA_DIR / "regression_cases.jsonl"
RESULTS_DIR = DATA_DIR / "eval_runs"

GATE_THRESHOLDS = {
    "route_accuracy": 0.85,
    "sql_execution_success_rate": 0.90,
    "task_success_rate": 0.80,
    "citation_hit_rate": 0.75,
    "avg_latency_ms": 15000,  # 上限，不是下限
}


def load_cases(path: Path) -> list[dict]:
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def run_gate(baseline_path: Path | None = None) -> dict:
    """
    运行回归测试并检查门禁。

    Returns:
        {"passed": bool, "metrics": dict, "baseline_diff": dict | None, "results": list}
    """
    # 延迟导入，确保 FastAPI 应用已配置
    sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

    from app.services.agent import run_agent
    from app.schemas.chat import ChatRequest

    cases = load_cases(REGRESSION_PATH)
    results = []
    route_correct = 0
    sql_success = 0
    sql_total = 0
    keyword_correct = 0
    citation_hits = 0
    citation_total = 0
    total_latency = 0

    for i, case in enumerate(cases):
        print(f"  [{i+1}/{len(cases)}] {case['question'][:40]}...", end=" ")

        start = time.time()
        try:
            response = run_agent(ChatRequest(
                message=case["question"],
                session_id=f"ci_{case['id']}",
            ))
            latency_ms = (time.time() - start) * 1000
            total_latency += latency_ms

            # 路由检查
            if response.route == case["expected_route"]:
                route_correct += 1

            # SQL 执行检查
            if case["expected_route"] in ("sql", "hybrid"):
                sql_total += 1
                if response.sql_result and not response.sql_result.error:
                    sql_success += 1

            # 关键词检查
            if all(kw in response.answer for kw in case.get("expected_keywords", [])):
                keyword_correct += 1

            # 引用检查
            if case["expected_route"] in ("rag", "hybrid"):
                citation_total += 1
                if response.citations:
                    citation_hits += 1

            result = {
                "id": case["id"],
                "question": case["question"],
                "expected_route": case["expected_route"],
                "actual_route": response.route,
                "route_correct": response.route == case["expected_route"],
                "latency_ms": round(latency_ms, 2),
                "answer_preview": response.answer[:100],
            }
            results.append(result)
            status = "PASS" if response.route == case["expected_route"] else "FAIL"
            print(f"[{status}] {latency_ms:.0f}ms")

        except Exception as exc:
            print(f"[ERROR] {exc}")
            results.append({
                "id": case["id"],
                "question": case["question"],
                "error": str(exc),
            })

    # 计算指标
    n = len(cases)
    metrics = {
        "route_accuracy": round(route_correct / n, 4) if n else 0,
        "sql_execution_success_rate": round(sql_success / sql_total, 4) if sql_total else 1.0,
        "task_success_rate": round(keyword_correct / n, 4) if n else 0,
        "citation_hit_rate": round(citation_hits / citation_total, 4) if citation_total else 1.0,
        "avg_latency_ms": round(total_latency / n, 2) if n else 0,
    }

    # Baseline 对比
    baseline_diff = None
    if baseline_path and baseline_path.exists():
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)
        baseline_metrics = baseline.get("metrics", {})
        baseline_diff = {
            k: round(metrics.get(k, 0) - baseline_metrics.get(k, 0), 4)
            for k in metrics
        }

    # 门禁检查
    all_pass = True
    gate_results = {}
    for metric, threshold in GATE_THRESHOLDS.items():
        value = metrics.get(metric, 0)
        if metric == "avg_latency_ms":
            passed = value <= threshold
        else:
            passed = value >= threshold
        gate_results[metric] = {"value": value, "threshold": threshold, "passed": passed}
        if not passed:
            all_pass = False

    return {
        "passed": all_pass,
        "metrics": metrics,
        "gate_results": gate_results,
        "baseline_diff": baseline_diff,
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="CI Gate — Agent 回归测试门禁")
    parser.add_argument("--baseline", type=str, default=None, help="Baseline JSON 路径")
    args = parser.parse_args()

    baseline_path = Path(args.baseline) if args.baseline else None

    print("\n═══ CI Gate: Agent 回归测试 ═══\n")
    report = run_gate(baseline_path)

    print("\n─── 指标 ───")
    for metric, info in report["gate_results"].items():
        v = info["value"]
        t = info["threshold"]
        op = "≤" if metric == "avg_latency_ms" else "≥"
        status = "PASS" if info["passed"] else "FAIL"
        print(f"  {metric}: {v:.4f} {op} {t}  [{status}]")

    if report["baseline_diff"]:
        print("\n─── vs Baseline ───")
        for k, diff in report["baseline_diff"].items():
            sign = "+" if diff >= 0 else ""
            print(f"  {k}: {sign}{diff:.4f}")

    # 保存结果
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"gate_{ts}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至 {output_path}")

    if report["passed"]:
        print("\n✓ All gates passed.")
        sys.exit(0)
    else:
        print("\n✗ Some gates failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
