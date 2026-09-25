import argparse
import datetime
import json
import pathlib
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents.base_agent_v2 import get_agent_v2
from config_v2 import get_settings
from observability.logging import get_logger, log_context
from pipeline.artifacts import ArtifactManager
from pipeline.atomic_io import atomic_write_text
from pipeline.dependencies import get_default_dependency_graph
from pipeline.episode_ids import validate_episode_id
from pipeline.recovery import StageRecoveryManager
from pipeline.state import (
    CheckpointManager,
    PipelineState,
    StageStatus,
    StateStore,
    create_initial_state,
)
from validation.schemas import StageValidator

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOGGER = get_logger("pipeline.orchestrator")

DEFAULT_STAGES = [
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


@dataclass
class ExecutionContext:
    pipeline_id: str
    episode_id: str
    brief: dict[str, Any]
    pipeline_state: PipelineState
    artifact_manager: ArtifactManager
    validator: StageValidator
    recovery_manager: StageRecoveryManager
    settings: Any
    start_time: float = field(default_factory=time.perf_counter)
    completed_stages: list[str] = field(default_factory=list)
    failed_stages: list[dict[str, Any]] = field(default_factory=list)
    is_resume: bool = False


class PipelineOrchestratorV2:
    def __init__(
        self,
        stages: list[str] | None = None,
        agent_factory: Any | None = None,
        artifact_manager: ArtifactManager | None = None,
        validator: StageValidator | None = None,
        recovery_manager: StageRecoveryManager | None = None,
        state_store: StateStore | None = None,
        checkpoint_manager: CheckpointManager | None = None,
    ):
        self.stages = stages or DEFAULT_STAGES
        self.agent_factory = agent_factory
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.validator = validator or StageValidator()
        self.recovery_manager = recovery_manager or StageRecoveryManager()
        self.state_store = state_store or StateStore()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(self.state_store)
        self.settings = get_settings()
        self.logger = get_logger("pipeline.orchestrator")

    def run(
        self,
        brief_path_or_dict: str | pathlib.Path | dict[str, Any],
        resume: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        if isinstance(brief_path_or_dict, (str, pathlib.Path)):
            brief = json.loads(pathlib.Path(brief_path_or_dict).read_text(encoding="utf-8"))
        else:
            import copy
            brief = copy.deepcopy(brief_path_or_dict)
        episode_id = brief.get("episode_id", "UNKNOWN")
        validate_episode_id(episode_id)
        pipeline_id = str(uuid.uuid4())[:8]

        brief["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        brief["status"] = "in_progress"
        brief["version"] = 0

        with log_context(pipeline_id=pipeline_id, episode_id=episode_id):
            self.logger.pipeline_start(pipeline_id, episode_id, len(self.stages))

            pipeline_state = None
            if resume:
                pipeline_state = self.checkpoint_manager.restore(episode_id)

            if pipeline_state is None:
                pipeline_state = create_initial_state(episode_id, brief.get("title"), self.stages)
                pipeline_state.status = "running"
                pipeline_state.execution_id = pipeline_id
            else:
                pipeline_state.status = "running"
                if pipeline_state.execution_id:
                    pipeline_id = pipeline_state.execution_id
                else:
                    pipeline_state.execution_id = pipeline_id

                for stage in self.stages:
                    if pipeline_state.get_stage(stage) is None:
                        pipeline_state.add_stage(stage)

            context = ExecutionContext(
                pipeline_id=pipeline_id,
                episode_id=episode_id,
                brief=brief,
                pipeline_state=pipeline_state,
                artifact_manager=self.artifact_manager,
                validator=self.validator,
                recovery_manager=self.recovery_manager,
                settings=self.settings,
                is_resume=resume,
            )

            try:
                result = self._execute_pipeline(context, retry_failed=retry_failed)
            except KeyboardInterrupt:
                self.logger.pipeline_failed(
                    pipeline_id,
                    episode_id,
                    "Interrupted by user",
                    len(context.completed_stages),
                )
                pipeline_state.status = "interrupted"
                self.state_store.save(pipeline_state)
                raise
            except Exception as e:
                self.logger.pipeline_failed(
                    pipeline_id,
                    episode_id,
                    str(e),
                    len(context.completed_stages),
                )
                pipeline_state.status = "failed"
                self.state_store.save(pipeline_state)
                raise

            pipeline_state.status = "completed" if not context.failed_stages else "failed"
            pipeline_state.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.state_store.save(pipeline_state)

            summary = self._create_summary(context)
            self._save_summary(summary, episode_id)

            self.logger.pipeline_complete(
                pipeline_id,
                episode_id,
                (time.perf_counter() - context.start_time) * 1000,
                len(context.completed_stages),
                len(context.failed_stages),
            )

            return result

    def _execute_pipeline(
        self, context: ExecutionContext, retry_failed: bool = False
    ) -> dict[str, Any]:
        graph = get_default_dependency_graph()
        execution_order = graph.get_execution_order()

        current_data = context.brief
        current_data["version"] = 0

        for i, stage in enumerate(execution_order):
            if stage not in self.stages:
                continue

            pipeline_state = context.pipeline_state
            stage_state = pipeline_state.get_stage(stage)

            if context.is_resume:
                if stage_state and stage_state.status == StageStatus.COMPLETED:
                    context.completed_stages.append(stage)
                    current_data = self._hydrate_completed_stage(context, stage, current_data)
                    continue

                # Crash window reconciliation: if artifact was already committed, treat as completed
                try:
                    existing_artifact = self.artifact_manager.get_latest_artifact(
                        context.episode_id, stage
                    )
                except Exception:
                    existing_artifact = None

                if existing_artifact is not None:
                    context.completed_stages.append(stage)
                    if stage_state and stage_state.status != StageStatus.COMPLETED:
                        stage_state.status = StageStatus.COMPLETED
                        stage_state.completed_at = datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat()
                        pipeline_state.update_stage(stage_state)
                    current_data = self._hydrate_completed_stage(context, stage, current_data)
                    continue

            if stage_state and stage_state.status == StageStatus.FAILED:
                if retry_failed:
                    self.logger.info(
                        f"Retrying failed stage {stage} per operator request",
                        stage=stage,
                    )
                    stage_state.status = StageStatus.PENDING
                    stage_state.error = None
                    pipeline_state.update_stage(stage_state)
                else:
                    context.failed_stages.append(
                        {"stage": stage, "error": stage_state.error or "Unknown error"}
                    )
                    break

            self.logger.info(
                f"Executing stage {stage}",
                stage=stage,
                stage_index=i + 1,
                total_stages=len(self.stages),
            )

            if (
                stage_state
                and stage_state.status != StageStatus.RUNNING
                and stage_state.status
                in (
                    StageStatus.PENDING,
                    StageStatus.RETRYING,
                    StageStatus.QUEUED,
                )
            ):
                stage_state.mark_running()
                pipeline_state.update_stage(stage_state)

            if self.agent_factory is not None:
                agent = self.agent_factory(stage)
            else:
                agent = get_agent_v2(
                    stage,
                    artifact_manager=self.artifact_manager,
                    validator=self.validator,
                    recovery_manager=self.recovery_manager,
                )

            try:
                if hasattr(agent, "run"):
                    current_data = agent.run(
                        current_data,
                        pipeline_state=pipeline_state,
                        episode_id=context.episode_id,
                    )
                else:
                    current_data = agent(current_data)
                context.completed_stages.append(stage)

                should_checkpoint = (
                    self.settings.pipeline.checkpoint_enabled
                    and (i + 1) % self.settings.pipeline.checkpoint_interval == 0
                )
                if should_checkpoint:
                    self.checkpoint_manager.checkpoint(pipeline_state)
                    self.logger.checkpoint_saved(context.episode_id, stage)

            except Exception as e:
                context.failed_stages.append({"stage": stage, "error": str(e)})
                if stage_state and stage_state.status != StageStatus.FAILED:
                    stage_state.mark_failed(str(e))
                    pipeline_state.update_stage(stage_state)
                if self.settings.pipeline.checkpoint_enabled:
                    self.checkpoint_manager.checkpoint(pipeline_state)
                break

        context.pipeline_state = pipeline_state
        return current_data

    def _hydrate_completed_stage(
        self,
        context: ExecutionContext,
        stage: str,
        current_data: dict[str, Any],
    ) -> dict[str, Any]:
        artifact = self.artifact_manager.get_latest_artifact(context.episode_id, stage)
        if artifact is None:
            raise RuntimeError(
                f"Completed stage '{stage}' for episode '{context.episode_id}' "
                "has no stored artifact; cannot resume safely"
            )
        return self._merge_stage_result(current_data, artifact)

    def _merge_stage_result(
        self,
        inputs: dict[str, Any],
        result_data: dict[str, Any],
    ) -> dict[str, Any]:
        merged = {**inputs, **result_data}
        if isinstance(inputs.get("outputs"), dict) and isinstance(result_data.get("outputs"), dict):
            merged["outputs"] = {**inputs["outputs"], **result_data["outputs"]}
        stage_inputs = result_data.get("inputs")
        if isinstance(stage_inputs, dict):
            for key in [
                "characters",
                "locations",
                "scenes",
                "title",
                "logline",
                "duration_seconds",
            ]:
                if key in stage_inputs and key not in merged:
                    merged[key] = stage_inputs[key]
        return merged

    def _create_summary(self, context: ExecutionContext) -> dict[str, Any]:
        return {
            "pipeline_id": context.pipeline_id,
            "episode_id": context.episode_id,
            "title": context.brief.get("title"),
            "stages_total": len(self.stages),
            "stages_completed": len(context.completed_stages),
            "stages_failed": len(context.failed_stages),
            "status": context.pipeline_state.status,
            "completed_stages": context.completed_stages,
            "failed_stages": context.failed_stages,
            "duration_ms": (time.perf_counter() - context.start_time) * 1000,
        }

    def _save_summary(self, summary: dict[str, Any], episode_id: str):
        summary_file = ROOT / "outputs" / f"{episode_id}_pipeline_summary.json"
        atomic_write_text(summary_file, json.dumps(summary, indent=2))
        self.logger.info(f"Summary written to {summary_file}", path=str(summary_file))


def run(
    brief_path: str | pathlib.Path | dict[str, Any],
    resume: bool = False,
    retry_failed: bool = False,
) -> dict[str, Any]:
    orchestrator = PipelineOrchestratorV2()
    return orchestrator.run(brief_path, resume=resume, retry_failed=retry_failed)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ANANTA Multi-Agent Production Pipeline v2")
    ap.add_argument("--brief", required=True, help="Path to episode brief JSON")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument("--retry-failed", action="store_true", help="Retry failed stages on resume")
    args = ap.parse_args()

    try:
        run(args.brief, resume=args.resume, retry_failed=args.retry_failed)
    except KeyboardInterrupt:
        LOGGER.error("Pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        LOGGER.error(f"Pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
