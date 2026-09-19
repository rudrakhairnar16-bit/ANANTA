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
from pipeline.dependencies import get_default_dependency_graph
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
    "story", "screenplay", "scene_plan", "character", "world",
    "storyboard", "director", "camera", "visual", "motion",
    "voice", "music", "bgm", "sfx", "lipsync",
    "edit", "adobe_export", "qa", "export"
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


class PipelineOrchestratorV2:
    def __init__(
        self,
        stages: list[str] | None = None,
        artifact_manager: ArtifactManager | None = None,
        validator: StageValidator | None = None,
        recovery_manager: StageRecoveryManager | None = None,
        state_store: StateStore | None = None,
        checkpoint_manager: CheckpointManager | None = None,
    ):
        self.stages = stages or DEFAULT_STAGES
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.validator = validator or StageValidator()
        self.recovery_manager = recovery_manager or StageRecoveryManager()
        self.state_store = state_store or StateStore()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(self.state_store)
        self.settings = get_settings()
        self.logger = get_logger("pipeline.orchestrator")

    def run(self, brief_path: str, resume: bool = False) -> dict[str, Any]:
        brief = json.loads(pathlib.Path(brief_path).read_text(encoding="utf-8"))
        episode_id = brief.get("episode_id", "UNKNOWN")
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
            else:
                pipeline_state.status = "running"

            context = ExecutionContext(
                pipeline_id=pipeline_id,
                episode_id=episode_id,
                brief=brief,
                pipeline_state=pipeline_state,
                artifact_manager=self.artifact_manager,
                validator=self.validator,
                recovery_manager=self.recovery_manager,
                settings=self.settings,
            )

            try:
                result = self._execute_pipeline(context)
            except KeyboardInterrupt:
                self.logger.pipeline_failed(pipeline_id, episode_id, "Interrupted by user", len(context.completed_stages))
                pipeline_state.status = "interrupted"
                self.state_store.save(pipeline_state)
                raise
            except Exception as e:
                self.logger.pipeline_failed(pipeline_id, episode_id, str(e), len(context.completed_stages))
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

    def _execute_pipeline(self, context: ExecutionContext) -> dict[str, Any]:
        graph = get_default_dependency_graph()
        execution_order = graph.get_execution_order()

        current_data = context.brief
        current_data["version"] = 0

        for i, stage in enumerate(execution_order):
            if stage not in self.stages:
                continue

            pipeline_state = context.pipeline_state
            stage_state = pipeline_state.get_stage(stage)

            if stage_state and stage_state.status == StageStatus.COMPLETED:
                context.completed_stages.append(stage)
                continue

            if stage_state and stage_state.status == StageStatus.FAILED:
                context.failed_stages.append({"stage": stage, "error": stage_state.error or "Unknown error"})
                break

            self.logger.info(f"Executing stage {stage}", stage=stage, stage_index=i+1, total_stages=len(self.stages))

            agent = get_agent_v2(stage)

            try:
                current_data = agent.run(
                    current_data,
                    pipeline_state=pipeline_state,
                    episode_id=context.episode_id,
                )
                context.completed_stages.append(stage)

                if self.settings.pipeline.checkpoint_enabled and (i + 1) % self.settings.pipeline.checkpoint_interval == 0:
                    self.checkpoint_manager.checkpoint(pipeline_state)
                    self.logger.checkpoint_saved(context.episode_id, stage)

            except Exception as e:
                context.failed_stages.append({"stage": stage, "error": str(e)})
                if stage_state:
                    stage_state.mark_failed(str(e))
                    pipeline_state.update_stage(stage_state)
                if self.settings.pipeline.checkpoint_enabled:
                    self.checkpoint_manager.checkpoint(pipeline_state)
                break

        context.pipeline_state = pipeline_state
        return current_data

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
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        self.logger.info(f"Summary written to {summary_file}", path=str(summary_file))


def run(brief_path: str, resume: bool = False) -> dict[str, Any]:
    orchestrator = PipelineOrchestratorV2()
    return orchestrator.run(brief_path, resume=resume)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ANANTA Multi-Agent Production Pipeline v2")
    ap.add_argument("--brief", required=True, help="Path to episode brief JSON")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = ap.parse_args()

    try:
        run(args.brief, resume=args.resume)
    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nPipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
