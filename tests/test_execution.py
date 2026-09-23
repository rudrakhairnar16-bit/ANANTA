import json

import pytest

from pipeline.episode_ids import InvalidEpisodeIdError, validate_episode_id
from pipeline.execution import (
    EpisodeId,
    ExecutionId,
    InvalidAttemptNumberError,
    InvalidExecutionIdError,
    InvalidIdentifierError,
    PipelineId,
    StageAttemptId,
    StageId,
    StageInstance,
    new_execution_id,
)
from pipeline.state import InvalidStateTransitionError, StageStatus


def test_pipeline_id_roundtrip():
    pid = PipelineId("v2-default")
    assert pid.name == "v2-default"
    assert str(pid) == "v2-default"
    assert pid.to_dict() == {"pipeline_id": "v2-default"}
    assert PipelineId.from_dict({"pipeline_id": "v2-default"}) == pid


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "a b", "a/b", "a\\b", "a:b", "a" * 101, "../x", ".hidden"],
)
def test_pipeline_id_rejects_invalid(name):
    with pytest.raises(InvalidIdentifierError):
        PipelineId(name)


def test_pipeline_id_rejects_non_string():
    with pytest.raises(InvalidIdentifierError):
        PipelineId(123)


def test_stage_id_roundtrip():
    sid = StageId("screenplay")
    assert sid.value == "screenplay"
    assert str(sid) == "screenplay"
    assert sid.to_dict() == {"stage_id": "screenplay"}
    assert StageId.from_dict({"stage_id": "screenplay"}) == sid


@pytest.mark.parametrize("value", ["", "..", "a b", "a/b", "a" * 101, ".x"])
def test_stage_id_rejects_invalid(value):
    with pytest.raises(InvalidIdentifierError):
        StageId(value)


def test_episode_id_wrapper_reuses_m1_boundary():
    assert EpisodeId("ANANTA-S01E01").value == "ANANTA-S01E01"
    with pytest.raises(InvalidEpisodeIdError):
        EpisodeId("../evil")
    with pytest.raises(InvalidEpisodeIdError):
        EpisodeId("")
    assert validate_episode_id(EpisodeId("TEST").value) == "TEST"


def test_execution_id_requires_full_32_char_hex():
    full = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    assert ExecutionId(full).value == full
    with pytest.raises(InvalidExecutionIdError):
        ExecutionId("2c4c6e2a")
    with pytest.raises(InvalidExecutionIdError):
        ExecutionId("short")
    with pytest.raises(InvalidExecutionIdError):
        ExecutionId("A1B2C3D4E5F60718293A4B5C6D7E8F90")
    with pytest.raises(InvalidExecutionIdError):
        ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f9")


def test_execution_id_roundtrip():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    assert eid.to_dict() == {"execution_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90"}
    assert ExecutionId.from_dict(
        {"execution_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90"}
    ) == eid


def test_new_execution_id_unique_full_length_lowercase():
    first = new_execution_id()
    second = new_execution_id()
    assert first != second
    assert len(first.value) == 32
    assert len(second.value) == 32
    assert first.value == first.value.lower()


def test_stage_attempt_id_roundtrip_and_validation():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    aid = StageAttemptId(execution_id=eid, stage=StageId("story"), attempt_number=1)
    assert aid.attempt_number == 1
    assert aid.to_dict() == {
        "execution_id": eid.value,
        "stage": "story",
        "attempt_number": 1,
    }
    assert StageAttemptId.from_dict(aid.to_dict()) == aid
    with pytest.raises(InvalidAttemptNumberError):
        StageAttemptId(execution_id=eid, stage=StageId("story"), attempt_number=0)
    with pytest.raises(InvalidAttemptNumberError):
        StageAttemptId(execution_id=eid, stage=StageId("story"), attempt_number=-1)


