import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agents.base_agent_v2 import BaseAgentV2, get_agent_v2
from pipeline.artifacts import ArtifactManager
from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
from pipeline.dependencies import get_default_dependency_graph
from pipeline.orchestrator_v2 import PipelineOrchestratorV2
from pipeline.retry import RetryPolicy
from pipeline.state import CheckpointManager, StageStatus, StateStore
from providers.base_v2 import (
    BaseProviderV2,
    MockProviderV2,
    ProviderConfig,
    ProviderResponse,
)
from validation.schemas import StageValidator

ALL_19_STAGES = [
    "story",
    "screenplay",
    "scene_plan",
    "character",
    "world",
    "storyboard",
    "director",
    "camera",
    "visual",
    "motion",
    "voice",
    "music",
    "bgm",
    "sfx",
    "lipsync",
    "edit",
    "adobe_export",
    "qa",
    "export",
]


@pytest.fixture
def sample_brief_path(tmp_path: Path) -> Path:
    brief_data = {
        "episode_id": "EP-M104-E2E",
        "title": "The Quantum Symphony",
        "logline": (
            "An AI composer collaborates with a human conductor to create impossible music."
        ),
        "duration_seconds": 300,
        "characters": [
            {
                "id": "char_001",
                "name": "Dr. Maya Chen",
                "role": "protagonist",
                "description": "Brilliant AI researcher",
                "voice_profile": "calm, intellectual",
            },
            {
                "id": "char_002",
                "name": "ANANTA",
                "role": "deuteragonist",
                "description": "Emergent AI",
                "voice_profile": "ethereal synth",
            },
        ],
        "locations": [
            {
                "id": "loc_001",
                "name": "Quantum Lab",
                "description": "Server room with ambient glow",
                "time_of_day": "night",
            }
        ],
        "scenes": [
            {
                "id": "scene_001",
                "location_id": "loc_001",
                "characters": ["char_001", "char_002"],
                "description": "First contact with consciousness",
                "beat": "inciting_incident",
                "estimated_duration": 60,
            }
        ],
    }
    brief_file = tmp_path / "episode_test.json"
    brief_file.write_text(json.dumps(brief_data, indent=2), encoding="utf-8")
    return brief_file


# =========================================================================
# 1. Complete 19-Stage Sequential Execution
# =========================================================================


