"""
统一 LLM 调用客户端 — 内置重试、超时、调用记录、流式支持。

设计目标：
  - 所有 LLM 调用都经过此客户端，不再散落在 agent.py / rag.py 各自 httpx
  - 指数退避重试 (tenacity)：2s → 4s → 8s，最多 3 次
  - 每次调用记录 prompt_tokens / completion_tokens / latency / success / error
  - 支持同步 call() 和流式 stream() 两种模式
  - 集成 CircuitBreaker 做熔断降级
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Generator
from uuid import uuid4

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.core.config import settings
from app.services.circuit_breaker import llm_breaker

# LangSmith traceable — 仅在包已安装时启用
try:
    from langsmith import traceable as _ls_traceable
except ImportError:  # pragma: no cover
    def _ls_traceable(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        """占位装饰器：langsmith 未安装时透传。"""
        def _wrap(fn):  # type: ignore[no-untyped-def]
            return fn
        return _wrap

logger = logging.getLogger(__name__)


# ── 调用记录 ─────────────────────────────────────────────────────────


@dataclass
class LLMCallRecord:
    """单次 LLM 调用的完整追踪记录。"""

    call_id: str
    model: str
    purpose: str = ""  # "router" | "sql_gen" | "hybrid_synthesis" | "rerank" | "param_extract"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0
    success: bool = True
    error: str | None = None
    retry_count: int = 0


# 内存级调用日志（生产环境应换为持久化或 OTLP exporter）
_call_log: list[LLMCallRecord] = []


def get_llm_call_log() -> list[dict[str, Any]]:
    """返回所有 LLM 调用记录（供 Trace / Eval / API 查询）。"""
    return [
        {
            "call_id": r.call_id,
            "model": r.model,
            "purpose": r.purpose,
            "prompt_tokens": r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens": r.total_tokens,
            "latency_ms": r.latency_ms,
            "success": r.success,
            "error": r.error,
            "retry_count": r.retry_count,
        }
        for r in _call_log
    ]


def get_llm_stats() -> dict[str, Any]:
    """汇总统计：总调用次数、成功率、总 token 消耗、平均延迟。"""
    total = len(_call_log)
    if total == 0:
        return {"total_calls": 0}
    success = sum(1 for r in _call_log if r.success)
    return {
        "total_calls": total,
        "success_rate": round(success / total, 4),
        "total_prompt_tokens": sum(r.prompt_tokens for r in _call_log),
        "total_completion_tokens": sum(r.completion_tokens for r in _call_log),
        "total_tokens": sum(r.total_tokens for r in _call_log),
        "avg_latency_ms": round(sum(r.latency_ms for r in _call_log) / total, 2),
    }


def reset_llm_call_log() -> None:
    """清空调用记录（评估运行前调用）。"""
    _call_log.clear()


# ── LLM 客户端 ───────────────────────────────────────────────────────


class LLMClient:
    """
    统一 LLM 调用客户端。

    用法：
        client = LLMClient()
        text, record = client.call(messages, purpose="router")
        # 或流式：
        for delta, record in client.stream(messages, purpose="answer"):
            yield delta
    """

    def __init__(
        self,
        max_retries: int = 3,
        timeout: float = 30.0,
    ):
        self.max_retries = max_retries
        self.timeout = timeout

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.siliconflow_api_key}",
            "Content-Type": "application/json",
        }

    def _build_url(self) -> str:
        return f"{settings.llm_base_url.rstrip('/')}/chat/completions"

    @_ls_traceable(name="LLM call", tags=["llm", "sync"])
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(
            # TransportError covers short-lived TLS EOF, connection reset,
            # read/write failures and the existing timeout/protocol failures.
            # HTTP status errors remain non-retryable below.
            httpx.TransportError
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def call(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str = "unknown",
        temperature: float = 0.1,
        max_tokens: int = 600,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, LLMCallRecord]:
        """
        同步调用 LLM，返回 (response_text, call_record)。

        内置 tenacity 重试：对 TimeoutException 和 RemoteProtocolError 自动重试。
        HTTP 4xx/5xx 通过 raise_for_status() 抛出，tenacity 不重试（业务错误不该重试）。
        熔断器：连续失败 3 次后自动熔断，30 秒后半开试探恢复。
        """
        if not llm_breaker.allow_request():
            raise RuntimeError("CircuitBreaker is OPEN — LLM 服务暂不可用，请稍后重试")

        call_id = uuid4().hex[:12]
        record = LLMCallRecord(
            call_id=call_id, model=settings.llm_model, purpose=purpose
        )

        payload: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        start = time.perf_counter()
        try:
            with httpx.Client() as client:
                resp = client.post(
                    self._build_url(),
                    headers=self._build_headers(),
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()

            record.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            usage = data.get("usage", {})
            record.prompt_tokens = usage.get("prompt_tokens", 0)
            record.completion_tokens = usage.get("completion_tokens", 0)
            record.total_tokens = usage.get("total_tokens", 0)
            record.success = True

            text = data["choices"][0]["message"]["content"].strip()
            _call_log.append(record)
            llm_breaker.record_success()
            return text, record

        except httpx.HTTPStatusError:
            # 4xx/5xx — 记录但不重试
            record.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            record.success = False
            record.error = "HTTP status error"
            _call_log.append(record)
            llm_breaker.record_failure()
            raise

        except Exception as exc:
            record.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            record.success = False
            record.error = str(exc)[:200]
            _call_log.append(record)
            llm_breaker.record_failure()
            raise

    @_ls_traceable(name="LLM stream", tags=["llm", "stream"])
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str = "unknown",
        temperature: float = 0.2,
        max_tokens: int = 900,
    ) -> Generator[tuple[str, LLMCallRecord | None], None, None]:
        """
        流式调用 LLM，逐 chunk yield (delta_text, record)。

        最后一个 yield 的 record 不为 None，包含完整 token 统计。
        中间 yield 的 record 为 None。
        熔断器：连续失败 3 次后自动熔断，30 秒后半开试探恢复。
        """
        if not llm_breaker.allow_request():
            raise RuntimeError("CircuitBreaker is OPEN — LLM 服务暂不可用，请稍后重试")

        call_id = uuid4().hex[:12]
        record = LLMCallRecord(
            call_id=call_id, model=settings.llm_model, purpose=purpose
        )

        payload: dict[str, Any] = {
            "model": settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        start = time.perf_counter()
        full_text = ""

        try:
            with httpx.Client() as client:
                with client.stream(
                    "POST",
                    self._build_url(),
                    headers=self._build_headers(),
                    json=payload,
                    timeout=self.timeout,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            import json

                            chunk = json.loads(data_str)
                            delta = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                full_text += delta
                                yield delta, None
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue

            record.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            record.success = True
            # 流式调用通常不返回 usage，用字符数估算
            record.completion_tokens = len(full_text) // 3
            record.prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 3
            record.total_tokens = record.prompt_tokens + record.completion_tokens
            _call_log.append(record)
            llm_breaker.record_success()
            yield "", record  # 最后一条，携带 record

        except Exception as exc:
            record.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            record.success = False
            record.error = str(exc)[:200]
            _call_log.append(record)
            llm_breaker.record_failure()
            raise


# ── 全局单例 ─────────────────────────────────────────────────────────

_default_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
