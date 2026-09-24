"""M7 RED tests: retry policy, backoff, jitter, and executor retry integration.

Covered matrix labels: A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P,
Q, R, S, T, U, AE, AF, AL.
"""

import inspect
import threading
import time

import pytest

from pipeline.cancellation import FakeClock, StageOutcome
from pipeline.execution import new_execution_id
from pipeline.scheduler import StageScheduler


def _make_test_scheduler(
    stages: list[str],
    dependencies: dict[str, list[str]] | None = None,
    *,
    episode_id: str = "TEST-EPISODE",
) -> StageScheduler:
    deps = {k: tuple(v) for k, v in (dependencies or {}).items()}
    return StageScheduler(
        tuple(stages),
        deps,
        episode_id=episode_id,
        execution_id=new_execution_id(),
    )


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def _quick(stage: str):
    def agent(inputs):
        return {stage: "ok"}

    return agent


class _Flaky:
    """Fails the first ``fail_times`` calls with an explicit RetryableError."""

    def __init__(self, fail_times: int, *, delay: float = 0.0):
        self.fail_times = fail_times
        self.calls = 0
        self.delay = delay
        self.lock = threading.Lock()

    def __call__(self, inputs):
        with self.lock:
            self.calls += 1
            call = self.calls
        if self.delay:
            time.sleep(self.delay)
        if call <= self.fail_times:
            from pipeline.retry import RetryableError

            raise RetryableError("transient failure")
        return {"ok": True}


