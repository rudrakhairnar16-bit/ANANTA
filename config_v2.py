import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class OllamaSettings(BaseModel):
    base_url: str = Field(default="http://localhost:11434")
    model: str | None = Field(default=None)
    timeout: int = Field(default=120)
    max_retries: int = Field(default=3)
    temperature: float = Field(default=0.7)

    @property
    def enabled(self) -> bool:
        return self.model is not None and len(self.model.strip()) > 0

    def load_from_env(self) -> "OllamaSettings":
        self.base_url = os.getenv("OLLAMA_BASE_URL", self.base_url)
        self.model = os.getenv("OLLAMA_MODEL", self.model)
        if self.model == "":
            self.model = None
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT", str(self.timeout)))
        self.max_retries = int(os.getenv("OLLAMA_MAX_RETRIES", str(self.max_retries)))
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", str(self.temperature)))
        return self


class ProviderSettings(BaseModel):
    type: str = "mock"
    timeout: float = 120.0
    max_retries: int = 3
    temperature: float = 0.7
    extra: dict[str, Any] = Field(default_factory=dict)


class StageSettings(BaseModel):
    provider: ProviderSettings = Field(default_factory=lambda: ProviderSettings(type="mock"))
    optional: bool = False
    timeout_seconds: float = 300.0
    max_retries: int = 3
    validate_input: bool = True
    validate_output: bool = True
    parallel_group: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PipelineSettings(BaseModel):
    stages: list[str] = Field(default_factory=lambda: [
        "story", "screenplay", "scene_plan", "character", "world",
        "storyboard", "director", "camera", "visual", "motion",
        "voice", "music", "bgm", "sfx", "lipsync",
        "edit", "adobe_export", "qa", "export"
    ])
    stage_settings: dict[str, StageSettings] = Field(default_factory=dict)
    execution_mode: str = "sequential"
    max_parallel_stages: int = 4
    checkpoint_enabled: bool = True
    checkpoint_interval: int = 1
    artifact_versioning: bool = True
    failure_recovery: bool = True


class OutputSettings(BaseModel):
    root_dir: str = "outputs"
    stage_dirs: dict[str, str] = Field(default_factory=dict)
    state_dir: str = "outputs/state"
    artifact_dir: str = "outputs/artifacts"
    log_dir: str = "outputs/logs"


class ObservabilitySettings(BaseModel):
    log_level: str = "INFO"
    json_logs: bool = True
    log_correlation_ids: bool = True
    metrics_enabled: bool = True
    tracing_enabled: bool = False
    log_dir: str = "outputs/logs"


class Settings(BaseModel):
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    def apply_yaml(self, path: str | Path) -> "Settings":
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        ollama_data = data.get("ollama", {})
        if ollama_data:
            for key, value in ollama_data.items():
                if value is not None and hasattr(self.ollama, key):
                    setattr(self.ollama, key, value)

        pipeline_data = data.get("pipeline", {})
        if pipeline_data:
            for key, value in pipeline_data.items():
                if value is not None and hasattr(self.pipeline, key):
                    if key == "stage_settings" and isinstance(value, dict):
                        self.pipeline.stage_settings = {
                            k: StageSettings(**v) if isinstance(v, dict) else v
                            for k, v in value.items()
                        }
                    else:
                        setattr(self.pipeline, key, value)

        output_data = data.get("output", {})
        if output_data:
            for key, value in output_data.items():
                if value is not None and hasattr(self.output, key):
                    setattr(self.output, key, value)

        observability_data = data.get("observability", {})
        if observability_data:
            for key, value in observability_data.items():
                if value is not None and hasattr(self.observability, key):
                    setattr(self.observability, key, value)

        return self

    def load_env(self) -> "Settings":
        self.ollama.load_from_env()

        if os.getenv("PIPELINE_EXECUTION_MODE"):
            self.pipeline.execution_mode = os.getenv("PIPELINE_EXECUTION_MODE", self.pipeline.execution_mode)

        if os.getenv("PIPELINE_MAX_PARALLEL"):
            self.pipeline.max_parallel_stages = int(os.getenv("PIPELINE_MAX_PARALLEL"))

        if os.getenv("PIPELINE_CHECKPOINT_ENABLED"):
            self.pipeline.checkpoint_enabled = os.getenv("PIPELINE_CHECKPOINT_ENABLED").lower() == "true"

        if os.getenv("LOG_LEVEL"):
            self.observability.log_level = os.getenv("LOG_LEVEL")

        if os.getenv("JSON_LOGS"):
            self.observability.json_logs = os.getenv("JSON_LOGS").lower() == "true"

        return self

    @classmethod
    def load_yaml(cls, path: str | Path) -> "Settings":
        settings = cls()
        settings.apply_yaml(path)
        settings.load_env()
        return settings

    def get_stage_settings(self, stage: str) -> StageSettings:
        return self.pipeline.stage_settings.get(stage, StageSettings())


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        config_path = Path(__file__).parent / "config.yaml"
        if config_path.exists():
            _settings = Settings.load_yaml(config_path)
        else:
            _settings = Settings().load_env()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = None
    return get_settings()
