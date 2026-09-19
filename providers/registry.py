from config import get_settings
from providers.base import BaseProvider, MockProvider
from providers.ollama import OllamaProvider


def create_ollama_provider() -> OllamaProvider:
    settings = get_settings()
    ollama = settings.ollama
    if not ollama.enabled:
        raise ValueError("Ollama not configured. Set OLLAMA_MODEL environment variable.")
    return OllamaProvider(
        base_url=ollama.base_url,
        model=ollama.model,
        timeout=ollama.timeout,
        max_retries=ollama.max_retries,
        temperature=ollama.temperature,
    )


def get_provider_for_stage(stage: str, use_ollama: bool = False) -> BaseProvider:
    if use_ollama and stage == "story":
        return create_ollama_provider()
    return MockProvider(stage)


def get_mock_provider(stage: str) -> MockProvider:
    return MockProvider(stage)
