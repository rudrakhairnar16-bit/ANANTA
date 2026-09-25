import time
from unittest.mock import MagicMock, patch

import httpx

from config_v2 import OllamaSettings
from providers.base_v2 import OllamaProviderV2


class TestM106OllamaHealthCheck:
    """
    M10.6 Task 1 Test Suite:
    Ollama Pre-flight Health Checks & Model Availability Verification.
    """

    def test_ollama_endpoint_responds_successfully_with_model(self):
        """1. Ollama endpoint responds successfully and configured model is present."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            health_check_timeout=2.0,
            health_check_ttl=60.0,
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.1:latest", "model": "llama3.1:latest", "size": 4661224676},
                {"name": "mistral:latest", "model": "mistral:latest", "size": 4109865159},
            ]
        }

        with patch.object(provider.client, "get", return_value=mock_response) as mock_get:
            healthy = provider.health_check()
            assert healthy is True
            assert mock_get.call_count == 1
            mock_get.assert_called_with("/api/tags", timeout=2.0)

    def test_ollama_connection_refused(self):
        """2. Connection refused returns False without raising an unhandled exception."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
        )
        with patch.object(
            provider.client,
            "get",
            side_effect=httpx.ConnectError("Connection refused to http://localhost:11434"),
        ) as mock_get:
            healthy = provider.health_check()
            assert healthy is False
            assert mock_get.call_count == 1

    def test_ollama_request_timeout(self):
        """3. Request timeout returns False gracefully."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            health_check_timeout=1.5,
        )
        with patch.object(
            provider.client,
            "get",
            side_effect=httpx.TimeoutException("Read timeout after 1.5s"),
        ) as mock_get:
            healthy = provider.health_check(timeout=1.5)
            assert healthy is False
            assert mock_get.call_count == 1

    def test_ollama_invalid_http_status_and_malformed_json(self):
        """4. Invalid HTTP status (500/404) or malformed/invalid JSON returns False."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
        )

        # 4a. HTTP 500 internal server error
        mock_500 = MagicMock(spec=httpx.Response)
        mock_500.status_code = 500
        with patch.object(provider.client, "get", return_value=mock_500):
            assert provider.health_check(force=True) is False

        # 4b. HTTP 200 with invalid JSON body
        mock_bad_json = MagicMock(spec=httpx.Response)
        mock_bad_json.status_code = 200
        mock_bad_json.json.side_effect = ValueError("Invalid JSON")
        with patch.object(provider.client, "get", return_value=mock_bad_json):
            assert provider.health_check(force=True) is False

        # 4c. HTTP 200 with missing "models" key
        mock_no_models = MagicMock(spec=httpx.Response)
        mock_no_models.status_code = 200
        mock_no_models.json.return_value = {"error": "unknown error"}
        with patch.object(provider.client, "get", return_value=mock_no_models):
            assert provider.health_check(force=True) is False

    def test_configured_model_available_matching_variants(self):
        """5. Configured model availability handles exact tag, untagged, and :latest."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3.1:latest"},
                {"name": "qwen2.5:7b"},
                {"name": "nomic-embed-text"},
            ]
        }

        # Match "llama3.1" when remote has "llama3.1:latest"
        provider1 = OllamaProviderV2(model="llama3.1")
        with patch.object(provider1.client, "get", return_value=mock_response):
            assert provider1.health_check(force=True) is True

        # Match exact "qwen2.5:7b"
        provider2 = OllamaProviderV2(model="qwen2.5:7b")
        with patch.object(provider2.client, "get", return_value=mock_response):
            assert provider2.health_check(force=True) is True

        # Match exact "nomic-embed-text"
        provider3 = OllamaProviderV2(model="nomic-embed-text")
        with patch.object(provider3.client, "get", return_value=mock_response):
            assert provider3.health_check(force=True) is True

    def test_configured_model_is_missing(self):
        """6. Configured model missing returns False even if endpoint is 200 OK."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "mistral:latest"},
                {"name": "phi3:latest"},
            ]
        }

        with patch.object(provider.client, "get", return_value=mock_response):
            healthy = provider.health_check(force=True)
            assert healthy is False

    def test_health_check_ttl_caching(self):
        """7. Health-check TTL caching prevents repeated network calls within TTL window."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            health_check_ttl=60.0,
        )
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3.1:latest"}]
        }

        with patch.object(provider.client, "get", return_value=mock_response) as mock_get:
            # 1st call: network probe
            res1 = provider.health_check()
            assert res1 is True
            assert mock_get.call_count == 1

            # 2nd call: within TTL -> uses cache
            res2 = provider.health_check()
            assert res2 is True
            assert mock_get.call_count == 1

            # 3rd call: within TTL -> uses cache
            res3 = provider.health_check()
            assert res3 is True
            assert mock_get.call_count == 1

    def test_cache_expiration_triggers_fresh_probe(self):
        """8. Expired cache or force=True triggers a fresh probe."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            health_check_ttl=10.0,
        )
        mock_ok = MagicMock(spec=httpx.Response)
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"models": [{"name": "llama3.1:latest"}]}

        mock_down = MagicMock(spec=httpx.Response)
        mock_down.status_code = 503

        with patch.object(provider.client, "get", side_effect=[mock_ok, mock_down]) as mock_get:
            # First probe: OK
            assert provider.health_check() is True
            assert mock_get.call_count == 1

            # Advance time beyond TTL
            provider._last_health_check_time = time.monotonic() - 15.0

            # Second probe: triggered because cache expired, returns False
            assert provider.health_check() is False
            assert mock_get.call_count == 2

    def test_force_bypass_cache(self):
        """Force=True bypasses the TTL cache unconditionally."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            health_check_ttl=60.0,
        )
        mock_ok = MagicMock(spec=httpx.Response)
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"models": [{"name": "llama3.1:latest"}]}

        with patch.object(provider.client, "get", return_value=mock_ok) as mock_get:
            assert provider.health_check() is True
            assert mock_get.call_count == 1

            # Force re-check
            assert provider.health_check(force=True) is True
            assert mock_get.call_count == 2

    def test_ollama_settings_configuration(self):
        """Verify OllamaSettings includes health-check timeout and TTL defaults."""
        settings = OllamaSettings()
        assert settings.health_check_timeout == 3.0
        assert settings.health_check_ttl_seconds == 60
