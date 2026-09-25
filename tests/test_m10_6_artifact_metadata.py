import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agents.base_agent_v2 import BaseAgentV2, StoryAgentV2
from pipeline.artifacts import ArtifactManager, ArtifactStore
from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
from providers.base_v2 import (
    MockProviderV2,
    OllamaProviderV2,
    ProviderConfig,
)
from providers.registry_v2 import (
    ModelRouter,
    ProviderRegistry,
    ProviderRegistryConfig,
    StageProviderConfig,
)


@pytest.fixture
def temp_artifact_dir(tmp_path):
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    yield art_dir
    if art_dir.exists():
        shutil.rmtree(art_dir)


class TestM106ArtifactMetadataAndSafety:
    """
    M10.6 Task 3 Test Suite:
    Artifact Metadata Tracking, Fallback Declarations, and Publication Safety.
    """

    def test_ollama_generated_artifact_metadata(self, temp_artifact_dir, sample_brief):
        """1. Ollama-generated artifacts record provider_type, name, and model."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": json.dumps({
                "synopsis": "Maya develops an AI.",
                "themes": ["ethics", "ai"],
                "acts": 3,
                "beats": ["intro", "middle", "end"],
            })
        }

        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="story",
        )

        with patch.object(provider.client, "post", return_value=mock_resp):
            agent = StoryAgentV2(provider=provider, artifact_manager=manager)
            result = agent.run(sample_brief)

            # Check payload metadata
            assert "metadata" in result
            meta = result["metadata"]
            assert meta["provider_type"] == "ollama"
            assert "OllamaProvider" in meta["provider_name"]
            assert meta["model_name"] == "llama3.1"
            assert meta["is_fallback"] is False

            # Check stored artifact on disk
            latest = manager.get_latest_artifact("ANANTA-S01E01", "story")
            assert latest is not None
            assert latest["metadata"]["provider_type"] == "ollama"
            assert latest["metadata"]["model_name"] == "llama3.1"
            assert latest["metadata"]["is_fallback"] is False

    def test_mock_generated_artifact_metadata(self, temp_artifact_dir, sample_brief):
        """2. Mock-generated artifacts identify provider_type=mock and is_fallback=False."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        provider = MockProviderV2(stage="story", seed=42)
        agent = StoryAgentV2(provider=provider, artifact_manager=manager)
        result = agent.run(sample_brief)

        assert "metadata" in result
        meta = result["metadata"]
        assert meta["provider_type"] == "mock"
        assert meta["provider_name"] == "MockProvider_story"
        assert meta["is_fallback"] is False
        assert meta["model_name"] is None

        # Check stored artifact
        latest = manager.get_latest_artifact("ANANTA-S01E01", "story")
        assert latest is not None
        assert latest["metadata"]["provider_type"] == "mock"
        assert latest["metadata"]["is_fallback"] is False

    def test_fallback_generated_artifact_declares_fallback(self, temp_artifact_dir, sample_brief):
        """3 & 4. Fallback-generated artifacts declare is_fallback, fallback_from, warnings."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        # Provider created through explicit fallback
        fallback_provider = MockProviderV2(
            stage="story",
            seed=42,
            is_fallback=True,
            fallback_from_provider="ollama",
        )
        agent = StoryAgentV2(provider=fallback_provider, artifact_manager=manager)
        result = agent.run(sample_brief)

        # Check metadata declarations
        assert "metadata" in result
        meta = result["metadata"]
        assert meta["is_fallback"] is True
        assert meta["provider_type"] == "mock"
        assert meta["fallback_from"] == "ollama"

        # Check fallback warnings in artifact
        assert "warnings" in result
        assert any("fallback" in str(w).lower() for w in result["warnings"])

        # Check persisted artifact
        latest = manager.get_latest_artifact("ANANTA-S01E01", "story")
        assert latest is not None
        assert latest["metadata"]["is_fallback"] is True
        assert any("fallback" in str(w).lower() for w in latest.get("warnings", []))

    def test_fallback_routing_integration_attaches_fallback_metadata(
        self, temp_artifact_dir, sample_brief
    ):
        """5. ModelRouter fallback routing supplies provider with is_fallback=True to agent."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=True,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        with patch(
            "httpx.Client.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            provider = router.route("story", prefer_ollama=True, allow_fallback=True)
            assert isinstance(provider, MockProviderV2)
            assert provider.is_fallback is True

            agent = BaseAgentV2("story", provider=provider, artifact_manager=manager)
            result = agent.run(sample_brief)

            assert result["metadata"]["is_fallback"] is True
            assert result["metadata"]["provider_type"] == "mock"
            assert any("fallback" in str(w).lower() for w in result["warnings"])

    def test_mock_output_cannot_be_mislabeled_as_ollama(
        self, mock_env, temp_artifact_dir, sample_brief
    ):
        """6. Mock provider cannot generate artifacts with provider_type=ollama."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        mock_provider = MockProviderV2(stage="story")
        agent = BaseAgentV2("story", provider=mock_provider, artifact_manager=manager)
        result = agent.run(sample_brief)

        assert result["metadata"]["provider_type"] != "ollama"
        assert result["metadata"]["provider_type"] == "mock"

    def test_failed_provider_execution_publishes_no_artifact(
        self, temp_artifact_dir, sample_brief
    ):
        """8. Provider failure raises an error and does not write or publish any artifact."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            stage="story",
        )

        # Simulate provider connection failure during generation
        with patch.object(
            provider.client,
            "post",
            side_effect=httpx.ConnectError("Connection refused to Ollama"),
        ):
            agent = StoryAgentV2(provider=provider, artifact_manager=manager)
            with pytest.raises(RuntimeError) as exc_info:
                agent.run(sample_brief)

            assert "failed" in str(exc_info.value).lower()

            # Verify no artifact was stored or published
            assert manager.get_latest_artifact("ANANTA-S01E01", "story") is None
            assert len(store.list_artifacts("ANANTA-S01E01")) == 0

    def test_concurrent_execution_preserves_metadata(
        self, mock_env, temp_artifact_dir, sample_brief
    ):
        """9. Concurrent pipeline execution preserves provider metadata on all stage artifacts."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        manager = ArtifactManager(artifact_store=store)

        orchestrator = ConcurrentPipelineOrchestrator(
            artifact_manager=manager,
            max_workers=2,
        )

        orchestrator.run(sample_brief)

        # Verify produced artifacts contain metadata
        for st in ["story", "character", "screenplay"]:
            art = manager.get_latest_artifact("ANANTA-S01E01", st)
            assert art is not None, f"Missing artifact for {st}"
            assert "metadata" in art, f"Missing metadata for {st}"
            assert "provider_type" in art["metadata"], f"Missing provider_type for {st}"
            assert "provider_name" in art["metadata"], f"Missing provider_name for {st}"
            assert "is_fallback" in art["metadata"], f"Missing is_fallback for {st}"

    def test_artifact_store_records_metadata_in_index(self, temp_artifact_dir):
        """10. ArtifactStore stores provider metadata in ArtifactMetadata and .meta.json."""
        store = ArtifactStore(base_path=temp_artifact_dir)
        data = {
            "episode_id": "TEST-EP01",
            "stage": "story",
            "outputs": {"synopsis": "Test"},
            "metadata": {
                "provider_name": "OllamaProvider_story",
                "provider_type": "ollama",
                "is_fallback": False,
                "model_name": "llama3.1",
            },
        }

        ref = store.store("TEST-EP01", "story", data)
        assert ref is not None

        # Verify ArtifactMetadata object in index
        meta = store._index.get(ref.artifact_id)
        assert meta is not None
        assert meta.provider_name == "OllamaProvider_story"
        assert meta.provider_type == "ollama"
        assert meta.is_fallback is False
        assert meta.model_name == "llama3.1"

        # Verify .meta.json file on disk
        meta_file = Path(temp_artifact_dir) / "TEST-EP01" / "story_v1.meta.json"
        assert meta_file.exists()
        meta_json = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta_json["provider_name"] == "OllamaProvider_story"
        assert meta_json["provider_type"] == "ollama"
        assert meta_json["is_fallback"] is False
        assert meta_json["model_name"] == "llama3.1"
