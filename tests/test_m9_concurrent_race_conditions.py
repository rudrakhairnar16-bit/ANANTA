import json
import pathlib
import threading
import time
from typing import Any

from observability.logging import get_current_context
from pipeline.artifacts import ArtifactManager
from pipeline.dependencies import DependencyGraph, StageSpec

try:
    from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
except ImportError:
    try:
        from pipeline.orchestrator_v2 import ConcurrentPipelineOrchestrator  # type: ignore
    except ImportError:
        ConcurrentPipelineOrchestrator = None


class TestM9ConcurrentRaceConditions:
    """M9 Test File 3: Race condition and concurrency hazard tests."""

    def test_parallel_artifact_writes(self, tmp_path: pathlib.Path):
        """
        Test H: Parallel Artifact Writes
        Execute multiple independent stages in parallel, all writing output artifacts.
        Verify:
        - No torn writes or corrupted JSON
        - All artifacts properly indexed in metadata index
        - All SHA-256 checksums verify cleanly via artifact manager integrity check
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        artifact_dir = tmp_path / "artifacts"
        artifact_manager = ArtifactManager(artifact_dir)

        graph = DependencyGraph()
        graph.add_stage(StageSpec("root", produces_outputs=["root_data"]))
        num_parallel = 8
        for i in range(num_parallel):
            graph.add_stage(
                StageSpec(
                    f"worker_stage_{i}", produces_outputs=[f"data_{i}"], dependencies=["root"]
                )
            )
        graph.add_stage(
            StageSpec("collector", dependencies=[f"worker_stage_{i}" for i in range(num_parallel)])
        )

        def make_agent(stage: str):
            def agent(inputs: dict[str, Any]) -> dict[str, Any]:
                # Generate reasonably sized payload
                payload = {f"key_{j}": f"val_{j}" * 50 for j in range(100)}
                return {f"out_{stage}": payload}

            return agent

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=make_agent,
            artifact_manager=artifact_manager,
            max_workers=4,
        )

        ep_id = "ANANTA-M9-RACE-W"
        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": ep_id, "title": "Parallel Write Test"}), encoding="utf-8"
        )

        orch.run(str(brief_file))

        # Check all artifacts
        for i in range(num_parallel):
            art = artifact_manager.get_latest_artifact(ep_id, f"worker_stage_{i}")
            assert art is not None, f"Artifact missing for worker_stage_{i}"
            assert f"out_worker_stage_{i}" in art["outputs"]

        # Integrity verification must pass 100%
        assert artifact_manager.verify_integrity(ep_id) is True

    def test_parallel_read_write_isolation(self, tmp_path: pathlib.Path):
        """
        Test I: Parallel Read/Write Isolation
        While one stage is actively committing an artifact, concurrent stages
        must only observe atomic, fully-committed versions (never partial files).
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        artifact_dir = tmp_path / "artifacts"
        artifact_manager = ArtifactManager(artifact_dir)

        graph = DependencyGraph()
        graph.add_stage(StageSpec("writer_stage", produces_outputs=["writer_out"]))
        graph.add_stage(StageSpec("reader_stage", produces_outputs=["reader_out"]))

        read_observations: list[Any] = []

        def agent_writer(inputs: dict[str, Any]) -> dict[str, Any]:
            time.sleep(0.02)
            return {"writer_out": {"large_array": list(range(10000))}}

        def agent_reader(inputs: dict[str, Any]) -> dict[str, Any]:
            # Try reading whatever exists in artifact store
            for _ in range(20):
                art = artifact_manager.get_latest_artifact("ANANTA-M9-RW", "writer_stage")
                if art is not None:
                    read_observations.append(art)
                time.sleep(0.005)
            return {"reader_out": True}

        agent_map = {"writer_stage": agent_writer, "reader_stage": agent_reader}

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            artifact_manager=artifact_manager,
            max_workers=2,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-RW", "title": "RW Isolation"}), encoding="utf-8"
        )

        orch.run(str(brief_file))

        # Any artifact observed by the reader must be fully formed, valid JSON with all 10000 items
        for obs in read_observations:
            assert "outputs" in obs
            assert len(obs["outputs"]["writer_out"]["large_array"]) == 10000

    def test_thread_local_execution_context(self, tmp_path: pathlib.Path):
        """
        Test J: Thread-Local Execution Context
        Verify that structured logging correlation context (stage, correlation_id, episode_id)
        is strictly isolated per worker thread and does not leak or contaminate parallel workers.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("root", produces_outputs=["root"]))
        graph.add_stage(StageSpec("worker_a", dependencies=["root"]))
        graph.add_stage(StageSpec("worker_b", dependencies=["root"]))

        contexts_observed: dict[str, dict[str, Any]] = {}
        barrier = threading.Barrier(2, timeout=5.0)

        def make_agent(stage: str):
            def agent(inputs: dict[str, Any]) -> dict[str, Any]:
                if stage in ("worker_a", "worker_b"):
                    barrier.wait()  # Align execution
                    ctx = get_current_context()
                    contexts_observed[stage] = {
                        "stage": ctx.stage if ctx else None,
                        "episode_id": ctx.episode_id if ctx else None,
                        "correlation_id": ctx.correlation_id if ctx else None,
                    }
                return {f"{stage}_done": True}

            return agent

        orch = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=make_agent,
            max_workers=2,
        )

        brief_file = tmp_path / "brief.json"
        brief_file.write_text(
            json.dumps({"episode_id": "ANANTA-M9-CTX", "title": "Context Test"}), encoding="utf-8"
        )

        orch.run(str(brief_file))

        assert "worker_a" in contexts_observed
        assert "worker_b" in contexts_observed
        assert contexts_observed["worker_a"]["stage"] == "worker_a"
        assert contexts_observed["worker_b"]["stage"] == "worker_b"
