import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from app.schemas.chat import ChatRequest
from app.services.agent import run_agent


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "data"
JSONL_PATH = DATA_DIR / "eval_dataset.jsonl"
RESULTS_PATH = DATA_DIR / "eval_results.json"
REPORT_PATH = DATA_DIR / "eval_report.md"


EVAL_CASES = [
    {
        "id": "builtin-001",
        "question": "4月服装类商品退款率是多少？",
        "expected_route": "sql",
        "expected_keywords": ["退款率"],
        "expected_tools": ["execute_readonly_sql"],
        "difficulty": "easy",
        "category": "sql",
    },
    {
        "id": "builtin-002",
        "question": "退款率指标口径是什么？",
        "expected_route": "rag",
        "expected_keywords": ["知识库", "依据"],
        "expected_tools": ["retrieve_docs"],
        "difficulty": "easy",
        "category": "rag",
    },
    {
        "id": "builtin-003",
        "question": "4月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。",
        "expected_route": "hybrid",
        "expected_keywords": ["退款率", "知识库"],
        "expected_tools": ["execute_readonly_sql", "retrieve_docs"],
        "difficulty": "medium",
        "category": "hybrid",
    },
    {
        "id": "builtin-004",
        "question": "随便看看",
        "expected_route": "clarification",
        "expected_keywords": ["补充"],
        "expected_tools": [],
        "difficulty": "easy",
        "category": "clarification",
    },
]


