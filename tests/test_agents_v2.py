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


def test_validate_inputs_top_level():
    agent = get_agent_v2("character")
    inputs = {"episode_id": "TEST", "characters": [{"id": "c1"}]}
    assert agent.validate_inputs(inputs) is True


def test_validate_inputs_nested_outputs():
    agent = get_agent_v2("screenplay")
    inputs = {
        "episode_id": "TEST",
        "outputs": {"synopsis": "test synopsis", "themes": ["theme1"]},
    }
    assert agent.validate_inputs(inputs) is True


def test_validate_inputs_missing_required():
    agent = get_agent_v2("screenplay")
    inputs = {"episode_id": "TEST", "outputs": {"other_field": "value"}}
    assert agent.validate_inputs(inputs) is False


def test_validate_inputs_qa_accepts_all():
    agent = get_agent_v2("qa")
    inputs = {"episode_id": "TEST", "outputs": {"some": "data"}}
    assert agent.validate_inputs(inputs) is True


def test_validate_inputs_empty_outputs_dict():
    agent = get_agent_v2("screenplay")
    inputs = {"episode_id": "TEST", "outputs": {}}
    assert agent.validate_inputs(inputs) is False


def test_validate_inputs_outputs_not_dict():
    agent = get_agent_v2("screenplay")
    inputs = {"episode_id": "TEST", "outputs": "not a dict"}
    assert agent.validate_inputs(inputs) is False


def test_v2_full_pipeline_19_stages(tmp_path):
    import json
    import pathlib

    from pipeline.orchestrator_v2 import PipelineOrchestratorV2

    brief_path = pathlib.Path("shared/episode_01.json")
    orchestrator = PipelineOrchestratorV2()
    result = orchestrator.run(str(brief_path))

    assert result is not None
    summary_path = pathlib.Path("outputs/ANANTA-S01E01_pipeline_summary.json")
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["stages_completed"] == 19
    assert summary["stages_failed"] == 0
    assert summary["status"] == "completed"


def test_v2_agent_output_accumulates_outputs():
    provider = MockProviderV2("story")
    agent = StoryAgentV2(provider=provider)
    brief = {"episode_id": "TEST", "title": "Test Episode"}
    result = agent.run(brief)

    assert "outputs" in result
    assert "synopsis" in result["outputs"]

    screen_agent = get_agent_v2("screenplay")
    result2 = screen_agent.run(result)

    assert "outputs" in result2
    assert "synopsis" in result2["outputs"]
    assert "scenes" in result2["outputs"]
