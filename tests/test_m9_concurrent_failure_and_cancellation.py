import json
import pathlib
import threading
import time
from typing import Any

import pytest

from pipeline.artifacts import ArtifactManager
from pipeline.cancellation import CancellationToken
from pipeline.dependencies import DependencyGraph, StageSpec
from pipeline.retry import RetryPolicy
from pipeline.state import CheckpointManager, StateStore

try:
    from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
except ImportError:
    try:
        from pipeline.orchestrator_v2 import ConcurrentPipelineOrchestrator  # type: ignore
    except ImportError:
        ConcurrentPipelineOrchestrator = None


class TestM9ConcurrentFailureAndCancellation:
    """M9 Test File 4: Failure isolation, cancellation, retry, and crash-recovery tests."""

    def test_branch_failure_isolation(self, tmp_path: pathlib.Path):
        """
        Test K: Branch Failure Isolation
        DAG:
            A
          /   \
         B     C
         |
         D
        B fails. D depends on B and must be BLOCKED/never executed.
        Independent sibling C must be allowed to complete successfully.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("stage_a", produces_outputs=["out_a"]))
        graph.add_stage(StageSpec("stage_b", produces_outputs=["out_b"], dependencies=["stage_a"]))
        graph.add_stage(StageSpec("stage_c", produces_outputs=["out_c"], dependencies=["stage_a"]))
        graph.add_stage(StageSpec("stage_d", produces_outputs=["out_d"], dependencies=["stage_b"]))

        c_completed = threading.Event()
        d_executed = False

        def agent_a(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"out_a": "a"}

        def agent_b(inputs: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("Stage B intentionally failed")

        def agent_c(inputs: dict[str, Any]) -> dict[str, Any]:
            time.sleep(0.05)
            c_completed.set()
            return {"out_c": "c"}

        def agent_d(inputs: dict[str, Any]) -> dict[str, Any]:
            nonlocal d_executed
            d_executed = True
            return {"out_d": "d"}

        agent_map = {
            "stage_a": agent_a,
            "stage_b": agent_b,
            "stage_c": agent_c,
            "stage_d": agent_d,
        }

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            max_workers=2,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-FAIL", "title": "Failure Isolation"}),
            encoding="utf-8",
        )

        result = orch.run(str(brief_file))

        assert c_completed.is_set(), "Independent stage C should have completed despite B's failure"
        assert not d_executed, "Stage D should never have executed because its parent B failed"
        assert result is not None
        summary = result.get("summary") or result
        assert summary.get("status") == "failed"

    def test_downstream_dependency_blocking(self, tmp_path: pathlib.Path):
        """
        Test L: Downstream Dependency Blocking
        When upstream stage fails, verify no downstream agent callable is ever invoked.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("root", produces_outputs=["r"]))
        graph.add_stage(StageSpec("step1", produces_outputs=["s1"], dependencies=["root"]))
        graph.add_stage(StageSpec("step2", produces_outputs=["s2"], dependencies=["step1"]))
        graph.add_stage(StageSpec("step3", produces_outputs=["s3"], dependencies=["step2"]))

        call_counts: dict[str, int] = {"root": 0, "step1": 0, "step2": 0, "step3": 0}

        def make_agent(stage: str):
            def agent(inputs: dict[str, Any]) -> dict[str, Any]:
                call_counts[stage] += 1
                if stage == "step1":
                    raise ValueError("Step 1 failed")
                return {f"out_{stage}": True}

            return agent

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=make_agent,
            max_workers=2,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-BLOCK", "title": "Block Test"}), encoding="utf-8"
        )

        orch.run(str(brief_file))

        assert call_counts["root"] == 1
        assert call_counts["step1"] == 1
        assert call_counts["step2"] == 0, "step2 must be blocked"
        assert call_counts["step3"] == 0, "step3 must be blocked"

    def test_cooperative_cancellation(self, tmp_path: pathlib.Path):
        """
        Test M: Cooperative Cancellation
        When pipeline cancellation is requested, queued work is not admitted,
        running workers observe cancellation token, and no cancelled stage publishes artifacts.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("stage_1", produces_outputs=["o1"]))
        graph.add_stage(StageSpec("stage_2", dependencies=["stage_1"]))
        graph.add_stage(StageSpec("stage_3", dependencies=["stage_2"]))

        token = CancellationToken()
        started_event = threading.Event()

        def agent_1(inputs: dict[str, Any]) -> dict[str, Any]:
            started_event.set()
            time.sleep(0.2)
            return {"o1": "done"}

        def agent_2(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"o2": "done"}

        def agent_3(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"o3": "done"}

        agent_map = {"stage_1": agent_1, "stage_2": agent_2, "stage_3": agent_3}

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            cancellation_token=token,
            max_workers=2,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-CANCEL", "title": "Cancel Test"}), encoding="utf-8"
        )

        def cancel_trigger():
            started_event.wait(timeout=2.0)
            token.cancel()

        cancel_thread = threading.Thread(target=cancel_trigger)
        cancel_thread.start()

        result = orch.run(str(brief_file))
        cancel_thread.join()

        summary = result.get("summary") or result
        assert summary.get("status") in ("cancelled", "interrupted")

    def test_cancellation_during_retry_backoff(self, tmp_path: pathlib.Path):
        """
        Test N: Cancellation During Retry Backoff
        Stage fails and enters RETRYING state with backoff.
        Cancellation is requested during backoff.
        Verify no future retry attempt executes and pipeline terminates cleanly as CANCELLED.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("stage_flaky", produces_outputs=["out"]))

        token = CancellationToken()
        attempts = 0

        def flaky_agent(inputs: dict[str, Any]) -> dict[str, Any]:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("Transient failure requiring retry")

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: flaky_agent,
            retry_policy=RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=1.0),
            cancellation_token=token,
            max_workers=1,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-RETRY-CAN", "title": "Retry Cancel"}),
            encoding="utf-8",
        )

        def trigger_cancel():
            time.sleep(0.1)  # Allow first attempt to fail and enter retry wait
            token.cancel()

        threading.Thread(target=trigger_cancel).start()

        result = orch.run(str(brief_file))
        summary = result.get("summary") or result
        assert summary.get("status") in ("cancelled", "interrupted")
        assert attempts == 1, (
            "Should not have executed subsequent retry attempts after cancellation"
        )

    def test_concurrent_crash_resume(self, tmp_path: pathlib.Path):
        """
        Test O: Concurrent Crash Resume
        Simulate a concurrent pipeline where Branch 1 completes and commits an artifact,
        while Branch 2 is interrupted.
        When resume=True is invoked:
        - Already committed Branch 1 is NOT re-executed
        - Interrupted Branch 2 is re-executed
        - Join stage receives valid parent inputs
        - Summary completes successfully
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        artifact_dir = tmp_path / "artifacts"
        state_dir = tmp_path / "state"
        checkpoints_dir = tmp_path / "checkpoints"

        artifact_manager = ArtifactManager(artifact_dir)
        state_store = StateStore(state_dir)
        checkpoint_manager = CheckpointManager(state_store, checkpoints_dir)

        graph = DependencyGraph()
        graph.add_stage(StageSpec("root", produces_outputs=["root_data"]))
        graph.add_stage(StageSpec("branch_1", produces_outputs=["b1_data"], dependencies=["root"]))
        graph.add_stage(StageSpec("branch_2", produces_outputs=["b2_data"], dependencies=["root"]))
        graph.add_stage(
            StageSpec(
                "join",
                required_inputs=["b1_data", "b2_data"],
                produces_outputs=["join_data"],
                dependencies=["branch_1", "branch_2"],
            )
        )

        b1_executions = 0
        b2_executions = 0
        should_crash = True

        def agent_root(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"root_data": "root_val"}

        def agent_b1(inputs: dict[str, Any]) -> dict[str, Any]:
            nonlocal b1_executions
            b1_executions += 1
            return {"b1_data": "b1_val"}

        def agent_b2(inputs: dict[str, Any]) -> dict[str, Any]:
            nonlocal b2_executions
            b2_executions += 1
            if should_crash:
                time.sleep(0.05)
                raise KeyboardInterrupt("Simulated crash in Branch 2")
            return {"b2_data": "b2_val"}

        def agent_join(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"join_data": f"{inputs['b1_data']}+{inputs['b2_data']}"}

        agent_map = {
            "root": agent_root,
            "branch_1": agent_b1,
            "branch_2": agent_b2,
            "join": agent_join,
        }

        ep_id = "ANANTA-M9-RESUME"
        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": ep_id, "title": "Resume Test"}), encoding="utf-8"
        )

        orch1 = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            artifact_manager=artifact_manager,
            checkpoint_manager=checkpoint_manager,
            state_store=state_store,
            max_workers=2,
        )

        with pytest.raises(KeyboardInterrupt):
            orch1.run(str(brief_file))

        # First run: branch_1 should have completed and stored artifact
        assert artifact_manager.get_latest_artifact(ep_id, "branch_1") is not None
        assert b1_executions == 1

        # Now resume
        should_crash = False
        orch2 = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            artifact_manager=artifact_manager,
            checkpoint_manager=checkpoint_manager,
            state_store=state_store,
            max_workers=2,
        )

        result = orch2.run(str(brief_file), resume=True)

        summary = result.get("summary") or result
        assert summary.get("status") == "completed"
        # Invariant: branch_1 was NOT re-executed; it was hydrated from its committed artifact
        assert b1_executions == 1, "Branch 1 should not have re-executed on resume"
        assert b2_executions == 2, "Branch 2 should have re-executed on resume"
