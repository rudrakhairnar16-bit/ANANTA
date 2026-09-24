import json

import config_v2
from pipeline.artifacts import ArtifactManager, ArtifactStore
from pipeline.orchestrator_v2 import DEFAULT_STAGES, PipelineOrchestratorV2
from pipeline.state import (
    CheckpointManager,
    StageStatus,
    StateStore,
    create_initial_state,
)


def _setup_orchestrator(tmp_path, stages=None):
    artifact_store = ArtifactStore(base_path=tmp_path / "artifacts")
    state_store = StateStore(base_path=tmp_path / "state")
    orchestrator = PipelineOrchestratorV2(
        stages=stages or DEFAULT_STAGES,
        artifact_manager=ArtifactManager(artifact_store=artifact_store),
        state_store=state_store,
    )
    return orchestrator, artifact_store, state_store


def test_crash_recovery_running_stage_recovered_and_not_skipped(tmp_path, mock_env, sample_brief):
    """M8 invariant: A stage left in RUNNING on crash must be recovered, not skipped."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, artifact_store, state_store = _setup_orchestrator(
        tmp_path, stages=["story", "screenplay"]
    )

    # Setup state: story COMPLETED with stored artifact, screenplay crashed while RUNNING
    state = create_initial_state(episode_id, sample_brief["title"], ["story", "screenplay"])
    story_ref = artifact_store.store(
        episode_id, "story", {"outputs": {"synopsis": "Crash recovery story"}}
    )
    story_state = state.get_stage("story")
    story_state.mark_completed(output_path=story_ref.path)
    state.update_stage(story_state)

    screenplay_state = state.get_stage("screenplay")
    screenplay_state.mark_running()
    state.update_stage(screenplay_state)
    state_store.save(state)

    # Recovery check on CheckpointManager
    checkpoint_mgr = CheckpointManager(state_store)
    # Stage left in RUNNING must be detected as recoverable
    resume_stage = checkpoint_mgr.get_resume_stage(episode_id, ["story", "screenplay"])
    assert resume_stage == "screenplay", f"Expected 'screenplay', got {resume_stage}"

    # Execution on resume must execute screenplay and succeed
    result = orchestrator.run(str(brief_path), resume=True)
    has_screenplay = (
        "screenplay" in result.get("completed_stages", [])
        or "scenes" in result.get("outputs", {})
    )
    assert has_screenplay, "Expected screenplay to be completed after crash recovery"

    final_state = state_store.load(episode_id)
    assert final_state.get_stage("screenplay").status == StageStatus.COMPLETED


def test_crash_recovery_retrying_stage_preserves_retry_history(tmp_path, mock_env, sample_brief):
    """M8 invariant: Stage left in RETRYING must preserve retry_count and be recovered."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, _, state_store = _setup_orchestrator(tmp_path, stages=["story"])

    state = create_initial_state(episode_id, sample_brief["title"], ["story"])
    story_state = state.get_stage("story")
    story_state.mark_retrying()
    story_state.mark_retrying()
    assert story_state.retry_count == 2
    story_state.error = "Connection timeout during previous attempt"
    state.update_stage(story_state)
    state_store.save(state)

    # Verify CheckpointManager recognises RETRYING stage as runnable on resume
    checkpoint_mgr = CheckpointManager(state_store)
    assert checkpoint_mgr.can_resume(episode_id) is True
    resume_stage = checkpoint_mgr.get_resume_stage(episode_id, ["story"])
    assert resume_stage == "story"

    # Resuming should succeed and maintain/increment retry history
    _ = orchestrator.run(str(brief_path), resume=True)
    final_state = state_store.load(episode_id)
    assert final_state.get_stage("story").status == StageStatus.COMPLETED
    assert final_state.get_stage("story").retry_count >= 2


def test_failed_stage_resumability_with_explicit_retry(tmp_path, mock_env, sample_brief):
    """M8 invariant: An operator can retry a failed stage via resume(retry_failed=True)."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, artifact_store, state_store = _setup_orchestrator(
        tmp_path, stages=["story", "screenplay"]
    )

    state = create_initial_state(episode_id, sample_brief["title"], ["story", "screenplay"])
    story_ref = artifact_store.store(episode_id, "story", {"outputs": {"synopsis": "Good story"}})
    story_state = state.get_stage("story")
    story_state.mark_completed(output_path=story_ref.path)
    state.update_stage(story_state)

    screenplay_state = state.get_stage("screenplay")
    screenplay_state.mark_failed("Temporary LLM rate limit")
    state.update_stage(screenplay_state)
    state.status = "failed"
    state_store.save(state)

    checkpoint_mgr = CheckpointManager(state_store)
    # Normal can_resume must still report False unless explicit retry is enabled
    assert checkpoint_mgr.can_resume(episode_id, allow_failed=True) is True

    # Resuming with explicit retry_failed=True allows retrying the failed stage
    result = orchestrator.run(str(brief_path), resume=True, retry_failed=True)
    has_screenplay = (
        "screenplay" in result.get("completed_stages", [])
        or "scenes" in result.get("outputs", {})
    )
    assert has_screenplay

    final_state = state_store.load(episode_id)
    assert final_state.get_stage("screenplay").status == StageStatus.COMPLETED
    assert final_state.is_completed() is True


def test_failed_stage_not_resumed_without_explicit_retry_flag(tmp_path, mock_env, sample_brief):
    """M8 invariant: Normal resume without retry_failed=True MUST NOT silently re-execute."""
    config_v2.reload_settings()
    episode_id = sample_brief["episode_id"]
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(sample_brief), encoding="utf-8")

    orchestrator, artifact_store, state_store = _setup_orchestrator(
        tmp_path, stages=["story", "screenplay"]
    )

    state = create_initial_state(episode_id, sample_brief["title"], ["story", "screenplay"])
    story_ref = artifact_store.store(episode_id, "story", {"outputs": {"synopsis": "Good story"}})
    story_state = state.get_stage("story")
    story_state.mark_completed(output_path=story_ref.path)
    state.update_stage(story_state)

    screenplay_state = state.get_stage("screenplay")
    screenplay_state.mark_failed("Permanent validation failure")
    state.update_stage(screenplay_state)
    state.status = "failed"
    state_store.save(state)

    checkpoint_mgr = CheckpointManager(state_store)
    assert checkpoint_mgr.can_resume(episode_id) is False

    # Standard resume without retry_failed must not re-run screenplay
    _ = orchestrator.run(str(brief_path), resume=True)
    final_state = state_store.load(episode_id)
    assert final_state.get_stage("screenplay").status == StageStatus.FAILED
