import os
import re

import pytest

from pipeline import atomic_io
from pipeline.atomic_io import (
    _temp_path,
    atomic_write_bytes,
    atomic_write_text,
)


def test_atomic_write_text_success_creates_file(tmp_path):
    dest = tmp_path / "out.json"
    atomic_write_text(dest, '{"a": 1}')
    assert dest.read_text(encoding="utf-8") == '{"a": 1}'


def test_atomic_write_bytes_roundtrip(tmp_path):
    dest = tmp_path / "out.bin"
    payload = b"\x00\xff\nhello\x1f"
    atomic_write_bytes(dest, payload)
    assert dest.read_bytes() == payload


def test_atomic_write_missing_destination_creation(tmp_path):
    dest = tmp_path / "a" / "b" / "c" / "out.json"
    atomic_write_text(dest, "x")
    assert dest.read_text(encoding="utf-8") == "x"


def test_atomic_write_replaces_existing_content(tmp_path):
    dest = tmp_path / "out.json"
    atomic_write_text(dest, "old")
    atomic_write_text(dest, "new")
    assert dest.read_text(encoding="utf-8") == "new"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    dest = tmp_path / "out.json"
    atomic_write_text(dest, "x")
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_temp_path_unique_same_dir_hex(tmp_path):
    dest = tmp_path / "state.json"
    first = _temp_path(dest)
    second = _temp_path(dest)
    assert first.parent == dest.parent
    assert first != second
    assert re.fullmatch(r"\.state\.json\.[0-9a-f]{32}\.tmp", first.name)
    assert not first.name.endswith(".json")


def test_temp_path_does_not_expose_as_valid_state_file(tmp_path):
    dest = tmp_path / "ANANTA-S01E01_state.json"
    temp = _temp_path(dest)
    assert temp.name != dest.name
    assert not temp.name.endswith(".json")
    assert not temp.name.startswith("ANANTA-S01E01_state.json")


def test_replacement_failure_preserves_destination(monkeypatch, tmp_path):
    dest = tmp_path / "out.json"
    dest.write_text("PREVIOUS", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic_io, "_os_replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(dest, "NEW CONTENT")
    assert dest.read_text(encoding="utf-8") == "PREVIOUS"
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_write_failure_cleans_temp_and_preserves_destination(monkeypatch, tmp_path):
    dest = tmp_path / "out.json"
    dest.write_text("PREVIOUS", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(atomic_io, "_os_fsync", boom)
    with pytest.raises(OSError):
        atomic_write_text(dest, "PARTIAL")
    assert dest.read_text(encoding="utf-8") == "PREVIOUS"
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_temp_leftover_does_not_collide_with_new_write(tmp_path):
    dest = tmp_path / "state.json"
    stale = tmp_path / f".state.json.{'a' * 32}.tmp"
    stale.write_text("stale", encoding="utf-8")
    atomic_write_text(dest, "fresh")
    assert dest.read_text(encoding="utf-8") == "fresh"
    assert list(tmp_path.glob(".*.tmp")) == [stale]


@pytest.mark.skipif(os.name != "posix", reason="permission preservation is POSIX-specific")
def test_atomic_write_preserves_existing_permissions(tmp_path):
    dest = tmp_path / "out.json"
    dest.write_text("old", encoding="utf-8")
    dest.chmod(0o640)
    atomic_write_text(dest, "new")
    assert (dest.stat().st_mode & 0o777) == 0o640
