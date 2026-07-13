"""
简易熔断器 — 保护 LLM API 调用不被连续失败拖垮整个系统。

状态机：
  CLOSED  → 正常放行
  OPEN    → 连续失败超阈值，拒绝请求，等待冷却
  HALF_OPEN → 冷却期过，放行一次试探，成功则恢复 CLOSED

集成位置：LLMClient 调用前检查 llm_breaker.allow_request()。
"""

import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """
    简易熔断器。

    用法：
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        if breaker.allow_request():
            try:
                result = do_something()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
        else:
            # 熔断中，走降级逻辑
    """

    failure_threshold: int = 3
    recovery_timeout: float = 30.0

    state: CircuitState = field(default=CircuitState.CLOSED, repr=False)
    _failure_count: int = field(default=0, repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)
    _total_failures: int = field(default=0, repr=False)
    _total_successes: int = field(default=0, repr=False)

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True  # 允许一次试探
            return False
        # HALF_OPEN — 允许一次请求
        return True

    def record_success(self) -> None:
        self._failure_count = 0
        self._total_successes += 1
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._total_failures += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def get_stats(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
        }

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0


# ── 全局实例 ─────────────────────────────────────────────────────────

llm_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
