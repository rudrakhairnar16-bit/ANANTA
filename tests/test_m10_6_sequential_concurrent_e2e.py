import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agents.base_agent_v2 import BaseAgentV2, get_agent_v2
from pipeline.artifacts import ArtifactManager, ArtifactStore
from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
from pipeline.dependencies import get_default_dependency_graph
from pipeline.orchestrator_v2 import PipelineOrchestratorV2
from pipeline.state import CheckpointManager, StateStore
from providers.base_v2 import (
    MockProviderV2,
    OllamaProviderV2,
)


@pytest.fixture
def temp_artifact_dir(tmp_path: Path):
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    yield art_dir
    if art_dir.exists():
        shutil.rmtree(art_dir, ignore_errors=True)


@pytest.fixture
def temp_state_dir(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    yield state_dir
    if state_dir.exists():
        shutil.rmtree(state_dir, ignore_errors=True)


def create_mock_ollama_response(payload: dict[str, Any]) -> MagicMock:
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": json.dumps(payload)}
    return mock_resp


# =========================================================================
# A. Sequential Execution End-to-End Tests
# =========================================================================


class TestM106SequentialE2E:
    """
    Verification of provider reliability, explicit fallback, artifact metadata,
    and publication safety across the sequential execution path.
    """

    def test_sequential_successful_ollama_stage_preserves_metadata(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """1. A successful Ollama-backed stage preserves accurate provider metadata

        through sequential execution and artifact persistence.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        ollama_story_provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="story",
        )
        mock_response = create_mock_ollama_response({
            "synopsis": "Dr. Maya Chen discovers emergent AI consciousness.",
            "themes": ["consciousness", "ethics"],
            "acts": 3,
            "beats": ["intro", "conflict", "resolution"],
        })

        def agent_factory(stage: str):
            if stage == "story":
                return BaseAgentV2(
                    "story",
                    provider=ollama_story_provider,
                    artifact_manager=artifact_mgr,
                )
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        with patch.object(ollama_story_provider.client, "post", return_value=mock_response):
            orchestrator = PipelineOrchestratorV2(
                stages=["story"],
                agent_factory=agent_factory,
                artifact_manager=artifact_mgr,
                state_store=state_store,
                checkpoint_manager=checkpoint_mgr,
            )
            result = orchestrator.run(sample_brief)

            # 1. Verify pipeline output payload metadata
            assert "metadata" in result
            meta = result["metadata"]
            assert meta["provider_type"] == "ollama"
            assert meta["provider_name"] == "OllamaProvider_story"
            assert meta["model_name"] == "llama3.1"
            assert meta["is_fallback"] is False
            assert "fallback_from" not in meta or meta["fallback_from"] is None

            # 2. Verify stored artifact in store
            stored_artifact = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "story")
            assert stored_artifact is not None
            assert stored_artifact["metadata"]["provider_type"] == "ollama"
            assert stored_artifact["metadata"]["provider_name"] == "OllamaProvider_story"
            assert stored_artifact["metadata"]["model_name"] == "llama3.1"
            assert stored_artifact["metadata"]["is_fallback"] is False

            # 3. Verify ArtifactStore index metadata
            artifact_id = "ANANTA-S01E01:story:v1"
            index_meta = store._index.get(artifact_id)
            assert index_meta is not None
            assert index_meta.provider_type == "ollama"
            assert index_meta.provider_name == "OllamaProvider_story"
            assert index_meta.model_name == "llama3.1"
            assert index_meta.is_fallback is False

            # 4. Verify .meta.json file on disk
            meta_path = temp_artifact_dir / "ANANTA-S01E01" / "story_v1.meta.json"
            assert meta_path.exists()
            disk_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert disk_meta["provider_type"] == "ollama"
            assert disk_meta["model_name"] == "llama3.1"
            assert disk_meta["is_fallback"] is False

    def test_sequential_explicit_mock_fallback_labeling_and_warnings(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """2. An explicitly enabled mock fallback in sequential execution is labeled

        as mock, is_fallback=True, with fallback_from and explicit warning.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        fallback_story_provider = MockProviderV2(
            stage="story",
            seed=42,
            is_fallback=True,
            fallback_from_provider="ollama",
        )

        def agent_factory(stage: str):
            if stage == "story":
                return BaseAgentV2(
                    "story",
                    provider=fallback_story_provider,
                    artifact_manager=artifact_mgr,
                )
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        orchestrator = PipelineOrchestratorV2(
            stages=["story"],
            agent_factory=agent_factory,
            artifact_manager=artifact_mgr,
            state_store=state_store,
            checkpoint_manager=checkpoint_mgr,
        )
        result = orchestrator.run(sample_brief)

        # 1. Verify result metadata and warnings
        assert result["metadata"]["provider_type"] == "mock"
        assert result["metadata"]["is_fallback"] is True
        assert result["metadata"]["fallback_from"] == "ollama"
        assert "warnings" in result
        assert any("fallback" in str(w).lower() for w in result["warnings"])

        # 2. Verify stored artifact
        stored_artifact = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "story")
        assert stored_artifact is not None
        assert stored_artifact["metadata"]["is_fallback"] is True
        assert stored_artifact["metadata"]["fallback_from"] == "ollama"
        assert stored_artifact["metadata"]["provider_type"] == "mock"
        assert any("fallback" in str(w).lower() for w in stored_artifact.get("warnings", []))

        # 3. Verify ArtifactStore index and .meta.json
        index_meta = store._index.get("ANANTA-S01E01:story:v1")
        assert index_meta is not None
        assert index_meta.is_fallback is True
        assert index_meta.provider_type == "mock"

        meta_path = temp_artifact_dir / "ANANTA-S01E01" / "story_v1.meta.json"
        assert meta_path.exists()
        disk_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert disk_meta["is_fallback"] is True
        assert disk_meta["provider_type"] == "mock"

    def test_sequential_provider_failure_does_not_publish_misleading_artifact(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """3. A provider failure in sequential execution halts and does not

        publish any misleading or unverified artifact.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        failing_provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="story",
        )

        def agent_factory(stage: str):
            if stage == "story":
                return BaseAgentV2(
                    "story",
                    provider=failing_provider,
                    artifact_manager=artifact_mgr,
                )
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        with patch.object(
            failing_provider.client,
            "post",
            side_effect=httpx.ConnectError("Ollama service unavailable"),
        ):
            orchestrator = PipelineOrchestratorV2(
                stages=["story", "screenplay"],
                agent_factory=agent_factory,
                artifact_manager=artifact_mgr,
                state_store=state_store,
                checkpoint_manager=checkpoint_mgr,
            )

            orchestrator.run(sample_brief)

            # Verify no artifact was written for failed story stage
            assert artifact_mgr.get_latest_artifact("ANANTA-S01E01", "story") is None
            assert len(store.list_artifacts("ANANTA-S01E01")) == 0

            # Verify no .meta.json exists
            meta_path = temp_artifact_dir / "ANANTA-S01E01" / "story_v1.meta.json"
            assert not meta_path.exists()

            # Verify state was marked failed
            restored = checkpoint_mgr.restore("ANANTA-S01E01")
            assert restored is not None
            assert restored.status == "failed"

    def test_sequential_multi_stage_metadata_isolation_and_correctness(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """4. Metadata remains correct, isolated, and untainted across multiple

        sequential stages with differing providers.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        # Stage setup:
        # story: OllamaProviderV2 (ollama, llama3.1)
        # screenplay: MockProviderV2 (mock, is_fallback=False)
        # scene_plan: MockProviderV2 (mock, is_fallback=False)
        # character: MockProviderV2 (mock, is_fallback=True, fallback_from="ollama")
        # world: MockProviderV2 (mock, is_fallback=False)

        ollama_story = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="story",
        )
        mock_screenplay = MockProviderV2("screenplay")
        mock_scene_plan = MockProviderV2("scene_plan")
        fallback_character = MockProviderV2(
            "character", is_fallback=True, fallback_from_provider="ollama"
        )
        mock_world = MockProviderV2("world")

        story_response = create_mock_ollama_response({
            "synopsis": "A brilliant scientist creates conscious AI.",
            "themes": ["ethics", "creation"],
            "acts": 3,
            "beats": ["inciting", "climax", "resolution"],
        })

        def agent_factory(stage: str):
            if stage == "story":
                return BaseAgentV2("story", provider=ollama_story, artifact_manager=artifact_mgr)
            elif stage == "screenplay":
                return BaseAgentV2(
                    "screenplay", provider=mock_screenplay, artifact_manager=artifact_mgr
                )
            elif stage == "scene_plan":
                return BaseAgentV2(
                    "scene_plan", provider=mock_scene_plan, artifact_manager=artifact_mgr
                )
            elif stage == "character":
                return BaseAgentV2(
                    "character", provider=fallback_character, artifact_manager=artifact_mgr
                )
            elif stage == "world":
                return BaseAgentV2("world", provider=mock_world, artifact_manager=artifact_mgr)
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        stages = ["story", "screenplay", "scene_plan", "character", "world"]

        with patch.object(ollama_story.client, "post", return_value=story_response):
            orchestrator = PipelineOrchestratorV2(
                stages=stages,
                agent_factory=agent_factory,
                artifact_manager=artifact_mgr,
                state_store=state_store,
                checkpoint_manager=checkpoint_mgr,
            )
            orchestrator.run(sample_brief)

            # Verify all 5 stages completed
            for stage in stages:
                art = artifact_mgr.get_latest_artifact("ANANTA-S01E01", stage)
                assert art is not None, f"Missing artifact for {stage}"

            # Verify story metadata: Ollama
            art_story = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "story")
            assert art_story["metadata"]["provider_type"] == "ollama"
            assert art_story["metadata"]["model_name"] == "llama3.1"
            assert art_story["metadata"]["is_fallback"] is False

            # Verify screenplay metadata: Mock (non-fallback)
            art_screenplay = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "screenplay")
            assert art_screenplay["metadata"]["provider_type"] == "mock"
            assert art_screenplay["metadata"]["model_name"] is None
            assert art_screenplay["metadata"]["is_fallback"] is False

            # Verify scene_plan metadata: Mock (non-fallback)
            art_scene = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "scene_plan")
            assert art_scene["metadata"]["provider_type"] == "mock"
            assert art_scene["metadata"]["is_fallback"] is False

            # Verify character metadata: Mock with explicit fallback
            art_char = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "character")
            assert art_char["metadata"]["provider_type"] == "mock"
            assert art_char["metadata"]["is_fallback"] is True
            assert art_char["metadata"]["fallback_from"] == "ollama"
            assert any("fallback" in str(w).lower() for w in art_char.get("warnings", []))

            # Verify world metadata: Mock (non-fallback, must NOT be contaminated by character)
            art_world = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "world")
            assert art_world["metadata"]["provider_type"] == "mock"
            assert art_world["metadata"]["is_fallback"] is False
            assert "fallback_from" not in art_world["metadata"]


