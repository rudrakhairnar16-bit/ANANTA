from pipeline.artifacts import (
    ArtifactManager,
    ArtifactMetadata,
    ArtifactReference,
    ArtifactStore,
)


def test_artifact_metadata_creation():
    meta = ArtifactMetadata(
        name="test:v1",
        stage="story",
        version=1,
        size_bytes=100,
        checksum="abc123",
    )
    assert meta.name == "test:v1"
    assert meta.stage == "story"
    assert meta.version == 1


def test_artifact_metadata_to_dict():
    meta = ArtifactMetadata(name="test:v1", stage="story", version=1)
    d = meta.to_dict()
    assert d["name"] == "test:v1"
    assert d["stage"] == "story"
    assert d["version"] == 1


def test_artifact_metadata_from_dict():
    data = {
        "name": "test:v1",
        "stage": "story",
        "version": 1,
        "created_at": "2024-01-01T00:00:00+00:00",
        "size_bytes": 100,
        "checksum": "abc123",
        "content_type": "application/json",
        "schema_version": "1.0",
        "lineage": {},
        "tags": [],
    }
    meta = ArtifactMetadata.from_dict(data)
    assert meta.name == "test:v1"


def test_artifact_reference_creation():
    ref = ArtifactReference(
        artifact_id="test:v1",
        stage="story",
        version=1,
        path="/path/to/file.json",
    )
    assert ref.artifact_id == "test:v1"
    assert ref.stage == "story"
    assert ref.version == 1


def test_artifact_store_creation(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    assert store.base_path == tmp_path
    assert store.base_path.exists()


def test_artifact_store_store(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test"}}
    ref = store.store("TEST-E01", "story", data)

    assert ref.artifact_id == "TEST-E01:story:v1"
    assert ref.stage == "story"
    assert ref.version == 1


def test_artifact_store_get(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test"}}
    store.store("TEST-E01", "story", data)

    retrieved_data, metadata = store.get("TEST-E01", "story", version=1)
    assert retrieved_data is not None
    assert retrieved_data["outputs"]["synopsis"] == "Test"
    assert metadata.version == 1
    assert metadata.checksum != ""


def test_artifact_store_get_latest(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data1 = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test 1"}}
    data2 = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test 2"}}

    store.store("TEST-E01", "story", data1)
    store.store("TEST-E01", "story", data2)

    retrieved_data, metadata = store.get_latest("TEST-E01", "story")
    assert retrieved_data["outputs"]["synopsis"] == "Test 2"
    assert metadata.version == 2


def test_artifact_store_list_artifacts(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "TEST", "stage": "story", "outputs": {}}
    store.store("TEST-E01", "story", data)
    store.store("TEST-E01", "screenplay", data)

    artifacts = store.list_artifacts("TEST-E01")
    assert len(artifacts) == 2
    stages = {a.stage for a in artifacts}
    assert stages == {"story", "screenplay"}


def test_artifact_store_list_stages(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "TEST", "stage": "story", "outputs": {}}
    store.store("TEST-E01", "story", data)
    store.store("TEST-E01", "screenplay", data)

    stages = store.list_stages("TEST-E01")
    assert "story" in stages
    assert "screenplay" in stages


def test_artifact_store_delete(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "TEST", "stage": "story", "outputs": {}}
    store.store("TEST-E01", "story", data)

    store.delete("TEST-E01", "story", version=1)
    retrieved = store.get("TEST-E01", "story", version=1)
    assert retrieved is None


def test_artifact_store_cleanup_episode(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "TEST", "stage": "story", "outputs": {}}
    store.store("TEST-E01", "story", data)
    store.store("TEST-E01", "screenplay", data)

    store.cleanup_episode("TEST-E01")
    artifacts = store.list_artifacts("TEST-E01")
    assert len(artifacts) == 0


def test_artifact_manager(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    manager = ArtifactManager(artifact_store=store)

    output_data = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test"}}
    input_refs = [
        ArtifactReference(artifact_id="ref1", stage="brief", version=1, path="/path/ref1.json")
    ]

    ref = manager.store_stage_output("TEST-E01", "story", output_data, input_artifacts=input_refs)
    assert ref.stage == "story"

    stored_data, metadata = store.get("TEST-E01", "story", version=1)
    assert stored_data["outputs"]["synopsis"] == "Test"
    assert metadata.lineage["input_artifacts"][0]["artifact_id"] == "ref1"


def test_artifact_manager_get_stage_input(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    manager = ArtifactManager(artifact_store=store)

    output_data = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test"}}
    manager.store_stage_output("TEST-E01", "story", output_data)

    retrieved = manager.get_stage_input("TEST-E01", "story")
    assert retrieved["outputs"]["synopsis"] == "Test"


def test_artifact_manager_get_latest_artifact(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    manager = ArtifactManager(artifact_store=store)

    data1 = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test 1"}}
    data2 = {"episode_id": "TEST", "stage": "story", "outputs": {"synopsis": "Test 2"}}

    manager.store_stage_output("TEST-E01", "story", data1)
    manager.store_stage_output("TEST-E01", "story", data2)

    retrieved = manager.get_latest_artifact("TEST-E01", "story")
    assert retrieved["outputs"]["synopsis"] == "Test 2"