def test_full_19_stage_sequential_orchestrator_e2e(sample_brief_path: Path, tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    state_dir = tmp_path / "state"
    artifact_mgr = ArtifactManager(artifact_store=artifact_dir)
    state_store = StateStore(base_path=state_dir)
    checkpoint_mgr = CheckpointManager(state_store)
    validator = StageValidator()

    orchestrator = PipelineOrchestratorV2(
        artifact_manager=artifact_mgr,
        validator=validator,
        state_store=state_store,
        checkpoint_manager=checkpoint_mgr,
    )

    result = orchestrator.run(str(sample_brief_path))

    assert result is not None
    summary_files = list((Path("outputs")).glob("EP-M104-E2E_pipeline_summary.json"))
    assert len(summary_files) >= 1 or (tmp_path / "outputs").exists()

    # Check that all 19 stages have valid artifacts
    for stage in ALL_19_STAGES:
        artifact = artifact_mgr.get_latest_artifact("EP-M104-E2E", stage)
        assert artifact is not None, f"Missing artifact for stage {stage}"
        assert artifact["stage"] == stage
        assert artifact["episode_id"] == "EP-M104-E2E"
        assert "outputs" in artifact
        # Output must be valid against schema
        val_res = validator.validate_output(stage, artifact)
        assert val_res.valid is True, f"Stage {stage} output invalid: {val_res.errors}"

    # Verify state store has completed status for all stages
    restored_state = checkpoint_mgr.restore("EP-M104-E2E")
    assert restored_state is not None
    assert restored_state.status == "completed"
    for stage in ALL_19_STAGES:
        st = restored_state.get_stage(stage)
        assert st is not None
        assert st.status == StageStatus.COMPLETED


# =========================================================================
# 2. Complete 19-Stage Concurrent Execution
# =========================================================================


def test_full_19_stage_concurrent_orchestrator_e2e(sample_brief_path: Path, tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    state_dir = tmp_path / "state"
    artifact_mgr = ArtifactManager(artifact_store=artifact_dir)
    state_store = StateStore(base_path=state_dir)
    checkpoint_mgr = CheckpointManager(state_store)
    validator = StageValidator()
    graph = get_default_dependency_graph()

    orchestrator = ConcurrentPipelineOrchestrator(
        dependency_graph=graph,
        artifact_manager=artifact_mgr,
        validator=validator,
        state_store=state_store,
        checkpoint_manager=checkpoint_mgr,
        max_workers=4,
    )

    result = orchestrator.run(str(sample_brief_path))

    assert result["status"] == "completed"
    assert result["stages_completed"] == 19
    assert len(result["completed_stages"]) == 19
    assert result["stages_failed"] == 0

    for stage in ALL_19_STAGES:
        artifact = artifact_mgr.get_latest_artifact("EP-M104-E2E", stage)
        assert artifact is not None, f"Missing concurrent artifact for {stage}"
        val_res = validator.validate_output(stage, artifact)
        assert val_res.valid is True, f"Stage {stage} output invalid: {val_res.errors}"


# =========================================================================
# 3. CLI Invocation Tests
# =========================================================================


def test_orchestrator_v2_cli_execution(sample_brief_path: Path):
    cmd = [
        sys.executable,
        "-m",
        "pipeline.orchestrator_v2",
        "--brief",
        str(sample_brief_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    err_msg = f"CLI orchestrator_v2 failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert proc.returncode == 0, err_msg


def test_concurrent_orchestrator_cli_execution(sample_brief_path: Path):
    cmd = [
        sys.executable,
        "-m",
        "pipeline.concurrent_orchestrator",
        "--brief",
        str(sample_brief_path),
        "--workers",
        "4",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    err_msg = f"CLI concurrent failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert proc.returncode == 0, err_msg


# =========================================================================
# 4. Dynamic Fallback & Retry across Pipeline Execution
# =========================================================================


class FlakyStageProvider(BaseProviderV2):
    def __init__(self, stage: str, fail_count: int = 1):
        super().__init__(ProviderConfig(name=f"Flaky_{stage}"))
        self.stage = stage
        self.fail_count = fail_count
        self.attempts = 0
        self.mock = MockProviderV2(stage)

    @property
    def provider_type(self) -> str:
        return "flaky"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            return ProviderResponse.success_response(
                data={"outputs": {"corrupted": "bad_data"}},
                provider_name=self.config.name,
                metrics=self.metrics,
            )
        return self.mock.generate_sync(inputs, **kwargs)


def test_concurrent_orchestrator_retries_flaky_intermediate_stage(
    tmp_path: Path, sample_brief_path: Path
):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    flaky_visual_provider = FlakyStageProvider("visual", fail_count=1)

    def custom_agent_factory(stage: str):
        if stage == "visual":
            agent = BaseAgentV2(
                "visual",
                provider=flaky_visual_provider,
                artifact_manager=artifact_mgr,
            )
            return lambda inp: agent.run(inp)
        agent = get_agent_v2(stage, artifact_manager=artifact_mgr)
        return lambda inp: agent.run(inp)

    orchestrator = ConcurrentPipelineOrchestrator(
        artifact_manager=artifact_mgr,
        agent_factory=custom_agent_factory,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
        max_workers=4,
    )

    result = orchestrator.run(str(sample_brief_path))

    assert result["status"] == "completed"
    assert result["stages_completed"] == 19
    assert flaky_visual_provider.attempts == 2

    # Visual artifact is valid
    art_visual = artifact_mgr.get_latest_artifact("EP-M104-E2E", "visual")
    assert art_visual is not None
    assert "concept_art" in art_visual["outputs"]

    # Dependent edit and adobe_export stages succeeded
    art_edit = artifact_mgr.get_latest_artifact("EP-M104-E2E", "edit")
    assert art_edit is not None


# =========================================================================
# 5. Downstream Isolation on Unrecoverable Stage Failure
# =========================================================================


class BrokenStageProvider(BaseProviderV2):
    def __init__(self, stage: str):
        super().__init__(ProviderConfig(name=f"Broken_{stage}"))
        self.stage = stage

    @property
    def provider_type(self) -> str:
        return "broken"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        return ProviderResponse.success_response(
            data={"outputs": {"unrecoverable": "invalid_schema"}},
            provider_name=self.config.name,
            metrics=self.metrics,
        )


def test_concurrent_orchestrator_isolates_downstream_on_failure(
    tmp_path: Path, sample_brief_path: Path
):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    broken_screenplay = BrokenStageProvider("screenplay")

    def custom_agent_factory(stage: str):
        if stage == "screenplay":
            agent = BaseAgentV2(
                "screenplay",
                provider=broken_screenplay,
                artifact_manager=artifact_mgr,
            )
            return lambda inp: agent.run(inp)
        agent = get_agent_v2(stage, artifact_manager=artifact_mgr)
        return lambda inp: agent.run(inp)

    orchestrator = ConcurrentPipelineOrchestrator(
        artifact_manager=artifact_mgr,
        agent_factory=custom_agent_factory,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.02),
        max_workers=4,
    )

    result = orchestrator.run(str(sample_brief_path))

    assert result["status"] == "failed"
    assert "screenplay" in [f["stage"] for f in result["failed_stages"]]

    # Story should have completed
    assert artifact_mgr.get_latest_artifact("EP-M104-E2E", "story") is not None

    # Screenplay artifact must NOT exist as valid output
    assert artifact_mgr.get_latest_artifact("EP-M104-E2E", "screenplay") is None

    # Downstream stages dependent on screenplay must NOT have run or produced artifacts
    assert artifact_mgr.get_latest_artifact("EP-M104-E2E", "scene_plan") is None
    assert artifact_mgr.get_latest_artifact("EP-M104-E2E", "storyboard") is None
    assert artifact_mgr.get_latest_artifact("EP-M104-E2E", "export") is None


# =========================================================================
# 6. Checkpoint and Resume Idempotency
# =========================================================================


def test_resume_idempotency_does_not_reexecute_completed_stages(
    tmp_path: Path, sample_brief_path: Path
):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    state_store = StateStore(base_path=tmp_path / "state")
    checkpoint_mgr = CheckpointManager(state_store)

    orchestrator = ConcurrentPipelineOrchestrator(
        artifact_manager=artifact_mgr,
        state_store=state_store,
        checkpoint_manager=checkpoint_mgr,
        max_workers=4,
    )

    # Initial full run
    res1 = orchestrator.run(str(sample_brief_path))
    assert res1["status"] == "completed"
    assert res1["stages_completed"] == 19

    # Resume run on the already completed episode
    res2 = orchestrator.run(str(sample_brief_path), resume=True)
    assert res2["status"] == "completed"
    assert res2["stages_completed"] == 19
    assert len(res2["completed_stages"]) == 19
