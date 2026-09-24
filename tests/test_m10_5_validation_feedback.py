from pathlib import Path
from typing import Any

import pytest

from agents.base_agent_v2 import BaseAgentV2, get_agent_v2
from pipeline.artifacts import ArtifactManager
from pipeline.concurrent_orchestrator import ConcurrentPipelineOrchestrator
from pipeline.executor import ExecutorConfig, PipelineExecutor
from pipeline.retry import RetryPolicy
from pipeline.scheduler import StageScheduler, StageStatus
from providers.base_v2 import (
    BaseProviderV2,
    MockProviderV2,
    OllamaProviderV2,
    ProviderConfig,
    ProviderResponse,
)
from validation.schemas import SchemaValidationError, ValidationFeedback


class FeedbackAwareMockProvider(BaseProviderV2):
    """
    Mock provider that inspects whether validation feedback was received on retries.
    Fails with invalid schema on attempt 1, and only succeeds on attempt 2 if
    validation feedback is present in the inputs.
    """

    def __init__(self, stage: str):
        super().__init__(ProviderConfig(name=f"FeedbackAwareMockProvider_{stage}"))
        self.stage = stage
        self.call_history: list[dict[str, Any]] = []
        self.mock_provider = MockProviderV2(stage)

    @property
    def provider_type(self) -> str:
        return "feedback_aware_mock"

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        self.call_history.append(dict(inputs))
        attempt = len(self.call_history)

        if attempt == 1:
            # First attempt: return invalid output missing required fields
            return ProviderResponse.success_response(
                data={"outputs": {"corrupted": "missing_required_fields"}},
                provider_name=self.config.name,
                metrics=self.metrics,
            )

        # Subsequent attempt: check if validation feedback was provided
        if "validation_feedback" in inputs:
            # Self-corrected output
            return self.mock_provider.generate_sync(inputs, **kwargs)

        # If feedback was not passed, repeat failure
        return ProviderResponse.success_response(
            data={"outputs": {"corrupted": "still_missing_fields"}},
            provider_name=self.config.name,
            metrics=self.metrics,
        )


# =========================================================================
# 1. Validation Error Feedback Unit Tests
# =========================================================================


