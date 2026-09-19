import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class FailureType(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    RETRY = "retry"
    SKIP = "skip"
    ROLLBACK = "rollback"
    MANUAL = "manual"
    ABORT = "abort"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True

    def get_delay(self, attempt: int) -> float:
        import random
        delay = min(
            self.base_delay_seconds * (self.exponential_base ** attempt),
            self.max_delay_seconds,
        )
        if self.jitter:
            delay *= (0.5 + random.random())
        return delay


@dataclass
class CircuitBreakerState:
    failures: int = 0
    successes: int = 0
    last_failure_time: str | None = None
    is_open: bool = False
    opened_at: str | None = None


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: float = 60.0,
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds
        self.state = CircuitBreakerState()

    def record_success(self):
        self.state.failures = 0
        self.state.successes += 1
        if self.state.successes >= self.success_threshold:
            self.state.is_open = False
            self.state.opened_at = None

    def record_failure(self):
        self.state.failures += 1
        self.state.successes = 0
        self.state.last_failure_time = datetime.now(timezone.utc).isoformat()
        if self.state.failures >= self.failure_threshold:
            self.state.is_open = True
            self.state.opened_at = datetime.now(timezone.utc).isoformat()

    def can_execute(self) -> bool:
        if not self.state.is_open:
            return True
        if self.state.opened_at:
            opened = datetime.fromisoformat(self.state.opened_at.replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - opened).total_seconds() > self.timeout_seconds:
                self.state.is_open = False
                self.state.failures = 0
                return True
        return False

    def get_state(self) -> dict[str, Any]:
        return {
            "is_open": self.state.is_open,
            "failures": self.state.failures,
            "successes": self.state.successes,
            "last_failure_time": self.state.last_failure_time,
            "opened_at": self.state.opened_at,
        }


class FailureClassifier:
    TRANSIENT_ERRORS = [
        "timeout",
        "connection",
        "connect",
        "temporary",
        "unavailable",
        "rate limit",
        "503",
        "504",
        "429",
    ]

    PERMANENT_ERRORS = [
        "not found",
        "404",
        "invalid",
        "unauthorized",
        "401",
        "403",
        "forbidden",
        "bad request",
        "400",
        "validation",
        "schema",
    ]

    @classmethod
    def classify(cls, error: Exception | str) -> FailureType:
        error_str = str(error).lower()

        for transient in cls.TRANSIENT_ERRORS:
            if transient in error_str:
                return FailureType.TRANSIENT

        for permanent in cls.PERMANENT_ERRORS:
            if permanent in error_str:
                return FailureType.PERMANENT

        return FailureType.UNKNOWN


@dataclass
class RecoveryStrategy:
    action: RecoveryAction
    reason: str
    retry_policy: RetryPolicy | None = None
    fallback_stage: str | None = None


class RecoveryPlanner:
    def __init__(
        self,
        default_retry_policy: RetryPolicy | None = None,
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
    ):
        self.default_retry_policy = default_retry_policy or RetryPolicy()
        self.circuit_breakers = circuit_breakers or {}

    def get_circuit_breaker(self, stage: str) -> CircuitBreaker:
        if stage not in self.circuit_breakers:
            self.circuit_breakers[stage] = CircuitBreaker()
        return self.circuit_breakers[stage]

    def plan_recovery(
        self,
        stage: str,
        error: Exception | str,
        attempt: int,
        is_optional: bool = False,
    ) -> RecoveryStrategy:
        failure_type = FailureClassifier.classify(error)
        circuit_breaker = self.get_circuit_breaker(stage)

        if failure_type == FailureType.PERMANENT:
            if is_optional:
                return RecoveryStrategy(
                    action=RecoveryAction.SKIP,
                    reason=f"Permanent failure in optional stage: {error}",
                )
            return RecoveryStrategy(
                action=RecoveryAction.ABORT,
                reason=f"Permanent failure in required stage: {error}",
            )

        if failure_type == FailureType.TRANSIENT:
            if circuit_breaker.state.is_open:
                return RecoveryStrategy(
                    action=RecoveryAction.MANUAL,
                    reason=f"Circuit breaker open for {stage}",
                )

            if attempt < self.default_retry_policy.max_retries:
                return RecoveryStrategy(
                    action=RecoveryAction.RETRY,
                    reason=f"Transient failure, will retry (attempt {attempt + 1})",
                    retry_policy=self.default_retry_policy,
                )

            if is_optional:
                return RecoveryStrategy(
                    action=RecoveryAction.SKIP,
                    reason="Max retries exceeded for optional stage",
                )

            return RecoveryStrategy(
                action=RecoveryAction.MANUAL,
                reason="Max retries exceeded for required stage",
            )

        if attempt < self.default_retry_policy.max_retries:
            return RecoveryStrategy(
                action=RecoveryAction.RETRY,
                reason=f"Unknown failure type, will retry (attempt {attempt + 1})",
                retry_policy=self.default_retry_policy,
            )

        if is_optional:
            return RecoveryStrategy(
                action=RecoveryAction.SKIP,
                reason="Max retries exceeded for optional stage (unknown failure)",
            )

        return RecoveryStrategy(
            action=RecoveryAction.MANUAL,
            reason="Max retries exceeded for required stage (unknown failure)",
        )


def execute_with_retry(
    func: Callable,
    retry_policy: RetryPolicy,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Any:
    last_exception = None

    for attempt in range(retry_policy.max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < retry_policy.max_retries:
                delay = retry_policy.get_delay(attempt)
                if on_retry:
                    on_retry(attempt + 1, e)
                time.sleep(delay)
            else:
                break

    raise last_exception


class StageRecoveryManager:
    def __init__(self, recovery_planner: RecoveryPlanner | None = None):
        self.planner = recovery_planner or RecoveryPlanner()
        self._stage_attempts: dict[str, int] = {}

    def get_attempt(self, stage: str) -> int:
        return self._stage_attempts.get(stage, 0)

    def increment_attempt(self, stage: str):
        self._stage_attempts[stage] = self.get_attempt(stage) + 1

    def reset_attempt(self, stage: str):
        self._stage_attempts[stage] = 0

    def execute_stage(
        self,
        stage: str,
        func: Callable,
        is_optional: bool = False,
        on_retry: Callable[[int, Exception], None] | None = None,
    ) -> tuple[bool, Any, str | None]:
        while True:
            attempt = self.get_attempt(stage)
            try:
                result = func()
                self.planner.get_circuit_breaker(stage).record_success()
                self.reset_attempt(stage)
                return True, result, None
            except Exception as e:
                self.planner.get_circuit_breaker(stage).record_failure()
                self.increment_attempt(stage)

                strategy = self.planner.plan_recovery(stage, e, attempt, is_optional)

                if strategy.action == RecoveryAction.RETRY:
                    if strategy.retry_policy and on_retry:
                        on_retry(attempt + 1, e)
                    delay = strategy.retry_policy.get_delay(attempt) if strategy.retry_policy else 1.0
                    time.sleep(delay)
                    continue

                elif strategy.action == RecoveryAction.SKIP:
                    self.reset_attempt(stage)
                    return False, None, f"Skipped: {strategy.reason}"

                elif strategy.action == RecoveryAction.ABORT:
                    self.reset_attempt(stage)
                    return False, None, f"Aborted: {strategy.reason}"

                else:
                    self.reset_attempt(stage)
                    return False, None, strategy.reason
