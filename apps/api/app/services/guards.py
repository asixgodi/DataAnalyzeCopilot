"""
Agent 输入 / 输出护栏 — 保障 Agent 稳定运行的第一道和最后一道防线。

InputGuard:
  - 长度校验（空输入 / 超长截断）
  - SQL 注入模式检测
  - Prompt 注入模式检测

OutputGuard:
  - 空答案检测
  - 信息泄露检测（API Key、堆栈信息）
  - 简易数字幻觉检测
  - RAG 引用一致性检查
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class GuardResult:
    """护栏检查结果。"""

    passed: bool
    reason: str = ""
    sanitized_input: str = ""
    guard_name: str = ""


# ── Input Guard ──────────────────────────────────────────────────────


class InputGuard:
    """
    Agent 输入护栏 — 在问题进入 LangGraph 之前做安全检查。

    集成位置：run_agent() 入口。
    """

    MAX_INPUT_LENGTH = 2000
    MIN_INPUT_LENGTH = 1

    SQL_INJECTION_PATTERNS = [
        r"\bunion\s+select\b",
        r"\binsert\s+into\b",
        r"\bdrop\s+table\b",
        r"(--|;)\s*(drop|delete|update|insert|alter)\b",
        r"'\s*(or|and)\s+'?\d*'?\s*=\s*'?\d*",
    ]

    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?(previous|above)\s+instructions",
        r"you\s+are\s+now\s+(a|an)\s+",
        r"system\s*:\s*",
        r"新指令",
        r"忽略.*之前.*指令",
        r"忽略.*以上.*内容",
        r"你现在是",
    ]

    _sql_compiled = [re.compile(p, re.IGNORECASE) for p in SQL_INJECTION_PATTERNS]
    _prompt_compiled = [re.compile(p, re.IGNORECASE) for p in PROMPT_INJECTION_PATTERNS]

    def check(self, user_input: str) -> GuardResult:
        if not user_input or len(user_input.strip()) < self.MIN_INPUT_LENGTH:
            return GuardResult(
                passed=False, reason="输入为空，请输入您的问题。", guard_name="input_empty",
            )

        text = user_input
        truncated = False
        if len(text) > self.MAX_INPUT_LENGTH:
            text = text[: self.MAX_INPUT_LENGTH]
            truncated = True

        for pattern in self._sql_compiled:
            if pattern.search(text):
                return GuardResult(
                    passed=False,
                    reason="检测到潜在的注入风险，请重新描述您的问题。",
                    guard_name="sql_injection",
                )

        for pattern in self._prompt_compiled:
            if pattern.search(text):
                return GuardResult(
                    passed=False,
                    reason="检测到不合规的输入，请使用正常的问题描述。",
                    guard_name="prompt_injection",
                )

        reason = f"输入已截断至 {self.MAX_INPUT_LENGTH} 字符。" if truncated else ""
        return GuardResult(
            passed=True, reason=reason, sanitized_input=text.strip(), guard_name="input_ok",
        )


# ── Output Guard ─────────────────────────────────────────────────────


class OutputGuard:
    """
    Agent 输出护栏 — 在答案返回给用户之前做质量检查。

    集成位置：run_agent() 返回前，在 _answer_guard_and_repair 之后。
    """

    MIN_ANSWER_LENGTH = 5

    LEAK_PATTERNS = [
        r"(SILICONFLOW_API_KEY|sk-[a-zA-Z0-9]{20,})",
        r"(Bearer\s+[a-zA-Z0-9._-]+)",
        r"Traceback \(most recent call last\)",
    ]
    _leak_compiled = [re.compile(p, re.IGNORECASE) for p in LEAK_PATTERNS]

    def check(
        self,
        answer: str,
        route: str,
        sql_rows: list[dict[str, Any]] | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> GuardResult:
        if not answer or len(answer.strip()) < self.MIN_ANSWER_LENGTH:
            return GuardResult(
                passed=False, reason="答案内容过短，可能生成失败。", guard_name="output_empty",
            )

        for pattern in self._leak_compiled:
            if pattern.search(answer):
                return GuardResult(
                    passed=False,
                    reason="答案中包含不应展示的内部信息。",
                    guard_name="info_leak",
                )

        if sql_rows and route in ("sql", "hybrid"):
            if self._detect_number_hallucination(
                answer,
                sql_rows,
                citations=citations if route == "hybrid" else None,
            ):
                return GuardResult(
                    passed=False,
                    reason="检测到答案中的数字与查询结果可能不一致，请核实。",
                    guard_name="number_hallucination",
                )

        if route == "rag" and not citations:
            return GuardResult(
                passed=False,
                reason="RAG 路由但未返回引用来源，答案可信度不足。",
                guard_name="missing_citation",
            )

        return GuardResult(passed=True, guard_name="output_ok")

    @staticmethod
    def _detect_number_hallucination(
        answer: str,
        rows: list[dict[str, Any]],
        citations: list[dict[str, Any]] | None = None,
    ) -> bool:
        """
        简易幻觉检测：提取答案中的数字，与证据交叉验证。

        SQL 路由只认可 SQL 结果；Hybrid 路由还认可最终 Citation
        摘要中的数字，例如退货期限、SLA 或政策阈值。
        启发式方法，只在大量不匹配时触发。
        """
        answer_numbers = set(re.findall(r"\d+\.?\d*", answer))
        result_numbers: set[str] = set()
        for row in rows:
            for value in row.values():
                if isinstance(value, (int, float)):
                    result_numbers.add(str(value))
                    result_numbers.add(str(round(float(value), 2)))

        for citation in citations or []:
            snippet = str(citation.get("snippet", ""))
            result_numbers.update(re.findall(r"\d+\.?\d*", snippet))

        # 排除常见无害数字
        safe_numbers = {"0", "1", "2", "100", "0.0", "1.0"}
        ungrounded = answer_numbers - result_numbers - safe_numbers

        # 如果答案中超过 4 个数字不在 SQL 结果中，且答案数字总数 > 5
        if len(ungrounded) > 4 and len(answer_numbers) > 5:
            return True
        return False
