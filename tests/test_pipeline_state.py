from pipeline.state import (
    CheckpointManager,
    PipelineState,
    StageState,
    StageStatus,
    StateStore,
    create_initial_state,
)


def test_stage_state_creation():
    state = StageState(stage="story")
    assert state.stage == "story"
    assert state.status == StageStatus.PENDING
    assert state.retry_count == 0


def test_stage_state_mark_running():
    state = StageState(stage="story")
    state.mark_running()
    assert state.status == StageStatus.RUNNING
    assert state.started_at is not None


def test_stage_state_mark_completed():
    state = StageState(stage="story")
    state.mark_completed(output_path="/path/to/output", metrics={"latency": 100})
    assert state.status == StageStatus.COMPLETED
    assert state.completed_at is not None
    assert state.output_path == "/path/to/output"
    assert state.metrics == {"latency": 100}


def test_stage_state_mark_failed():
    state = StageState(stage="story")
    state.mark_failed("Test error")
    assert state.status == StageStatus.FAILED
    assert state.completed_at is not None
    assert state.error == "Test error"


def test_stage_state_mark_skipped():
    state = StageState(stage="story")
    state.mark_skipped()
    assert state.status == StageStatus.SKIPPED
    assert state.completed_at is not None


def test_stage_state_mark_retrying():
    state = StageState(stage="story")
    state.mark_retrying()
    assert state.status == StageStatus.RETRYING
    assert state.retry_count == 1


def test_stage_state_to_dict():
    state = StageState(stage="story")
    state.mark_completed()
    d = state.to_dict()
    assert d["stage"] == "story"
    assert d["status"] == "completed"
    assert d["completed_at"] is not None


def test_stage_state_from_dict():
    data = {
        "stage": "story",
        "status": "completed",
        "started_at": "2024-01-01T00:00:00+00:00",
        "completed_at": "2024-01-01T00:01:00+00:00",
        "error": None,
        "retry_count": 0,
        "output_path": "/path",
        "metrics": {"latency": 100},
    }
    state = StageState.from_dict(data)
    assert state.stage == "story"
    assert state.status == StageStatus.COMPLETED
    assert state.retry_count == 0


def test_pipeline_state_creation():
    state = PipelineState(episode_id="TEST-E01", title="Test", total_stages=19)
    assert state.episode_id == "TEST-E01"
    assert state.title == "Test"
    assert state.total_stages == 19
    assert state.status == "pending"


def test_pipeline_state_add_stage():
    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    state.add_stage("screenplay")
    assert state.total_stages == 2
    assert "story" in state.stages
    assert "screenplay" in state.stages


def test_pipeline_state_get_stage():
    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    stage_state = state.get_stage("story")
    assert stage_state is not None
    assert stage_state.stage == "story"


def test_pipeline_state_update_stage():
    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    stage_state = state.get_stage("story")
    stage_state.mark_completed()
    state.update_stage(stage_state)
    assert state.completed_stages == 1


def test_pipeline_state_is_completed():
    state = PipelineState(episode_id="TEST-E01", title="Test", total_stages=2)
    state.add_stage("story")
    state.add_stage("screenplay")
    state.get_stage("story").mark_completed()
    state.get_stage("screenplay").mark_completed()
    state.update_stage(state.get_stage("story"))
    state.update_stage(state.get_stage("screenplay"))
    assert state.is_completed() is True


def test_pipeline_state_is_failed():
    state = PipelineState(episode_id="TEST-E01", title="Test", total_stages=2)
    state.add_stage("story")
    state.add_stage("screenplay")
    state.get_stage("story").mark_failed("Error")
    state.update_stage(state.get_stage("story"))
    assert state.is_failed() is True


def test_pipeline_state_get_next_pending_stage():
    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    state.add_stage("screenplay")
    state.add_stage("character")

    next_stage = state.get_next_pending_stage(["story", "screenplay", "character"])
    assert next_stage == "story"

    state.get_stage("story").mark_completed()
    state.update_stage(state.get_stage("story"))
    next_stage = state.get_next_pending_stage(["story", "screenplay", "character"])
    assert next_stage == "screenplay"


