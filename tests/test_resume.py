import json
import pathlib

import pytest

import config_v2
import pipeline.orchestrator_v2 as orchestrator_module
from pipeline.artifacts import ArtifactManager, ArtifactStore
from pipeline.dependencies import get_default_dependency_graph
from pipeline.episode_ids import InvalidEpisodeIdError
from pipeline.orchestrator_v2 import DEFAULT_STAGES, PipelineOrchestratorV2
from pipeline.state import StateStore, create_initial_state

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _build_orchestrator(tmp_path, stages=None, suffix="service"):
    artifact_store = ArtifactStore(base_path=tmp_path / f"{suffix}_artifacts")
    state_store = StateStore(base_path=tmp_path / f"{suffix}_state")
    return (
        PipelineOrchestratorV2(
            stages=stages,
            artifact_manager=ArtifactManager(artifact_store=artifact_store),
            state_store=state_store,
        ),
        artifact_store,
        state_store,
    )


def test_resume_hydrates_completed_outputs_without_reexecution(
    tmp_path,
    mock_env,
    sample_brief,
    monkeypatch,
):
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    interrupted, artifact_store, state_store = _build_orchestrator(
        tmp_path, stages=["story", "screenplay"], suffix="interrupted"
    )
    interrupted.run(str(brief_path))

    calls = []
    real_get_agent = orchestrator_module.get_agent_v2

    def spy(stage, **kwargs):
        calls.append(stage)
        return real_get_agent(stage, **kwargs)

    monkeypatch.setattr(orchestrator_module, "get_agent_v2", spy)

    resumed = PipelineOrchestratorV2(
        stages=DEFAULT_STAGES,
        artifact_manager=ArtifactManager(artifact_store=artifact_store),
        state_store=state_store,
    )
    result = resumed.run(str(brief_path), resume=True)

    assert "story" not in calls
    assert "screenplay" not in calls
    assert len(calls) == len(DEFAULT_STAGES) - 2

    expected_order = [
        stage
        for stage in get_default_dependency_graph().get_execution_order()
        if stage in DEFAULT_STAGES and stage not in ("story", "screenplay")
    ]
    assert calls == expected_order

    assert "outputs" in result
    assert result["outputs"].get("synopsis")
    assert result["outputs"].get("scenes")

    story_versions = [
        meta.version
        for meta in artifact_store.list_artifacts(episode_id)
        if meta.stage == "story"
    ]
    assert story_versions == [1]

    restored = state_store.load(episode_id)
    assert restored is not None
    assert restored.total_stages == 19
    assert restored.is_completed() is True


def test_resume_result_matches_uninterrupted(tmp_path, mock_env, sample_brief):
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    uninterrupted, _, _ = _build_orchestrator(tmp_path, suffix="uninterrupted")
    full_result = uninterrupted.run(str(brief_path))

    interrupted, resumed_artifact_store, resumed_state = _build_orchestrator(
        tmp_path,
        stages=["story", "screenplay", "scene_plan", "character", "world"],
        suffix="resumed",
    )
    interrupted.run(str(brief_path))

    resumed = PipelineOrchestratorV2(
        artifact_manager=ArtifactManager(artifact_store=resumed_artifact_store),
        state_store=resumed_state,
    )
    resume_result = resumed.run(str(brief_path), resume=True)

    assert resume_result["outputs"] == full_result["outputs"]
    assert resume_result.get("title") == full_result.get("title")
    assert resume_result.get("episode_id") == episode_id


def test_resume_missing_artifact_raises(tmp_path, mock_env, sample_brief):
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]

    state = create_initial_state(episode_id, sample_brief["title"], DEFAULT_STAGES)
    story_state = state.get_stage("story")
    story_state.mark_completed(output_path="missing.json")
    state.update_stage(story_state)
    state_store = StateStore(base_path=tmp_path / "state")
    state_store.save(state)

    orchestrator = PipelineOrchestratorV2(
        artifact_manager=ArtifactManager(ArtifactStore(base_path=tmp_path / "artifacts")),
        state_store=state_store,
    )
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    with pytest.raises(RuntimeError, match="no stored artifact"):
        orchestrator.run(str(brief_path), resume=True)

    restored = state_store.load(episode_id)
    assert restored is not None
    assert restored.status == "failed"


def test_run_rejects_traversal_episode_id(tmp_path, sample_brief):
    brief = dict(sample_brief)
    brief["episode_id"] = "../evil"
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(brief), encoding="utf-8")

    orchestrator, _, _ = _build_orchestrator(tmp_path, suffix="guard")
    with pytest.raises(InvalidEpisodeIdError):
        orchestrator.run(str(brief_path))

    assert not (REPO_ROOT / "outputs" / "evil_pipeline_summary.json").exists()
    assert not (REPO_ROOT / "evil_pipeline_summary.json").exists()