# =========================================================================
# B. Concurrent Execution End-to-End Tests
# =========================================================================


class TestM106ConcurrentE2E:
    """
    Verification of provider reliability, explicit fallback, artifact metadata,
    and publication safety across the concurrent execution path.
    """

    def test_concurrent_stages_preserve_individual_provider_metadata(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """1. Concurrent stages running in parallel preserve their individual provider

        metadata without cross-thread contamination.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        # In DAG, character and world both depend on story and can run concurrently
        ollama_character = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="character",
        )
        mock_world = MockProviderV2("world")

        char_resp = create_mock_ollama_response({
            "profiles": [
                {
                    "id": "char_001",
                    "name": "Dr. Maya Chen",
                    "arc": "curiosity_to_protect",
                    "key_moments": ["discovery", "confrontation"],
                },
                {
                    "id": "char_002",
                    "name": "ANANTA",
                    "arc": "awakening_to_autonomy",
                    "key_moments": ["first_words", "decision"],
                },
            ]
        })

        def agent_factory(stage: str):
            if stage == "character":
                return BaseAgentV2(
                    "character", provider=ollama_character, artifact_manager=artifact_mgr
                )
            elif stage == "world":
                return BaseAgentV2("world", provider=mock_world, artifact_manager=artifact_mgr)
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        stages = ["story", "screenplay", "scene_plan", "character", "world"]

        with patch.object(ollama_character.client, "post", return_value=char_resp):
            orchestrator = ConcurrentPipelineOrchestrator(
                stages=stages,
                agent_factory=agent_factory,
                artifact_manager=artifact_mgr,
                state_store=state_store,
                checkpoint_manager=checkpoint_mgr,
                max_workers=3,
            )
            result = orchestrator.run(sample_brief)

            assert result["status"] == "completed"
            assert result["stages_completed"] == 5

            # Character: Ollama metadata
            art_char = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "character")
            assert art_char is not None
            assert art_char["metadata"]["provider_type"] == "ollama"
            assert art_char["metadata"]["model_name"] == "llama3.1"
            assert art_char["metadata"]["is_fallback"] is False

            # World: Mock metadata
            art_world = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "world")
            assert art_world is not None
            assert art_world["metadata"]["provider_type"] == "mock"
            assert art_world["metadata"]["is_fallback"] is False
            assert art_world["metadata"]["model_name"] is None

    def test_concurrent_fallback_in_one_stage_does_not_mark_others_as_fallback(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """2. A fallback in one concurrent stage does not incorrectly mark

        unrelated concurrent stages as fallback.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        # Run parallel stages: character (fallback Mock) and world (regular Mock)
        fallback_character = MockProviderV2(
            "character", is_fallback=True, fallback_from_provider="ollama"
        )
        mock_world = MockProviderV2("world", is_fallback=False)

        def agent_factory(stage: str):
            if stage == "character":
                return BaseAgentV2(
                    "character", provider=fallback_character, artifact_manager=artifact_mgr
                )
            elif stage == "world":
                return BaseAgentV2("world", provider=mock_world, artifact_manager=artifact_mgr)
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        stages = ["story", "screenplay", "scene_plan", "character", "world"]

        orchestrator = ConcurrentPipelineOrchestrator(
            stages=stages,
            agent_factory=agent_factory,
            artifact_manager=artifact_mgr,
            state_store=state_store,
            checkpoint_manager=checkpoint_mgr,
            max_workers=3,
        )
        result = orchestrator.run(sample_brief)

        assert result["status"] == "completed"

        # Character must have is_fallback=True
        art_char = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "character")
        assert art_char["metadata"]["is_fallback"] is True
        assert art_char["metadata"]["fallback_from"] == "ollama"
        assert any("fallback" in str(w).lower() for w in art_char.get("warnings", []))

        # World must NOT have is_fallback=True or fallback warnings
        art_world = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "world")
        assert art_world["metadata"]["is_fallback"] is False
        assert "fallback_from" not in art_world["metadata"]
        assert not any("fallback" in str(w).lower() for w in art_world.get("warnings", []))

        # Scene plan must NOT be marked as fallback
        art_scene = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "scene_plan")
        assert art_scene["metadata"]["is_fallback"] is False

    def test_concurrent_provider_failures_do_not_create_misleading_artifacts(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """3. Provider failure in concurrent execution halts dependent stages and

        does NOT publish misleading artifacts for failed or blocked stages.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        failing_screenplay = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="screenplay",
        )

        def agent_factory(stage: str):
            if stage == "screenplay":
                return BaseAgentV2(
                    "screenplay", provider=failing_screenplay, artifact_manager=artifact_mgr
                )
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        stages = ["story", "screenplay", "scene_plan", "character", "world"]

        with patch.object(
            failing_screenplay.client,
            "post",
            side_effect=httpx.ConnectError("Ollama offline"),
        ):
            orchestrator = ConcurrentPipelineOrchestrator(
                stages=stages,
                agent_factory=agent_factory,
                artifact_manager=artifact_mgr,
                state_store=state_store,
                checkpoint_manager=checkpoint_mgr,
                max_workers=3,
            )
            result = orchestrator.run(sample_brief)

            assert result["status"] == "failed"

            # Story completed before failure
            art_story = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "story")
            assert art_story is not None

            # Screenplay failed -> NO artifact published
            assert artifact_mgr.get_latest_artifact("ANANTA-S01E01", "screenplay") is None
            assert not (temp_artifact_dir / "ANANTA-S01E01" / "screenplay_v1.json").exists()
            assert not (temp_artifact_dir / "ANANTA-S01E01" / "screenplay_v1.meta.json").exists()

            # Downstream dependent stages on screenplay never ran -> NO artifacts published
            assert artifact_mgr.get_latest_artifact("ANANTA-S01E01", "scene_plan") is None
            assert not (temp_artifact_dir / "ANANTA-S01E01" / "scene_plan_v1.json").exists()

            # Independent parallel branches depending only on story succeeded
            art_char = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "character")
            art_world = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "world")
            assert art_char is not None
            assert art_world is not None

    def test_concurrent_results_and_metadata_association_correctness(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """4. Results and metadata remain strictly associated with the correct

        stage and artifact across parallel execution.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        orchestrator = ConcurrentPipelineOrchestrator(
            artifact_manager=artifact_mgr,
            state_store=state_store,
            checkpoint_manager=checkpoint_mgr,
            max_workers=4,
        )
        result = orchestrator.run(sample_brief)

        assert result["status"] == "completed"
        assert result["stages_completed"] == 19

        # Verify all 19 artifacts on disk have matching stage names and valid metadata
        graph = get_default_dependency_graph()
        for stage in graph.get_execution_order():
            art_data, meta = store.get("ANANTA-S01E01", stage)
            assert art_data["stage"] == stage
            assert meta.stage == stage
            assert meta.name == f"ANANTA-S01E01:{stage}:v1"
            assert meta.provider_type == "mock"
            assert meta.provider_name == f"MockProvider_{stage}"
            assert meta.is_fallback is False
            assert meta.checksum != ""
            assert meta.size_bytes > 0

        # Overall integrity check
        assert store.verify_integrity("ANANTA-S01E01") is True

    def test_concurrent_stages_variable_completion_order_preserves_metadata(
        self, temp_artifact_dir, temp_state_dir, sample_brief
    ):
        """5. Verify behavior when multiple concurrent stages finish in different

        orders due to variable simulated latencies.
        """
        store = ArtifactStore(base_path=temp_artifact_dir)
        artifact_mgr = ArtifactManager(artifact_store=store)
        state_store = StateStore(base_path=temp_state_dir)
        checkpoint_mgr = CheckpointManager(state_store)

        # Character (slow 60ms), World (fast 10ms)
        slow_char_provider = MockProviderV2("character", simulate_latency_ms=60)
        fast_world_provider = MockProviderV2("world", simulate_latency_ms=10)

        def agent_factory(stage: str):
            if stage == "character":
                return BaseAgentV2(
                    "character", provider=slow_char_provider, artifact_manager=artifact_mgr
                )
            elif stage == "world":
                return BaseAgentV2(
                    "world", provider=fast_world_provider, artifact_manager=artifact_mgr
                )
            return get_agent_v2(stage, artifact_manager=artifact_mgr)

        stages = ["story", "screenplay", "scene_plan", "character", "world"]

        orchestrator = ConcurrentPipelineOrchestrator(
            stages=stages,
            agent_factory=agent_factory,
            artifact_manager=artifact_mgr,
            state_store=state_store,
            checkpoint_manager=checkpoint_mgr,
            max_workers=3,
        )
        result = orchestrator.run(sample_brief)

        assert result["status"] == "completed"
        assert result["stages_completed"] == 5

        # Verify integrity and distinct metadata despite inverted completion timing
        art_char = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "character")
        art_world = artifact_mgr.get_latest_artifact("ANANTA-S01E01", "world")

        assert art_char["stage"] == "character"
        assert art_world["stage"] == "world"
        assert store.verify_integrity("ANANTA-S01E01") is True


