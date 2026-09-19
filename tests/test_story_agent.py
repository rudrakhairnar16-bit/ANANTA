import pytest

from agents.base_agent import StoryAgent, get_agent
from config import reload_settings


def test_story_agent_exists_in_registry(mock_env):
    reload_settings()
    agent = get_agent("story")
    assert isinstance(agent, StoryAgent)


def test_story_agent_validates_inputs(mock_env, sample_brief):
    reload_settings()
    agent = StoryAgent()
    assert agent.validate_inputs(sample_brief) is True
    assert agent.validate_inputs({"episode_id": "TEST"}) is False
    assert agent.validate_inputs({"title": "Test"}) is False
    assert agent.validate_inputs({}) is False


def test_story_agent_mock_mode_output_contract(mock_env, sample_brief):
    reload_settings()
    agent = StoryAgent()
    result = agent.run(sample_brief)
    required_fields = [
        "episode_id",
        "stage",
        "version",
        "generated_at",
        "inputs",
        "outputs",
        "assumptions",
        "warnings",
        "approval_status",
    ]
    for field in required_fields:
        assert field in result, f"Missing required field: {field}"
    assert result["episode_id"] == "ANANTA-S01E01"
    assert result["stage"] == "story"
    assert result["version"] == 2  # brief has no version, defaults to 1, then +1
    assert result["approval_status"] == "pending"
    assert isinstance(result["outputs"], dict)
    assert "synopsis" in result["outputs"]
    assert "themes" in result["outputs"]
    assert "acts" in result["outputs"]
    assert "beats" in result["outputs"]


def test_story_agent_output_types(mock_env, sample_brief):
    reload_settings()
    agent = StoryAgent()
    result = agent.run(sample_brief)
    assert isinstance(result["outputs"]["synopsis"], str)
    assert isinstance(result["outputs"]["themes"], list)
    assert isinstance(result["outputs"]["acts"], int)
    assert isinstance(result["outputs"]["beats"], list)
    assert len(result["outputs"]["synopsis"]) > 0


def test_story_agent_preserves_original_data(mock_env, sample_brief):
    reload_settings()
    agent = StoryAgent()
    result = agent.run(sample_brief)
    assert "characters" in result
    assert "locations" in result
    assert "scenes" in result
    assert len(result["characters"]) == 3
    assert len(result["locations"]) == 3
    assert len(result["scenes"]) == 5


def test_story_agent_ollama_mode_works(ollama_env, sample_brief):
    reload_settings()
    agent = StoryAgent()
    # Should not raise, but will fail at runtime without actual Ollama server
    assert agent.provider is not None
    assert hasattr(agent.provider, "generate_sync")


def test_story_agent_invalid_inputs_raises_error(mock_env):
    reload_settings()
    agent = StoryAgent()
    with pytest.raises(ValueError, match="Invalid inputs for story agent"):
        agent.run({"episode_id": "TEST"})


def test_story_agent_mock_mode_warnings(mock_env, sample_brief):
    reload_settings()
    agent = StoryAgent()
    result = agent.run(sample_brief)
    assert len(result["warnings"]) > 0
    assert "mock provider" in result["warnings"][0].lower()
