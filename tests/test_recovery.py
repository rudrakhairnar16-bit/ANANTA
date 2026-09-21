import pytest

from pipeline.recovery import (
    CircuitBreaker,
    FailureClassifier,
    FailureType,
    RecoveryAction,
    RecoveryPlanner,
    RetryPolicy,
    StageRecoveryManager,
    execute_with_retry,
)


def test_failure_type_enum():
    assert FailureType.TRANSIENT == "transient"
    assert FailureType.PERMANENT == "permanent"
    assert FailureType.UNKNOWN == "unknown"


def test_recovery_action_enum():
    assert RecoveryAction.RETRY == "retry"
    assert RecoveryAction.SKIP == "skip"
    assert RecoveryAction.ROLLBACK == "rollback"
    assert RecoveryAction.MANUAL == "manual"
    assert RecoveryAction.ABORT == "abort"


def test_retry_policy_default():
    policy = RetryPolicy()
    assert policy.max_retries == 3
    assert policy.base_delay_seconds == 1.0
    assert policy.max_delay_seconds == 60.0
    assert policy.exponential_base == 2.0
    assert policy.jitter is True


def test_retry_policy_get_delay():
    policy = RetryPolicy(
        base_delay_seconds=1.0,
        exponential_base=2.0,
        max_delay_seconds=10.0,
        jitter=False,
    )
    assert policy.get_delay(0) == 1.0
    assert policy.get_delay(1) == 2.0
    assert policy.get_delay(2) == 4.0
    assert policy.get_delay(10) == 10.0


def test_circuit_breaker_creation():
    cb = CircuitBreaker(failure_threshold=3, success_threshold=2, timeout_seconds=60.0)
    assert cb.state.failures == 0
    assert cb.state.successes == 0
    assert cb.state.is_open is False


def test_circuit_breaker_record_success():
    cb = CircuitBreaker(failure_threshold=3, success_threshold=2)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_success()
    assert cb.state.is_open is False


def test_circuit_breaker_record_failure_opens():
    cb = CircuitBreaker(failure_threshold=2, success_threshold=2)
    cb.record_failure()
    assert cb.state.is_open is False
    cb.record_failure()
    assert cb.state.is_open is True


def test_circuit_breaker_can_execute():
    cb = CircuitBreaker(failure_threshold=1, timeout_seconds=0.01)
    cb.record_failure()
    assert cb.can_execute() is False

    import time
    time.sleep(0.02)
    assert cb.can_execute() is True


def test_failure_classifier_transient():
    assert FailureClassifier.classify("Connection timeout") == FailureType.TRANSIENT
    assert FailureClassifier.classify("Temporary unavailable") == FailureType.TRANSIENT
    assert FailureClassifier.classify("Rate limit exceeded") == FailureType.TRANSIENT
    assert FailureClassifier.classify("503 Service Unavailable") == FailureType.TRANSIENT


def test_failure_classifier_permanent():
    assert FailureClassifier.classify("Not found") == FailureType.PERMANENT
    assert FailureClassifier.classify("404 Not Found") == FailureType.PERMANENT
    assert FailureClassifier.classify("Invalid request") == FailureType.PERMANENT
    assert FailureClassifier.classify("401 Unauthorized") == FailureType.PERMANENT
    assert FailureClassifier.classify("403 Forbidden") == FailureType.PERMANENT


def test_failure_classifier_unknown():
    assert FailureClassifier.classify("Some random error") == FailureType.UNKNOWN


def test_recovery_planner_plan_transient_retry():
    planner = RecoveryPlanner()
    strategy = planner.plan_recovery("story", "Connection timeout", attempt=0)
    assert strategy.action == RecoveryAction.RETRY
    assert strategy.retry_policy is not None


def test_recovery_planner_plan_transient_max_retries_optional():
    planner = RecoveryPlanner()
    strategy = planner.plan_recovery("story", "Connection timeout", attempt=5, is_optional=True)
    assert strategy.action == RecoveryAction.SKIP


def test_recovery_planner_plan_transient_max_retries_required():
    planner = RecoveryPlanner()
    strategy = planner.plan_recovery("story", "Connection timeout", attempt=5, is_optional=False)
    assert strategy.action == RecoveryAction.MANUAL


def test_recovery_planner_plan_permanent_optional():
    planner = RecoveryPlanner()
    strategy = planner.plan_recovery("story", "Not found", attempt=0, is_optional=True)
    assert strategy.action == RecoveryAction.SKIP


def test_recovery_planner_plan_permanent_required():
    planner = RecoveryPlanner()
    strategy = planner.plan_recovery("story", "Not found", attempt=0, is_optional=False)
    assert strategy.action == RecoveryAction.ABORT


def test_execute_with_retry_success():
    result = execute_with_retry(lambda: "success", RetryPolicy(max_retries=3))
    assert result == "success"


def test_execute_with_retry_fails_then_succeeds():
    attempts = [0]
    def func():
        attempts[0] += 1
        if attempts[0] < 2:
            raise ValueError("Temporary error")
        return "success"

    result = execute_with_retry(
        func,
        RetryPolicy(max_retries=3, base_delay_seconds=0.01, jitter=False),
    )
    assert result == "success"
    assert attempts[0] == 2


def test_execute_with_retry_all_fail():
    with pytest.raises(ValueError):
        execute_with_retry(
            lambda: (_ for _ in ()).throw(ValueError("Permanent")),
            RetryPolicy(max_retries=2, base_delay_seconds=0.01, jitter=False),
        )


def test_stage_recovery_manager():
    manager = StageRecoveryManager()
    assert manager.get_attempt("story") == 0
    manager.increment_attempt("story")
    assert manager.get_attempt("story") == 1
    manager.reset_attempt("story")
    assert manager.get_attempt("story") == 0


def test_stage_recovery_manager_execute_success():
    manager = StageRecoveryManager()
    success, result, error = manager.execute_stage("story", lambda: "success", is_optional=False)
    assert success is True
    assert result == "success"
    assert error is None


def test_stage_recovery_manager_execute_retry_then_success():
    manager = StageRecoveryManager()
    attempts = [0]

    def func():
        attempts[0] += 1
        if attempts[0] < 2:
            raise ValueError("Connection timeout")
        return "success"

    success, result, error = manager.execute_stage("story", func, is_optional=False)
    assert success is True
    assert result == "success"
    assert error is None


def test_stage_recovery_manager_execute_permanent_fail_optional():
    manager = StageRecoveryManager()
    success, result, error = manager.execute_stage(
        "story",
        lambda: (_ for _ in ()).throw(ValueError("Not found")),
        is_optional=True,
    )
    assert success is False
    assert "Skipped" in error


def test_stage_recovery_manager_execute_permanent_fail_required():
    manager = StageRecoveryManager()
    success, result, error = manager.execute_stage(
        "story",
        lambda: (_ for _ in ()).throw(ValueError("Not found")),
        is_optional=False,
    )
    assert success is False
    assert "Aborted" in error
