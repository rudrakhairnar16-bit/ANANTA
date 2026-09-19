import pytest

from config import reload_settings
from providers.base import MockProvider
from providers.ollama import OllamaProvider
from providers.registry import create_ollama_provider, get_mock_provider, get_provider_for_stage


def test_mock_provider_creates_valid_output(mock_env):
    reload_settings()
    provider = MockProvider("story")
    inputs = {"episode_id": "TEST-E01", "title": "Test"}
    result = provider.generate_sync(inputs)
    assert result["episode_id"] == "TEST-E01"
    assert result["stage"] == "story"
    assert "outputs" in result
    assert "synopsis" in result["outputs"]
    assert "themes" in result["outputs"]
    assert "acts" in result["outputs"]
    assert "beats" in result["outputs"]
    assert result["approval_status"] == "pending"
    assert "Mock output for story stage" in result["assumptions"]


def test_mock_provider_all_stages(mock_env):
    reload_settings()
    stages = [
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
    ]
    for stage in stages:
        provider = MockProvider(stage)
        result = provider.generate_sync({"episode_id": "TEST", "title": "Test"})
        assert result["stage"] == stage
        assert "outputs" in result


def test_get_mock_provider(mock_env):
    reload_settings()
    provider = get_mock_provider("story")
    assert isinstance(provider, MockProvider)
    assert provider.stage == "story"


def test_get_provider_for_stage_mock_mode(mock_env):
    reload_settings()
    provider = get_provider_for_stage("story", use_ollama=False)
    assert isinstance(provider, MockProvider)
    assert provider.stage == "story"


def test_get_provider_for_stage_ollama_mode(ollama_env):
    reload_settings()
    provider = get_provider_for_stage("story", use_ollama=True)
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama3.1"
    provider.close()


def test_get_provider_for_stage_non_story_returns_mock(ollama_env):
    reload_settings()
    provider = get_provider_for_stage("screenplay", use_ollama=True)
    assert isinstance(provider, MockProvider)
    assert provider.stage == "screenplay"


def test_create_ollama_provider_requires_config(mock_env):
    reload_settings()
    with pytest.raises(ValueError, match="Ollama not configured"):
        create_ollama_provider()


def test_ollama_provider_initialization(ollama_env):
    reload_settings()
    provider = create_ollama_provider()
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama3.1"
    assert provider.base_url == "http://localhost:11434"
    assert provider.timeout == 120.0
    assert provider.max_retries == 3
    assert provider.temperature == 0.7
    provider.close()
