from pipeline.orchestrator_v2 import (
    DEFAULT_STAGES,
    ExecutionContext,
    PipelineOrchestratorV2,
)


def test_pipeline_orchestrator_creation():
    orchestrator = PipelineOrchestratorV2()
    assert orchestrator.stages == DEFAULT_STAGES
    assert orchestrator.artifact_manager is not None
    assert orchestrator.validator is not None
    assert orchestrator.recovery_manager is not None


def test_pipeline_orchestrator_custom_stages():
    custom_stages = ["story", "screenplay"]
    orchestrator = PipelineOrchestratorV2(stages=custom_stages)
    assert orchestrator.stages == custom_stages


def test_execution_context_creation(mock_env, sample_brief):
    from config_v2 import get_settings
    from pipeline.artifacts import ArtifactManager
    from pipeline.recovery import StageRecoveryManager
    from pipeline.state import create_initial_state
    from validation.schemas import StageValidator

    settings = get_settings()
    pipeline_state = create_initial_state(sample_brief["episode_id"], sample_brief["title"], DEFAULT_STAGES)

    context = ExecutionContext(
        pipeline_id="test-pipeline",
        episode_id=sample_brief["episode_id"],
        brief=sample_brief,
        pipeline_state=pipeline_state,
        artifact_manager=ArtifactManager(),
        validator=StageValidator(),
        recovery_manager=StageRecoveryManager(),
        settings=settings,
    )
    assert context.pipeline_id == "test-pipeline"
    assert context.episode_id == sample_brief["episode_id"]
    assert context.completed_stages == []


def test_create_summary(mock_env, sample_brief):
    from config_v2 import get_settings
    from pipeline.artifacts import ArtifactManager
    from pipeline.recovery import StageRecoveryManager
    from pipeline.state import create_initial_state
    from validation.schemas import StageValidator

    settings = get_settings()
    pipeline_state = create_initial_state(sample_brief["episode_id"], sample_brief["title"], DEFAULT_STAGES)
    pipeline_state.status = "running"

    context = ExecutionContext(
        pipeline_id="test-pipeline",
        episode_id=sample_brief["episode_id"],
        brief=sample_brief,
        pipeline_state=pipeline_state,
        artifact_manager=ArtifactManager(),
        validator=StageValidator(),
        recovery_manager=StageRecoveryManager(),
        settings=settings,
    )
    context.completed_stages = ["story", "screenplay"]
    context.failed_stages = []

    orchestrator = PipelineOrchestratorV2()
    summary = orchestrator._create_summary(context)

    assert summary["pipeline_id"] == "test-pipeline"
    assert summary["episode_id"] == sample_brief["episode_id"]
    assert summary["stages_total"] == 19
    assert summary["stages_completed"] == 2
    assert summary["stages_failed"] == 0
    assert summary["status"] == "running"
    assert summary["completed_stages"] == ["story", "screenplay"]
    assert "duration_ms" in summary
