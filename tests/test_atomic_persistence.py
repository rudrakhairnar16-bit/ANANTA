import json

import pytest

from pipeline import atomic_io
from pipeline.artifacts import ArtifactStore
from pipeline.state import PipelineState, StateStore


def _assert_no_temp_files(root):
    assert list(root.glob("*.tmp")) == []
    assert list(root.glob(".*.tmp")) == []


class _FailingPayloadStore(ArtifactStore):
    def _write_payload(self, path, data):
        raise OSError("simulated payload write failure")


class _FailingMetadataStore(ArtifactStore):
    def _write_metadata(self, path, metadata):
        raise OSError("simulated metadata write failure")


class _FailingIndexStore(ArtifactStore):
    def _save_index(self):
        raise OSError("simulated index write failure")


def _index_text(root) -> str:
    return (root / "index.json").read_text(encoding="utf-8")


# --- STATE ATOMICITY ---


def test_state_save_failure_preserves_existing_file(monkeypatch, tmp_path):
    store = StateStore(base_path=tmp_path)
    state = PipelineState(episode_id="TEST-E01", title="original")
    store.save(state)
    state_file = tmp_path / "TEST-E01_state.json"
    before = state_file.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(atomic_io, "_os_fsync", boom)
    with pytest.raises(OSError):
        store.save(PipelineState(episode_id="TEST-E01", title="draft"))

    assert state_file.read_text(encoding="utf-8") == before
    assert store.load("TEST-E01").title == "original"
    _assert_no_temp_files(tmp_path)


def test_state_save_replacement_failure_preserves_existing(monkeypatch, tmp_path):
    store = StateStore(base_path=tmp_path)
    store.save(PipelineState(episode_id="TEST-E01", title="original"))
    state_file = tmp_path / "TEST-E01_state.json"
    before = state_file.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_io, "_os_replace", boom)
    with pytest.raises(OSError):
        store.save(PipelineState(episode_id="TEST-E01", title="draft"))

    assert state_file.read_text(encoding="utf-8") == before
    assert store.load("TEST-E01").title == "original"
    _assert_no_temp_files(tmp_path)


def test_state_save_success_is_complete_and_deterministic(tmp_path):
    store = StateStore(base_path=tmp_path)
    first = PipelineState(
        episode_id="TEST-E01",
        title="Test",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )
    second = PipelineState(
        episode_id="TEST-E01",
        title="Test",
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )
    store.save(first)
    one = (tmp_path / "TEST-E01_state.json").read_text(encoding="utf-8")
    store.save(second)
    two = (tmp_path / "TEST-E01_state.json").read_text(encoding="utf-8")
    assert one == two
    assert "object at" not in one
    assert "<" not in json.dumps(first.to_dict())
    assert store.base_path.exists()


def test_state_dir_does_not_expose_temp_files_as_valid_state(tmp_path):
    store = StateStore(base_path=tmp_path)
    store.save(PipelineState(episode_id="TEST-E01", title="Test"))
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["TEST-E01_state.json"]


def test_state_save_missing_destination_creation(tmp_path):
    base = tmp_path / "nested" / "state"
    store = StateStore(base_path=base)
    store.save(PipelineState(episode_id="TEST-E01", title="Test"))
    state_file = base / "TEST-E01_state.json"
    assert state_file.exists()
    assert store.load("TEST-E01").title == "Test"


# --- ARTIFACT PAYLOAD ATOMICITY ---


def test_artifact_payload_failure_preserves_previous_artifact(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"synopsis": "old"}})
    payload_before = (tmp_path / "TEST-E01" / "story_v1.json").read_text(encoding="utf-8")
    index_before = _index_text(tmp_path)

    failing = _FailingPayloadStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.store("TEST-E01", "story", {"outputs": {"synopsis": "new"}})

    assert (tmp_path / "TEST-E01" / "story_v1.json").read_text(encoding="utf-8") == payload_before
    assert _index_text(tmp_path) == index_before
    data, metadata = store.get("TEST-E01", "story", version=1)
    assert data["outputs"]["synopsis"] == "old"
    assert metadata.version == 1
    assert not (tmp_path / "TEST-E01" / "story_v2.json").exists()
    _assert_no_temp_files(tmp_path / "TEST-E01")
    _assert_no_temp_files(tmp_path)


