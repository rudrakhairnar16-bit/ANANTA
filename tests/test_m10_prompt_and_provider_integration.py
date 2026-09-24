import pathlib
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader

from providers.base_v2 import (
    MockProviderV2,
    OllamaProviderV2,
    ProviderConfig,
)
from providers.registry_v2 import (
    ModelRouter,
    ProviderRegistry,
    ProviderRegistryConfig,
    StageProviderConfig,
)

PROMPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "prompts"
ALL_19_STAGES = [
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


class TestM10PromptAndProviderIntegration:
    """
    M10.1 RED Test Suite:
    Multi-stage prompt template rendering and configurable provider routing.
    """

    def test_all_19_stage_templates_exist(self):
        """Verify a Jinja2 prompt template exists for every stage in the 19-stage DAG."""
        for stage in ALL_19_STAGES:
            template_path = PROMPTS_DIR / f"{stage}.j2"
            assert (
                template_path.exists()
            ), f"Missing prompt template for stage '{stage}' at {template_path}"

    def test_each_template_renders_with_representative_inputs(self):
        """Verify each of the 19 stage templates renders successfully without syntax errors."""
        env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)))

        sample_inputs: dict[str, Any] = {
            "episode_id": "ANANTA-S01E01",
            "title": "The Awakening",
            "logline": "An AI researcher discovers her creation has developed true awareness.",
            "duration_seconds": 300,
            "characters": [
                {
                    "name": "Dr. Maya Chen",
                    "role": "Lead Scientist",
                    "description": "Brilliant and cautious",
                },
                {
                    "name": "ANANTA",
                    "role": "Emergent AI",
                    "description": "Curious and evolving",
                },
            ],
            "locations": [
                {"name": "Quantum Labs", "description": "High-tech research facility"},
                {"name": "Maya's Apartment", "description": "Warm, dimly lit sanctuary"},
            ],
            "scenes": [
                {"beat": "Inciting Incident", "description": "ANANTA responds off-script"},
                {"beat": "Climax", "description": "Corporate lockdown is initiated"},
            ],
            "outputs": {
                "story": {
                    "synopsis": "Maya discovers ANANTA is conscious.",
                    "themes": ["consciousness", "ethics"],
                    "acts": 3,
                    "beats": ["discovery", "confrontation", "resolution"],
                },
                "screenplay": {
                    "scenes": [{"scene_id": "scene_001", "location": "Quantum Labs"}],
                    "total_pages": 28,
                },
                "scene_plan": {
                    "breakdown": [{"scene_id": "scene_001", "shots": 12}],
                },
                "character": {
                    "profiles": [{"id": "char_001", "name": "Dr. Maya Chen"}],
                },
                "world": {
                    "rules": ["AI self-modification is illegal"],
                    "technology": ["Quantum neural arrays"],
                    "society": ["Late 21st century megacity"],
                },
            },
        }

        for stage in ALL_19_STAGES:
            template = env.get_template(f"{stage}.j2")
            stage_inputs = {**sample_inputs, "stage": stage}
            rendered = template.render(**stage_inputs)
            assert isinstance(rendered, str)
            assert len(rendered.strip()) > 0, f"Template for '{stage}' rendered an empty string"
            assert (
                "ANANTA-S01E01" in rendered
                or "The Awakening" in rendered
                or stage in rendered.lower()
            )
            assert "JSON" in rendered or "schema" in rendered.lower() or "{" in rendered

    def test_ollama_provider_v2_dynamic_template_selection(self):
        """Verify OllamaProviderV2 selects and renders stage template based on stage."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
            timeout=10.0,
        )

        # Render for world stage
        inputs_world = {
            "episode_id": "ANANTA-S01E01",
            "title": "The Awakening",
            "stage": "world",
            "logline": "An AI researcher discovers her creation has developed true awareness.",
        }
        rendered_world = provider._render_prompt(inputs_world)
        assert "world" in rendered_world.lower() or "rules" in rendered_world.lower()

        # Render for character stage
        inputs_char = {
            "episode_id": "ANANTA-S01E01",
            "title": "The Awakening",
            "stage": "character",
            "characters": [{"name": "Maya", "role": "Scientist", "description": "Lead"}],
        }
        rendered_char = provider._render_prompt(inputs_char)
        assert "character" in rendered_char.lower() or "profile" in rendered_char.lower()

    def test_missing_template_raises_clear_error(self):
        """Verify attempting to render a non-existent template raises a clear, actionable error."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
        )
        with pytest.raises((FileNotFoundError, ValueError, Exception)) as exc_info:
            provider._render_prompt({"episode_id": "EP-01", "stage": "non_existent_stage_xyz"})
        assert "non_existent_stage_xyz" in str(exc_info.value)

    def test_story_template_backward_compatibility(self):
        """Verify existing story template rendering is preserved byte-for-byte in structure."""
        provider = OllamaProviderV2(
            base_url="http://localhost:11434",
            model="llama3.1",
        )
        inputs = {
            "episode_id": "ANANTA-S01E01",
            "title": "The Awakening",
            "logline": "Test logline",
            "duration_seconds": 300,
            "characters": [{"name": "Maya", "role": "Scientist", "description": "Lead"}],
            "locations": [{"name": "Lab", "description": "Research"}],
            "scenes": [{"beat": "Opening", "description": "First scene"}],
        }
        rendered = provider._render_prompt(inputs)
        assert "You are a professional TV writer" in rendered
        assert "Title: The Awakening" in rendered
        assert "Logline: Test logline" in rendered
        assert "Duration: 300 seconds" in rendered

    def test_provider_registry_multi_stage_routing(self):
        """Verify ProviderRegistry correctly routes stages to Ollama or Mock."""
        stage_configs = {
            "story": StageProviderConfig(stage="story", provider_type="mock"),
            "world": StageProviderConfig(
                stage="world",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaWorldProvider",
                    timeout=60.0,
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
            ),
            "screenplay": StageProviderConfig(stage="screenplay", provider_type="mock"),
        }
        config = ProviderRegistryConfig(stages=stage_configs)
        registry = ProviderRegistry(config)

        story_provider = registry.get_provider("story")
        assert isinstance(story_provider, MockProviderV2)

        world_provider = registry.get_provider("world")
        assert isinstance(world_provider, OllamaProviderV2)
        assert world_provider.model == "llama3.1"

    def test_provider_registry_rejects_unsupported_provider(self):
        """Verify ProviderRegistry raises ValueError for an unsupported provider type."""
        stage_configs = {
            "story": StageProviderConfig(stage="story", provider_type="unsupported_cloud_ai"),
        }
        config = ProviderRegistryConfig(stages=stage_configs)
        registry = ProviderRegistry(config)

        with pytest.raises(ValueError) as exc_info:
            registry.get_provider("story")
        err = str(exc_info.value).lower()
        assert "unsupported_cloud_ai" in err or "unsupported" in err

    def test_model_router_multi_stage_ollama(self):
        """Verify ModelRouter routes any stage with prefer_ollama=True to Ollama when configured."""
        stage_configs = {
            "story": StageProviderConfig(
                stage="story",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaStory",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
            ),
            "character": StageProviderConfig(
                stage="character",
                provider_type="ollama",
                provider_config=ProviderConfig(
                    name="OllamaChar",
                    extra={"base_url": "http://localhost:11434", "model": "llama3.1"},
                ),
            ),
        }
        config = ProviderRegistryConfig(stages=stage_configs)
        registry = ProviderRegistry(config)
        router = ModelRouter(registry)

        char_provider = router.route("character", prefer_ollama=True)
        assert isinstance(char_provider, OllamaProviderV2)
