import pytest

from pipeline.artifacts import ArtifactStore
from pipeline.episode_ids import InvalidEpisodeIdError, validate_episode_id
from pipeline.state import PipelineState, StateStore


def test_valid_episode_ids_accepted_and_preserved():
    for episode_id in [
        "ANANTA-S01E01",
        "TEST",
        "TEST-E01",
        "episode.1",
        "a_b",
        "X1",
        "COM0",
        "COM10",
        "LPT10",
        "Episode-01_v2",
    ]:
        assert validate_episode_id(episode_id) == episode_id


@pytest.mark.parametrize(
    "episode_id",
    [
        "",
        ".",
        "..",
        ".hidden",
        "../evil",
        "..\\evil",
        "a/../b",
        "a\\b",
        "C:\\evil",
        "/abs",
        "a:b",
        "a\nb",
        "a\tb",
        "with space",
        "CON",
        "con",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "lpt9",
    ],
)
def test_invalid_episode_ids_rejected(episode_id):
    with pytest.raises(InvalidEpisodeIdError):
        validate_episode_id(episode_id)


def test_max_length_boundary():
    assert validate_episode_id("A" * 100) == "A" * 100
    with pytest.raises(InvalidEpisodeIdError):
        validate_episode_id("A" * 101)


def test_non_string_rejected():
    with pytest.raises(InvalidEpisodeIdError):
        validate_episode_id(123)
    with pytest.raises(InvalidEpisodeIdError):
        validate_episode_id(None)


def test_invalid_episode_id_is_value_error():
    assert issubclass(InvalidEpisodeIdError, ValueError)


def test_state_store_rejects_traversal_on_save(tmp_path):
    store = StateStore(base_path=tmp_path)
    state = PipelineState(episode_id="../evil", title="Evil")
    with pytest.raises(InvalidEpisodeIdError):
        store.save(state)
    assert list(tmp_path.iterdir()) == []


def test_state_store_rejects_traversal_on_load_and_delete(tmp_path):
    store = StateStore(base_path=tmp_path)
    with pytest.raises(InvalidEpisodeIdError):
        store.load("../evil")
    with pytest.raises(InvalidEpisodeIdError):
        store.delete("a/../../evil")


def test_artifact_store_rejects_invalid_episode(tmp_path):
    store = ArtifactStore(base_path=tmp_path)
    data = {"episode_id": "../evil", "stage": "story", "outputs": {}}
    with pytest.raises(InvalidEpisodeIdError):
        store.store("../evil", "story", data)
    with pytest.raises(InvalidEpisodeIdError):
        store.get("../evil", "story")
    with pytest.raises(InvalidEpisodeIdError):
        store.delete("../evil", "story", 1)
    with pytest.raises(InvalidEpisodeIdError):
        store.cleanup_episode("../evil")
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path / ".." / "evil").exists()