def test_pipeline_state_to_dict():
    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    state.get_stage("story").mark_completed()
    state.update_stage(state.get_stage("story"))
    d = state.to_dict()
    assert d["episode_id"] == "TEST-E01"
    assert d["title"] == "Test"
    assert d["completed_stages"] == 1


def test_pipeline_state_from_dict():
    data = {
        "episode_id": "TEST-E01",
        "title": "Test",
        "status": "running",
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "completed_at": None,
        "stages": {
            "story": {
                "stage": "story",
                "status": "completed",
                "started_at": "2024-01-01T00:00:00+00:00",
                "completed_at": "2024-01-01T00:01:00+00:00",
                "error": None,
                "retry_count": 0,
                "output_path": "/path",
                "metrics": {},
            }
        },
        "current_stage": "story",
        "total_stages": 19,
        "completed_stages": 1,
        "failed_stages": 0,
        "metadata": {},
    }
    state = PipelineState.from_dict(data)
    assert state.episode_id == "TEST-E01"
    assert state.title == "Test"
    assert state.completed_stages == 1


def test_state_store_save_load(tmp_path):
    store = StateStore(base_path=tmp_path)
    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    state.get_stage("story").mark_completed()
    state.update_stage(state.get_stage("story"))

    store.save(state)
    loaded = store.load("TEST-E01")

    assert loaded is not None
    assert loaded.episode_id == "TEST-E01"
    assert loaded.completed_stages == 1


def test_state_store_load_nonexistent(tmp_path):
    store = StateStore(base_path=tmp_path)
    loaded = store.load("NONEXISTENT")
    assert loaded is None


def test_state_store_delete(tmp_path):
    store = StateStore(base_path=tmp_path)
    state = PipelineState(episode_id="TEST-E01", title="Test")
    store.save(state)
    store.delete("TEST-E01")
    loaded = store.load("TEST-E01")
    assert loaded is None


def test_checkpoint_manager(tmp_path):
    state_store = StateStore(base_path=tmp_path)
    manager = CheckpointManager(state_store)

    state = PipelineState(episode_id="TEST-E01", title="Test")
    state.add_stage("story")
    state.get_stage("story").mark_completed()
    state.update_stage(state.get_stage("story"))

    manager.checkpoint(state)
    restored = manager.restore("TEST-E01")

    assert restored is not None
    assert restored.episode_id == "TEST-E01"
    assert restored.completed_stages == 1


def test_checkpoint_manager_can_resume(tmp_path):
    state_store = StateStore(base_path=tmp_path)
    manager = CheckpointManager(state_store)

    state = PipelineState(episode_id="TEST-E01", title="Test", total_stages=2)
    state.add_stage("story")
    state.add_stage("screenplay")
    state.get_stage("story").mark_completed()
    state.update_stage(state.get_stage("story"))

    manager.checkpoint(state)
    assert manager.can_resume("TEST-E01") is True

    state.get_stage("screenplay").mark_completed()
    state.update_stage(state.get_stage("screenplay"))
    manager.checkpoint(state)
    assert manager.can_resume("TEST-E01") is False


def test_checkpoint_manager_get_resume_stage(tmp_path):
    state_store = StateStore(base_path=tmp_path)
    manager = CheckpointManager(state_store)

    state = PipelineState(episode_id="TEST-E01", title="Test", total_stages=3)
    state.add_stage("story")
    state.add_stage("screenplay")
    state.add_stage("character")
    state.get_stage("story").mark_completed()
    state.update_stage(state.get_stage("story"))

    manager.checkpoint(state)
    resume_stage = manager.get_resume_stage("TEST-E01", ["story", "screenplay", "character"])
    assert resume_stage == "screenplay"


def test_create_initial_state():
    state = create_initial_state("TEST-E01", "Test Episode", ["story", "screenplay"])
    assert state.episode_id == "TEST-E01"
    assert state.title == "Test Episode"
    assert state.total_stages == 2
    assert "story" in state.stages
    assert "screenplay" in state.stages