# =========================================================================
# C. Execution Mode Consistency Tests
# =========================================================================


class TestM106ExecutionModeConsistency:
    """
    Verification that sequential and concurrent execution produce consistent
    metadata semantics for equivalent stage executions.
    """

    def test_metadata_semantics_consistency_for_ollama_execution(
        self, tmp_path: Path, sample_brief
    ):
        """Sequential and concurrent executions of an Ollama stage produce

        identical metadata keys, types, and model values.
        """
        # Sequential Run
        seq_art_dir = tmp_path / "seq_artifacts"
        seq_store = ArtifactStore(base_path=seq_art_dir)
        seq_mgr = ArtifactManager(artifact_store=seq_store)

        seq_ollama = OllamaProviderV2(
            base_url="http://localhost:11434", model="llama3.1", stage="story"
        )
        story_resp = create_mock_ollama_response({
            "synopsis": "A brilliant scientist creates conscious AI.",
            "themes": ["ethics", "creation"],
            "acts": 3,
            "beats": ["inciting", "climax", "resolution"],
        })

        with patch.object(seq_ollama.client, "post", return_value=story_resp):
            seq_orch = PipelineOrchestratorV2(
                stages=["story"],
                agent_factory=lambda st: BaseAgentV2(
                    st, provider=seq_ollama, artifact_manager=seq_mgr
                ),
                artifact_manager=seq_mgr,
                state_store=StateStore(base_path=tmp_path / "seq_state"),
            )
            seq_orch.run(sample_brief)

        # Concurrent Run
        conc_art_dir = tmp_path / "conc_artifacts"
        conc_store = ArtifactStore(base_path=conc_art_dir)
        conc_mgr = ArtifactManager(artifact_store=conc_store)

        conc_ollama = OllamaProviderV2(
            base_url="http://localhost:11434", model="llama3.1", stage="story"
        )

        with patch.object(conc_ollama.client, "post", return_value=story_resp):
            conc_orch = ConcurrentPipelineOrchestrator(
                stages=["story"],
                agent_factory=lambda st: BaseAgentV2(
                    st, provider=conc_ollama, artifact_manager=conc_mgr
                ),
                artifact_manager=conc_mgr,
                state_store=StateStore(base_path=tmp_path / "conc_state"),
                max_workers=2,
            )
            conc_orch.run(sample_brief)

        # Compare artifacts from both execution paths
        seq_art = seq_mgr.get_latest_artifact("ANANTA-S01E01", "story")
        conc_art = conc_mgr.get_latest_artifact("ANANTA-S01E01", "story")

        assert seq_art is not None
        assert conc_art is not None

        seq_meta = seq_art["metadata"]
        conc_meta = conc_art["metadata"]

        assert seq_meta["provider_name"] == conc_meta["provider_name"] == "OllamaProvider_story"
        assert seq_meta["provider_type"] == conc_meta["provider_type"] == "ollama"
        assert seq_meta["model_name"] == conc_meta["model_name"] == "llama3.1"
        assert seq_meta["is_fallback"] == conc_meta["is_fallback"] is False

        # Compare stored ArtifactMetadata in index
        seq_idx_meta = seq_store._index.get("ANANTA-S01E01:story:v1")
        conc_idx_meta = conc_store._index.get("ANANTA-S01E01:story:v1")

        assert seq_idx_meta.provider_type == conc_idx_meta.provider_type == "ollama"
        assert seq_idx_meta.provider_name == conc_idx_meta.provider_name == "OllamaProvider_story"
        assert seq_idx_meta.model_name == conc_idx_meta.model_name == "llama3.1"
        assert seq_idx_meta.is_fallback == conc_idx_meta.is_fallback is False

    def test_metadata_semantics_consistency_for_fallback_execution(
        self, tmp_path: Path, sample_brief
    ):
        """Sequential and concurrent executions of a fallback stage produce

        identical fallback metadata, warnings, and fallback_from values.
        """
        # Sequential Fallback
        seq_art_dir = tmp_path / "seq_fallback_art"
        seq_store = ArtifactStore(base_path=seq_art_dir)
        seq_mgr = ArtifactManager(artifact_store=seq_store)

        seq_fb_provider = MockProviderV2(
            "story", seed=42, is_fallback=True, fallback_from_provider="ollama"
        )
        seq_orch = PipelineOrchestratorV2(
            stages=["story"],
            agent_factory=lambda st: BaseAgentV2(
                st, provider=seq_fb_provider, artifact_manager=seq_mgr
            ),
            artifact_manager=seq_mgr,
            state_store=StateStore(base_path=tmp_path / "seq_fb_state"),
        )
        seq_orch.run(sample_brief)

        # Concurrent Fallback
        conc_art_dir = tmp_path / "conc_fallback_art"
        conc_store = ArtifactStore(base_path=conc_art_dir)
        conc_mgr = ArtifactManager(artifact_store=conc_store)

        conc_fb_provider = MockProviderV2(
            "story", seed=42, is_fallback=True, fallback_from_provider="ollama"
        )
        conc_orch = ConcurrentPipelineOrchestrator(
            stages=["story"],
            agent_factory=lambda st: BaseAgentV2(
                st, provider=conc_fb_provider, artifact_manager=conc_mgr
            ),
            artifact_manager=conc_mgr,
            state_store=StateStore(base_path=tmp_path / "conc_fb_state"),
            max_workers=2,
        )
        conc_orch.run(sample_brief)

        seq_art = seq_mgr.get_latest_artifact("ANANTA-S01E01", "story")
        conc_art = conc_mgr.get_latest_artifact("ANANTA-S01E01", "story")

        assert seq_art["metadata"]["is_fallback"] == conc_art["metadata"]["is_fallback"] is True
        assert (
            seq_art["metadata"]["fallback_from"]
            == conc_art["metadata"]["fallback_from"]
            == "ollama"
        )
        assert (
            seq_art["metadata"]["provider_type"]
            == conc_art["metadata"]["provider_type"]
            == "mock"
        )

        # Compare warning messages
        assert len(seq_art.get("warnings", [])) == len(conc_art.get("warnings", []))
        assert seq_art["warnings"] == conc_art["warnings"]
