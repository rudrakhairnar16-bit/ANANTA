from agents.base_agent_v2 import (
    AGENT_REGISTRY_V2,
    BaseAgentV2,
    StoryAgentV2,
    create_agent_v2,
    get_agent_v2,
)
from providers.base_v2 import MockProviderV2


def test_base_agent_v2_creation():
    provider = MockProviderV2("story")
    agent = BaseAgentV2("story", provider=provider)
    assert agent.stage == "story"
    assert agent.provider is not None
    assert agent.artifact_manager is not None
    assert agent.validator is not None
    assert agent.recovery_manager is not None


def test_base_agent_v2_validate_inputs():
    provider = MockProviderV2("story")
    agent = BaseAgentV2("story", provider=provider)
    assert agent.validate_inputs({"episode_id": "TEST", "title": "Test"}) is True
    assert agent.validate_inputs({"episode_id": "TEST"}) is False


def test_base_agent_v2_process_not_implemented():
    provider = MockProviderV2("story")
    agent = BaseAgentV2("story", provider=provider)
    response = agent.process({})
    assert response.success is True
    assert response.data is not None


def test_story_agent_v2_creation():
    agent = StoryAgentV2()
    assert agent.stage == "story"
    assert agent.provider is not None


def test_story_agent_v2_validate_inputs():
    agent = StoryAgentV2()
    assert agent.validate_inputs({"episode_id": "TEST", "title": "Test"}) is True
    assert agent.validate_inputs({"episode_id": "TEST"}) is False
    assert agent.validate_inputs({"title": "Test"}) is False


def test_story_agent_v2_process():
    provider = MockProviderV2("story")
    agent = StoryAgentV2(provider=provider)
    response = agent.process({"episode_id": "TEST", "title": "Test"})
    assert response.success is True
    assert response.data is not None


def test_story_agent_v2_run():
    provider = MockProviderV2("story")
    agent = StoryAgentV2(provider=provider)
    result = agent.run({"episode_id": "TEST", "title": "Test"})

    assert result["episode_id"] == "TEST"
    assert result["stage"] == "story"
    assert result["version"] == 2
    assert "outputs" in result
    assert "synopsis" in result["outputs"]


def test_create_agent_v2():
    agent = create_agent_v2("screenplay")
    assert agent.stage == "screenplay"
    assert agent.provider is not None


def test_get_agent_v2_story():
    agent = get_agent_v2("story")
    assert isinstance(agent, StoryAgentV2)


def test_get_agent_v2_other():
    agent = get_agent_v2("screenplay")
    assert agent.stage == "screenplay"
    assert agent.provider is not None


def test_agent_registry_v2():
    assert "story" in AGENT_REGISTRY_V2
    assert AGENT_REGISTRY_V2["story"] == StoryAgentV2
