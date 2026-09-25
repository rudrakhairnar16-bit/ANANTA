import datetime
import json
import pathlib
import time
from typing import Any

from config_v2 import get_settings
from observability.logging import get_logger, log_context
from pipeline.artifacts import ArtifactManager
from pipeline.atomic_io import atomic_write_text
from pipeline.dependencies import StageSpec, get_default_dependency_graph
from pipeline.recovery import StageRecoveryManager
from pipeline.state import PipelineState
from providers.base_v2 import BaseProviderV2, ProviderResponse
from providers.registry_v2 import get_provider_for_stage_v2
from validation.schemas import SchemaValidationError, StageValidator, ValidationFeedback

ROOT = pathlib.Path(__file__).resolve().parents[1]

DEFAULT_STAGE_DIRS = {
    "story": "outputs/scripts",
    "screenplay": "outputs/scripts",
    "scene_plan": "outputs/scripts",
    "character": "outputs/character",
    "world": "outputs/world",
    "storyboard": "outputs/storyboard",
    "director": "outputs/director",
    "camera": "outputs/camera",
    "visual": "outputs/visual",
    "motion": "outputs/motion",
    "voice": "outputs/voice",
    "music": "outputs/music",
    "bgm": "outputs/bgm",
    "sfx": "outputs/sfx",
    "lipsync": "outputs/lipsync",
    "edit": "outputs/edit",
    "adobe_export": "outputs/adobe_export",
    "qa": "outputs/qa",
    "export": "outputs/export",
}


