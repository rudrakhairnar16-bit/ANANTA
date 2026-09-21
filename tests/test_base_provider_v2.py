from providers.base_v2 import (
    MockProviderV2,
    ProviderConfig,
    ProviderError,
    ProviderMetrics,
    ProviderResponse,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderValidationError,
)


def test_provider_config_creation():
    config = ProviderConfig(name="TestProvider", timeout=60.0, max_retries=5, temperature=0.5)
    assert config.name == "TestProvider"
    assert config.timeout == 60.0
    assert config.max_retries == 5
    assert config.temperature == 0.5


def test_provider_config_to_dict():
    config = ProviderConfig(name="TestProvider", extra={"key": "value"})
    d = config.to_dict()
    assert d["name"] == "TestProvider"
    assert d["extra"]["key"] == "value"


def test_provider_metrics_record_success():
    metrics = ProviderMetrics()
    metrics.record_success(100.0, {"prompt": 10, "completion": 20, "total": 30})
    assert metrics.latency_ms == 100.0
    assert metrics.success_count == 1
    assert metrics.tokens_prompt == 10
    assert metrics.tokens_completion == 20
    assert metrics.tokens_total == 30
    assert metrics.last_success_at is not None


def test_provider_metrics_record_error():
    metrics = ProviderMetrics()
    metrics.record_error("Connection failed")
    assert metrics.error_count == 1
    assert metrics.last_error == "Connection failed"


def test_provider_metrics_record_retry():
    metrics = ProviderMetrics()
    metrics.record_retry()
    assert metrics.retry_count == 1


def test_provider_response_success():
    metrics = ProviderMetrics()
    response = ProviderResponse.success_response(
        data={"key": "value"},
        provider_name="TestProvider",
        metrics=metrics,
    )
    assert response.success is True
    assert response.data == {"key": "value"}
    assert response.provider_name == "TestProvider"
    assert response.metrics == metrics
    assert response.request_id is not None


def test_provider_response_error():
    metrics = ProviderMetrics()
    response = ProviderResponse.error_response(
        error="Test error",
        provider_name="TestProvider",
        metrics=metrics,
    )
    assert response.success is False
    assert response.error == "Test error"
    assert response.provider_name == "TestProvider"


def test_mock_provider_v2_creation():
    provider = MockProviderV2("story", seed=42)
    assert provider.stage == "story"
    assert provider.seed == 42
    assert provider.config.name == "MockProvider_story"


def test_mock_provider_v2_generate_sync():
    provider = MockProviderV2("story", seed=42)
    inputs = {"episode_id": "TEST-E01", "title": "Test"}
    response = provider.generate_sync(inputs)

    assert response.success is True
    assert response.data is not None
    assert response.data["episode_id"] == "TEST-E01"
    assert response.data["stage"] == "story"
    assert "outputs" in response.data
    assert "synopsis" in response.data["outputs"]
    assert response.provider_name == "MockProvider_story"
    assert response.metrics is not None


def test_mock_provider_v2_all_stages():
    stages = [
        "story", "screenplay", "scene_plan", "character", "world",
        "storyboard", "director", "camera", "visual", "motion",
        "voice", "music", "bgm", "sfx", "lipsync",
        "edit", "adobe_export", "qa", "export"
    ]

    for stage in stages:
        provider = MockProviderV2(stage)
        response = provider.generate_sync({"episode_id": "TEST", "title": "Test"})
        assert response.success is True
        assert response.data["stage"] == stage


def test_mock_provider_v2_deterministic():
    provider1 = MockProviderV2("story", seed=42)
    provider2 = MockProviderV2("story", seed=42)

    response1 = provider1.generate_sync({"episode_id": "TEST", "title": "Test"})
    response2 = provider2.generate_sync({"episode_id": "TEST", "title": "Test"})

    assert response1.data["outputs"]["synopsis"] == response2.data["outputs"]["synopsis"]


def test_mock_provider_v2_different_seeds():
    provider1 = MockProviderV2("story", seed=42)
    provider2 = MockProviderV2("story", seed=123)

    response1 = provider1.generate_sync({"episode_id": "TEST", "title": "Test"})
    response2 = provider2.generate_sync({"episode_id": "TEST", "title": "Test"})

    assert response1.data["outputs"]["synopsis"] != response2.data["outputs"]["synopsis"]


def test_provider_exceptions():
    assert issubclass(ProviderUnavailableError, ProviderError)
    assert issubclass(ProviderTimeoutError, ProviderError)
    assert issubclass(ProviderValidationError, ProviderError)


def test_ollama_provider_extract_json_valid():
    from providers.base_v2 import OllamaProviderV2

    provider = OllamaProviderV2()
    result = provider._extract_json_from_text(
        'Here is the result: {"synopsis": "test", "themes": ["a"], "acts": 1, "beats": ["b"]}'
    )
    assert isinstance(result, dict)
    assert result["synopsis"] == "test"
    assert result["themes"] == ["a"]


def test_ollama_provider_extract_json_no_json():
    from providers.base_v2 import OllamaProviderV2

    provider = OllamaProviderV2()
    result = provider._extract_json_from_text("No JSON here at all")
    assert result == {}


def test_ollama_provider_extract_json_nested():
    from providers.base_v2 import OllamaProviderV2

    provider = OllamaProviderV2()
    result = provider._extract_json_from_text(
        'Text before {"key": "value"} and more text'
    )
    assert result == {"key": "value"}


def test_ollama_provider_parse_response_valid_json():
    from providers.base_v2 import OllamaProviderV2

    provider = OllamaProviderV2()
    response = {
        "response": '{"synopsis": "AI story", "themes": ["ethics"], "acts": 3, "beats": ["intro"]}'
    }
    result = provider._parse_response(response, {"episode_id": "TEST"})
    assert result["outputs"]["synopsis"] == "AI story"
    assert result["outputs"]["themes"] == ["ethics"]
    assert result["stage"] == "story"
    assert result["episode_id"] == "TEST"


def test_ollama_provider_parse_response_non_json():
    from providers.base_v2 import OllamaProviderV2

    provider = OllamaProviderV2()
    response = {"response": "This is plain text without any JSON"}
    result = provider._parse_response(response, {"episode_id": "TEST"})
    assert result["outputs"]["synopsis"] == "This is plain text without any JSON"
    assert result["outputs"]["themes"] == []
    assert result["outputs"]["acts"] == 3
