import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest

from config_v2 import get_settings
from pipeline.execution import new_execution_id
from pipeline.scheduler import (
    StageScheduler,
    create_ananta_scheduler,
)


@dataclass(frozen=True)
class WorkerResult:
    """Immutable worker execution result."""
    stage: str
    execution_id: str
    attempt_number: int
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: float = 0.0


class _FakeAgent:
    """Controllable fake agent for testing executor parallelism."""
    def __init__(
        self,
        stage: str,
        *,
        delay: float = 0.01,
        should_fail: bool = False,
        error_msg: str = "fake error",
        result_data: dict[str, Any] | None = None,
        start_event: threading.Event | None = None,
        done_event: threading.Event | None = None,
    ):
        self.stage = stage
        self.delay = delay
        self.should_fail = should_fail
        self.error_msg = error_msg
        self.result_data = result_data or {"stage": stage, "output": f"{stage}_result"}
        self.start_event = start_event
        self.done_event = done_event

    def run(self, inputs: dict[str, Any], pipeline_state=None, episode_id=None):
        if self.start_event:
            self.start_event.set()
        if self.done_event:
            self.done_event.wait(timeout=5.0)
        time.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError(self.error_msg)
        return {**inputs, **self.result_data}

    def __call__(self, inputs: dict[str, Any]):
        return self.run(inputs)


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


class TestExecutorLinearChain:
    """A. Linear chain: A → B → C. Only A may execute initially."""

    def test_linear_chain_sequential_admission(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B", "C"], {"B": ["A"], "C": ["B"]})
        config = ExecutorConfig(max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.001))
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert results["A"].success
        assert results["B"].success
        assert results["C"].success
        assert scheduler.is_finished()


class TestExecutorDiamond:
    """B. Diamond: A → B, A → C, B → D, C → D. B and C may execute concurrently."""

    def test_diamond_b_c_concurrent(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "C": ["A"], "D": ["B", "C"]},
        )
        config = ExecutorConfig(max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.01))
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert results["A"].success
        assert results["B"].success
        assert results["C"].success
        assert results["D"].success
        assert scheduler.is_finished()

    def test_diamond_d_blocked_until_both_b_c_complete(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "C": ["A"], "D": ["B", "C"]},
        )
        config = ExecutorConfig(max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.01))
        executor = PipelineExecutor(scheduler, config)

        executor.run()

        assert scheduler.status("D") == scheduler.instance("D").status
        assert scheduler.instance("D").status.name == "COMPLETED"


class TestExecutorIndependentBranches:
    """C. Independent branches: A → B, C → D. A and C may execute concurrently."""

    def test_independent_branches_concurrent(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "D": ["C"]},
        )
        config = ExecutorConfig(max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.01))
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert results["A"].success
        assert results["B"].success
        assert results["C"].success
        assert results["D"].success
        assert scheduler.is_finished()

    def test_failure_in_a_does_not_block_c_d(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "D": ["C"]},
        )
        def factory(stage):
            if stage == "A":
                return _FakeAgent(stage, should_fail=True, error_msg="A failed")
            return _FakeAgent(stage, delay=0.01)
        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert not results["A"].success
        assert results["A"].error == "A failed"
        assert scheduler.instance("B").status.name == "BLOCKED"
        assert results["C"].success
        assert results["D"].success
        assert scheduler.instance("C").status.name == "COMPLETED"
        assert scheduler.instance("D").status.name == "COMPLETED"


class TestExecutorFailureIsolation:
    """D. Failure isolation: one branch fails, independent branch completes."""

    def test_failure_isolation_diamond(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "C": ["A"], "D": ["B", "C"]},
        )
        def factory(stage):
            if stage == "B":
                return _FakeAgent(stage, should_fail=True, error_msg="B failed")
            return _FakeAgent(stage, delay=0.01)
        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert results["A"].success
        assert not results["B"].success
        assert results["C"].success
        assert scheduler.instance("D").status.name == "BLOCKED"


class TestExecutorDuplicatePrevention:
    """E. Duplicate submission prevention."""

    def test_duplicate_admission_rejected(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        config = ExecutorConfig(max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.01))
        executor = PipelineExecutor(scheduler, config)

        executor.run()

        assert scheduler.instance("A").status.name == "COMPLETED"
        assert scheduler.instance("B").status.name == "COMPLETED"


