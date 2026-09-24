from dataclasses import dataclass, field
from typing import Any

from config_v2 import get_settings
from providers.base_v2 import (
    BaseProviderV2,
    MockProviderV2,
    OllamaProviderV2,
    ProviderConfig,
)
from providers.registry import get_provider_for_stage as get_provider_v1


@dataclass
class StageProviderConfig:
    stage: str
    provider_type: str
    provider_config: ProviderConfig | None = None
    fallback_provider_type: str | None = None
    enabled: bool = True


@dataclass
class ProviderRegistryConfig:
    stages: dict[str, StageProviderConfig] = field(default_factory=dict)
    default_provider: str = "mock"
    health_check_interval_seconds: int = 60

    @classmethod
    def from_settings(cls) -> "ProviderRegistryConfig":
        settings = get_settings()
        ollama = settings.ollama

        stages = {}
        for stage in settings.pipeline.stages:
            stage_settings = settings.get_stage_settings(stage)
            provider_type = (
                stage_settings.provider.type
                if stage_settings and stage_settings.provider
                else "mock"
            )

            if provider_type == "ollama" or (stage == "story" and ollama.enabled):
                prov_timeout = (
                    stage_settings.provider.timeout
                    if stage_settings and stage_settings.provider
                    else ollama.timeout
                )
                prov_retries = (
                    stage_settings.provider.max_retries
                    if stage_settings and stage_settings.provider
                    else ollama.max_retries
                )
                prov_temp = (
                    stage_settings.provider.temperature
                    if stage_settings and stage_settings.provider
                    else ollama.temperature
                )
                prov_extra = {
                    "base_url": (
                        stage_settings.provider.extra.get("base_url", ollama.base_url)
                        if stage_settings and stage_settings.provider
                        else ollama.base_url
                    ),
                    "model": (
                        stage_settings.provider.extra.get("model", ollama.model or "llama3.1")
                        if stage_settings and stage_settings.provider
                        else (ollama.model or "llama3.1")
                    ),
                }
                stages[stage] = StageProviderConfig(
                    stage=stage,
                    provider_type="ollama",
                    provider_config=ProviderConfig(
                        name=f"OllamaProvider_{stage}",
                        timeout=prov_timeout,
                        max_retries=prov_retries,
                        temperature=prov_temp,
                        extra=prov_extra,
                    ),
                    fallback_provider_type="mock",
                )
            else:
                stages[stage] = StageProviderConfig(
                    stage=stage,
                    provider_type=provider_type,
                    provider_config=ProviderConfig(name=f"MockProvider_{stage}"),
                )

        return cls(stages=stages)


class ProviderRegistry:
    def __init__(self, config: ProviderRegistryConfig | None = None):
        self.config = config or ProviderRegistryConfig.from_settings()
        self._providers: dict[str, BaseProviderV2] = {}
        self._health_cache: dict[str, tuple[bool, float]] = {}
        self._health_check_interval = self.config.health_check_interval_seconds

    def get_provider(self, stage: str) -> BaseProviderV2:
        if stage in self._providers:
            return self._providers[stage]

        stage_config = self.config.stages.get(stage)
        if not stage_config:
            provider = MockProviderV2(stage)
            self._providers[stage] = provider
            return provider

        if not stage_config.enabled:
            provider = MockProviderV2(stage)
            self._providers[stage] = provider
            return provider

        provider = self._create_provider(stage_config)
        self._providers[stage] = provider
        return provider

    def _create_provider(self, stage_config: StageProviderConfig) -> BaseProviderV2:
        if stage_config.provider_type == "ollama":
            cfg = stage_config.provider_config
            extra = cfg.extra if cfg else {}
            timeout = cfg.timeout if cfg else 120.0
            max_retries = cfg.max_retries if cfg else 3
            temperature = cfg.temperature if cfg else 0.7
            return OllamaProviderV2(
                base_url=extra.get("base_url", "http://localhost:11434"),
                model=extra.get("model", "llama3.1"),
                timeout=timeout,
                max_retries=max_retries,
                temperature=temperature,
                stage=stage_config.stage,
            )
        elif stage_config.provider_type == "mock":
            return MockProviderV2(stage_config.stage)

        raise ValueError(
            f"Unsupported provider type: '{stage_config.provider_type}' "
            f"for stage '{stage_config.stage}'"
        )

    def get_provider_for_stage(self, stage: str, use_ollama: bool = False) -> BaseProviderV2:
        if use_ollama:
            ollama_config = self.config.stages.get(stage)
            if ollama_config and ollama_config.provider_type == "ollama":
                return self._create_provider(ollama_config)
            settings = get_settings()
            if settings.ollama.enabled:
                return OllamaProviderV2(
                    base_url=settings.ollama.base_url,
                    model=settings.ollama.model,
                    timeout=settings.ollama.timeout,
                    max_retries=settings.ollama.max_retries,
                    temperature=settings.ollama.temperature,
                    stage=stage,
                )
        return self.get_provider(stage)

    def get_mock_provider(self, stage: str) -> MockProviderV2:
        return MockProviderV2(stage)

    def create_ollama_provider(self, stage: str | None = None) -> OllamaProviderV2:
        settings = get_settings()
        ollama = settings.ollama
        if not ollama.enabled:
            raise ValueError("Ollama not configured. Set OLLAMA_MODEL environment variable.")
        return OllamaProviderV2(
            base_url=ollama.base_url,
            model=ollama.model,
            timeout=ollama.timeout,
            max_retries=ollama.max_retries,
            temperature=ollama.temperature,
            stage=stage,
        )

    def health_check(self, stage: str | None = None) -> dict[str, bool]:
        results = {}
        stages_to_check = [stage] if stage else list(self._providers.keys())

        for s in stages_to_check:
            provider = self._providers.get(s)
            if provider:
                is_healthy = provider.health_check()
                results[s] = is_healthy
            else:
                results[s] = True

        return results

    def close_all(self):
        for provider in self._providers.values():
            provider.close()
        self._providers.clear()

    def list_providers(self) -> dict[str, str]:
        return {stage: type(provider).__name__ for stage, provider in self._providers.items()}


class ModelRouter:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def route(self, stage: str, prefer_ollama: bool = False) -> BaseProviderV2:
        return self.registry.get_provider_for_stage(stage, use_ollama=prefer_ollama)

    def get_preferred_provider(self, stage: str) -> str:
        stage_config = self.registry.config.stages.get(stage)
        if stage_config:
            return stage_config.provider_type
        return "mock"


_global_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ProviderRegistry()
    return _global_registry


def get_provider_for_stage_v2(stage: str, use_ollama: bool = False) -> BaseProviderV2:
    return get_registry().get_provider_for_stage(stage, use_ollama=use_ollama)


def get_mock_provider_v2(stage: str) -> MockProviderV2:
    return get_registry().get_mock_provider(stage)


def create_ollama_provider_v2() -> OllamaProviderV2:
    return get_registry().create_ollama_provider()


def get_provider_v1_compat(stage: str) -> Any:
    return get_provider_v1(stage)
