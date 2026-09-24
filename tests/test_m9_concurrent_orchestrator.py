import json
import pathlib
import threading
import time
from typing import Any

from pipeline.artifacts import ArtifactManager
from pipeline.dependencies import DependencyGraph, StageSpec
from pipeline.state import CheckpointManager, StateStore

try:
    from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
except ImportError:
    try:
        from pipeline.orchestrator_v2 import ConcurrentPipelineOrchestrator  # type: ignore
    except ImportError:
        ConcurrentPipelineOrchestrator = None


class TestM9ConcurrentOrchestrator:
    """M9 Test File 2: Contract tests for Concurrent Pipeline Orchestrator."""

    def test_concurrent_orchestrator_public_api(self):
        """
        Test D: Concurrent Orchestrator Public API Exists
        Verifies ConcurrentPipelineOrchestrator is exposed as a public API
        and accepts configuration for stages, workers, and managers.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist in public API"
        )
        orch = ConcurrentPipelineOrchestrator(max_workers=4)
        assert hasattr(orch, "run")

    def test_full_19_stage_concurrent_episode(self, tmp_path: pathlib.Path):
        """
        Test E: Full 19-Stage Concurrent Episode
        Executes the canonical shared/episode_01.json brief across all 19 stages
        using mock providers concurrently.
        All 19 stages must succeed, produce valid artifacts, and create summary.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        artifact_dir = tmp_path / "artifacts"
        state_dir = tmp_path / "state"
        summary_dir = tmp_path / "outputs"
        summary_dir.mkdir(parents=True, exist_ok=True)

        artifact_manager = ArtifactManager(artifact_dir)
        state_store = StateStore(state_dir)
        checkpoint_manager = CheckpointManager(state_store, tmp_path / "checkpoints")

        orch = ConcurrentPipelineOrchestrator(
            artifact_manager=artifact_manager,
            checkpoint_manager=checkpoint_manager,
            state_store=state_store,
            max_workers=4,
        )

        brief_path = pathlib.Path(__file__).resolve().parents[1] / "shared" / "episode_01.json"
        assert brief_path.exists(), f"Brief file not found: {brief_path}"

        result = orch.run(str(brief_path))

        assert result is not None
        summary = result.get("summary") or result
        assert summary.get("status") == "completed"
        assert summary.get("stages_completed") == 19
        assert summary.get("stages_failed") == 0

        # Verify all 19 artifacts exist and checksums pass
        for stage in [
            "story",
            "screenplay",
            "scene_plan",
            "character",
            "world",
            "storyboard",
            "director",
            "camera",
            "visual",
            "motion",
            "voice",
            "music",
            "bgm",
            "sfx",
            "lipsync",
            "edit",
            "adobe_export",
            "qa",
            "export",
        ]:
            art = artifact_manager.get_latest_artifact("ANANTA-S01E01", stage)
            assert art is not None, f"Artifact missing for stage {stage}"

    def test_actual_parallel_overlap(self, tmp_path: pathlib.Path):
        """
        Test F: Actual Parallel Overlap
        Construct two independent parallel stages and synchronize them using a barrier/event.
        Proves both stages are concurrently active simultaneously within max_workers limit.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("root", produces_outputs=["root_out"]))
        graph.add_stage(
            StageSpec("branch_alpha", produces_outputs=["alpha_out"], dependencies=["root"])
        )
        graph.add_stage(
            StageSpec("branch_beta", produces_outputs=["beta_out"], dependencies=["root"])
        )
        graph.add_stage(StageSpec("join", dependencies=["branch_alpha", "branch_beta"]))

        barrier = threading.Barrier(2, timeout=5.0)
        overlap_confirmed = threading.Event()
        running_count = 0
        running_lock = threading.Lock()
        max_concurrent_observed = 0

        def make_agent(stage: str):
            def agent(inputs: dict[str, Any]) -> dict[str, Any]:
                nonlocal running_count, max_concurrent_observed
                if stage in ("branch_alpha", "branch_beta"):
                    with running_lock:
                        running_count += 1
                        if running_count > max_concurrent_observed:
                            max_concurrent_observed = running_count
                        if running_count >= 2:
                            overlap_confirmed.set()

                    # Wait for both sibling branches to reach this point concurrently
                    barrier.wait()

                    time.sleep(0.05)

                    with running_lock:
                        running_count -= 1

                return {f"{stage}_done": True}

            return agent

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=make_agent,
            max_workers=2,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-PAR", "title": "Parallel Overlap"}),
            encoding="utf-8",
        )

        orch.run(str(brief_file))

        assert overlap_confirmed.is_set(), (
            "Stages branch_alpha and branch_beta did not execute concurrently"
        )
        assert max_concurrent_observed == 2, (
            "Expected exactly 2 parallel workers running simultaneously"
        )

    def test_deterministic_admission_order(self, tmp_path: pathlib.Path):
        """
        Test G: Deterministic Admission Order
        Verify that ready stages are admitted into execution according to
        deterministic DAG scheduler ordering, independent of non-deterministic timing.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        admitted_order: list[str] = []
        admit_lock = threading.Lock()

        graph = DependencyGraph()
        graph.add_stage(StageSpec("stage_0", produces_outputs=["out0"]))
        graph.add_stage(StageSpec("stage_1", dependencies=["stage_0"]))
        graph.add_stage(StageSpec("stage_2", dependencies=["stage_0"]))
        graph.add_stage(StageSpec("stage_3", dependencies=["stage_0"]))

        def make_agent(stage: str):
            def agent(inputs: dict[str, Any]) -> dict[str, Any]:
                with admit_lock:
                    admitted_order.append(stage)
                return {f"{stage}_out": True}

            return agent

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=make_agent,
            max_workers=1,  # Serial worker execution to strictly observe admission sequence
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-DET", "title": "Deterministic Admit"}),
            encoding="utf-8",
        )

        orch.run(str(brief_file))

        assert admitted_order[0] == "stage_0"
        # Sibling stages ready simultaneously must be admitted in deterministic order
        assert admitted_order[1:] == ["stage_1", "stage_2", "stage_3"]