def test_artifact_metadata_failure_leaves_no_partial_meta(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"synopsis": "old"}})
    meta_before = (tmp_path / "TEST-E01" / "story_v1.meta.json").read_text(encoding="utf-8")
    index_before = _index_text(tmp_path)

    failing = _FailingMetadataStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.store("TEST-E01", "story", {"outputs": {"synopsis": "new"}})

    assert (tmp_path / "TEST-E01" / "story_v1.meta.json").read_text(encoding="utf-8") == meta_before
    assert _index_text(tmp_path) == index_before
    v2_payload = tmp_path / "TEST-E01" / "story_v2.json"
    assert v2_payload.exists()
    parsed = json.loads(v2_payload.read_text(encoding="utf-8"))
    assert parsed["outputs"]["synopsis"] == "new"
    assert not (tmp_path / "TEST-E01" / "story_v2.meta.json").exists()
    assert failing.get("TEST-E01", "story", version=2) is None
    _assert_no_temp_files(tmp_path / "TEST-E01")
    _assert_no_temp_files(tmp_path)


# --- ARTIFACT INDEX CONSISTENCY ---


def test_artifact_index_failure_preserves_previous_index_and_rolls_back(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"synopsis": "old"}})
    index_before = _index_text(tmp_path)

    failing = _FailingIndexStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.store("TEST-E01", "story", {"outputs": {"synopsis": "new"}})

    assert _index_text(tmp_path) == index_before
    assert failing.get("TEST-E01", "story", version=2) is None
    data, metadata = failing.get("TEST-E01", "story", version=1)
    assert data["outputs"]["synopsis"] == "old"
    assert [_index_text(tmp_path).count(k) for k in ("story_v2",)] == [0]
    _assert_no_temp_files(tmp_path)

    recovered = ArtifactStore(base_path=tmp_path)
    ref = recovered.store("TEST-E01", "story", {"outputs": {"synopsis": "new"}})
    assert ref.version == 2
    data, metadata = recovered.get("TEST-E01", "story", version=2)
    assert data["outputs"]["synopsis"] == "new"
    assert metadata.version == 2


def test_artifact_delete_index_failure_rolls_back(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"a": 1}})
    store.store("TEST-E01", "story", {"outputs": {"a": 2}})
    index_before = _index_text(tmp_path)

    failing = _FailingIndexStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.delete("TEST-E01", "story", version=1)

    assert _index_text(tmp_path) == index_before
    assert failing.get("TEST-E01", "story", version=1) is not None
    assert (tmp_path / "TEST-E01" / "story_v1.json").exists()
    _assert_no_temp_files(tmp_path)


def test_artifact_cleanup_index_failure_rolls_back(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"a": 1}})
    store.store("TEST-E01", "story", {"outputs": {"a": 2}})
    index_before = _index_text(tmp_path)

    failing = _FailingIndexStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.cleanup_episode("TEST-E01")

    assert _index_text(tmp_path) == index_before
    assert len(failing.list_artifacts("TEST-E01")) == 2
    _assert_no_temp_files(tmp_path)


def test_artifact_index_is_valid_json_and_deterministic(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    for i in (1, 2):
        store.store("TEST-E01", "story", {"outputs": {"synopsis": f"s{i}"}})
        store.store("TEST-E01", "screenplay", {"outputs": {"scenes": i}})
    raw = _index_text(tmp_path)
    parsed = json.loads(raw)
    assert "TEST-E01:story:v2" in parsed
    assert len(parsed) == 4
    assert "object at" not in raw
    assert "<" not in raw
    reloaded = ArtifactStore(base_path=tmp_path)
    assert reloaded.get_latest("TEST-E01", "story")[1].version == 2


def test_artifact_rejects_non_serializable_data_without_touching_index(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"synopsis": "ok"}})
    index_before = _index_text(tmp_path)
    with pytest.raises(TypeError):
        store.store("TEST-E01", "story", {"outputs": {"synopsis": {"set-value"}}})
    assert _index_text(tmp_path) == index_before
    assert not (tmp_path / "TEST-E01" / "story_v2.json").exists()
    assert store.get("TEST-E01", "story", version=1)[0]["outputs"]["synopsis"] == "ok"
    _assert_no_temp_files(tmp_path)


# --- VERSIONING SEMANTICS PRESERVED ---


def test_artifact_versioning_survives_failed_index_write(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    store.store("TEST-E01", "story", {"outputs": {"synopsis": "v1"}})
    failing = _FailingIndexStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.store("TEST-E01", "story", {"outputs": {"synopsis": "v2-failed"}})
    recovered = ArtifactStore(base_path=tmp_path)
    ref = recovered.store("TEST-E01", "story", {"outputs": {"synopsis": "v2"}})
    assert ref.version == 2
    data, metadata = recovered.get_latest("TEST-E01", "story")
    assert data["outputs"]["synopsis"] == "v2"
    assert metadata.checksum != ""
    assert metadata.size_bytes > 0