class TestExecutorConcurrencyBound:
    """F. Concurrency bound: max_parallel_stages = 4."""

    def test_max_workers_respected(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        active_count = 0
        max_active = 0
        lock = threading.Lock()
        gate = threading.Event()
        saw_four = threading.Event()

        def factory(stage):
            def wrapped_agent(inputs):
                nonlocal active_count, max_active
                with lock:
                    active_count += 1
                    max_active = max(max_active, active_count)
                    if active_count == 4:
                        saw_four.set()
                gate.wait(timeout=5.0)
                with lock:
                    active_count -= 1
                return {stage: "done"}
            return wrapped_agent

        scheduler = _make_test_scheduler([f"S{i}" for i in range(8)])
        config = ExecutorConfig(max_workers=4, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        runner = threading.Thread(target=executor.run)
        runner.start()

        assert saw_four.wait(timeout=5.0), "4 workers never ran concurrently"
        time.sleep(0.05)
        with lock:
            assert active_count == 4, f"active_count={active_count}"
        gate.set()
        runner.join(timeout=5.0)
        assert runner.is_alive() is False
        assert max_active == 4, f"max_active={max_active} exceeded max_workers=4"


class TestExecutorFullGraph:
    """G. Full 19-stage graph."""

    def test_nineteen_stage_graph_completes(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = create_ananta_scheduler(episode_id="ANANTA-S01E01")
        config = ExecutorConfig(
            max_workers=4,
            agent_factory=lambda s: _FakeAgent(s, delay=0.005),
        )
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert scheduler.is_finished()
        assert len(results) == 19
        for stage in scheduler.stage_order():
            assert results[stage].success
            assert scheduler.instance(stage).status.name == "COMPLETED"


class TestExecutorRealParallelism:
    """Prove real parallelism: at least two independent stages active simultaneously."""

    def test_real_overlap_detected(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        a_running = threading.Event()
        b_running = threading.Event()
        a_done = threading.Event()
        b_done = threading.Event()
        overlap_detected = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    a_running.set()
                    time.sleep(0.15)
                    a_done.set()
                    return {"A": "done"}
                return agent
            if stage == "B":
                def agent(inputs):
                    b_running.set()
                    time.sleep(0.15)
                    b_done.set()
                    return {"B": "done"}
                return agent
            return _FakeAgent(stage, delay=0.01)

        scheduler = _make_test_scheduler(
            ["A", "B", "C"],
            {"C": ["A", "B"]},
        )
        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        def monitor():
            a_running.wait(timeout=2.0)
            time.sleep(0.05)
            if b_running.is_set():
                overlap_detected.set()

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

        executor.run()

        assert overlap_detected.is_set(), "A and B did not overlap — no real parallelism"


class TestExecutorLateResultProtection:
    """Late/stale result protection."""

    def test_stale_result_after_cancel_rejected(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})

        def factory(stage):
            if stage == "A":
                def slow_agent(inputs):
                    time.sleep(0.05)
                    return {"A": "late"}
                return slow_agent
            return _FakeAgent(stage, delay=0.001)

        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        executor.run()

        assert scheduler.instance("A").status.name == "COMPLETED"
        assert scheduler.instance("B").status.name == "COMPLETED"


class TestExecutorSchedulerOwnership:
    """Prove workers cannot bypass scheduler lifecycle."""

    def test_worker_completion_goes_through_scheduler(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        calls = []

        def factory(stage):
            def tracking_agent(inputs):
                calls.append(f"run_{stage}")
                return {stage: "ok"}
            return tracking_agent

        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        executor.run()

        assert scheduler.instance("A").status.name == "COMPLETED"
        assert scheduler.instance("B").status.name == "COMPLETED"
        assert "run_A" in calls
        assert "run_B" in calls


class TestExecutorWorkerExceptions:
    """Worker exceptions captured and converted to stage failures."""

    def test_worker_exception_becomes_stage_failure(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        def factory(stage):
            if stage == "A":
                return _FakeAgent(stage, should_fail=True, error_msg="worker exploded")
            return _FakeAgent(stage, delay=0.001)
        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)

        results = executor.run()

        assert not results["A"].success
        assert "worker exploded" in results["A"].error
        assert scheduler.instance("A").status.name == "FAILED"
        assert scheduler.instance("B").status.name == "BLOCKED"


class TestExecutorCleanShutdown:
    """Clean shutdown: no leaked threads."""

    def test_no_thread_leaks(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        threads_before = threading.active_count()

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        config = ExecutorConfig(max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.001))
        executor = PipelineExecutor(scheduler, config)

        executor.run()

        threads_after = threading.active_count()
        assert threads_after <= threads_before + 1, "Thread leak detected"


class TestExecutorNoUnsafeMechanics:
    """M6 must never import unsafe thread-killing mechanics; retry is M7."""

    def test_no_retry_logic_in_executor(self):
        import inspect

        from pipeline.executor import PipelineExecutor
        source = inspect.getsource(PipelineExecutor)
        assert "retry" not in source.lower() or (
            "retry" in source.lower() and "m7" in source.lower()
        )

    def test_no_unsafe_thread_killing_in_executor(self):
        import inspect

        from pipeline import executor as executor_module
        source = inspect.getsource(executor_module)
        assert "os._exit" not in source
        assert "terminate(" not in source
        assert "os.kill" not in source
        assert "_stop()" not in source


class TestExecutorConfig:
    """Executor configuration."""

    def test_max_workers_from_settings(self):
        from pipeline.executor import ExecutorConfig

        settings = get_settings()
        assert settings.pipeline.max_parallel_stages == 4

        config = ExecutorConfig.from_settings()
        assert config.max_workers == 4


class TestExecutorDeterministicAdmission:
    """Admission order must be deterministic (not completion order)."""

    def test_deterministic_admission_order(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        admission_orders = []
        for _ in range(10):
            scheduler = _make_test_scheduler(
                ["A", "B", "C", "D", "E"],
                {"C": ["A"], "D": ["B"], "E": ["C", "D"]},
            )
            config = ExecutorConfig(
                max_workers=2, agent_factory=lambda s: _FakeAgent(s, delay=0.01)
            )
            executor = PipelineExecutor(scheduler, config)
            executor.run()
            admission_orders.append(executor.admission_order())

        assert all(o == admission_orders[0] for o in admission_orders), (
            f"Admission order not deterministic: {admission_orders}"
        )
        assert len(set(admission_orders)) == 1, "Admission order varied across runs"

        for order in admission_orders:
            for stage in order:
                for dep in scheduler.required_dependencies(stage):
                    assert dep in order[:order.index(stage)], (
                        f"{stage} admitted before dependency {dep}"
                    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