def _load_cases() -> list[dict[str, Any]]:
    if JSONL_PATH.exists():
        cases: list[dict[str, Any]] = []
        with open(JSONL_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    cases.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if cases:
            return cases
    return EVAL_CASES


def _check_keywords(answer: str, keywords: list[str]) -> bool:
    return all(keyword in answer for keyword in keywords)


def _resolve_actual_tools(steps: list[Any], route: str) -> list[str]:
    tools: set[str] = set()
    node_names = {step.node_name for step in steps}
    if "list_tables" in node_names:
        tools.add("list_tables")
    if "execute_sql" in node_names:
        tools.add("execute_readonly_sql")
    if "retrieve_docs" in node_names:
        tools.add("retrieve_docs")
    return list(tools)


def run_eval() -> dict[str, object]:
    cases = _load_cases()
    results: list[dict[str, Any]] = []

    total = len(cases)
    route_hits = 0
    keyword_hits = 0
    tool_hits = 0
    sql_total = 0
    sql_success = 0
    citation_total = 0
    citation_hits = 0
    latency_values: list[float] = []
    tool_call_counts: list[int] = []
    retry_total = 0
    retry_success = 0
    task_success = 0

    category_counts: dict[str, dict[str, int]] = {}
    difficulty_counts: dict[str, dict[str, int]] = {}

    for case in cases:
        case_id = str(case.get("id", "unknown"))
        expected_route = str(case.get("expected_route", "sql"))
        expected_keywords: list[str] = case.get("expected_keywords", [])
        expected_tools: list[str] = case.get("expected_tools", [])
        difficulty = str(case.get("difficulty", "medium"))
        category = str(case.get("category", "unknown"))

        try:
            response = run_agent(ChatRequest(message=case["question"], session_id=f"eval_{case_id}"))
        except Exception as exc:
            results.append({
                "id": case_id,
                "question": case["question"],
                "expected_route": expected_route,
                "actual_route": "error",
                "route_ok": False,
                "keyword_ok": False,
                "tool_ok": False,
                "sql_ok": None,
                "citation_ok": None,
                "task_ok": False,
                "latency_ms": 0,
                "tool_calls": 0,
                "error": str(exc),
            })
            continue

        actual_route = response.route
        route_ok = actual_route == expected_route
        keyword_ok = _check_keywords(response.answer, expected_keywords)

        actual_tools = _resolve_actual_tools(response.steps, actual_route)
        tool_ok = set(expected_tools).issubset(set(actual_tools)) if expected_tools else True

        sql_ok: bool | None = None
        if actual_route in {"sql", "hybrid"} and response.sql_result is not None:
            sql_total += 1
            sql_ok = response.sql_result.error is None
            if sql_ok:
                sql_success += 1

        citation_ok: bool | None = None
        if actual_route in {"rag", "hybrid"} and expected_route in {"rag", "hybrid"}:
            citation_total += 1
            citation_ok = len(response.citations) > 0
            if citation_ok:
                citation_hits += 1

        task_ok = route_ok and keyword_ok and tool_ok

        route_hits += int(route_ok)
        keyword_hits += int(keyword_ok)
        tool_hits += int(tool_ok)
        task_success += int(task_ok)
        latency_values.append(response.metrics.latency_ms)
        tool_call_counts.append(response.metrics.tool_calls)

        if category not in category_counts:
            category_counts[category] = {"total": 0, "passed": 0}
        category_counts[category]["total"] += 1
        if task_ok:
            category_counts[category]["passed"] += 1

        if difficulty not in difficulty_counts:
            difficulty_counts[difficulty] = {"total": 0, "passed": 0}
        difficulty_counts[difficulty]["total"] += 1
        if task_ok:
            difficulty_counts[difficulty]["passed"] += 1

        results.append({
            "id": case_id,
            "question": case["question"],
            "expected_route": expected_route,
            "actual_route": actual_route,
            "route_ok": route_ok,
            "keyword_ok": keyword_ok,
            "tool_ok": tool_ok,
            "sql_ok": sql_ok,
            "citation_ok": citation_ok,
            "task_ok": task_ok,
            "latency_ms": response.metrics.latency_ms,
            "tool_calls": response.metrics.tool_calls,
        })

    route_accuracy = round(route_hits / total, 3) if total else 0
    keyword_accuracy = round(keyword_hits / total, 3) if total else 0
    tool_accuracy = round(tool_hits / total, 3) if total else 0
    task_success_rate = round(task_success / total, 3) if total else 0
    sql_success_rate = round(sql_success / sql_total, 3) if sql_total else None
    citation_hit_rate = round(citation_hits / citation_total, 3) if citation_total else None
    avg_latency = round(mean(latency_values), 2) if latency_values else 0
    avg_tool_calls = round(mean(tool_call_counts), 2) if tool_call_counts else 0
    retry_success_rate = round(retry_success / retry_total, 3) if retry_total else None

    summary = {
        "total": total,
        "task_success_rate": task_success_rate,
        "route_accuracy": route_accuracy,
        "keyword_accuracy": keyword_accuracy,
        "tool_call_accuracy": tool_accuracy,
        "sql_execution_success_rate": sql_success_rate,
        "citation_hit_rate": citation_hit_rate,
        "avg_latency_ms": avg_latency,
        "avg_tool_calls": avg_tool_calls,
        "retry_success_rate": retry_success_rate,
        "category_breakdown": {
            cat: {"total": v["total"], "passed": v["passed"], "rate": round(v["passed"] / v["total"], 3) if v["total"] else 0}
            for cat, v in category_counts.items()
        },
        "difficulty_breakdown": {
            diff: {"total": v["total"], "passed": v["passed"], "rate": round(v["passed"] / v["total"], 3) if v["total"] else 0}
            for diff, v in difficulty_counts.items()
        },
    }

    _write_results_json(summary, results)
    _write_report_md(summary, results, cases)

    return summary


def _write_results_json(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _write_report_md(summary: dict[str, Any], results: list[dict[str, Any]], cases: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    lines.append("# 评估报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")

    lines.append("## 总体指标")
    lines.append("")
    lines.append(f"| 指标 | 值 |")
    lines.append(f"| --- | --- |")
    lines.append(f"| 测试用例总数 | {summary['total']} |")
    lines.append(f"| 任务成功率 (task_success_rate) | {summary['task_success_rate']} |")
    lines.append(f"| 路由准确率 (route_accuracy) | {summary['route_accuracy']} |")
    lines.append(f"| 关键词召回率 (keyword_accuracy) | {summary['keyword_accuracy']} |")
    lines.append(f"| 工具调用准确率 (tool_call_accuracy) | {summary['tool_call_accuracy']} |")
    lines.append(f"| SQL 执行成功率 (sql_execution_success_rate) | {summary['sql_execution_success_rate'] if summary['sql_execution_success_rate'] is not None else 'N/A'} |")
    lines.append(f"| 文档引用命中率 (citation_hit_rate) | {summary['citation_hit_rate'] if summary['citation_hit_rate'] is not None else 'N/A'} |")
    lines.append(f"| 平均延迟 (avg_latency_ms) | {summary['avg_latency_ms']} ms |")
    lines.append(f"| 平均工具调用次数 (avg_tool_calls) | {summary['avg_tool_calls']} |")
    lines.append(f"| 重试成功率 (retry_success_rate) | {summary['retry_success_rate'] if summary['retry_success_rate'] is not None else 'N/A'} |")
    lines.append("")

    if summary.get("category_breakdown"):
        lines.append("## 分类指标")
        lines.append("")
        lines.append(f"| 分类 | 总数 | 通过 | 通过率 |")
        lines.append(f"| --- | --- | --- | --- |")
        for cat, info in summary["category_breakdown"].items():
            lines.append(f"| {cat} | {info['total']} | {info['passed']} | {info['rate']} |")
        lines.append("")

    if summary.get("difficulty_breakdown"):
        lines.append("## 难度指标")
        lines.append("")
        lines.append(f"| 难度 | 总数 | 通过 | 通过率 |")
        lines.append(f"| --- | --- | --- | --- |")
        for diff, info in summary["difficulty_breakdown"].items():
            lines.append(f"| {diff} | {info['total']} | {info['passed']} | {info['rate']} |")
        lines.append("")

    lines.append("## 失败用例明细")
    lines.append("")
    failed = [r for r in results if not r.get("task_ok", False)]
    if failed:
        for item in failed:
            lines.append(f"- **{item['id']}**: {item['question']}")
            lines.append(f"  - 预期路由: {item['expected_route']} / 实际路由: {item['actual_route']}")
            lines.append(f"  - 路由匹配: {item['route_ok']} / 关键词: {item['keyword_ok']} / 工具: {item.get('tool_ok', 'N/A')}")
            lines.append("")
    else:
        lines.append("无失败用例。")
        lines.append("")

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
