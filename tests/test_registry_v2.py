from config_v2 import reload_settings
from providers.registry_v2 import (
    ModelRouter,
    ProviderRegistry,
    ProviderRegistryConfig,
    StageProviderConfig,
    get_mock_provider_v2,
    get_provider_for_stage_v2,
    get_registry,
)


def test_stage_provider_config():
    config = StageProviderConfig(
        stage="story",
        provider_type="ollama",
        provider_config=None,
        fallback_provider_type="mock",
    )
    assert config.stage == "story"
    assert config.provider_type == "ollama"
    assert config.fallback_provider_type == "mock"
    assert config.enabled is True


def test_provider_registry_config_from_settings(mock_env):
    reload_settings()
    config = ProviderRegistryConfig.from_settings()
    assert "story" in config.stages
    assert config.stages["story"].provider_type == "mock"
    assert len(config.stages) == 19


def test_provider_registry_config_from_settings_with_ollama(ollama_env):
    reload_settings()
    config = ProviderRegistryConfig.from_settings()
    assert config.stages["story"].provider_type == "ollama"
    assert config.stages["story"].fallback_provider_type == "mock"
    assert config.stages["screenplay"].provider_type == "mock"


def test_provider_registry_creation(mock_env):
    reload_settings()
    config = ProviderRegistryConfig.from_settings()
    registry = ProviderRegistry(config)
    assert registry is not None
    assert len(registry.config.stages) == 19


def test_provider_registry_get_provider_mock(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    provider = registry.get_provider("story")
    assert provider is not None
    assert provider.config.name == "MockProvider_story"


def test_provider_registry_get_provider_caches(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    provider1 = registry.get_provider("story")
    provider2 = registry.get_provider("story")
    assert provider1 is provider2


def test_provider_registry_get_provider_for_stage(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    provider = registry.get_provider_for_stage("story", use_ollama=False)
    assert provider is not None


def test_provider_registry_get_provider_for_stage_ollama(ollama_env):
    reload_settings()
    registry = ProviderRegistry()
    provider = registry.get_provider_for_stage("story", use_ollama=True)
    assert provider is not None


def test_provider_registry_get_mock_provider(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    provider = registry.get_mock_provider("story")
    assert provider is not None
    assert provider.stage == "story"


def test_provider_registry_list_providers(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    # Instantiate all providers
    for stage in registry.config.stages:
        registry.get_provider(stage)
    providers = registry.list_providers()
    assert "story" in providers
    assert len(providers) == 19


def test_provider_registry_close_all(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    registry.get_provider("story")
    registry.close_all()
    assert len(registry._providers) == 0


def test_model_router(mock_env):
    reload_settings()
    registry = ProviderRegistry()
    router = ModelRouter(registry)
    provider = router.route("story", prefer_ollama=False)
    assert provider is not None
    preferred = router.get_preferred_provider("story")
    assert preferred == "mock"


def test_global_registry():
    reload_settings()
    registry1 = get_registry()
    registry2 = get_registry()
    assert registry1 is registry2


def test_get_provider_for_stage_v2(mock_env):
    reload_settings()
    provider = get_provider_for_stage_v2("story", use_ollama=False)
    assert provider is not None


def test_get_mock_provider_v2(mock_env):
    reload_settings()
    provider = get_mock_provider_v2("story")
    assert provider is not None
    assert provider.stage == "story"
