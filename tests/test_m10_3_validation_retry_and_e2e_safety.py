import threading
import time
from pathlib import Path
from typing import Any

from agents.base_agent_v2 import BaseAgentV2
from pipeline.artifacts import ArtifactManager
from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
from pipeline.dependencies import DependencyGraph, StageSpec
from pipeline.executor import ExecutorConfig, PipelineExecutor
from pipeline.retry import RetryPolicy
from pipeline.scheduler import StageScheduler, StageStatus
from providers.base_v2 import (
    BaseProviderV2,
    MockProviderV2,
    ProviderConfig,
    ProviderResponse,
)


class FlakyValidationProvider(BaseProviderV2):
    """Fails with invalid schema on early attempts, then succeeds."""

    def __init__(self, stage: str, fail_attempts: int = 1):
        super().__init__(ProviderConfig(name=f"FlakyValidationProvider_{stage}"))
        self.stage = stage
        self.fail_attempts = fail_attempts
        self.attempt_count = 0
        self.mock_provider = MockProviderV2(stage)

    @property
    def provider_type(self) -> str:
        return "flaky_validation"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        self.attempt_count += 1
        if self.attempt_count <= self.fail_attempts:
            # Return invalid schema missing required fields
            return ProviderResponse.success_response(
                data={"outputs": {"corrupted_field": "invalid_value"}},
                provider_name=self.config.name,
                metrics=self.metrics,
            )
        return self.mock_provider.generate_sync(inputs, **kwargs)


class PermanentInvalidProvider(BaseProviderV2):
    """Always returns invalid schema output."""

    def __init__(self, stage: str):
        super().__init__(ProviderConfig(name=f"PermanentInvalidProvider_{stage}"))
        self.stage = stage
        self.attempt_count = 0

    @property
    def provider_type(self) -> str:
        return "permanent_invalid"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        self.attempt_count += 1
        return ProviderResponse.success_response(
            data={"outputs": {"invalid": "never_valid"}},
            provider_name=self.config.name,
            metrics=self.metrics,
        )


# =========================================================================
# 1. Validation Retry Tests
# =========================================================================


