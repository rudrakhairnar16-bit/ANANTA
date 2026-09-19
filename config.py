import os
from pathlib import Path

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


class PipelineSettings(BaseModel):
    stages: list[str] = Field(default_factory=lambda: [
        "story", "screenplay", "scene_plan", "character", "world",
        "storyboard", "director", "camera", "visual", "motion",
        "voice", "music", "bgm", "sfx", "lipsync",
        "edit", "adobe_export", "qa", "export"
    ])


class OutputSettings(BaseModel):
    root_dir: str = "outputs"
    stage_dirs: dict[str, str] = Field(default_factory=dict)


class Settings(BaseModel):
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)

    def apply_yaml(self, path: str | Path) -> "Settings":
        """Apply YAML config as defaults."""
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
                    setattr(self.pipeline, key, value)

        output_data = data.get("output", {})
        if output_data:
            for key, value in output_data.items():
                if value is not None and hasattr(self.output, key):
                    setattr(self.output, key, value)

        return self

    def load_env(self) -> "Settings":
        """Load environment variables (highest priority)."""
        self.ollama.load_from_env()
        return self

    @classmethod
    def load_yaml(cls, path: str | Path) -> "Settings":
        """Load settings from YAML file, then apply env vars."""
        settings = cls()
        settings.apply_yaml(path)
        settings.load_env()
        return settings


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
