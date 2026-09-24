import json

import pytest

from pipeline.artifacts import ArtifactMetadata, ArtifactStore


def test_artifact_get_validates_checksum_success(tmp_path):
    """M8 invariant: Valid artifact loads and passes checksum validation."""
    store = ArtifactStore(base_path=tmp_path)
    ref = store.store("TEST-E01", "story", {"outputs": {"synopsis": "Valid content"}})

    data, meta = store.get("TEST-E01", "story", version=ref.version)
    assert data["outputs"]["synopsis"] == "Valid content"
    assert meta.checksum != ""


def test_artifact_get_detects_tampered_payload_and_raises_structured_error(tmp_path):
    """M8 invariant: Modifying payload on disk causes checksum mismatch & structured error."""
    store = ArtifactStore(base_path=tmp_path)
    ref = store.store("TEST-E01", "story", {"outputs": {"synopsis": "Authentic content"}})

    # Tamper with the artifact payload file directly on disk
    artifact_file = tmp_path / "TEST-E01" / f"story_v{ref.version}.json"
    tampered_data = {"outputs": {"synopsis": "TAMPERED EVIL CONTENT"}}
    artifact_file.write_text(json.dumps(tampered_data), encoding="utf-8")

    # M8 contract: must raise structured ArtifactCorruptionError
    with pytest.raises(Exception) as exc_info:
        store.get("TEST-E01", "story", version=ref.version)

    err = exc_info.value
    err_type_name = type(err).__name__
    assert (
        "Corruption" in err_type_name or "Integrity" in err_type_name
    ), f"Expected ArtifactCorruptionError or ArtifactIntegrityError, got {type(err)}: {err}"
    msg = str(err).lower()
    assert "checksum" in msg or "tamper" in msg or "integrity" in msg


def test_artifact_get_detects_truncated_payload(tmp_path):
    """M8 invariant: Truncated artifact payload on disk raises ArtifactCorruptionError."""
    store = ArtifactStore(base_path=tmp_path)
    ref = store.store("TEST-E01", "story", {"outputs": {"synopsis": "Full story"}})

    artifact_file = tmp_path / "TEST-E01" / f"story_v{ref.version}.json"
    artifact_file.write_text('{"outputs": {"synopsis": ', encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        store.get("TEST-E01", "story", version=ref.version)

    err = exc_info.value
    err_type_name = type(err).__name__
    assert (
        "Corruption" in err_type_name or "Integrity" in err_type_name
    ), f"Expected ArtifactCorruptionError, got {type(err)}: {err}"


def test_orphan_artifact_reconciliation(tmp_path):
    """M8 invariant: Valid payload + metadata pairs on disk unindexed can be safely reconciled."""
    store = ArtifactStore(base_path=tmp_path)
    episode_id = "TEST-E01"
    episode_dir = tmp_path / episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)

    # Simulate crash right before index write: payload and meta exist on disk, index empty
    payload = {"outputs": {"synopsis": "Orphaned story"}}
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    import hashlib
    checksum = hashlib.sha256(payload_bytes).hexdigest()[:16]

    (episode_dir / "story_v1.json").write_text(json.dumps(payload), encoding="utf-8")
    meta = ArtifactMetadata(
        name=f"{episode_id}:story:v1",
        stage="story",
        version=1,
        episode_id=episode_id,
        size_bytes=len(payload_bytes),
        checksum=checksum,
    )
    (episode_dir / "story_v1.meta.json").write_text(json.dumps(meta.to_dict()), encoding="utf-8")

    # M8 method: reconcile_artifacts should discover valid unindexed artifact
    assert hasattr(store, "reconcile_artifacts"), "ArtifactStore must provide reconcile_artifacts()"
    reconciled = store.reconcile_artifacts(episode_id)
    assert len(reconciled) == 1
    assert reconciled[0].version == 1

    # Now get should succeed
    data, _ = store.get(episode_id, "story", version=1)
    assert data["outputs"]["synopsis"] == "Orphaned story"


def test_corrupt_orphan_is_not_reconciled(tmp_path):
    """M8 invariant: An unindexed payload with missing metadata must NOT become authoritative."""
    store = ArtifactStore(base_path=tmp_path)
    episode_id = "TEST-E01"
    episode_dir = tmp_path / episode_id
    episode_dir.mkdir(parents=True, exist_ok=True)

    # Payload exists without any .meta.json file
    orphan_file = episode_dir / "story_v1.json"
    orphan_file.write_text('{"outputs": {"synopsis": "Rogue file"}}', encoding="utf-8")

    if hasattr(store, "reconcile_artifacts"):
        reconciled = store.reconcile_artifacts(episode_id)
        assert len(reconciled) == 0

    assert store.get(episode_id, "story", version=1) is None
