from config_v2 import (
    ObservabilitySettings,
    OllamaSettings,
    OutputSettings,
    PipelineSettings,
    ProviderSettings,
    Settings,
    StageSettings,
    get_settings,
    reload_settings,
)


def test_ollama_settings_defaults():
    settings = OllamaSettings()
    assert settings.base_url == "http://localhost:11434"
    assert settings.model is None
    assert settings.timeout == 120
    assert settings.max_retries == 3
    assert settings.temperature == 0.7
    assert settings.enabled is False


def test_ollama_settings_enabled():
    settings = OllamaSettings(model="llama3.1")
    assert settings.enabled is True


def test_ollama_settings_load_from_env(monkeypatch):
    settings = OllamaSettings()
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://custom:11434")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "60")
    monkeypatch.setenv("OLLAMA_MAX_RETRIES", "2")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.5")

    settings.load_from_env()
    assert settings.model == "test-model"
    assert settings.base_url == "http://custom:11434"
    assert settings.timeout == 60
    assert settings.max_retries == 2
    assert settings.temperature == 0.5
    assert settings.enabled is True


def test_provider_settings():
    settings = ProviderSettings(type="ollama", timeout=60.0, max_retries=5, temperature=0.5)
    assert settings.type == "ollama"
    assert settings.timeout == 60.0
    assert settings.max_retries == 5
    assert settings.temperature == 0.5


def test_stage_settings():
    settings = StageSettings(
        provider=ProviderSettings(type="mock"),
        optional=False,
        timeout_seconds=300.0,
        max_retries=3,
        validate_input=True,
        validate_output=True,
    )
    assert settings.provider.type == "mock"
    assert settings.optional is False
    assert settings.timeout_seconds == 300.0
    assert settings.max_retries == 3
    assert settings.validate_input is True
    assert settings.validate_output is True


def test_pipeline_settings_defaults():
    settings = PipelineSettings()
    assert len(settings.stages) == 19
    assert settings.execution_mode == "sequential"
    assert settings.max_parallel_stages == 4
    assert settings.checkpoint_enabled is True
    assert settings.checkpoint_interval == 1
    assert settings.artifact_versioning is True
    assert settings.failure_recovery is True


def test_output_settings():
    settings = OutputSettings(
        root_dir="custom_outputs",
        state_dir="custom_outputs/state",
        artifact_dir="custom_outputs/artifacts",
    )
    assert settings.root_dir == "custom_outputs"
    assert settings.state_dir == "custom_outputs/state"
    assert settings.artifact_dir == "custom_outputs/artifacts"


def test_observability_settings():
    settings = ObservabilitySettings(
        log_level="DEBUG",
        json_logs=True,
        log_correlation_ids=True,
        metrics_enabled=True,
        tracing_enabled=False,
    )
    assert settings.log_level == "DEBUG"
    assert settings.json_logs is True
    assert settings.log_correlation_ids is True
    assert settings.metrics_enabled is True
    assert settings.tracing_enabled is False


def test_settings_creation():
    settings = Settings()
    assert settings.ollama is not None
    assert settings.pipeline is not None
    assert settings.output is not None
    assert settings.observability is not None


def test_settings_apply_yaml(tmp_path):
    yaml_content = """
ollama:
  base_url: "http://yaml:11434"
  model: "yaml-model"
  timeout: 60
pipeline:
  execution_mode: "parallel"
  max_parallel_stages: 8
output:
  root_dir: "custom_outputs"
observability:
  log_level: "DEBUG"
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content)

    settings = Settings.load_yaml(config_file)
    assert settings.ollama.base_url == "http://yaml:11434"
    assert settings.ollama.model == "yaml-model"
    assert settings.ollama.timeout == 60
    assert settings.pipeline.execution_mode == "parallel"
    assert settings.pipeline.max_parallel_stages == 8
    assert settings.output.root_dir == "custom_outputs"
    assert settings.observability.log_level == "DEBUG"


def test_settings_env_overrides_yaml(tmp_path, monkeypatch):
    yaml_content = """
ollama:
  base_url: "http://yaml:11434"
  model: "yaml-model"
pipeline:
  execution_mode: "sequential"
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content)

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://env:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")
    monkeypatch.setenv("PIPELINE_EXECUTION_MODE", "parallel")
    monkeypatch.setenv("PIPELINE_MAX_PARALLEL", "16")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    settings = Settings.load_yaml(config_file)
    assert settings.ollama.base_url == "http://env:11434"
    assert settings.ollama.model == "env-model"
    assert settings.pipeline.execution_mode == "parallel"
    assert settings.pipeline.max_parallel_stages == 16
    assert settings.observability.log_level == "WARNING"


def test_settings_get_stage_settings():
    settings = Settings()
    settings.pipeline.stage_settings["story"] = StageSettings(
        provider=ProviderSettings(type="ollama"),
        optional=False,
    )
    stage_settings = settings.get_stage_settings("story")
    assert stage_settings.provider.type == "ollama"

    default_settings = settings.get_stage_settings("unknown")
    assert default_settings.provider.type == "mock"


def test_get_settings_singleton(mock_env):
    reload_settings()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_reload_settings():
    reload_settings()
    s1 = get_settings()
    reload_settings()
    s2 = get_settings()
    assert s1 is not s2