def test_retryable_validation_error_triggers_bounded_retry(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = FlakyValidationProvider("story", fail_attempts=1)
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    scheduler = StageScheduler(["story"], {}, episode_id="EP-RETRY-1")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent.run({"title": "Valid Story", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is True
    assert scheduler.status("story") == StageStatus.COMPLETED
    assert provider.attempt_count == 2

    # Exactly one valid artifact stored
    artifact = artifact_mgr.get_latest_artifact("EP-RETRY-1", "story")
    assert artifact is not None
    assert "synopsis" in artifact["outputs"]


def test_repeated_validation_failures_exhaust_retry_limit(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = PermanentInvalidProvider("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    scheduler = StageScheduler(["story"], {}, episode_id="EP-EXHAUST")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent.run({"title": "Exhaust Test", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is False
    assert scheduler.status("story") == StageStatus.FAILED
    assert provider.attempt_count == 3

    # No valid artifact stored
    artifact = artifact_mgr.get_latest_artifact("EP-EXHAUST", "story")
    assert artifact is None


def test_permanent_errors_do_not_retry(tmp_path: Path):
    call_count = 0

    def bad_agent(inputs):
        nonlocal call_count
        call_count += 1
        raise ValueError("Permanent configuration error: missing parameters")

    scheduler = StageScheduler(["story"], {}, episode_id="EP-PERM")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: bad_agent,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is False
    assert scheduler.status("story") == StageStatus.FAILED
    assert call_count == 1, "Permanent non-retryable error should not be retried"


# =========================================================================
# 2. Artifact Safety & Downstream Isolation
# =========================================================================


def test_dependent_stages_never_execute_on_failed_validation(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider_a = PermanentInvalidProvider("story")
    agent_a = BaseAgentV2("story", provider=provider_a, artifact_manager=artifact_mgr)

    b_executed = False

    def agent_b_fn(inputs):
        nonlocal b_executed
        b_executed = True
        return {"screenplay": "ok"}

    def factory(stage):
        if stage == "story":
            return lambda inp: agent_a.run({"title": "Story Title", **inp})
        return agent_b_fn

    scheduler = StageScheduler(
        ["story", "screenplay"],
        {"screenplay": ["story"]},
        episode_id="EP-DEP",
    )
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=factory,
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    executor.run()

    assert scheduler.status("story") == StageStatus.FAILED
    assert scheduler.status("screenplay") in (StageStatus.BLOCKED, StageStatus.PENDING)
    assert not b_executed, "Dependent stage B must never execute if stage A failed validation"


def test_successful_retry_publishes_valid_artifact_for_dependent(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider_a = FlakyValidationProvider("story", fail_attempts=1)
    agent_a = BaseAgentV2("story", provider=provider_a, artifact_manager=artifact_mgr)

    provider_b = MockProviderV2("screenplay")
    agent_b = BaseAgentV2("screenplay", provider=provider_b, artifact_manager=artifact_mgr)

    def factory(stage):
        if stage == "story":
            return lambda inp: agent_a.run({"title": "Story Title", **inp})
        return lambda inp: agent_b.run(
            {
                "title": "Story Title",
                "outputs": {"synopsis": "Valid Synopsis from Story"},
                **inp,
            }
        )

    scheduler = StageScheduler(
        ["story", "screenplay"],
        {"screenplay": ["story"]},
        episode_id="EP-RETRY-DEP",
    )
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=factory,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is True
    assert results["screenplay"].success is True
    assert scheduler.status("story") == StageStatus.COMPLETED
    assert scheduler.status("screenplay") == StageStatus.COMPLETED

    art_a = artifact_mgr.get_latest_artifact("EP-RETRY-DEP", "story")
    art_b = artifact_mgr.get_latest_artifact("EP-RETRY-DEP", "screenplay")
    assert art_a is not None
    assert art_b is not None


# =========================================================================
# 3. Cancellation and Recovery
# =========================================================================


def test_cancellation_during_retry_prevents_stale_publication(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = FlakyValidationProvider("story", fail_attempts=2)
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    scheduler = StageScheduler(["story"], {}, episode_id="EP-CANCEL")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent.run({"title": "Cancel Title", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.2, max_delay=0.5),
    )
    executor = PipelineExecutor(scheduler, config)

    t = threading.Thread(target=executor.run)
    t.start()

    for _ in range(50):
        if scheduler.status("story") == StageStatus.RETRYING:
            break
        time.sleep(0.01)

    assert scheduler.status("story") == StageStatus.RETRYING
    executor.request_pipeline_cancellation()
    t.join(timeout=3.0)

    assert scheduler.status("story") == StageStatus.CANCELLED
    artifact = artifact_mgr.get_latest_artifact("EP-CANCEL", "story")
    assert artifact is None


def test_concurrent_orchestrator_end_to_end_validation_with_retry(tmp_path: Path):
    graph = DependencyGraph(
        stages=[
            StageSpec(name="story", dependencies=(), required_inputs=()),
            StageSpec(name="screenplay", dependencies=("story",), required_inputs=("synopsis",)),
        ]
    )
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    orchestrator = ConcurrentPipelineOrchestrator(
        stages=["story", "screenplay"],
        dependency_graph=graph,
        artifact_manager=artifact_mgr,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )

    brief = {"episode_id": "EP-E2E-1", "title": "E2E Story Test"}
    result = orchestrator.run(brief)

    assert result["status"] == "completed"
    assert result["stages_completed"] == 2
    assert "story" in result["completed_stages"]
    assert "screenplay" in result["completed_stages"]
    assert artifact_mgr.get_latest_artifact("EP-E2E-1", "story") is not None
    assert artifact_mgr.get_latest_artifact("EP-E2E-1", "screenplay") is not None
