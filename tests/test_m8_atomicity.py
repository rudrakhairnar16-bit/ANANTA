import inspect
import json

import pytest

from agents.base_agent_v2 import BaseAgentV2
from pipeline import atomic_io
from pipeline.artifacts import ArtifactStore
from pipeline.orchestrator_v2 import PipelineOrchestratorV2


def test_save_summary_uses_atomic_write(tmp_path, monkeypatch):
    """M8 invariant: _save_summary must use atomic_write_text to avoid partial summary writes."""
    orchestrator = PipelineOrchestratorV2()

    # Check source code inspection: must call atomic_write_text
    src = inspect.getsource(orchestrator._save_summary)
    assert (
        "atomic_write_text" in src
    ), "PipelineOrchestratorV2._save_summary must use atomic_write_text"

    # Functional test: existing summary must be preserved if write fails
    episode_id = "ANANTA-S01E01"
    summary_path = orchestrator_module_root_outputs(episode_id)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps({"status": "previous_valid"}), encoding="utf-8")
    before_content = summary_path.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("Simulated write interruption")

    monkeypatch.setattr(atomic_io, "_os_fsync", boom)

    with pytest.raises(OSError):
        orchestrator._save_summary({"status": "new_partial"}, episode_id)

    # Destination summary must remain intact and not truncated
    assert summary_path.read_text(encoding="utf-8") == before_content
    assert list(summary_path.parent.glob("*.tmp")) == []


def test_write_output_legacy_uses_atomic_write(tmp_path, monkeypatch):
    """M8 invariant: BaseAgentV2._write_output_legacy must use atomic_write_text."""
    agent = BaseAgentV2("story")
    src = inspect.getsource(agent._write_output_legacy)
    assert "atomic_write_text" in src, "BaseAgentV2._write_output_legacy must use atomic_write_text"

    episode_id = "ANANTA-S01E01"
    output_dir = tmp_path / "outputs" / "scripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{episode_id}_story.json"
    out_file.write_text(json.dumps({"status": "previous_valid"}), encoding="utf-8")
    before_content = out_file.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("Simulated disk error during legacy write")

    monkeypatch.setattr(atomic_io, "_os_fsync", boom)

    with pytest.raises(OSError):
        agent._write_output_legacy({"status": "new_partial"}, episode_id)

    assert out_file.read_text(encoding="utf-8") == before_content
    assert list(output_dir.glob("*.tmp")) == []


def test_artifact_store_transactional_rollback_on_metadata_failure(tmp_path):
    """M8 invariant: If writing metadata or index fails, uncommitted payload must be removed."""
    class _FailingMetaStore(ArtifactStore):
        def _write_metadata(self, path, metadata):
            raise OSError("Metadata write failure")

    failing = _FailingMetaStore(base_path=tmp_path)
    with pytest.raises(OSError):
        failing.store("TEST-E01", "story", {"outputs": {"synopsis": "Failed attempt"}})

    # Uncommitted artifact must NOT become authoritative in index or via get()
    assert failing.get("TEST-E01", "story", version=1) is None
    assert "TEST-E01:story:v1" not in failing._index


def orchestrator_module_root_outputs(episode_id):
    import pipeline.orchestrator_v2 as orch_mod
    return orch_mod.ROOT / "outputs" / f"{episode_id}_pipeline_summary.json"
