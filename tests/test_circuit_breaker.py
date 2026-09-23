"""M7 RED tests: circuit breaker (policy, states, probe, executor integration).

Covered matrix labels: V, W, X, Y, Z, AB, AC.
"""

import threading
import time

import pytest

from pipeline.cancellation import FakeClock
from pipeline.scheduler import StageScheduler


def _make_test_scheduler(stages: list[str], dependencies: dict[str, list[str]] | None = None):
    deps = {k: tuple(v) for k, v in (dependencies or {}).items()}
    return StageScheduler(tuple(stages), deps, episode_id="CB-EPISODE")


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def _retryable_failures(times: int, then_error: type[Exception] | None = None):
    """Factory returning retryable-failing agents with a STABLE per-stage counter.

    The executor invokes ``agent_factory(stage)`` once per attempt (M7 retry
    contract), so the counter must live in the factory, not in the returned
    agent closure.
    """
    counter_lock = threading.Lock()
    counts: dict[str, int] = {}

    def make(stage: str):
        def agent(inputs):
            from pipeline.retry import RetryableError

            with counter_lock:
                counts[stage] = counts.get(stage, 0) + 1
                n = counts[stage]
            if n <= times:
                raise RetryableError("transient")
            if then_error is not None:
                raise then_error("hard")
            return {stage: "ok"}

        return agent

    return make


