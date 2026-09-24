import json

import config_v2
import pipeline.orchestrator_v2 as orchestrator_module
from pipeline.artifacts import ArtifactManager, ArtifactStore
from pipeline.orchestrator_v2 import DEFAULT_STAGES, PipelineOrchestratorV2
from pipeline.state import StateStore, create_initial_state


def _build_orchestrator(tmp_path, stages=None, suffix="idem"):
    artifact_store = ArtifactStore(base_path=tmp_path / f"{suffix}_artifacts")
    state_store = StateStore(base_path=tmp_path / f"{suffix}_state")
    return (
        PipelineOrchestratorV2(
            stages=stages or DEFAULT_STAGES,
            artifact_manager=ArtifactManager(artifact_store=artifact_store),
            state_store=state_store,
        ),
        artifact_store,
        state_store,
    )


def test_execution_identity_continuity_across_resume(tmp_path, mock_env, sample_brief):
    """M8 invariant: A resumed pipeline execution must preserve execution identity lineage."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, artifact_store, state_store = _build_orchestrator(
        tmp_path, stages=["story", "screenplay"]
    )

    # Run first stage
    interrupted, _, _ = _build_orchestrator(tmp_path, stages=["story"], suffix="idem")
    interrupted.run(str(brief_path))

    saved_state = state_store.load(episode_id)
    assert hasattr(saved_state, "execution_id"), "Saved state must record execution_id"
    initial_id = saved_state.execution_id

    # Resume the pipeline
    resumed = PipelineOrchestratorV2(
        stages=["story", "screenplay"],
        artifact_manager=ArtifactManager(artifact_store=artifact_store),
        state_store=state_store,
    )
    _ = resumed.run(str(brief_path), resume=True)

    final_state = state_store.load(episode_id)
    # The resumed execution must retain original execution_id or track lineage
    assert hasattr(final_state, "execution_id")
    has_continuity = (
        final_state.execution_id == initial_id
        or final_state.metadata.get("resumed_from_execution_id") == initial_id
    )
    assert has_continuity, f"Lineage broken: {final_state.execution_id} vs original {initial_id}"


def test_repeated_resume_is_strictly_idempotent(tmp_path, mock_env, sample_brief, monkeypatch):
    """M8 invariant: Repeated resume calls execute 0 stages and produce identical outputs."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, artifact_store, state_store = _build_orchestrator(
        tmp_path, stages=["story", "screenplay"]
    )
    first_result = orchestrator.run(str(brief_path))

    # Spy on get_agent_v2 to ensure no agents are called on resume
    agent_calls = []
    real_get_agent = orchestrator_module.get_agent_v2

    def spy(stage, **kwargs):
        agent_calls.append(stage)
        return real_get_agent(stage, **kwargs)

    monkeypatch.setattr(orchestrator_module, "get_agent_v2", spy)

    # Resume 1
    res1 = orchestrator.run(str(brief_path), resume=True)
    assert agent_calls == []
    assert res1["outputs"] == first_result["outputs"]

    # Resume 2
    res2 = orchestrator.run(str(brief_path), resume=True)
    assert agent_calls == []
    assert res2["outputs"] == first_result["outputs"]

    # Resume 3
    res3 = orchestrator.run(str(brief_path), resume=True)
    assert agent_calls == []
    assert res3["outputs"] == first_result["outputs"]

    # Verify artifact version did not increase from repeated resumes
    story_versions = [
        meta.version
        for meta in artifact_store.list_artifacts(episode_id)
        if meta.stage == "story"
    ]
    assert story_versions == [1], f"Expected exactly [1], got {story_versions}"


def test_crash_window_artifact_committed_state_uncommitted_reconciles(
    tmp_path, mock_env, sample_brief, monkeypatch
):
    """M8 invariant: If stage artifact was committed before state checkpoint, resume reconciles."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, artifact_store, state_store = _build_orchestrator(
        tmp_path, stages=["story", "screenplay"]
    )

    # Simulate crash: 'story' artifact stored, but StateStore still has 'story' as PENDING
    artifact_store.store(
        episode_id, "story", {"outputs": {"synopsis": "Pre-committed story synopsis"}}
    )

    state = create_initial_state(episode_id, sample_brief["title"], ["story", "screenplay"])
    # Leave story as PENDING in state on disk
    state_store.save(state)

    agent_calls = []
    real_get_agent = orchestrator_module.get_agent_v2

    def spy(stage, **kwargs):
        agent_calls.append(stage)
        return real_get_agent(stage, **kwargs)

    monkeypatch.setattr(orchestrator_module, "get_agent_v2", spy)

    # Resuming should detect that story artifact exists and reconcile, only running screenplay
    _ = orchestrator.run(str(brief_path), resume=True)

    assert "story" not in agent_calls, "Stage 'story' should have been reconciled from artifact"
    assert "screenplay" in agent_calls

    final_state = state_store.load(episode_id)
    assert final_state.get_stage("story").status == "completed"
    assert final_state.get_stage("screenplay").status == "completed"