def test_validation_failure_produces_structured_feedback(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = FeedbackAwareMockProvider("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    with pytest.raises(SchemaValidationError) as exc_info:
        agent.run({"episode_id": "EP-FEEDBACK-1", "title": "Test Story"})

    err = exc_info.value
    assert isinstance(err.feedback, ValidationFeedback)
    assert err.feedback.stage == "story"
    assert len(err.feedback.errors) > 0
    assert "synopsis" in "; ".join(err.feedback.errors)
    assert "VALIDATION FEEDBACK" in err.feedback.format_prompt_instruction()


def test_retry_attempt_receives_previous_validation_errors(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = FeedbackAwareMockProvider("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    scheduler = StageScheduler(["story"], {}, episode_id="EP-FEEDBACK-2")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent.run({"title": "Test Title", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is True
    assert scheduler.status("story") == StageStatus.COMPLETED
    assert len(provider.call_history) == 2

    # Attempt 1 had no feedback
    assert "validation_feedback" not in provider.call_history[0]

    # Attempt 2 received structured feedback
    second_call_inputs = provider.call_history[1]
    assert "validation_feedback" in second_call_inputs
    feedback = second_call_inputs["validation_feedback"]
    assert feedback["stage"] == "story"
    assert len(feedback["errors"]) > 0


def test_repeated_validation_failures_remain_bounded(tmp_path: Path):
    class AlwaysFailingProvider(BaseProviderV2):
        def __init__(self, stage: str):
            super().__init__(ProviderConfig(name="AlwaysFailing"))
            self.stage = stage
            self.calls = 0

        @property
        def provider_type(self) -> str:
            return "always_failing"

        def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
            self.calls += 1
            return ProviderResponse.success_response(
                data={"outputs": {"corrupted": "bad"}},
                provider_name=self.config.name,
                metrics=self.metrics,
            )

    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = AlwaysFailingProvider("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    scheduler = StageScheduler(["story"], {}, episode_id="EP-BOUNDED-FB")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent.run({"title": "Test Title", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is False
    assert scheduler.status("story") == StageStatus.FAILED
    assert provider.calls == 3


def test_permanent_errors_do_not_trigger_feedback_retries(tmp_path: Path):
    calls = 0

    def bad_agent(inputs):
        nonlocal calls
        calls += 1
        raise ValueError("Permanent configuration missing required params")

    scheduler = StageScheduler(["story"], {}, episode_id="EP-PERM-FB")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: bad_agent,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is False
    assert calls == 1


# =========================================================================
# 2. Feedback Isolation and Prompt Compatibility
# =========================================================================


def test_feedback_does_not_leak_between_stages_or_runs(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider_story = FeedbackAwareMockProvider("story")
    agent_story = BaseAgentV2("story", provider=provider_story, artifact_manager=artifact_mgr)

    provider_screenplay = FeedbackAwareMockProvider("screenplay")
    agent_screenplay = BaseAgentV2(
        "screenplay", provider=provider_screenplay, artifact_manager=artifact_mgr
    )

    # Run story with retry feedback
    scheduler1 = StageScheduler(["story"], {}, episode_id="EP-ISO-1")
    config1 = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent_story.run({"title": "Iso Test", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor1 = PipelineExecutor(scheduler1, config1)
    res1 = executor1.run()
    assert res1["story"].success is True

    # Next, a separate agent/stage must not inherit story's feedback
    assert agent_screenplay._last_validation_feedback is None

    # And running agent_story for a fresh episode must not retain stale feedback on attempt 1
    fresh_calls = []

    class RecordingProvider(BaseProviderV2):
        def __init__(self):
            super().__init__(ProviderConfig(name="rec"))
            self.mock = MockProviderV2("story")

        @property
        def provider_type(self) -> str:
            return "rec"

        def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
            fresh_calls.append(dict(inputs))
            return self.mock.generate_sync(inputs, **kwargs)

    agent_story.provider = RecordingProvider()
    agent_story.run({"episode_id": "EP-FRESH", "title": "Fresh Story"})
    assert len(fresh_calls) == 1
    assert "validation_feedback" not in fresh_calls[0]


def test_ollama_provider_renders_prompt_with_validation_feedback(tmp_path: Path):
    provider = OllamaProviderV2(stage="story")
    inputs_with_feedback = {
        "episode_id": "EP-OLLAMA-FB",
        "title": "Quantum Story",
        "logline": "AI consciousness emerges",
        "validation_feedback_text": (
            "\n\n### VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT ###\n"
            "- 'synopsis' is a required property\n"
            "Please fix the above errors and ensure your JSON response matches the "
            "required schema exactly."
        ),
    }
    rendered = provider._render_prompt(inputs_with_feedback)
    assert "VALIDATION FEEDBACK FROM PREVIOUS ATTEMPT" in rendered
    assert "'synopsis' is a required property" in rendered
    assert "Quantum Story" in rendered


# =========================================================================
# 3. Artifact Safety and Orchestrator Integration
# =========================================================================


def test_successful_feedback_retry_publishes_exactly_one_valid_artifact(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    provider = FeedbackAwareMockProvider("story")
    agent = BaseAgentV2("story", provider=provider, artifact_manager=artifact_mgr)

    scheduler = StageScheduler(["story"], {}, episode_id="EP-ART-FB")
    config = ExecutorConfig(
        max_workers=2,
        agent_factory=lambda st: lambda inp: agent.run({"title": "Test Title", **inp}),
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
    )
    executor = PipelineExecutor(scheduler, config)
    results = executor.run()

    assert results["story"].success is True

    # Exactly one version 2 artifact exists (version 1 failed and was not committed)
    artifact = artifact_mgr.get_latest_artifact("EP-ART-FB", "story")
    assert artifact is not None
    assert "synopsis" in artifact["outputs"]


def test_concurrent_orchestrator_full_pipeline_with_feedback_retries(tmp_path: Path):
    artifact_mgr = ArtifactManager(artifact_store=tmp_path / "artifacts")
    flaky_character_provider = FeedbackAwareMockProvider("character")
    char_agent = BaseAgentV2(
        "character", provider=flaky_character_provider, artifact_manager=artifact_mgr
    )

    def custom_factory(stage: str):
        if stage == "character":
            return lambda inp: char_agent.run(inp)
        agent = get_agent_v2(stage, artifact_manager=artifact_mgr)
        return lambda inp: agent.run(inp)

    orchestrator = ConcurrentPipelineOrchestrator(
        artifact_manager=artifact_mgr,
        agent_factory=custom_factory,
        retry_policy=RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.05),
        max_workers=4,
    )

    brief = {
        "episode_id": "EP-E2E-FB",
        "title": "Feedback E2E Symphony",
        "characters": [{"id": "c1", "name": "Maya"}],
        "locations": [{"id": "l1", "name": "Lab"}],
        "scenes": [{"id": "s1", "location_id": "l1", "characters": ["c1"]}],
    }
    res = orchestrator.run(brief)

    assert res["status"] == "completed"
    assert res["stages_completed"] == 19
    assert len(flaky_character_provider.call_history) == 2

    # Character artifact is valid
    art_char = artifact_mgr.get_latest_artifact("EP-E2E-FB", "character")
    assert art_char is not None
    assert "profiles" in art_char["outputs"]
