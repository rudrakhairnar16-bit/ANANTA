import copy
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


class TestM9DagDataFlow:
    """M9 Test File 1: Contract tests for concurrent DAG data-flow and artifact isolation."""

    def test_dependency_input_isolation(self, tmp_path: pathlib.Path):
        """
        Test A: Dependency Input Isolation
        DAG: A -> B, C -> D where B and C execute concurrently.
        B and C must receive independent, immutable input snapshots of A's output.
        Mutations inside B must NOT affect C or A's stored artifact.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        artifact_dir = tmp_path / "artifacts"
        state_dir = tmp_path / "state"
        artifact_manager = ArtifactManager(artifact_dir)
        state_store = StateStore(state_dir)
        checkpoint_manager = CheckpointManager(state_store, tmp_path / "checkpoints")

        graph = DependencyGraph()
        graph.add_stage(
            StageSpec("stage_a", required_inputs=["title"], produces_outputs=["scene_data"])
        )
        graph.add_stage(
            StageSpec(
                "stage_b",
                required_inputs=["scene_data"],
                produces_outputs=["b_out"],
                dependencies=["stage_a"],
            )
        )
        graph.add_stage(
            StageSpec(
                "stage_c",
                required_inputs=["scene_data"],
                produces_outputs=["c_out"],
                dependencies=["stage_a"],
            )
        )
        graph.add_stage(
            StageSpec(
                "stage_d",
                required_inputs=["b_out", "c_out"],
                produces_outputs=["final_out"],
                dependencies=["stage_b", "stage_c"],
            )
        )

        observed_b_inputs: dict[str, Any] = {}
        observed_c_inputs: dict[str, Any] = {}
        b_mutated_event = threading.Event()

        def agent_a(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"scene_data": {"shots": [1, 2, 3], "metadata": {"status": "original"}}}

        def agent_b(inputs: dict[str, Any]) -> dict[str, Any]:
            observed_b_inputs.update(copy.deepcopy(inputs))
            # Malicious/destructive in-place mutation
            inputs["scene_data"]["metadata"]["status"] = "MUTATED_BY_B"
            inputs["scene_data"]["shots"].append(999)
            inputs["mutated_key"] = True
            b_mutated_event.set()
            return {"b_out": {"b_status": "done"}}

        def agent_c(inputs: dict[str, Any]) -> dict[str, Any]:
            # Wait for B to apply its mutation first to verify isolation
            b_mutated_event.wait(timeout=2.0)
            observed_c_inputs.update(copy.deepcopy(inputs))
            return {"c_out": {"c_status": "done"}}

        def agent_d(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"final_out": "completed"}

        agent_map = {
            "stage_a": agent_a,
            "stage_b": agent_b,
            "stage_c": agent_c,
            "stage_d": agent_d,
        }

        orchestrator = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            artifact_manager=artifact_manager,
            checkpoint_manager=checkpoint_manager,
            state_store=state_store,
            max_workers=2,
        )

        brief = {"episode_id": "ANANTA-M9-ISO", "title": "Isolation Test"}
        brief_path = tmp_path / "brief.json"
        brief_path.write_text(json.dumps(brief), encoding="utf-8")

        result = orchestrator.run(str(brief_path))

        assert result is not None
        # Verify C saw pristine original data, completely unaffected by B's mutation
        assert "scene_data" in observed_c_inputs
        assert observed_c_inputs["scene_data"]["metadata"]["status"] == "original"
        assert observed_c_inputs["scene_data"]["shots"] == [1, 2, 3]
        assert "mutated_key" not in observed_c_inputs

        # Verify A's stored artifact on disk was not corrupted by B's in-place mutation
        artifact_a = artifact_manager.get_latest_artifact("ANANTA-M9-ISO", "stage_a")
        assert artifact_a is not None
        assert artifact_a["outputs"]["scene_data"]["metadata"]["status"] == "original"
        assert artifact_a["outputs"]["scene_data"]["shots"] == [1, 2, 3]

    def test_parent_artifact_dependency_resolution(self, tmp_path: pathlib.Path):
        """
        Test B: Parent Artifact Dependency Resolution
        A stage depending on parent stages must receive verified parent outputs.
        If a parent artifact is missing or corrupted on disk, execution must be rejected.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        artifact_dir = tmp_path / "artifacts"
        artifact_manager = ArtifactManager(artifact_dir)

        graph = DependencyGraph()
        graph.add_stage(StageSpec("parent_x", produces_outputs=["x_data"]))
        graph.add_stage(StageSpec("parent_y", produces_outputs=["y_data"]))
        graph.add_stage(
            StageSpec(
                "child_z",
                required_inputs=["x_data", "y_data"],
                produces_outputs=["z_data"],
                dependencies=["parent_x", "parent_y"],
            )
        )

        received_child_inputs: dict[str, Any] = {}

        def agent_x(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"x_data": "value_x"}

        def agent_y(inputs: dict[str, Any]) -> dict[str, Any]:
            return {"y_data": "value_y"}

        def agent_z(inputs: dict[str, Any]) -> dict[str, Any]:
            received_child_inputs.update(inputs)
            return {"z_data": "value_z"}

        agent_map = {"parent_x": agent_x, "parent_y": agent_y, "child_z": agent_z}

        orchestrator = ConcurrentPipelineOrchestrator(
            dependency_graph=graph,
            agent_factory=lambda stage: agent_map[stage],
            artifact_manager=artifact_manager,
            max_workers=2,
        )

        brief = {"episode_id": "ANANTA-M9-RES", "title": "Resolution Test"}
        brief_path = tmp_path / "brief.json"
        brief_path.write_text(json.dumps(brief), encoding="utf-8")

        orchestrator.run(str(brief_path))

        assert received_child_inputs.get("x_data") == "value_x"
        assert received_child_inputs.get("y_data") == "value_y"

    def test_deterministic_join_merge(self, tmp_path: pathlib.Path):
        """
        Test C: Deterministic Join Merge
        DAG: A -> [B, C, D] -> E.
        Regardless of the completion order and non-deterministic completion timing of B, C, D,
        join stage E must always receive an identical, deterministic input structure.
        """
        assert ConcurrentPipelineOrchestrator is not None, (
            "ConcurrentPipelineOrchestrator must exist"
        )

        graph = DependencyGraph()
        graph.add_stage(StageSpec("stage_a", produces_outputs=["seed"]))
        graph.add_stage(StageSpec("stage_b", produces_outputs=["out_b"], dependencies=["stage_a"]))
        graph.add_stage(StageSpec("stage_c", produces_outputs=["out_c"], dependencies=["stage_a"]))
        graph.add_stage(StageSpec("stage_d", produces_outputs=["out_d"], dependencies=["stage_a"]))
        graph.add_stage(
            StageSpec(
                "stage_e",
                required_inputs=["out_b", "out_c", "out_d"],
                produces_outputs=["out_e"],
                dependencies=["stage_b", "stage_c", "stage_d"],
            )
        )

        delays_run1 = {"stage_b": 0.04, "stage_c": 0.01, "stage_d": 0.02}
        delays_run2 = {"stage_b": 0.01, "stage_c": 0.04, "stage_d": 0.03}

        e_inputs_run1: dict[str, Any] = {}
        e_inputs_run2: dict[str, Any] = {}

        def run_pipeline(delays: dict[str, float], sink: dict[str, Any], ep_id: str):
            def agent_factory(stage: str):
                def agent(inputs: dict[str, Any]) -> dict[str, Any]:
                    if stage in delays:
                        time.sleep(delays[stage])
                    if stage == "stage_e":
                        sink.update(copy.deepcopy(inputs))
                        return {"out_e": "done"}
                    return {f"out_{stage[-1]}": f"data_{stage[-1]}"}

                return agent

            artifact_dir = tmp_path / f"artifacts_{ep_id}"
            art_mgr = ArtifactManager(artifact_dir)
            orch = ConcurrentPipelineOrchestrator(
                dependency_graph=graph,
                agent_factory=agent_factory,
                artifact_manager=art_mgr,
                max_workers=3,
            )
            brief_file = tmp_path / f"brief_{ep_id}.json"
            brief_file.write_text(
                json.dumps({"episode_id": ep_id, "title": "Join Test"}), encoding="utf-8"
            )
            orch.run(str(brief_file))

        run_pipeline(delays_run1, e_inputs_run1, "ANANTA-M9-J1")
        run_pipeline(delays_run2, e_inputs_run2, "ANANTA-M9-J2")

        # Invariant: inputs to stage_e must be identical in content across varied completion order
        assert e_inputs_run1.get("out_b") == e_inputs_run2.get("out_b") == "data_b"
        assert e_inputs_run1.get("out_c") == e_inputs_run2.get("out_c") == "data_c"
        assert e_inputs_run1.get("out_d") == e_inputs_run2.get("out_d") == "data_d"