class TestCircuitBreakerPolicyValidation:
    """V. Policy validation: threshold >= 1, cooldown >= 0."""

    def test_defaults(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy

        policy = CircuitBreakerPolicy()
        assert policy.failure_threshold == 3
        assert policy.cooldown_seconds == 5.0

    def test_invalid_threshold(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy

        with pytest.raises(ValueError):
            CircuitBreakerPolicy(failure_threshold=0)
        with pytest.raises(ValueError):
            CircuitBreakerPolicy(failure_threshold=-1)

    def test_invalid_cooldown(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy

        with pytest.raises(ValueError):
            CircuitBreakerPolicy(cooldown_seconds=-0.1)


class TestCircuitBreakerClosedState:
    """W. CLOSED state: allowed, threshold not reached yet, success resets."""

    def test_initial_closed_allows(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        breaker = CircuitBreaker(
            "A", CircuitBreakerPolicy(failure_threshold=3, cooldown_seconds=10.0), FakeClock(0.0)
        )
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request()

    def test_below_threshold_stays_closed(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        breaker = CircuitBreaker(
            "A", CircuitBreakerPolicy(failure_threshold=3, cooldown_seconds=10.0), FakeClock(0.0)
        )
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request()

    def test_success_resets_failure_counter(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        breaker = CircuitBreaker(
            "A", CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0), FakeClock(0.0)
        )
        breaker.record_retryable_failure()
        breaker.record_success()
        breaker.record_retryable_failure()
        assert breaker.state == CircuitState.CLOSED, "counter reset broke threshold logic"
        assert breaker.allow_request()

    def test_non_retryable_failure_does_not_increment(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        breaker = CircuitBreaker(
            "A", CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0), FakeClock(0.0)
        )
        breaker.record_non_retryable_failure()
        breaker.record_non_retryable_failure()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request()


class TestCircuitBreakerOpenState:
    """X. OPEN state: threshold reached, no requests until cooldown expires."""

    def test_threshold_opens(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        clock = FakeClock(0.0)
        policy = CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0)
        breaker = CircuitBreaker("A", policy, clock)
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        assert breaker.state == CircuitState.OPEN
        assert not breaker.allow_request()

    def test_open_blocks_until_cooldown(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        clock = FakeClock(0.0)
        policy = CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0)
        breaker = CircuitBreaker("A", policy, clock)
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        assert breaker.state == CircuitState.OPEN

        clock.advance(5.0)
        assert not breaker.allow_request(), "still inside cooldown"

    def test_cooldown_expires_into_half_open_single_probe(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        clock = FakeClock(0.0)
        policy = CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0)
        breaker = CircuitBreaker("A", policy, clock)
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        assert breaker.state == CircuitState.OPEN

        clock.advance(10.0)
        assert breaker.allow_request(), "probe allowed after cooldown"
        assert breaker.state == CircuitState.HALF_OPEN
        assert not breaker.allow_request(), "only one probe in flight"


class TestCircuitBreakerProbe:
    """Y/Z. Probe outcome transitions: success -> CLOSED, retryable -> OPEN,
    non-retryable -> CLOSED."""

    def test_probe_success_closes(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        clock = FakeClock(0.0)
        policy = CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0)
        breaker = CircuitBreaker("A", policy, clock)
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        clock.advance(10.0)
        assert breaker.allow_request()
        breaker.record_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request()

    def test_probe_retryable_failure_reopens(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        clock = FakeClock(0.0)
        policy = CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0)
        breaker = CircuitBreaker("A", policy, clock)
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        clock.advance(10.0)
        assert breaker.allow_request()
        breaker.record_retryable_failure()
        assert breaker.state == CircuitState.OPEN
        assert not breaker.allow_request()

    def test_probe_non_retryable_failure_closes(self):
        from pipeline.circuit_breaker import (
            CircuitBreaker,
            CircuitBreakerPolicy,
            CircuitState,
        )

        clock = FakeClock(0.0)
        policy = CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0)
        breaker = CircuitBreaker("A", policy, clock)
        breaker.record_retryable_failure()
        breaker.record_retryable_failure()
        clock.advance(10.0)
        assert breaker.allow_request()
        breaker.record_non_retryable_failure()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.allow_request()


class TestExecutorCircuitBreakerIntegration:
    """AB. OPEN circuit blocks admission; no worker consumed; retry pending."""

    def test_open_circuit_blocks_retry_without_worker(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy, CircuitState
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"])
        clock = FakeClock(0.0)
        factory = _retryable_failures(times=99999)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=factory,
            clock=clock,
            retry_policy=RetryPolicy(max_attempts=10, base_delay=0.0, max_delay=0.0),
            breaker_policy=CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=500.0),
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: executor.circuit_state("A") == CircuitState.OPEN)
        assert scheduler.status("A").name == "RETRYING"
        assert executor.active_worker_count() == 0, "OPEN circuit must not consume a worker"
        assert executor.retry_counts()["A"] == 2

        executor.cancel_stage("A")
        runner.join(timeout=5.0)
        assert scheduler.status("A").name == "CANCELLED"
        assert executor.circuit_state("A") == CircuitState.OPEN

    def test_half_open_probe_recovers_to_closed(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy, CircuitState
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"])
        clock = FakeClock(0.0)
        factory = _retryable_failures(times=2)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=factory,
            clock=clock,
            retry_policy=RetryPolicy(max_attempts=5, base_delay=1.0, max_delay=1.0),
            breaker_policy=CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0),
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        clock.advance(2.0)
        assert _wait_until(lambda: executor.circuit_state("A") == CircuitState.OPEN)
        assert scheduler.status("A").name == "RETRYING"
        clock.advance(11.0)
        assert _wait_until(lambda: executor.circuit_state("A") == CircuitState.CLOSED)
        runner.join(timeout=5.0)

        assert scheduler.status("A").name == "COMPLETED"
        assert executor.retry_counts()["A"] == 2
        assert executor.circuit_state("A") == CircuitState.CLOSED

    def test_half_open_non_retryable_probe_closes_and_fails_stage(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy, CircuitState
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"])
        clock = FakeClock(0.0)
        calls = {"n": 0}

        def agent(inputs):
            from pipeline.retry import RetryableError

            calls["n"] += 1
            if calls["n"] <= 2:
                raise RetryableError("transient")
            raise RuntimeError("hard probe")

        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda stage: agent,
            clock=clock,
            retry_policy=RetryPolicy(max_attempts=5, base_delay=1.0, max_delay=1.0),
            breaker_policy=CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=10.0),
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        clock.advance(2.0)
        assert _wait_until(lambda: executor.circuit_state("A") == CircuitState.OPEN)
        clock.advance(11.0)
        assert _wait_until(lambda: executor.circuit_state("A") == CircuitState.CLOSED)
        runner.join(timeout=5.0)

        assert calls["n"] == 3, "probe ran once and failed non-retryably"
        assert scheduler.status("A").name == "FAILED"
        assert executor.circuit_state("A") == CircuitState.CLOSED


class TestExecutorCircuitIsolation:
    """AC. Each stage gets its own breaker; failures are isolated."""

    def test_stage_breakers_are_independent(self):
        from pipeline.circuit_breaker import CircuitBreakerPolicy, CircuitState
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"])
        clock = FakeClock(0.0)
        factory_a = _retryable_failures(times=99999)

        def agent_b(inputs):
            return {"B": "ok"}

        def factory(stage):
            if stage == "A":
                return factory_a(stage)
            return agent_b

        config = ExecutorConfig(
            max_workers=2,
            agent_factory=factory,
            clock=clock,
            retry_policy=RetryPolicy(max_attempts=10, base_delay=0.0, max_delay=0.0),
            breaker_policy=CircuitBreakerPolicy(failure_threshold=2, cooldown_seconds=500.0),
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: executor.circuit_state("A") == CircuitState.OPEN)
        assert executor.circuit_state("B") == CircuitState.CLOSED
        assert scheduler.status("B").name == "COMPLETED"
        assert scheduler.status("A").name == "RETRYING"
        assert executor.active_worker_count() == 0

        executor.cancel_stage("A")
        runner.join(timeout=5.0)
        assert scheduler.status("A").name == "CANCELLED"
        assert executor.circuit_state("B") == CircuitState.CLOSED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
