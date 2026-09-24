import json

import pytest

from pipeline.execution import new_execution_id
from pipeline.state import (
    PipelineState,
    StateStore,
    create_initial_state,
)


def test_pipeline_state_has_schema_version_and_execution_id():
    """M8 invariant: PipelineState must track schema_version and execution_id."""
    exec_id = new_execution_id()
    state = create_initial_state("ANANTA-S01E01", "Test Episode", ["story", "screenplay"])

    assert hasattr(state, "schema_version"), "PipelineState must define schema_version"
    assert (
        state.schema_version == "2.0"
    ), f"Expected schema_version '2.0', got {state.schema_version}"

    assert hasattr(state, "execution_id"), "PipelineState must define execution_id"
    state.execution_id = str(exec_id)

    data = state.to_dict()
    assert "schema_version" in data, "schema_version missing from to_dict()"
    assert data["schema_version"] == "2.0"
    assert "execution_id" in data, "execution_id missing from to_dict()"
    assert data["execution_id"] == str(exec_id)

    restored = PipelineState.from_dict(data)
    assert restored.schema_version == "2.0"
    assert restored.execution_id == str(exec_id)


def test_state_store_load_validates_schema_version(tmp_path):
    """M8 invariant: StateStore.load() must reject future schema versions with structured error."""
    store = StateStore(base_path=tmp_path)
    state_file = tmp_path / "TEST-E01_state.json"
    raw_payload = {
        "schema_version": "99.0",
        "episode_id": "TEST-E01",
        "title": "Future State",
        "status": "pending",
        "stages": {},
    }
    state_file.write_text(json.dumps(raw_payload), encoding="utf-8")

    # M8 contract: must raise a structured StateVersionError or StatePersistenceError
    with pytest.raises(Exception) as exc_info:
        store.load("TEST-E01")

    err = exc_info.value
    err_type_name = type(err).__name__
    assert (
        "Version" in err_type_name or "Persistence" in err_type_name or "Schema" in err_type_name
    ), f"Expected structured version error, got {type(err)}: {err}"
    assert "99.0" in str(err) or "version" in str(err).lower()


def test_state_store_load_malformed_json_raises_structured_error(tmp_path):
    """M8 invariant: Malformed state JSON in StateStore must raise StateCorruptionError."""
    store = StateStore(base_path=tmp_path)
    state_file = tmp_path / "TEST-E01_state.json"
    state_file.write_text('{"episode_id": "TEST-E01", "truncated": ', encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        store.load("TEST-E01")

    err = exc_info.value
    err_type_name = type(err).__name__
    assert (
        "Corruption" in err_type_name or "Persistence" in err_type_name
    ), f"Expected structured StateCorruptionError or StatePersistenceError, got {type(err)}: {err}"


def test_state_store_load_missing_required_fields_raises_structured_error(tmp_path):
    """M8 invariant: Missing required schema fields must raise structured StateCorruptionError."""
    store = StateStore(base_path=tmp_path)
    state_file = tmp_path / "TEST-E01_state.json"
    state_file.write_text(json.dumps({"title": "No episode id"}), encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        store.load("TEST-E01")

    err = exc_info.value
    assert not isinstance(err, KeyError), "Raw KeyError must not leak from StateStore.load()"
    err_type_name = type(err).__name__
    assert (
        "Corruption" in err_type_name
        or "Persistence" in err_type_name
        or "Validation" in err_type_name
    ), f"Expected structured StateCorruptionError, got {type(err)}: {err}"


def test_state_store_recovers_from_backup_when_primary_corrupted(tmp_path):
    """M8 invariant: If state file is corrupted, StateStore.load() falls back to valid .bak file."""
    store = StateStore(base_path=tmp_path)
    state_file = tmp_path / "TEST-E01_state.json"
    backup_file = tmp_path / "TEST-E01_state.json.bak"

    # Write corrupted primary file
    state_file.write_text("{corrupt json payload", encoding="utf-8")

    # Write valid backup file
    valid_state = create_initial_state("TEST-E01", "Recovered From Backup", ["story"])
    if hasattr(valid_state, "schema_version"):
        valid_state.schema_version = "2.0"
    backup_file.write_text(json.dumps(valid_state.to_dict(), indent=2), encoding="utf-8")

    # Should recover from backup instead of failing
    recovered = store.load("TEST-E01")
    assert recovered is not None
    assert recovered.title == "Recovered From Backup"
