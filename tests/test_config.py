from config import Settings, get_settings, reload_settings


def test_config_defaults(mock_env):
    reload_settings()
    settings = get_settings()
    assert settings.ollama.base_url == "http://localhost:11434"
    assert settings.ollama.model is None
    assert settings.ollama.timeout == 120
    assert settings.ollama.max_retries == 3
    assert settings.ollama.temperature == 0.7
    assert settings.ollama.enabled is False


def test_config_from_env(ollama_env):
    reload_settings()
    settings = get_settings()
    assert settings.ollama.model == "llama3.1"
    assert settings.ollama.base_url == "http://localhost:11434"
    assert settings.ollama.timeout == 120
    assert settings.ollama.max_retries == 3
    assert settings.ollama.temperature == 0.7
    assert settings.ollama.enabled is True


def test_config_from_yaml(tmp_path):
    yaml_content = """
ollama:
  base_url: "http://custom:11434"
  model: "custom-model"
  timeout: 60
  max_retries: 2
  temperature: 0.5
pipeline:
  stages: ["story", "screenplay"]
output:
  root_dir: "custom_outputs"
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content)
    settings = Settings.load_yaml(config_file)
    assert settings.ollama.base_url == "http://custom:11434"
    assert settings.ollama.model == "custom-model"
    assert settings.ollama.timeout == 60
    assert settings.ollama.max_retries == 2
    assert settings.ollama.temperature == 0.5
    assert settings.ollama.enabled is True
    assert settings.pipeline.stages == ["story", "screenplay"]
    assert settings.output.root_dir == "custom_outputs"


def test_env_overrides_yaml(tmp_path, monkeypatch):
    yaml_content = """
ollama:
  base_url: "http://yaml:11434"
  model: "yaml-model"
"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml_content)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://env:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "env-model")
    settings = Settings.load_yaml(config_file)
    assert settings.ollama.base_url == "http://env:11434"
    assert settings.ollama.model == "env-model"


def test_pipeline_stages_default(mock_env):
    reload_settings()
    settings = get_settings()
    expected_stages = [
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
    assert settings.pipeline.stages == expected_stages
