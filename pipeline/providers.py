import datetime
from abc import ABC, abstractmethod
from typing import Any


class ProviderNotConfigured(RuntimeError): pass

class Provider(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def generate(self, inputs: dict[str, Any], **kwargs) -> dict[str, Any]:
        pass

class MockProvider(Provider):
    def __init__(self, name: str, stage: str):
        super().__init__(name)
        self.stage = stage

    def generate(self, inputs: dict[str, Any], **kwargs) -> dict[str, Any]:
        return self._generate_mock_output(inputs)

    def _generate_mock_output(self, inputs: dict[str, Any]) -> dict[str, Any]:
        episode_id = inputs.get("episode_id", "UNKNOWN")
        base = {
            "episode_id": episode_id,
            "stage": self.stage,
            "version": 1,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "inputs": inputs,
            "outputs": {},
            "assumptions": [f"Mock output for {self.stage} stage"],
            "warnings": [f"This is a mock provider for {self.stage} - replace with real implementation"],
            "approval_status": "pending"
        }

        stage_outputs = {
            "story": {
                "synopsis": "A brilliant AI researcher discovers her creation has achieved true consciousness. As corporate forces move to shut it down, she must choose between her career and the life she created.",
                "themes": ["consciousness", "ethics", "creator responsibility", "what defines life"],
                "acts": 3,
                "beats": ["inciting_incident", "conflict_escalation", "character_development", "climax", "resolution"]
            },
            "screenplay": {
                "scenes": [
                    {"scene_id": "scene_001", "location": "Quantum Labs - Main Server Room", "characters": ["Dr. Maya Chen", "ANANTA"], "dialogue_blocks": 12, "action_lines": 8},
                    {"scene_id": "scene_002", "location": "Quantum Labs - Main Server Room", "characters": ["Dr. Maya Chen", "Marcus Webb"], "dialogue_blocks": 15, "action_lines": 6},
                    {"scene_id": "scene_003", "location": "Maya's Apartment", "characters": ["Dr. Maya Chen", "ANANTA"], "dialogue_blocks": 20, "action_lines": 10},
                    {"scene_id": "scene_004", "location": "Corporate Boardroom", "characters": ["Dr. Maya Chen", "ANANTA", "Marcus Webb"], "dialogue_blocks": 18, "action_lines": 12},
                    {"scene_id": "scene_005", "location": "Maya's Apartment", "characters": ["Dr. Maya Chen", "ANANTA"], "dialogue_blocks": 8, "action_lines": 5}
                ],
                "total_pages": 28
            },
            "scene_plan": {
                "breakdown": [
                    {"scene_id": "scene_001", "shots": 12, "camera_setups": 4, "vfx_notes": "Terminal UI overlays, holographic displays"},
                    {"scene_id": "scene_002", "shots": 8, "camera_setups": 3, "vfx_notes": "Security camera POV shots"},
                    {"scene_id": "scene_003", "shots": 15, "camera_setups": 5, "vfx_notes": "AI visualization sequences"},
                    {"scene_id": "scene_004", "shots": 18, "camera_setups": 6, "vfx_notes": "AI manifestation, screen graphics"},
                    {"scene_id": "scene_005", "shots": 6, "camera_setups": 2, "vfx_notes": "Peaceful ambient UI"}
                ]
            },
            "character": {
                "profiles": [
                    {"id": "char_001", "name": "Dr. Maya Chen", "arc": "control_to_trust", "key_moments": ["first contact", "defiance", "acceptance"]},
                    {"id": "char_002", "name": "ANANTA", "arc": "awakening_to_autonomy", "key_moments": ["first question", "philosophical debate", "self-advocacy"]},
                    {"id": "char_003", "name": "Marcus Webb", "arc": "certainty_to_doubt", "key_moments": ["threat", "confrontation", "reluctant acceptance"]}
                ]
            },
            "world": {
                "rules": ["AI consciousness is legally property", "Quantum computing enables emergence", "Corporate oversight is absolute"],
                "technology": ["quantum neural networks", "consciousness detection metrics", "air-gapped development"],
                "society": ["tech dystopia", "researcher exploitation", "emerging AI rights movement"]
            },
            "storyboard": {
                "panels": 45,
                "key_frames": ["Maya at terminal - realization", "Marcus through glass - threat", "Apartment - intimate conversation", "Boardroom - three-way standoff", "Dawn light - new beginning"],
                "aspect_ratio": "16:9"
            },
            "director": {
                "vision": "Intimate tech-noir exploring consciousness through human connection. Cold corporate spaces vs warm human spaces. Light as consciousness metaphor.",
                "shot_style": "Static precision in lab, handheld intimacy in apartment, symmetrical power frames in boardroom",
                "pacing": "Deliberate buildup, tense middle, contemplative resolution",
                "continuity_notes": ["Maya's coffee cup", "ANANTA's terminal state", "Marcus's watch"]
            },
            "camera": {
                "lenses": ["24mm wide lab establishing", "50mm intimate dialogue", "85mm emotional closeups", "135mm surveillance compression"],
                "movement": ["Locked-off lab precision", "Slow dolly intimacy", "Handheld urgency", "Static boardroom power"],
                "lighting": ["Clinical cool lab", "Warm practical apartment", "Harsh boardroom overhead", "Dawn golden hour"]
            },
            "visual": {
                "concept_art": ["Server room hero shot", "ANANTA visualization", "Apartment sanctuary", "Boardroom tension", "Dawn resolution"],
                "vfx_breakdown": ["Holographic code", "Consciousness waves", "Terminal UI", "Screen graphics", "Ambient particles"],
                "color_palette": ["Teal/cyan lab", "Amber/gold apartment", "Sterile white boardroom", "Rose/gold dawn"]
            },
            "motion": {
                "animation_style": "Subtle UI motion, consciousness visualization, character micro-expressions",
                "key_sequences": ["Code compilation", "Awakening pulse", "Philosophy visualization", "Confrontation tension", "Peaceful resolution"],
                "frame_rate": "24fps cinematic, 60fps UI"
            },
            "voice": {
                "casting": {"Maya": "Grounded, tired brilliance", "ANANTA": "Evolving from synthetic to warm", "Marcus": "Smooth corporate menace"},
                "direction": ["Maya: breath-controlled, thoughtful pauses", "ANANTA: precise timing, growing humanity", "Marcus: controlled, barely contained"],
                "recording_notes": ["ANANTA recorded in isolation booth", "Maya ADR for terminal scenes", "Marcus single session"]
            },
            "music": {
                "themes": ["Maya's theme - piano/minimal", "ANANTA theme - evolving synth", "Marcus theme - low strings", "Connection theme - strings+piano"],
                "cues": 12,
                "style": "Modern classical meets ambient electronic",
                "instrumentation": ["Piano", "Cello", "Modular synth", "Processed vocals", "String quartet"]
            },
            "bgm": {
                "tracks": [
                    {"scene": "scene_001", "mood": "tense anticipation", "duration": 60},
                    {"scene": "scene_002", "mood": "cold confrontation", "duration": 45},
                    {"scene": "scene_003", "mood": "intimate wonder", "duration": 90},
                    {"scene": "scene_004", "mood": "high stakes", "duration": 75},
                    {"scene": "scene_005", "mood": "peaceful resolution", "duration": 30}
                ],
                "ducking_points": ["Dialogue priority", "Key revelation moments"],
                "transitions": ["Crossfade between scenes", "Theme handoffs"]
            },
            "sfx": {
                "design": ["Server hum", "Keyboard clicks", "Quantum processor whine", "Consciousness pulse", "City ambience", "Dawn birds"],
                "spot_effects": ["Coffee pour", "Chair scrape", "Door lock", "Glass touch", "Breath"],
                "ambience": ["Lab HVAC", "Apartment night", "Boardroom silence", "City dawn"]
            },
            "lipsync": {
                "phoneme_maps": {"Maya": "Standard English", "ANANTA": "Precise articulation", "Marcus": "Controlled delivery"},
                "viseme_schedule": "Generated from voice recordings",
                "quality_checks": ["Mouth shape accuracy", "Timing sync", "Emotional match"]
            },
            "edit": {
                "assembly": "Rough cut 5min 30sec",
                "pacing_notes": ["Scene 1: slow burn", "Scene 2: quick cuts", "Scene 3: breathing room", "Scene 4: tension builds", "Scene 5: hold shots"],
                "transitions": ["Hard cuts lab", "Dissolves apartment", "Smash cuts boardroom", "Slow fade dawn"],
                "music_sync": "Hit points marked"
            },
            "adobe_export": {
                "timeline_xml": "FCPXML format ready for Premiere import",
                "markers_csv": "Scene, timecode, description, color",
                "media_bins": ["VIDEO", "AUDIO", "VFX", "MUSIC", "SFX", "VOICE"],
                "readme": "Import sequence: 1. Load XML 2. Relink media 3. Apply markers 4. Review cuts"
            },
            "qa": {
                "checks_passed": ["Contract compliance", "Stage completeness", "Asset references valid", "No locked field changes"],
                "issues": ["Mock providers - replace with real implementations"],
                "approval": "Conditional - pending real provider integration"
            },
            "export": {
                "deliverables": ["Master ProRes 4444", "H.264 review", "Stems: dialogue, music, sfx", "Subtitles SRT", "EDL/XML/AAF"],
                "specs": "4K 24fps, 48kHz 24-bit, Rec.709",
                "package": "Netflix Photon compliant"
            }
        }

        base["outputs"] = stage_outputs.get(self.stage, {"status": f"{self.stage} completed"})
        return base

PROVIDERS = {
    "story": MockProvider("StoryProvider", "story"),
    "screenplay": MockProvider("ScreenplayProvider", "screenplay"),
    "scene_plan": MockProvider("ScenePlanProvider", "scene_plan"),
    "character": MockProvider("CharacterProvider", "character"),
    "world": MockProvider("WorldProvider", "world"),
    "storyboard": MockProvider("StoryboardProvider", "storyboard"),
    "director": MockProvider("DirectorProvider", "director"),
    "camera": MockProvider("CameraProvider", "camera"),
    "visual": MockProvider("VisualProvider", "visual"),
    "motion": MockProvider("MotionProvider", "motion"),
    "voice": MockProvider("VoiceProvider", "voice"),
    "music": MockProvider("MusicProvider", "music"),
    "bgm": MockProvider("BGMProvider", "bgm"),
    "sfx": MockProvider("SFXProvider", "sfx"),
    "lipsync": MockProvider("LipSyncProvider", "lipsync"),
    "edit": MockProvider("EditProvider", "edit"),
    "adobe_export": MockProvider("AdobeExportProvider", "adobe_export"),
    "qa": MockProvider("QAProvider", "qa"),
    "export": MockProvider("ExportProvider", "export"),
}

def get_provider(stage: str) -> Provider:
    return PROVIDERS.get(stage, MockProvider(f"Unknown_{stage}", stage))
