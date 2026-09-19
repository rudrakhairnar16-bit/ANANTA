import datetime
import json
import pathlib
from abc import ABC, abstractmethod
from typing import Any

from pipeline.providers import get_provider

ROOT = pathlib.Path(__file__).resolve().parents[1]

class BaseAgent(ABC):
    def __init__(self, stage: str):
        self.stage = stage
        self.provider = get_provider(stage)

    @abstractmethod
    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        pass

    @abstractmethod
    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        pass

    def run(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.validate_inputs(inputs):
            raise ValueError(f"Invalid inputs for {self.stage} agent")

        result = self.process(inputs)
        result["episode_id"] = inputs.get("episode_id", "UNKNOWN")
        result["stage"] = self.stage
        result["version"] = inputs.get("version", 1) + 1
        result["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result["inputs"] = inputs
        result["approval_status"] = "pending"

        self._write_output(result)

        merged = {**inputs, **result}
        if "inputs" in inputs and isinstance(inputs["inputs"], dict):
            for key in [
                "characters",
                "locations",
                "scenes",
                "title",
                "logline",
                "duration_seconds",
            ]:
                if key in inputs["inputs"] and key not in merged:
                    merged[key] = inputs["inputs"][key]
        return merged

    def _write_output(self, data: dict[str, Any]):
        stage_dirs = {
            "story": "outputs/scripts",
            "screenplay": "outputs/scripts",
            "scene_plan": "outputs/scripts",
            "character": "outputs/character",
            "world": "outputs/world",
            "storyboard": "outputs/storyboard",
            "director": "outputs/director",
            "camera": "outputs/camera",
            "visual": "outputs/visual",
            "motion": "outputs/motion",
            "voice": "outputs/voice",
            "music": "outputs/music",
            "bgm": "outputs/bgm",
            "sfx": "outputs/sfx",
            "lipsync": "outputs/lipsync",
            "edit": "outputs/edit",
            "adobe_export": "outputs/adobe_export",
            "qa": "outputs/qa",
            "export": "outputs/export"
        }

        output_dir = ROOT / stage_dirs.get(self.stage, f"outputs/{self.stage}")
        output_dir.mkdir(parents=True, exist_ok=True)

        episode_id = data.get("episode_id", "UNKNOWN")
        output_file = output_dir / f"{episode_id}_{self.stage}.json"
        output_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  [{self.stage}] Written to {output_file}")


class StoryAgent(BaseAgent):
    def __init__(self):
        from config import get_settings
        from providers.registry import get_provider_for_stage

        settings = get_settings()
        use_ollama = settings.ollama.enabled

        self.stage = "story"
        self.provider = get_provider_for_stage("story", use_ollama=use_ollama)

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "episode_id" in inputs and "title" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate_sync(inputs)


class ScreenplayAgent(BaseAgent):
    def __init__(self):
        super().__init__("screenplay")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs and "synopsis" in inputs.get("outputs", {})

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class ScenePlanAgent(BaseAgent):
    def __init__(self):
        super().__init__("scene_plan")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs and "scenes" in inputs.get("outputs", {})

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class CharacterAgent(BaseAgent):
    def __init__(self):
        super().__init__("character")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "characters" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class WorldAgent(BaseAgent):
    def __init__(self):
        super().__init__("world")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "locations" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class StoryboardAgent(BaseAgent):
    def __init__(self):
        super().__init__("storyboard")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class DirectorAgent(BaseAgent):
    def __init__(self):
        super().__init__("director")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class CameraAgent(BaseAgent):
    def __init__(self):
        super().__init__("camera")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class VisualAgent(BaseAgent):
    def __init__(self):
        super().__init__("visual")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class MotionAgent(BaseAgent):
    def __init__(self):
        super().__init__("motion")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class VoiceAgent(BaseAgent):
    def __init__(self):
        super().__init__("voice")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "characters" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class MusicAgent(BaseAgent):
    def __init__(self):
        super().__init__("music")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class BGMAgent(BaseAgent):
    def __init__(self):
        super().__init__("bgm")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class SFXAgent(BaseAgent):
    def __init__(self):
        super().__init__("sfx")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class LipSyncAgent(BaseAgent):
    def __init__(self):
        super().__init__("lipsync")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "characters" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class EditAgent(BaseAgent):
    def __init__(self):
        super().__init__("edit")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class AdobeExportAgent(BaseAgent):
    def __init__(self):
        super().__init__("adobe_export")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return "outputs" in inputs

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class QAAgent(BaseAgent):
    def __init__(self):
        super().__init__("qa")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return True

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


class ExportAgent(BaseAgent):
    def __init__(self):
        super().__init__("export")

    def validate_inputs(self, inputs: dict[str, Any]) -> bool:
        return True

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.provider.generate(inputs)


AGENT_REGISTRY = {
    "story": StoryAgent,
    "screenplay": ScreenplayAgent,
    "scene_plan": ScenePlanAgent,
    "character": CharacterAgent,
    "world": WorldAgent,
    "storyboard": StoryboardAgent,
    "director": DirectorAgent,
    "camera": CameraAgent,
    "visual": VisualAgent,
    "motion": MotionAgent,
    "voice": VoiceAgent,
    "music": MusicAgent,
    "bgm": BGMAgent,
    "sfx": SFXAgent,
    "lipsync": LipSyncAgent,
    "edit": EditAgent,
    "adobe_export": AdobeExportAgent,
    "qa": QAAgent,
    "export": ExportAgent,
}

def get_agent(stage: str) -> BaseAgent:
    agent_class = AGENT_REGISTRY.get(stage)
    if not agent_class:
        raise ValueError(f"No agent registered for stage: {stage}")
    return agent_class()