class BaseAgentV2:
    def __init__(
        self,
        stage: str,
        provider: BaseProviderV2 | None = None,
        artifact_manager: ArtifactManager | None = None,
        validator: StageValidator | None = None,
        recovery_manager: StageRecoveryManager | None = None,
        logger: Any | None = None,
    ):
        self.stage = stage
        self.provider = provider
        self.artifact_manager = artifact_manager or ArtifactManager()
        self.validator = validator or StageValidator()
        self.recovery_manager = recovery_manager or StageRecoveryManager()
        self.logger = logger or get_logger(f"agent.{stage}")
        self._stage_spec = self._get_stage_spec()
        self._last_validation_feedback: ValidationFeedback | None = None
        self._current_episode_id: str | None = None
        self._attempt_count: int = 0

    def __call__(self, inputs: dict[str, Any], **kwargs) -> dict[str, Any]:
        return self.run(inputs, **kwargs)

    def reset_feedback(self):
        self._last_validation_feedback = None
        self._current_episode_id = None
        self._attempt_count = 0

    def _get_stage_spec(self) -> StageSpec | None:
        graph = get_default_dependency_graph()
        return graph.stages.get(self.stage)

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        if not self._stage_spec or not self._stage_spec.required_inputs:
            return True

        outputs = inputs.get("outputs", {}) if isinstance(inputs.get("outputs"), dict) else {}

        for req in self._stage_spec.required_inputs:
            if req == "all":
                continue
            found = req in inputs or req in outputs
            if not found:
                return False
        return True

    def process(self, inputs: dict[str, Any]) -> ProviderResponse:
        if self.provider is None:
            raise RuntimeError(f"No provider configured for {self.stage}")
        return self.provider.generate_sync(inputs)

    def run(
        self,
        inputs: dict[str, Any],
        pipeline_state: PipelineState | None = None,
        episode_id: str | None = None,
    ) -> dict[str, Any]:
        if not self.validate_inputs(inputs):
            raise ValueError(f"Invalid inputs for {self.stage} agent")

        episode_id = episode_id or inputs.get("episode_id", "UNKNOWN")

        if self._current_episode_id != episode_id:
            self._current_episode_id = episode_id
            self._last_validation_feedback = None
            self._attempt_count = 0

        self._attempt_count += 1

        if (
            self._last_validation_feedback is not None
            and self._last_validation_feedback.stage == self.stage
        ):
            inputs["validation_feedback"] = self._last_validation_feedback.to_dict()
            inputs["validation_feedback_text"] = (
                self._last_validation_feedback.format_prompt_instruction()
            )

        with log_context(episode_id=episode_id, stage=self.stage):
            self.logger.stage_start(self.stage, 0, 1)

            start_time = time.perf_counter()

            def execute():
                return self.process(inputs)

            def on_retry(attempt: int, error: Exception):
                self.logger.warning(
                    f"Retrying stage {self.stage}",
                    stage=self.stage,
                    attempt=attempt,
                    error=str(error),
                )

            success, response, error_msg = self.recovery_manager.execute_stage(
                self.stage,
                execute,
                is_optional=self._stage_spec.optional if self._stage_spec else False,
                on_retry=on_retry,
            )

            duration_ms = (time.perf_counter() - start_time) * 1000

            if not success:
                self.logger.stage_failed(self.stage, 0, error_msg or "Unknown error", duration_ms)
                if pipeline_state:
                    stage_state = pipeline_state.get_stage(self.stage)
                    if stage_state:
                        stage_state.mark_failed(error_msg or "Unknown error")
                        pipeline_state.update_stage(stage_state)
                raise RuntimeError(f"Stage {self.stage} failed: {error_msg}")

            if not response.success:
                self.logger.stage_failed(
                    self.stage,
                    0,
                    response.error or "Provider error",
                    duration_ms,
                )
                if pipeline_state:
                    stage_state = pipeline_state.get_stage(self.stage)
                    if stage_state:
                        stage_state.mark_failed(response.error or "Provider error")
                        pipeline_state.update_stage(stage_state)
                raise RuntimeError(f"Stage {self.stage} failed: {response.error}")

            result_data = response.data or {}
            result_data["episode_id"] = episode_id
            result_data["stage"] = self.stage
            result_data["version"] = inputs.get("version", 1) + 1
            result_data["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            result_data["inputs"] = {k: v for k, v in inputs.items() if k != "cancellation_token"}
            result_data["approval_status"] = "pending"

            # Attach / synchronize provider metadata
            provider_type = (
                getattr(self.provider, "provider_type", "mock")
                if self.provider
                else "mock"
            )
            provider_name = (
                getattr(self.provider.config, "name", type(self.provider).__name__)
                if self.provider and hasattr(self.provider, "config")
                else (type(self.provider).__name__ if self.provider else "None")
            )
            is_fallback = (
                getattr(self.provider, "is_fallback", False)
                if self.provider
                else False
            )
            model_name = (
                getattr(self.provider, "model", None)
                if self.provider and provider_type == "ollama"
                else None
            )

            if "metadata" not in result_data or not isinstance(result_data.get("metadata"), dict):
                result_data["metadata"] = {}

            result_data["metadata"]["provider_name"] = provider_name
            result_data["metadata"]["provider_type"] = provider_type
            result_data["metadata"]["is_fallback"] = is_fallback
            result_data["metadata"]["model_name"] = model_name

            if is_fallback:
                fallback_from = getattr(self.provider, "fallback_from_provider", "ollama")
                result_data["metadata"]["fallback_from"] = fallback_from
                if "warnings" not in result_data or not isinstance(
                    result_data.get("warnings"), list
                ):
                    result_data["warnings"] = []
                fallback_warning = (
                    f"Fallback to mock provider executed for stage '{self.stage}' "
                    f"because configured real provider was unavailable."
                )
                if fallback_warning not in result_data["warnings"]:
                    result_data["warnings"].append(fallback_warning)

            validation_result = self.validator.validate_output(self.stage, result_data)
            if not validation_result.valid:
                error_messages = "; ".join(e.message for e in validation_result.errors)
                self.logger.stage_failed(
                    self.stage,
                    0,
                    f"Output validation failed: {error_messages}",
                    duration_ms,
                )
                if pipeline_state:
                    stage_state = pipeline_state.get_stage(self.stage)
                    if stage_state:
                        stage_state.mark_failed(f"Output validation failed: {error_messages}")
                        pipeline_state.update_stage(stage_state)

                errors_list = [e.message for e in validation_result.errors]
                feedback = ValidationFeedback(
                    stage=self.stage,
                    attempt=self._attempt_count,
                    errors=errors_list,
                    message=error_messages,
                    previous_output=result_data.get("outputs"),
                )
                self._last_validation_feedback = feedback

                raise SchemaValidationError(
                    f"Output validation failed for stage '{self.stage}': {error_messages}",
                    feedback=feedback,
                    errors=errors_list,
                    stage=self.stage,
                )

            self._last_validation_feedback = None

            if pipeline_state:
                stage_state = pipeline_state.get_stage(self.stage)
                if stage_state:
                    stage_state.metrics = response.metrics.to_dict() if response.metrics else None

            artifact_ref = self.artifact_manager.store_stage_output(
                episode_id=episode_id,
                stage=self.stage,
                output_data=result_data,
            )

            if pipeline_state:
                stage_state = pipeline_state.get_stage(self.stage)
                if stage_state:
                    stage_state.mark_completed(
                        output_path=artifact_ref.path,
                        metrics=stage_state.metrics,
                    )
                    pipeline_state.update_stage(stage_state)

            self._write_output_legacy(result_data, episode_id)

            self.logger.stage_complete(self.stage, 0, duration_ms)
            self.logger.artifact_written(
                self.stage,
                artifact_ref.path,
                len(json.dumps(result_data).encode()),
            )

            merged = {**inputs, **result_data}
            has_outputs_merge = (
                "outputs" in inputs
                and isinstance(inputs["outputs"], dict)
                and "outputs" in result_data
                and isinstance(result_data["outputs"], dict)
            )
            if has_outputs_merge:
                merged["outputs"] = {**inputs["outputs"], **result_data["outputs"]}
            if "inputs" in inputs and isinstance(inputs["inputs"], dict):
                for key in [
                    "characters",
                    "locations",
                    "scenes",
                    "title",
                    "logline",
                    "duration_seconds",
                ]:
                    if key in inputs["inputs"] and key not in merged:
                        merged[key] = inputs["inputs"][key]

            return merged

    def _write_output_legacy(self, data: dict[str, Any], episode_id: str):
        output_dir = ROOT / DEFAULT_STAGE_DIRS.get(self.stage, f"outputs/{self.stage}")
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / f"{episode_id}_{self.stage}.json"
        atomic_write_text(output_file, json.dumps(data, indent=2))
        self.logger.info(
            f"Written to {output_file}",
            stage=self.stage,
            path=str(output_file),
        )


class StoryAgentV2(BaseAgentV2):
    def __init__(
        self,
        provider: BaseProviderV2 | None = None,
        **kwargs,
    ):
        if provider is None:
            settings = get_settings()
            use_ollama = settings.ollama.enabled
            provider = get_provider_for_stage_v2("story", use_ollama=use_ollama)
        super().__init__("story", provider=provider, **kwargs)

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "episode_id" in inputs and "title" in inputs

    def process(self, inputs: dict[str, Any]) -> ProviderResponse:
        return self.provider.generate_sync(inputs)


class VoiceAgentV2(BaseAgentV2):
    def __init__(
        self,
        provider: BaseProviderV2 | None = None,
        tts_provider: Any | None = None,
        generate_audio: bool = False,
        **kwargs,
    ):
        if provider is None:
            settings = get_settings()
            stage_settings = settings.get_stage_settings("voice")
            use_ollama = stage_settings.provider.type == "ollama"
            provider = get_provider_for_stage_v2("voice", use_ollama=use_ollama)
        super().__init__("voice", provider=provider, **kwargs)
        self.tts_provider = tts_provider
        self.generate_audio = generate_audio

    def run(
        self,
        inputs: dict[str, Any],
        pipeline_state: PipelineState | None = None,
        episode_id: str | None = None,
    ) -> dict[str, Any]:
        result = super().run(inputs, pipeline_state=pipeline_state, episode_id=episode_id)

        if self.generate_audio or self.tts_provider is not None:
            from pipeline.dialogue_extractor import extract_dialogue
            from providers.registry_v2 import get_tts_provider

            tts = self.tts_provider or get_tts_provider("mock")
            ep_id = episode_id or inputs.get("episode_id", "UNKNOWN")
            lines = extract_dialogue(inputs)

            if lines:
                audio_meta = tts.synthesize_dialogue(lines, episode_id=ep_id)
                audio_dicts = [a.to_dict() for a in audio_meta]
                result["audio_files"] = audio_dicts
                if "outputs" in result and isinstance(result["outputs"], dict):
                    result["outputs"]["audio_files"] = audio_dicts
                    result["outputs"]["dialogue_lines"] = [line.to_dict() for line in lines]
                    result["outputs"]["total_audio_duration_seconds"] = sum(
                        a.duration_seconds for a in audio_meta
                    )

                self.artifact_manager.store_stage_output(
                    episode_id=ep_id,
                    stage="voice",
                    output_data=result,
                )

        return result


def create_agent_v2(
    stage: str,
    provider: BaseProviderV2 | None = None,
    **kwargs,
) -> BaseAgentV2:
    settings = get_settings()
    stage_settings = settings.get_stage_settings(stage)

    if provider is None:
        use_ollama = stage_settings.provider.type == "ollama"
        provider = get_provider_for_stage_v2(stage, use_ollama=use_ollama)

    return BaseAgentV2(stage, provider=provider, **kwargs)


AGENT_REGISTRY_V2 = {
    "story": StoryAgentV2,
    "voice": VoiceAgentV2,
}


def get_agent_v2(stage: str, **kwargs) -> BaseAgentV2:
    agent_class = AGENT_REGISTRY_V2.get(stage)
    if agent_class:
        return agent_class(**kwargs)
    return create_agent_v2(stage, **kwargs)