def test_stage_instance_creation_and_attempt_id():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    instance = StageInstance(
        stage=StageId("bgm"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
        dependencies=("music", "screenplay"),
        attempt_number=2,
        status=StageStatus.RUNNING,
        started_at="2024-01-01T00:00:00+00:00",
        timeout_seconds=120.0,
    )
    assert instance.stage.value == "bgm"
    assert instance.episode_id.value == "ANANTA-S01E01"
    assert instance.execution_id == eid
    assert instance.dependencies == ("music", "screenplay")
    assert instance.attempt_number == 2
    assert instance.status == StageStatus.RUNNING
    assert instance.attempt_id == StageAttemptId(eid, StageId("bgm"), 2)


def test_stage_instance_dependencies_normalized_deterministically():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    staged = StageInstance(
        stage=StageId("qa"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
        dependencies=["bgm", "adobe_export", "sfx", "lipsync"],
    )
    scrambled = StageInstance(
        stage=StageId("qa"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
        dependencies={"lipsync", "sfx", "adobe_export", "bgm"},
    )
    expected = ("adobe_export", "bgm", "lipsync", "sfx")
    assert staged.dependencies == expected
    assert scrambled.dependencies == expected
    assert json.dumps(staged.to_dict(), sort_keys=True) == json.dumps(
        scrambled.to_dict(), sort_keys=True
    )


def test_stage_instance_serde_roundtrip():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    instance = StageInstance(
        stage=StageId("screenplay"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
        dependencies=("story",),
        attempt_number=1,
        status=StageStatus.QUEUED,
    )
    data = instance.to_dict()
    assert list(data.keys()) == [
        "stage",
        "episode_id",
        "execution_id",
        "dependencies",
        "attempt_number",
        "status",
        "started_at",
        "completed_at",
        "error",
        "timeout_seconds",
    ]
    restored = StageInstance.from_dict(json.loads(json.dumps(data)))
    assert restored == instance


def test_stage_instance_from_dict_parses_new_status_string():
    data = {
        "stage": "story",
        "episode_id": "ANANTA-S01E01",
        "execution_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "dependencies": [],
        "attempt_number": 1,
        "status": "queued",
    }
    instance = StageInstance.from_dict(data)
    assert instance.status == StageStatus.QUEUED


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("stage", "a/b", InvalidIdentifierError),
        ("episode_id", "../evil", InvalidEpisodeIdError),
        ("execution_id", "abcd1234", InvalidExecutionIdError),
        ("attempt_number", 0, InvalidAttemptNumberError),
        ("status", "bogus", ValueError),
        ("dependencies", ["bad/stage"], InvalidIdentifierError),
    ],
)
def test_stage_instance_from_dict_validates(field, value, error):
    base = {
        "stage": "story",
        "episode_id": "ANANTA-S01E01",
        "execution_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "dependencies": [],
        "attempt_number": 1,
        "status": "pending",
    }
    base[field] = value
    with pytest.raises(error):
        StageInstance.from_dict(base)


def test_worker_returns_result_without_mutating_scheduler_state():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    original = StageInstance(
        stage=StageId("story"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
    )
    running = original.with_status(StageStatus.QUEUED).with_status(StageStatus.RUNNING)
    completed = running.with_status(StageStatus.COMPLETED)

    assert original.status == StageStatus.PENDING
    assert running.status == StageStatus.RUNNING
    assert completed.status == StageStatus.COMPLETED
    assert original.to_dict() != completed.to_dict()


def test_stage_instance_rejects_invalid_transition():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    instance = StageInstance(
        stage=StageId("story"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
        status=StageStatus.QUEUED,
    )
    with pytest.raises(InvalidStateTransitionError):
        instance.with_status(StageStatus.COMPLETED)


def test_stage_instance_immutable_value_semantics():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    instance = StageInstance(
        stage=StageId("story"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
    )
    with pytest.raises(AttributeError):
        instance.attempt_number = 2


def test_serialization_contains_no_python_object_representations():
    eid = ExecutionId("a1b2c3d4e5f60718293a4b5c6d7e8f90")
    instance = StageInstance(
        stage=StageId("story"),
        episode_id=EpisodeId("ANANTA-S01E01"),
        execution_id=eid,
    )
    encoded = json.dumps(instance.to_dict())
    assert "<" not in encoded
    assert "object at" not in encoded


def test_v2_persisted_state_with_original_statuses_still_parses(tmp_path):
    state_dict = {
        "episode_id": "ANANTA-S01E01",
        "title": "Test",
        "status": "running",
        "created_at": "2024-01-01T00:00:00+00:00",
        "updated_at": "2024-01-01T00:00:00+00:00",
        "completed_at": None,
        "stages": {
            "story": {
                "stage": "story",
                "status": "completed",
                "started_at": None,
                "completed_at": "2024-01-01T00:01:00+00:00",
                "error": None,
                "retry_count": 0,
                "output_path": "/path",
                "metrics": {},
            },
            "screenplay": {
                "stage": "screenplay",
                "status": "queued",
                "error": None,
                "retry_count": 0,
                "metrics": {},
            },
        },
        "current_stage": "screenplay",
        "total_stages": 2,
        "completed_stages": 1,
        "failed_stages": 0,
        "metadata": {},
    }
    from pipeline.state import PipelineState

    state = PipelineState.from_dict(state_dict)
    assert state.get_stage("story").status == StageStatus.COMPLETED
    assert state.get_stage("screenplay").status == StageStatus.QUEUED
