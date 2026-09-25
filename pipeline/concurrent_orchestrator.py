import argparse
import copy
import datetime
import json
import pathlib
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from agents.base_agent_v2 import get_agent_v2
from config_v2 import get_settings
from observability.logging import get_logger, log_context
from pipeline.artifacts import ArtifactManager
from pipeline.atomic_io import atomic_write_text
from pipeline.cancellation import (
    CancellationToken,
    Clock,
)
from pipeline.circuit_breaker import CircuitBreakerPolicy
from pipeline.dependencies import DependencyGraph, get_default_dependency_graph
from pipeline.episode_ids import validate_episode_id
from pipeline.execution import ExecutionId, new_execution_id
from pipeline.executor import ExecutorConfig, PipelineExecutor
from pipeline.retry import RetryPolicy
from pipeline.scheduler import StageScheduler
from pipeline.state import (
    CheckpointManager,
    StageStatus,
    StateStore,
    create_initial_state,
)
from validation.schemas import StageValidator

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOGGER = get_logger("pipeline.concurrent_orchestrator")


class ConcurrentPipelineOrchestrator:
    """
    Concurrent DAG Data-Flow Pipeline Orchestrator.

    Integrates StageScheduler, PipelineExecutor, ArtifactManager,
    and BaseAgentV2/custom agents with immutable parent-artifact input passing,
    failure isolation, cooperative cancellation, and crash-safe M8 persistence.
    """

    def __init__(
        self,
        stages: list[str] | None = None,
        dependency_graph: DependencyGraph | None = None,
        agent_factory: Callable[[str], Callable[..., dict[str, Any]]] | None = None,
        artifact_manager: ArtifactManager | None = None,
        validator: StageValidator | None = None,
        state_store: StateStore | None = None,
        checkpoint_manager: CheckpointManager | None = None,
        cancellation_token: CancellationToken | None = None,
        retry_policy: RetryPolicy | None = None,
        breaker_policy: CircuitBreakerPolicy | None = None,
        max_workers: int | None = None,
        clock: Clock | None = None,
        timeout_seconds: float | None = None,
        stage_timeouts: dict[str, float] | None = None,
    ):
        self.dependency_graph = dependency_graph or get_default_dependency_graph()
        self.stages = stages or self.dependency_graph.get_execution_order()
        self.agent_factory = agent_factory
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.validator = validator or StageValidator()
        self.state_store = state_store or StateStore()
        self.checkpoint_manager = checkpoint_manager or CheckpointManager(self.state_store)
        self.cancellation_token = cancellation_token
        if retry_policy is not None:
            if not retry_policy.retryable_exceptions and retry_policy.classifier is None:
                self.retry_policy = replace(retry_policy, retryable_exceptions=(Exception,))
            else:
                self.retry_policy = retry_policy
        else:
            self.retry_policy = None
        self.breaker_policy = breaker_policy
        self.settings = get_settings()
        self.max_workers = max_workers or self.settings.pipeline.max_parallel_stages or 4
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self.stage_timeouts = stage_timeouts
        self.logger = get_logger("pipeline.concurrent_orchestrator")

    def run(
        self,
        brief_path_or_dict: str | pathlib.Path | dict[str, Any],
        resume: bool = False,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        start_time = time.perf_counter()

        if isinstance(brief_path_or_dict, (str, pathlib.Path)):
            brief = json.loads(pathlib.Path(brief_path_or_dict).read_text(encoding="utf-8"))
        else:
            brief = copy.deepcopy(brief_path_or_dict)

        episode_id = brief.get("episode_id", "UNKNOWN")
        validate_episode_id(episode_id)
        exec_id_obj = new_execution_id()
        pipeline_id = exec_id_obj.value

        brief["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        brief["status"] = "in_progress"
        brief["version"] = 0

        graph = self.dependency_graph
        execution_order = graph.get_execution_order()
        stage_list = [s for s in execution_order if s in self.stages]
        if not stage_list:
            stage_list = [s for s in self.stages if s in graph.stages]

        dependencies_map = {
            stage: [d for d in graph.get_dependencies(stage) if d in stage_list]
            for stage in stage_list
        }

        pipeline_state = None
        if resume:
            pipeline_state = self.checkpoint_manager.restore(episode_id)

        if pipeline_state is None:
            pipeline_state = create_initial_state(episode_id, brief.get("title"), stage_list)
            pipeline_state.status = "running"
            pipeline_state.execution_id = pipeline_id
        else:
            pipeline_state.status = "running"
            if pipeline_state.execution_id:
                try:
                    exec_id_obj = ExecutionId(pipeline_state.execution_id)
                    pipeline_id = exec_id_obj.value
                except Exception:
                    pipeline_state.execution_id = pipeline_id
            else:
                pipeline_state.execution_id = pipeline_id

            for stage in stage_list:
                if pipeline_state.get_stage(stage) is None:
                    pipeline_state.add_stage(stage)

        # Hydrate completed stages and handle resume reconciliation
        completed_on_resume: set[str] = set()
        if resume:
            self.artifact_manager.reconcile_artifacts(episode_id)
            for stage in stage_list:
                st_state = pipeline_state.get_stage(stage)
                try:
                    existing_art = self.artifact_manager.get_latest_artifact(episode_id, stage)
                except Exception:
                    existing_art = None

                if existing_art is not None:
                    completed_on_resume.add(stage)
                    if st_state and st_state.status != StageStatus.COMPLETED:
                        st_state.status = StageStatus.COMPLETED
                        st_state.completed_at = datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat()
                        pipeline_state.update_stage(st_state)
                elif st_state and st_state.status == StageStatus.FAILED:
                    if retry_failed:
                        st_state.status = StageStatus.PENDING
                        st_state.error = None
                        pipeline_state.update_stage(st_state)
                elif st_state and st_state.status in (StageStatus.RUNNING, StageStatus.RETRYING):
                    st_state.status = StageStatus.PENDING
                    st_state.error = None
                    pipeline_state.update_stage(st_state)

        scheduler = StageScheduler(
            stage_list,
            dependencies_map,
            episode_id=episode_id,
            execution_id=exec_id_obj,
        )

        # Advance scheduler for already completed stages in topological order
        for stage in stage_list:
            if stage in completed_on_resume:
                scheduler.complete(stage)
            else:
                st_state = pipeline_state.get_stage(stage)
                if st_state and st_state.status == StageStatus.FAILED and not retry_failed:
                    scheduler.fail(stage, error=st_state.error or "Failed prior run")

        state_lock = threading.Lock()
        completed_stages_list: list[str] = list(completed_on_resume)
        failed_stages_list: list[dict[str, Any]] = []

        def make_worker_callable(stage: str):
            custom_agent = self.agent_factory(stage) if self.agent_factory is not None else None
            stage_agent = None
            if custom_agent is None:
                stage_agent = get_agent_v2(
                    stage,
                    artifact_manager=self.artifact_manager,
                    validator=self.validator,
                )

            def worker_callable(worker_inputs: dict[str, Any]) -> dict[str, Any]:
                deps = dependencies_map.get(stage, [])
                parent_artifacts: dict[str, Any] = {}
                for dep in sorted(deps):
                    art = self.artifact_manager.get_latest_artifact(episode_id, dep)
                    if art is None:
                        raise RuntimeError(
                            f"Stage '{stage}' requires parent artifact from '{dep}', "
                            "but none found on disk"
                        )
                    parent_artifacts[dep] = copy.deepcopy(art)

                # Assemble immutable input snapshot
                stage_inputs: dict[str, Any] = copy.deepcopy(brief)
                stage_inputs["episode_id"] = episode_id
                stage_inputs["stage"] = stage
                stage_inputs["version"] = 0

                if "outputs" not in stage_inputs or not isinstance(stage_inputs["outputs"], dict):
                    stage_inputs["outputs"] = {}

                # Merge parent outputs deterministically in sorted dependency order
                for dep in sorted(deps):
                    parent_art = parent_artifacts[dep]
                    parent_out = parent_art.get("outputs")
                    if isinstance(parent_out, dict):
                        stage_inputs["outputs"][dep] = copy.deepcopy(parent_out)
                        for k, v in parent_out.items():
                            stage_inputs[k] = copy.deepcopy(v)
                            stage_inputs["outputs"][k] = copy.deepcopy(v)
                    elif parent_out is not None:
                        stage_inputs["outputs"][dep] = copy.deepcopy(parent_out)
                        stage_inputs[f"{dep}_out"] = copy.deepcopy(parent_out)

                    # Also copy produced top-level keys if any
                    for key in [
                        "synopsis",
                        "themes",
                        "acts",
                        "beats",
                        "scenes",
                        "total_pages",
                        "breakdown",
                        "characters",
                        "profiles",
                        "rules",
                        "technology",
                        "society",
                        "panels",
                        "key_frames",
                        "vision",
                        "shot_style",
                        "pacing",
                        "lenses",
                        "movement",
                        "lighting",
                        "concept_art",
                        "vfx_breakdown",
                        "color_palette",
                        "animation_style",
                        "key_sequences",
                        "casting",
                        "direction",
                        "recording_notes",
                        "cues",
                        "instrumentation",
                        "tracks",
                        "ducking_points",
                        "transitions",
                        "design",
                        "spot_effects",
                        "ambience",
                        "phoneme_maps",
                        "viseme_schedule",
                        "assembly",
                        "pacing_notes",
                        "timeline_xml",
                        "markers_csv",
                        "checks_passed",
                        "issues",
                        "approval",
                        "deliverables",
                        "specs",
                        "package",
                        "scene_data",
                        "b_out",
                        "c_out",
                        "x_data",
                        "y_data",
                        "out_b",
                        "out_c",
                        "out_d",
                        "root_data",
                        "alpha_out",
                        "beta_out",
                        "writer_out",
                        "b1_data",
                        "b2_data",
                    ]:
                        if key in parent_art and key not in stage_inputs:
                            stage_inputs[key] = copy.deepcopy(parent_art[key])

                if stage == "qa":
                    with state_lock:
                        current_done = list(completed_stages_list)
                    for comp_stage in sorted(current_done):
                        c_art = self.artifact_manager.get_latest_artifact(episode_id, comp_stage)
                        if c_art and isinstance(c_art.get("outputs"), dict):
                            stage_inputs["outputs"][comp_stage] = copy.deepcopy(c_art["outputs"])

                with log_context(pipeline_id=pipeline_id, episode_id=episode_id, stage=stage):
                    token = worker_inputs.get("cancellation_token")
                    if token and token.is_cancelled():
                        raise RuntimeError(f"Stage '{stage}' cancelled before execution")

                    if custom_agent is not None:
                        if hasattr(custom_agent, "run"):
                            agent_out = custom_agent.run(
                                stage_inputs,
                                pipeline_state=pipeline_state,
                                episode_id=episode_id,
                            )
                            with state_lock:
                                completed_stages_list.append(stage)
                                if self.settings.pipeline.checkpoint_enabled:
                                    self.checkpoint_manager.checkpoint(pipeline_state)
                            return agent_out

                        raw_result = custom_agent(stage_inputs)
                        if not isinstance(raw_result, dict):
                            raw_result = {f"{stage}_out": raw_result}

                        # Format payload to store as artifact
                        payload_to_store = {
                            "episode_id": episode_id,
                            "stage": stage,
                            "version": 1,
                            "generated_at": datetime.datetime.now(
                                datetime.timezone.utc
                            ).isoformat(),
                            "inputs": stage_inputs,
                            "outputs": copy.deepcopy(raw_result),
                            **copy.deepcopy(raw_result),
                        }
                        ref = self.artifact_manager.store_stage_output(
                            episode_id=episode_id,
                            stage=stage,
                            output_data=payload_to_store,
                        )
                        with state_lock:
                            st = pipeline_state.get_stage(stage)
                            if st:
                                st.mark_completed(output_path=ref.path)
                                pipeline_state.update_stage(st)
                            completed_stages_list.append(stage)
                            if self.settings.pipeline.checkpoint_enabled:
                                self.checkpoint_manager.checkpoint(pipeline_state)
                        return raw_result
                    else:
                        agent_out = stage_agent.run(
                            stage_inputs,
                            pipeline_state=pipeline_state,
                            episode_id=episode_id,
                        )
                        with state_lock:
                            completed_stages_list.append(stage)
                            if self.settings.pipeline.checkpoint_enabled:
                                self.checkpoint_manager.checkpoint(pipeline_state)
                        return agent_out

            return worker_callable

        executor_config = ExecutorConfig(
            max_workers=self.max_workers,
            agent_factory=make_worker_callable,
            episode_id=episode_id,
            timeout_seconds=self.timeout_seconds,
            stage_timeouts=self.stage_timeouts,
            clock=self.clock,
            retry_policy=self.retry_policy,
            breaker_policy=self.breaker_policy,
        )

        executor = PipelineExecutor(scheduler, executor_config)

        if self.cancellation_token is not None:

            def monitor_cancel():
                while not scheduler.is_finished() and not executor.pipeline_cancelled():
                    if self.cancellation_token.is_cancelled():
                        executor.request_pipeline_cancellation(
                            reason=self.cancellation_token.reason or "cancelled"
                        )
                        break
                    time.sleep(0.01)

            watcher = threading.Thread(target=monitor_cancel, daemon=True)
            watcher.start()

        try:
            results = executor.run()
        except KeyboardInterrupt:
            self.logger.pipeline_failed(
                pipeline_id,
                episode_id,
                "Interrupted by user",
                len(completed_stages_list),
            )
            pipeline_state.status = "interrupted"
            self.state_store.save(pipeline_state)
            self.checkpoint_manager.checkpoint(pipeline_state)
            raise
        except Exception as e:
            self.logger.pipeline_failed(
                pipeline_id,
                episode_id,
                str(e),
                len(completed_stages_list),
            )
            pipeline_state.status = "failed"
            self.state_store.save(pipeline_state)
            self.checkpoint_manager.checkpoint(pipeline_state)
            raise

        for stage in stage_list:
            sched_status = scheduler.status(stage)
            st_state = pipeline_state.get_stage(stage)
            if sched_status == StageStatus.FAILED:
                failed_stages_list.append({"stage": stage, "error": sched_status.name})
                if st_state and st_state.status != StageStatus.FAILED:
                    st_state.mark_failed("Stage failed during concurrent execution")
                    pipeline_state.update_stage(st_state)
            elif sched_status == StageStatus.CANCELLED:
                if st_state and st_state.status != StageStatus.CANCELLED:
                    st_state.status = StageStatus.CANCELLED
                    pipeline_state.update_stage(st_state)

        if self.cancellation_token and self.cancellation_token.is_cancelled():
            pipeline_state.status = "cancelled"
        elif failed_stages_list:
            pipeline_state.status = "failed"
        elif all(scheduler.status(s) == StageStatus.COMPLETED for s in stage_list):
            pipeline_state.status = "completed"
        else:
            pipeline_state.status = "failed"

        pipeline_state.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.state_store.save(pipeline_state)

        duration_ms = (time.perf_counter() - start_time) * 1000
        summary = {
            "pipeline_id": pipeline_id,
            "episode_id": episode_id,
            "title": brief.get("title"),
            "stages_total": len(stage_list),
            "stages_completed": len(set(completed_stages_list)),
            "stages_failed": len(failed_stages_list),
            "status": pipeline_state.status,
            "completed_stages": sorted(set(completed_stages_list)),
            "failed_stages": failed_stages_list,
            "duration_ms": duration_ms,
        }

        summary_file = ROOT / "outputs" / f"{episode_id}_pipeline_summary.json"
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(summary_file, json.dumps(summary, indent=2))

        return {
            "summary": summary,
            **summary,
            "pipeline_state": pipeline_state,
            "results": results,
        }


def run(
    brief_path: str,
    resume: bool = False,
    retry_failed: bool = False,
    max_workers: int | None = None,
) -> dict[str, Any]:
    orchestrator = ConcurrentPipelineOrchestrator(max_workers=max_workers)
    return orchestrator.run(brief_path, resume=resume, retry_failed=retry_failed)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ANANTA Multi-Agent Concurrent Production Pipeline")
    ap.add_argument("--brief", required=True, help="Path to episode brief JSON")
    ap.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    ap.add_argument("--retry-failed", action="store_true", help="Retry failed stages on resume")
    ap.add_argument("--workers", type=int, default=None, help="Max parallel workers")
    args = ap.parse_args()

    try:
        run(
            args.brief, resume=args.resume, retry_failed=args.retry_failed, max_workers=args.workers
        )
    except KeyboardInterrupt:
        LOGGER.error("Concurrent pipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        LOGGER.error(f"Concurrent pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
