import threading
import time

import pytest

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


def _quick_agent(stage: str):
    def agent(inputs):
        return {stage: "ok"}
    return agent


def _cooperative_agent(stage: str, observed: threading.Event):
    def agent(inputs):
        token = inputs["cancellation_token"]
        while not token.is_cancelled():
            time.sleep(0.001)
        observed.set()
        return {stage: "ok"}
    return agent


def _noncooperative_agent(stage: str, delay: float = 0.05):
    def agent(inputs):
        time.sleep(delay)
        return {stage: "ok"}
    return agent


class TestStageTimeout:
    """A. Stage timeout: exceeds deadline; attempt invalidated; no completion."""

    def test_stage_timeout_detected(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        release = threading.Event()

        def factory(stage):
            def agent(inputs):
                release.wait(timeout=10.0)
                return {"A": "ok"}
            return agent

        config = ExecutorConfig(
            max_workers=1, agent_factory=factory, timeout_seconds=10.0, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(11.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        release.set()
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert executor.outcomes()["A"] == StageOutcome.TIMEOUT
        assert executor.outcomes()["A"] != StageOutcome.SUCCESS
        assert scheduler.instance("B").status.name == "BLOCKED"
        assert "B" not in executor.outcomes()


class TestTimeoutIndependentBranch:
    """B. Timeout with independent branch: A times out; C/D continue."""

    def test_timeout_isolates_branch(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "D": ["C"]},
        )
        clock = FakeClock(0.0)
        release_a = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    release_a.wait(timeout=10.0)
                    return {"A": "late"}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(
            max_workers=2, agent_factory=factory, timeout_seconds=5.0, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        release_a.set()
        runner.join(timeout=10.0)

        assert executor.outcomes()["A"] == StageOutcome.TIMEOUT
        assert scheduler.instance("B").status.name == "BLOCKED"
        assert scheduler.instance("C").status.name == "COMPLETED"
        assert scheduler.instance("D").status.name == "COMPLETED"


class TestCooperativeCancellation:
    """C. Cooperative cancellation: worker observes token and exits cleanly."""

    def test_cooperative_worker_observes_cancel(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        observed = threading.Event()

        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: _cooperative_agent("A", observed),
            timeout_seconds=5.0,
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: observed.is_set())
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert executor.outcomes()["A"] == StageOutcome.TIMEOUT


class TestNonCooperativeCancellation:
    """D. Non-cooperative: worker ignores token; state authoritative; late result discarded."""

    def test_noncooperative_worker_late_result_discarded(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)

        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: _noncooperative_agent("A", delay=0.08),
            timeout_seconds=5.0,
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert executor.outcomes()["A"] == StageOutcome.TIMEOUT
        assert scheduler.instance("B").status.name == "BLOCKED"
        assert "A" not in executor.outcomes() or executor.outcomes()["A"] == StageOutcome.TIMEOUT


class TestQueuedCancellation:
    """E. Queued cancellation: stage admitted to the pool but worker not started."""

    def test_queued_stage_cancelled_before_start(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "H", "B", "C"],
            {"C": ["B"]},
        )
        hold_a = threading.Event()
        hold_h = threading.Event()
        executed = []

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    hold_a.wait(timeout=10.0)
                    executed.append("A")
                    return {"A": "ok"}
                return agent
            if stage == "H":
                def agent(inputs):
                    hold_h.wait(timeout=10.0)
                    executed.append("H")
                    return {"H": "ok"}
                return agent
            def agent(inputs):
                executed.append(stage)
                return {stage: "ok"}
            return agent

        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        assert _wait_until(lambda: scheduler.status("H").name == "RUNNING")
        assert _wait_until(lambda: scheduler.status("B").name == "QUEUED")
        executor.cancel_stage("B")
        hold_a.set()
        hold_h.set()
        runner.join(timeout=5.0)

        assert scheduler.instance("B").status.name == "CANCELLED"
        assert "B" not in executed
        assert scheduler.instance("C").status.name == "BLOCKED"


class TestRunningCancellation:
    """F. Running stage cancellation: request cooperative cancellation; no unsafe kill."""

    def test_running_stage_cooperative_cancel(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        observed = threading.Event()

        config = ExecutorConfig(
            max_workers=1,
            agent_factory=lambda s: _cooperative_agent("A", observed),
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        executor.cancel_stage("A")
        assert _wait_until(lambda: observed.is_set())
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert executor.outcomes()["A"] == StageOutcome.CANCELLED


class TestPipelineCancellation:
    """G. Pipeline cancellation: no new admissions; running workers cancelled; clean shutdown."""

    def test_pipeline_cancel_stops_admission(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D", "E"],
            {"D": ["C"], "E": ["D"]},
        )
        clock = FakeClock(0.0)
        hold = threading.Event()
        admitted_before_cancel = []

        def factory(stage):
            def agent(inputs):
                hold.wait(timeout=10.0)
                admitted_before_cancel.append(stage)
                return {stage: "ok"}
            return agent

        config = ExecutorConfig(
            max_workers=2, agent_factory=factory, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        assert _wait_until(lambda: scheduler.status("B").name == "RUNNING")
        executor.request_pipeline_cancellation()
        hold.set()
        runner.join(timeout=10.0)

        assert executor.pipeline_cancelled()
        assert scheduler.status("A").name == "CANCELLED"
        assert scheduler.status("B").name == "CANCELLED"
        assert scheduler.status("C").name in ("CANCELLED", "PENDING", "BLOCKED")
        assert scheduler.status("D").name in ("PENDING", "BLOCKED", "CANCELLED")
        assert scheduler.status("E").name in ("PENDING", "BLOCKED", "CANCELLED")
        assert executor.outcomes().get("A") in (StageOutcome.CANCELLED, None)
        assert executor.outcomes().get("B") in (StageOutcome.CANCELLED, None)


class TestIndividualStageCancellation:
    """H. Individual stage cancellation in A→B, C→D graph."""

    def test_cancel_a_leaves_cd_schedulable(self):
        from pipeline.cancellation import StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C", "D"],
            {"B": ["A"], "D": ["C"]},
        )
        release_a = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    release_a.wait(timeout=5.0)
                    return {"A": "ok"}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(max_workers=2, agent_factory=factory)
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        executor.cancel_stage("A")
        release_a.set()
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert executor.outcomes()["A"] == StageOutcome.CANCELLED
        assert scheduler.instance("B").status.name == "BLOCKED"
        assert scheduler.instance("C").status.name == "COMPLETED"
        assert scheduler.instance("D").status.name == "COMPLETED"

    def test_cancel_completed_stage_rejected(self):
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.scheduler import SchedulerError

        scheduler = _make_test_scheduler(["P"])
        executor = PipelineExecutor(
            scheduler, ExecutorConfig(max_workers=1, agent_factory=lambda s: _quick_agent(s))
        )
        executor.run()

        with pytest.raises(SchedulerError):
            executor.cancel_stage("P")


class TestTimeoutPropagation:
    """I. A times out; B must not become READY."""

    def test_timeout_does_not_satisfy_dependency(self):
        from pipeline.cancellation import FakeClock
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B", "C"], {"B": ["A"], "C": ["B"]})
        clock = FakeClock(0.0)
        hold = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    hold.wait(timeout=10.0)
                    return {"A": "late"}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(
            max_workers=1, agent_factory=factory, timeout_seconds=5.0, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        hold.set()
        runner.join(timeout=5.0)

        assert scheduler.instance("B").status.name == "BLOCKED"
        assert scheduler.instance("C").status.name == "BLOCKED"
        assert scheduler.status("B").name != "READY"


class TestStaleResults:
    """J-M. Stale/late result protection."""

    def test_stale_timeout_result_rejected(self):
        from pipeline.cancellation import FakeClock
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        hold = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    hold.wait(timeout=10.0)
                    return {"A": "late"}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(
            max_workers=1, agent_factory=factory, timeout_seconds=5.0, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        hold.set()
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert executor.outcomes()["A"].name == "TIMEOUT"

    def test_execution_id_mismatch_rejected(self):
        from pipeline.cancellation import StageOutcome
        from pipeline.execution import ExecutionId
        from pipeline.executor import ExecutorConfig, PipelineExecutor, WorkerResult

        scheduler = _make_test_scheduler(["A"])
        executor = PipelineExecutor(
            scheduler, ExecutorConfig(max_workers=1, agent_factory=_quick_agent)
        )
        wrong = WorkerResult(
            stage="A",
            execution_id=ExecutionId("0" * 32),
            attempt_number=1,
            success=True,
            outcome=StageOutcome.SUCCESS,
        )
        assert not executor._is_result_valid("A", wrong)

    def test_attempt_mismatch_rejected(self):
        from pipeline.cancellation import StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor, WorkerResult

        scheduler = _make_test_scheduler(["A"])
        executor = PipelineExecutor(
            scheduler, ExecutorConfig(max_workers=1, agent_factory=_quick_agent)
        )
        stale = WorkerResult(
            stage="A",
            execution_id=scheduler.execution_id,
            attempt_number=99,
            success=True,
            outcome=StageOutcome.SUCCESS,
        )
        assert not executor._is_result_valid("A", stale)

    def test_terminal_state_result_rejected(self):
        from pipeline.cancellation import StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor, WorkerResult

        scheduler = _make_test_scheduler(["A", "B", "C"])
        executor = PipelineExecutor(
            scheduler, ExecutorConfig(max_workers=1, agent_factory=_quick_agent)
        )
        ok = WorkerResult(
            stage="A",
            execution_id=scheduler.execution_id,
            attempt_number=1,
            success=True,
            outcome=StageOutcome.SUCCESS,
        )
        scheduler.block_stage("A")
        assert not executor._is_result_valid("A", ok)
        scheduler.skip("B")
        bs_res = WorkerResult(
            stage="B",
            execution_id=scheduler.execution_id,
            attempt_number=1,
            success=True,
            outcome=StageOutcome.SUCCESS,
        )
        assert not executor._is_result_valid("B", bs_res)
        scheduler.cancel("C")
        cs_res = WorkerResult(
            stage="C",
            execution_id=scheduler.execution_id,
            attempt_number=1,
            success=True,
            outcome=StageOutcome.SUCCESS,
        )
        assert not executor._is_result_valid("C", cs_res)


class TestArtifactSafety:
    """N. A stale attempt's output cannot become authoritative."""

    def test_cancelled_attempt_output_not_committed(self):
        from pipeline.cancellation import FakeClock
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(["A", "B"], {"B": ["A"]})
        clock = FakeClock(0.0)
        hold = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    hold.wait(timeout=10.0)
                    return {"A": "artifact", "outputs": {"path": "outputs/x.json"}}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(
            max_workers=1, agent_factory=factory, timeout_seconds=5.0, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        hold.set()
        runner.join(timeout=5.0)

        assert scheduler.instance("A").status.name == "CANCELLED"
        assert scheduler.instance("A").status.name != "COMPLETED"
        assert executor.outcomes()["A"].name == "TIMEOUT"


class TestDeadlineDeterminism:
    """O. Repeated fake-clock simulations produce identical outcomes."""

    def _scenario(self):
        from pipeline.cancellation import FakeClock
        from pipeline.executor import ExecutorConfig, PipelineExecutor

        scheduler = _make_test_scheduler(
            ["A", "B", "C"],
            {"B": ["A"], "C": ["B"]},
        )
        clock = FakeClock(0.0)
        hold = threading.Event()

        def factory(stage):
            if stage == "A":
                def agent(inputs):
                    hold.wait(timeout=10.0)
                    return {"A": "late"}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(
            max_workers=1, agent_factory=factory, timeout_seconds=5.0, clock=clock
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("A").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("A").name == "CANCELLED")
        hold.set()
        runner.join(timeout=5.0)
        return (
            tuple(sorted((k, v.name) for k, v in executor.outcomes().items())),
            tuple((st, scheduler.status(st).name) for st in scheduler.stage_order()),
        )

    def test_repeated_fake_clock_identical(self):

        first = self._scenario()
        second = self._scenario()
        assert first == second


class TestNineteenStageGraphTimeout:
    """P. Full 19-stage graph with controlled timeout."""

    def _downstream(self, scheduler: StageScheduler, route: str) -> list[str]:
        result = []
        for stage in scheduler.stage_order():
            if stage == route:
                continue
            stack = list(scheduler.required_dependencies(stage))
            seen = set()
            found = False
            while stack:
                dep = stack.pop()
                if dep in seen:
                    continue
                seen.add(dep)
                if dep == route:
                    found = True
                    break
                stack.extend(scheduler.required_dependencies(dep))
            if found:
                result.append(stage)
        return result

    def test_full_graph_camera_timeout_blocks_downstream_only(self):
        from pipeline.cancellation import FakeClock, StageOutcome
        from pipeline.executor import ExecutorConfig, PipelineExecutor
        from pipeline.scheduler import create_ananta_scheduler

        scheduler = create_ananta_scheduler(episode_id="ANANTA-S01E01")
        clock = FakeClock(0.0)
        hold_camera = threading.Event()

        def factory(stage):
            if stage == "camera":
                def agent(inputs):
                    hold_camera.wait(timeout=15.0)
                    return {"camera": "late"}
                return agent
            return _quick_agent(stage)

        config = ExecutorConfig(
            max_workers=4,
            agent_factory=factory,
            stage_timeouts={"camera": 5.0},
            clock=clock,
        )
        executor = PipelineExecutor(scheduler, config)
        runner = threading.Thread(target=executor.run)
        runner.start()

        assert _wait_until(lambda: scheduler.status("camera").name == "RUNNING")
        clock.advance(6.0)
        assert _wait_until(lambda: scheduler.status("camera").name == "CANCELLED")
        hold_camera.set()
        runner.join(timeout=15.0)

        downstream = self._downstream(scheduler, "camera")
        assert scheduler.instance("camera").status.name == "CANCELLED"
        assert executor.outcomes()["camera"] == StageOutcome.TIMEOUT
        for stage in downstream:
            assert scheduler.status(stage).name == "BLOCKED", f"{stage} not blocked"
        for stage in scheduler.stage_order():
            if stage == "camera" or stage in downstream:
                continue
            assert scheduler.status(stage).name == "COMPLETED", f"{stage} not completed"