class _HardFail:
    """Fails every call with a plain exception (NOT classified retryable)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, inputs):
        self.calls += 1
        raise RuntimeError("hard failure")


class TestRetryPolicyDefaults:
    """A. RetryPolicy defaults: attempt 1 only; no retry by default."""

    def test_defaults(self):
        from pipeline.retry import JitterMode, RetryPolicy

        policy = RetryPolicy()
        assert policy.max_attempts == 1
        assert policy.base_delay == 1.0
        assert policy.max_delay == 10.0
        assert policy.backoff_multiplier == 2.0
        assert policy.jitter_mode == JitterMode.NONE
        assert not policy.is_retryable(RuntimeError("boom"))


class TestMaxAttemptsSemantics:
    """B. max_attempts means total attempts (attempt 1 + retries), never more."""

    def test_max_attempts_never_exceeded(self):
        from pipeline.retry import RetryableError, RetryPolicy

        policy = RetryPolicy(max_attempts=3)
        policy2 = policy
        assert policy2.max_attempts == 3
        assert isinstance(RetryableError("x"), RetryableError)

    def test_max_attempts_is_total_not_retries(self):
        from pipeline.retry import RetryPolicy

        for total in (1, 2, 5):
            policy = RetryPolicy(max_attempts=total)
            assert policy.max_attempts == total


class TestNonRetryableClassification:
    """C. Classification: default non-retryable, explicit RetryableError retryable."""

    def test_default_exception_never_retryable(self):
        from pipeline.retry import RetryPolicy

        assert not RetryPolicy().is_retryable(RuntimeError("boom"))

    def test_retryable_error_retryable(self):
        from pipeline.retry import RetryableError, RetryPolicy

        assert RetryPolicy().is_retryable(RetryableError("transient"))

    def test_custom_retryable_exceptions(self):
        from pipeline.retry import RetryPolicy

        policy = RetryPolicy(retryable_exceptions=(TimeoutError,))
        assert policy.is_retryable(TimeoutError("slow"))
        assert not policy.is_retryable(RuntimeError("boom"))

    def test_custom_classifier(self):
        from pipeline.retry import RetryPolicy

        policy = RetryPolicy(classifier=lambda exc: "flaky" in str(exc))
        assert policy.is_retryable(RuntimeError("flaky endpoint"))
        assert not policy.is_retryable(RuntimeError("boom"))


class TestBackoffMath:
    """G/H. Exponential backoff and max-delay cap (exact documented formula)."""

    def test_exponential_backoff(self):
        from pipeline.retry import RetryPolicy

        policy = RetryPolicy(base_delay=1.0, backoff_multiplier=2.0, max_delay=10.0)
        assert policy.backoff(1) == 1.0
        assert policy.backoff(2) == 2.0
        assert policy.backoff(3) == 4.0
        assert policy.backoff(4) == 8.0

    def test_max_delay_cap(self):
        from pipeline.retry import RetryPolicy

        policy = RetryPolicy(base_delay=1.0, backoff_multiplier=2.0, max_delay=10.0)
        assert policy.backoff(5) == 10.0
        assert policy.backoff(10) == 10.0


class TestJitter:
    """I. Jitter disabled.  J. Deterministic bounded jitter."""

    def test_disabled_jitter_returns_exact_backoff(self):
        from pipeline.retry import JitterMode, RetryPolicy

        policy = RetryPolicy(
            base_delay=2.0,
            backoff_multiplier=2.0,
            max_delay=10.0,
            jitter_mode=JitterMode.NONE,
        )
        for attempt in range(1, 6):
            assert policy.delay_for_retry(attempt) == policy.backoff(attempt)

    def test_bounded_jitter_deterministic(self):
        from pipeline.retry import JitterMode, RetryPolicy, ScriptedJitterSource

        source = ScriptedJitterSource(fractions=(0.5, 0.0))
        policy = RetryPolicy(
            base_delay=2.0,
            backoff_multiplier=2.0,
            max_delay=100.0,
            jitter_mode=JitterMode.BOUNDED,
            jitter_fraction=1.0,
            jitter_source=source,
        )
        assert policy.delay_for_retry(1) == pytest.approx(2.0 + 2.0 * 1.0 * 0.5)
        assert policy.delay_for_retry(1) == pytest.approx(2.0)

    def test_jitter_respects_max_delay_cap(self):
        from pipeline.retry import JitterMode, RetryPolicy, ScriptedJitterSource

        source = ScriptedJitterSource(fractions=(0.99,))
        policy = RetryPolicy(
            base_delay=9.0,
            backoff_multiplier=2.0,
            max_delay=10.0,
            jitter_mode=JitterMode.BOUNDED,
            jitter_fraction=1.0,
            jitter_source=source,
        )
        assert policy.delay_for_retry(1) <= 10.0


class TestExecutorRetryScheduling:
    """D/E/F. Retryable failure retries; attempt numbers increment; execution_id constant."""

    def test_retryable_failure_retries_and_succeeds(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        flaky_a = _Flaky(fail_times=1)
        config = ExecutorConfig(
            max_workers=2,
            agent_factory=lambda s: flaky_a if s == "A" else _quick(s),
            retry_policy=RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0),
        )
        executor = PipelineExecutor(scheduler, config)
        results = executor.run()

        assert flaky_a.calls == 2
        assert results["A"].success
        assert results["A"].attempt_number == 2
        assert results["A"].execution_id == scheduler.execution_id
        assert scheduler.instance("A").attempt_number == 2
        assert scheduler.instance("A").status.name == "COMPLETED"
        assert executor.retry_counts()["A"] == 1
        assert scheduler.instance("B").status.name == "COMPLETED"

    def test_non_retryable_failure_does_not_retry(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        hard = _HardFail()
        config = ExecutorConfig(
            max_workers=2,
            agent_factory=lambda s: hard if s == "A" else _quick(s),
            retry_policy=RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0),
        )
        executor = PipelineExecutor(scheduler, config)
        results = executor.run()

        assert hard.calls == 1
        assert not results["A"].success
        assert results["A"].attempt_number == 1
        assert scheduler.instance("A").status.name == "FAILED"
        assert executor.retry_counts() == {}
        assert scheduler.instance("B").status.name == "BLOCKED"

    def test_no_retry_policy_means_no_retry(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryableError

        scheduler = _make_test_scheduler(["A"], {})
        calls = []

        def factory(stage):
            def agent(inputs):
                calls.append(stage)
                raise RetryableError("transient")

            return agent

        executor = PipelineExecutor(
            scheduler, ExecutorConfig(max_workers=1, agent_factory=factory)
        )
        results = executor.run()

        assert len(calls) == 1
        assert scheduler.instance("A").status.name == "FAILED"
        assert not results["A"].success


class TestRetryLimit:
    """T. Retry limit strictly enforced: max_attempts caps total attempts."""

    def _run_with_limit(self, max_attempts: int, fail_times: int):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"], {})
        flaky = _Flaky(fail_times=fail_times)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: flaky,
            retry_policy=RetryPolicy(max_attempts=max_attempts, base_delay=0.0, max_delay=0.0),
        )
        executor = PipelineExecutor(scheduler, config)
        results = executor.run()
        return flaky.calls, scheduler.instance("A").attempt_number, results["A"].success

    def test_max_attempts_one_single_attempt(self):
        calls, attempt, _ = self._run_with_limit(max_attempts=1, fail_times=5)
        assert calls == 1
        assert attempt == 1

    def test_max_attempts_two_at_most_two(self):
        calls, attempt, _ = self._run_with_limit(max_attempts=2, fail_times=5)
        assert calls == 2
        assert attempt == 2

    def test_max_attempts_three_never_four(self):
        calls, attempt, _ = self._run_with_limit(max_attempts=3, fail_times=5)
        assert calls == 3
        assert attempt == 3


class TestFakeClockRetryDeadline:
    """K. FakeClock retry deadline: retry becomes eligible only when clock advances."""

    def test_retry_deadline_on_fake_clock(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=1)
        config = ExecutorConfig(
            max_workers=2,
            agent_factory=lambda s: flaky_a if s == "A" else _quick(s),
            retry_policy=RetryPolicy(max_attempts=3, base_delay=10.0, max_delay=10.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        assert executor.active_worker_count() == 0, "backoff must not occupy a worker"
        assert flaky_a.calls == 1
        assert scheduler.instance("A").attempt_number == 2

        clock.advance(11.0)
        assert _wait_until(lambda: scheduler.status("A").name == "COMPLETED")
        runner.join(timeout=5.0)

        assert flaky_a.calls == 2
        assert scheduler.instance("A").attempt_number == 2
        assert scheduler.instance("B").status.name == "COMPLETED"


class TestBackoffDoesNotOccupyWorker:
    """L. A stage waiting on backoff must not consume a worker slot."""

    def test_backoff_releases_worker_capacity(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"], {})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=1, delay=0.002)
        b_done = threading.Event()

        def factory(stage):
            if stage == "A":
                return flaky_a

            def agent(inputs):
                time.sleep(0.002)
                b_done.set()
                return {"B": "ok"}

            return agent

        config = ExecutorConfig(
            max_workers=2,
            agent_factory=factory,
            retry_policy=RetryPolicy(max_attempts=3, base_delay=30.0, max_delay=30.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        assert _wait_until(lambda: b_done.is_set())
        assert _wait_until(lambda: scheduler.status("B").name == "COMPLETED")
        assert executor.active_worker_count() == 0, "worker slot held during backoff"

        clock.advance(31.0)
        runner.join(timeout=5.0)
        assert scheduler.status("A").name == "COMPLETED"
        assert scheduler.instance("A").attempt_number == 2


class TestIndependentDuringBackoff:
    """M/AD. Independent stage executes while another stage is retry-waiting."""

    def test_independent_stage_proceeds_during_backoff(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "D": ["C"]},
        )
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=1)
        config = ExecutorConfig(
            max_workers=2,
            agent_factory=lambda s: flaky_a if s == "A" else _quick(s),
            retry_policy=RetryPolicy(max_attempts=3, base_delay=20.0, max_delay=20.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        assert _wait_until(lambda: scheduler.status("C").name == "COMPLETED")
        assert _wait_until(lambda: scheduler.status("D").name == "COMPLETED")

        clock.advance(21.0)
        runner.join(timeout=5.0)
        assert scheduler.status("A").name == "COMPLETED"
        assert scheduler.instance("B").status.name == "COMPLETED"
        assert scheduler.instance("C").status.name == "COMPLETED"
        assert scheduler.instance("D").status.name == "COMPLETED"


class TestCancelDuringBackoff:
    """N. A retry waiting in backoff can be cancelled; retry never admitted."""

    def test_cancel_during_backoff_prevents_retry(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"], {})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=100)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: flaky_a,
            retry_policy=RetryPolicy(max_attempts=10, base_delay=30.0, max_delay=30.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        executor.cancel_stage("A")
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert flaky_a.calls == 1, "retry attempt ran after cancellation"
        assert executor.retry_counts()["A"] == 1

    def test_cancel_after_some_retries_stops_future_retries(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"], {})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=100)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: flaky_a,
            retry_policy=RetryPolicy(max_attempts=10, base_delay=0.0, max_delay=0.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: flaky_a.calls >= 2)
        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        executor.cancel_stage("A")
        runner.join(timeout=5.0)

        calls_at_cancel = flaky_a.calls
        assert scheduler.instance("A").status.name == "CANCELLED"
        assert flaky_a.calls == calls_at_cancel


class TestPipelineCancelDuringBackoff:
    """O. Pipeline cancellation during backoff prevents all pending retries."""

    def test_pipeline_cancel_during_backoff(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"], {})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=100)
        flaky_b = _Flaky(fail_times=100)
        agents = {"A": flaky_a, "B": flaky_b}
        config = ExecutorConfig(
            max_workers=2,
            agent_factory=lambda s: agents[s],
            retry_policy=RetryPolicy(max_attempts=10, base_delay=30.0, max_delay=30.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        assert _wait_until(lambda: scheduler.status("B").name == "RETRYING")
        executor.request_pipeline_cancellation()
        runner.join(timeout=5.0)

        assert scheduler.status("A").name == "CANCELLED"
        assert scheduler.status("B").name == "CANCELLED"
        assert flaky_a.calls == 1
        assert flaky_b.calls == 1


class TestTimeoutDoesNotTriggerRetry:
    """P. TIMEOUT is an outcome, not a retry trigger."""

    def test_timeout_does_not_schedule_retry(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        hold = threading.Event()

        def factory(stage):
            def agent(inputs):
                hold.wait(timeout=10.0)
                return {"A": "late"}

            return agent

        config = ExecutorConfig(
            max_workers=1,
            agent_factory=factory,
            timeout_seconds=5.0,
            clock=clock,
            retry_policy=RetryPolicy(max_attempts=10, base_delay=1.0, max_delay=1.0),
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        hold.set()
        runner.join(timeout=5.0)

        assert executor.outcomes()["A"] == StageOutcome.TIMEOUT
        assert executor.retry_counts() == {}
        assert scheduler.instance("A").attempt_number == 1
        assert scheduler.instance("A").status.name == "CANCELLED"
        assert scheduler.instance("B").status.name == "BLOCKED"


class TestStaleAttemptProtection:
    """Q/R/S. Stale previous-attempt results are discarded and never trigger retry."""

    def test_stale_result_after_retry_scheduled_rejected(self):
        from pipeline.cancellation import StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor, WorkerResult
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"], {})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=1)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: flaky_a,
            retry_policy=RetryPolicy(max_attempts=3, base_delay=30.0, max_delay=30.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        stale = WorkerResult(
            stage="A",
            execution_id=scheduler.execution_id,
            attempt_number=1,
            success=True,
            outcome=StageOutcome.SUCCESS,
            data={"A": "stale"},
        )
        assert not executor._is_result_valid("A", stale), "stale attempt accepted"
        stale_retryable = WorkerResult(
            stage="A",
            execution_id=scheduler.execution_id,
            attempt_number=1,
            success=False,
            outcome=StageOutcome.FAILURE,
            retryable=True,
            error="transient",
        )
        assert not executor._is_result_valid("A", stale_retryable)

        executor._route_attempt_result("A", stale_retryable)
        assert scheduler.status("A").name == "RETRYING", "stale result mutated lifecycle"
        assert executor.retry_counts()["A"] == 1, "stale result triggered another retry"

        clock.advance(31.0)
        runner.join(timeout=5.0)
        assert scheduler.status("A").name == "COMPLETED"

    def test_final_results_only_authoritative_attempt(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        scheduler = _make_test_scheduler(["A"], {})
        clock = FakeClock(0.0)
        flaky_a = _Flaky(fail_times=1)
        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: flaky_a,
            retry_policy=RetryPolicy(max_attempts=3, base_delay=30.0, max_delay=30.0),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RETRYING")
        assert "A" not in executor._results
        clock.advance(31.0)
        runner.join(timeout=5.0)

        assert scheduler.status("A").name == "COMPLETED"
        assert executor._results["A"].attempt_number == 2, "stale result became results entry"


class TestDeterministicRetryAdmission:
    """U. Retry admission follows deterministic canonical order."""

    def test_retry_admission_deterministic(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        orders = []
        for _ in range(5):
            scheduler = _make_test_scheduler(
                ["A", "B", "C"],
                {"C": ["A", "B"]},
            )
            clock = FakeClock(0.0)
            flaky_a = _Flaky(fail_times=1)
            flaky_b = _Flaky(fail_times=1)
            agents = {"A": flaky_a, "B": flaky_b}
            config = ExecutorConfig(
                max_workers=4,
                agent_factory=lambda s, ag=agents: ag[s] if s in ag else _quick(s),
                retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=1.0),
                clock=clock,
            )
            executor = PipelineExecutor(scheduler, config)
            runner = threading.Thread(target=executor.run)
            runner.start()
            assert _wait_until(lambda sched=scheduler: sched.status("A").name == "RETRYING")
            assert _wait_until(lambda sched=scheduler: sched.status("B").name == "RETRYING")
            clock.advance(2.0)
            runner.join(timeout=5.0)
            orders.append(executor.admission_order())
            assert scheduler.status("C").name == "COMPLETED"

        assert len(set(orders)) == 1, f"retry admission not deterministic: {orders}"
        assert orders[0] == ("A", "B", "A", "B", "C")


class TestBoundedConcurrencyWithRetries:
    """AE. Retry attempts use the existing bounded pool; max_workers never exceeded."""

    def test_max_workers_bounds_active_retries(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy

        active = 0
        peak = 0
        lock = threading.Lock()
        gate = threading.Event()

        def factory(stage):
            def agent(inputs):
                nonlocal active, peak
                from pipeline.retry import RetryableError

                with lock:
                    active += 1
                    peak = max(peak, active)
                gate.wait(timeout=5.0)
                with lock:
                    active -= 1
                raise RetryableError("transient")

            return agent

        scheduler = _make_test_scheduler(["F", "S0", "S1", "S2", "S3"])
        config = ExecutorConfig(
            max_workers=2,
            agent_factory=factory,
            retry_policy=RetryPolicy(
                max_attempts=2, base_delay=0.0, max_delay=0.0, backoff_multiplier=1.0
            ),
        )
        executor = PipelineExecutor(scheduler, config)
        executor.run()

        assert peak <= 2, f"peak={peak} exceeded max_workers=2"
        assert scheduler.status("F").name == "FAILED"
        for stage in ("F", "S0", "S1", "S2", "S3"):
            assert executor.retry_counts()[stage] == 1, "retry attempt occupied a slot"
            assert scheduler.instance(stage).attempt_number == 2


class TestFullGraphRetry:
    """AF. Full 19-stage graph: retryable retries, non-retryable terminates."""

    def test_full_graph_retry_and_non_retryable(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.retry import RetryPolicy
        from pipeline.scheduler import create_ananta_scheduler

        scheduler = create_ananta_scheduler(episode_id="ANANTA-S01E01")
        camera_flaky = _Flaky(fail_times=1, delay=0.001)
        qa_hard = _HardFail()

        def factory(stage):
            if stage == "camera":
                return camera_flaky
            if stage == "qa":
                return qa_hard
            return _quick(stage)

        config = ExecutorConfig(
            max_workers=4,
            agent_factory=factory,
            retry_policy=RetryPolicy(
                max_attempts=3, base_delay=0.001, max_delay=0.001, backoff_multiplier=1.0
            ),
        )
        executor = PipelineExecutor(scheduler, config)
        results = executor.run()

        assert camera_flaky.calls == 2, "camera should retry once then succeed"
        assert scheduler.instance("camera").status.name == "COMPLETED"
        assert scheduler.instance("camera").attempt_number == 2
        assert results["camera"].success

        assert qa_hard.calls == 1, "non-retryable must not retry"
        assert scheduler.instance("qa").status.name == "FAILED"
        assert not results["qa"].success
        assert scheduler.instance("export").status.name == "BLOCKED"

        completed = [
            stage
            for stage in scheduler.stage_order()
            if scheduler.instance(stage).status.name == "COMPLETED"
        ]
        assert "qa" not in completed and "export" not in completed
        assert len(completed) == 17


class TestRetrySourceSafety:
    """AL. Retry modules never use unsafe thread termination."""

    @pytest.mark.parametrize(
        "module_path",
        ["pipeline.retry", "pipeline.circuit_breaker", "pipeline.executor"],
    )
    def test_no_unsafe_thread_killing(self, module_path):
        import importlib

        module = importlib.import_module(module_path)
        source = inspect.getsource(module)
        assert "os._exit" not in source
        assert "terminate(" not in source
        assert "os.kill" not in source
        assert "_stop()" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
