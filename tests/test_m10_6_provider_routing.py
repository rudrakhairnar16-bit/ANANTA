import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from config_v2 import OllamaSettings, reload_settings
from providers.base_v2 import (
    MockProviderV2,
    OllamaProviderV2,
    ProviderConfig,
    ProviderUnavailableError,
)
from providers.registry_v2 import (
    ModelRouter,
    ProviderRegistry,
    ProviderRegistryConfig,
    StageProviderConfig,
)


class TestM106ProviderRoutingAndFallback:
    """
    M10.6 Task 2 Test Suite:
    Provider Routing, Fail-Fast by Default & Explicit Mock Fallback.
    """

    def test_healthy_ollama_endpoint_routes_to_ollama_provider(self):
        """1. Healthy Ollama endpoint routes to OllamaProviderV2."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=False,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        mock_ok = MagicMock(spec=httpx.Response)
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"models": [{"name": "llama3.1:latest"}]}

        with patch("httpx.Client.get", return_value=mock_ok):
            provider = router.route("story", prefer_ollama=True)
            assert isinstance(provider, OllamaProviderV2)
            assert provider.model == "llama3.1"

    def test_unavailable_ollama_fails_fast_when_fallback_disabled(self):
        """2. Unavailable Ollama endpoint raises error when fallback is disabled."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=False,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        with patch(
            "httpx.Client.get",
            side_effect=httpx.ConnectError("Connection refused to http://localhost:11434"),
        ):
            with pytest.raises(ProviderUnavailableError) as exc_info:
                router.route("story", prefer_ollama=True, allow_fallback=False)
            err_msg = str(exc_info.value)
            assert "unavailable" in err_msg.lower() or "connect" in err_msg.lower()
            assert "fallback is disabled" in err_msg.lower()

    def test_missing_model_fails_fast_when_fallback_disabled(self):
        """3. Missing configured model raises ProviderUnavailableError when fallback is disabled."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=False,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        mock_ok = MagicMock(spec=httpx.Response)
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"models": [{"name": "mistral:latest"}]}

        with patch("httpx.Client.get", return_value=mock_ok):
            with pytest.raises(ProviderUnavailableError) as exc_info:
                router.route("story", prefer_ollama=True, allow_fallback=False)
            err_msg = str(exc_info.value)
            assert "llama3.1" in err_msg
            assert "not available" in err_msg.lower() or "missing" in err_msg.lower()

    def test_explicit_fallback_routes_to_mock_and_records_warning(self, caplog):
        """4. Explicit fallback configuration routes to MockProviderV2 and logs a warning."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=True,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        with (
            patch(
                "httpx.Client.get",
                side_effect=httpx.ConnectError("Connection refused to http://localhost:11434"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            provider = router.route("story", prefer_ollama=True, allow_fallback=True)
            assert isinstance(provider, MockProviderV2)
            assert provider.stage == "story"
            # Verify clear warning was recorded
            assert any("fallback" in r.message.lower() for r in caplog.records)

    def test_mock_only_configuration_bypasses_network_probe(self):
        """5. Mock-only configurations bypass network health checks completely."""
        stage_configs = {
            "screenplay": StageProviderConfig(stage="screenplay", provider_type="mock"),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        with patch("httpx.Client.get") as mock_get:
            provider = router.route("screenplay", prefer_ollama=False)
            assert isinstance(provider, MockProviderV2)
            assert mock_get.call_count == 0

    def test_health_checks_not_repeated_within_ttl(self):
        """6. Provider health checks are cached and not repeated within TTL."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=False,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        mock_ok = MagicMock(spec=httpx.Response)
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"models": [{"name": "llama3.1:latest"}]}

        with patch("httpx.Client.get", return_value=mock_ok) as mock_get:
            p1 = router.route("story", prefer_ollama=True)
            p2 = router.route("story", prefer_ollama=True)
            assert p1 is p2
            assert mock_get.call_count == 1

    def test_no_silent_mock_substitution_when_fallback_disabled(self):
        """7. Health check failure must never silently return MockProvider when fallback False."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
                allow_fallback=False,
            ),
        }
        registry = ProviderRegistry(ProviderRegistryConfig(stages=stage_configs))
        router = ModelRouter(registry)

        with (
            patch(
                "httpx.Client.get",
                side_effect=httpx.TimeoutException("Read timeout"),
            ),
            pytest.raises(ProviderUnavailableError),
        ):
            router.route("story", prefer_ollama=True, allow_fallback=False)

    def test_allow_fallback_default_is_false(self):
        """Default allow_fallback setting is False in OllamaSettings and configs."""
        settings = OllamaSettings()
        assert settings.allow_fallback is False

        stage_cfg = StageProviderConfig(stage="story", provider_type="ollama")
        assert stage_cfg.allow_fallback is False

        reg_cfg = ProviderRegistryConfig()
        assert reg_cfg.allow_fallback is False

    def test_settings_allow_fallback_env_loading(self, monkeypatch):
        """OLLAMA_ALLOW_FALLBACK env var enables fallback when explicitly set."""
        monkeypatch.setenv("OLLAMA_ALLOW_FALLBACK", "true")
        monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
        reload_settings()

        reg_cfg = ProviderRegistryConfig.from_settings()
        assert reg_cfg.stages["story"].allow_fallback is True
