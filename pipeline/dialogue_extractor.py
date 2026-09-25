import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DialogueLine:
    """Represents an extracted character dialogue line in screenplay sequence."""

    scene_id: str
    sequence_index: int
    speaker: str
    text: str
    character_id: str | None = None
    emotion: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "sequence_index": self.sequence_index,
            "speaker": self.speaker,
            "text": self.text,
            "character_id": self.character_id,
            "emotion": self.emotion,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DialogueLine":
        return cls(
            scene_id=str(data.get("scene_id", "scene_001")),
            sequence_index=int(data.get("sequence_index", 1)),
            speaker=str(data.get("speaker", "UNKNOWN")),
            text=str(data.get("text", "")),
            character_id=data.get("character_id"),
            emotion=data.get("emotion"),
            metadata=data.get("metadata", {}),
        )


class DialogueExtractor:
    """Robust extractor for character dialogue lines from screenplay and episode data."""

    def extract(self, data: dict[str, Any] | list[Any]) -> list[DialogueLine]:
        """Extract all dialogue lines in strict sequential order from screenplay data."""
        if not data:
            return []

        scenes = self._find_scenes(data)
        if not scenes:
            return []

        extracted: list[DialogueLine] = []
        global_sequence_index = 1

        for scene_idx, scene in enumerate(scenes, 1):
            if not isinstance(scene, dict):
                continue

            scene_id = str(scene.get("scene_id") or scene.get("id") or f"scene_{scene_idx:03d}")
            scene_lines = self._extract_from_scene(scene, scene_id, global_sequence_index)

            for line in scene_lines:
                extracted.append(line)
                global_sequence_index += 1

        return extracted

    def _find_scenes(self, data: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
        """Locate the scene list from various possible screenplay/brief payloads."""
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]

        if not isinstance(data, dict):
            return []

        # Check outputs.screenplay.scenes
        if isinstance(data.get("outputs"), dict):
            screenplay_out = data["outputs"].get("screenplay")
            if isinstance(screenplay_out, dict) and isinstance(screenplay_out.get("scenes"), list):
                return screenplay_out["scenes"]

        # Check screenplay.scenes
        if isinstance(data.get("screenplay"), dict):
            sc_scenes = data["screenplay"].get("scenes")
            if isinstance(sc_scenes, list):
                return sc_scenes

        # Check top-level scenes
        if isinstance(data.get("scenes"), list):
            return data["scenes"]

        return []

    def _extract_from_scene(
        self,
        scene: dict[str, Any],
        scene_id: str,
        start_index: int,
    ) -> list[DialogueLine]:
        """Extract ordered dialogue lines from a single scene object."""
        lines: list[DialogueLine] = []
        seq = start_index

        # 1. Check for explicit dialogue list structures
        dialogue_items = None
        for key in ["dialogue", "dialogue_lines", "lines", "script_lines"]:
            val = scene.get(key)
            if isinstance(val, list):
                dialogue_items = val
                break

        if dialogue_items is not None:
            for item in dialogue_items:
                parsed = self._parse_dialogue_item(item, scene_id, seq)
                if parsed is not None:
                    lines.append(parsed)
                    seq += 1
            return lines

        # 2. Check for formatted script/dialogue string block
        raw_text = scene.get("dialogue") or scene.get("script") or scene.get("screenplay_text")
        if isinstance(raw_text, str) and raw_text.strip():
            parsed_lines = self._parse_script_text(raw_text, scene_id, seq)
            lines.extend(parsed_lines)
            return lines

        return []

    def _parse_dialogue_item(
        self,
        item: Any,
        scene_id: str,
        seq_index: int,
    ) -> DialogueLine | None:
        """Parse a single dialogue line entry (dict or string)."""
        if isinstance(item, dict):
            speaker = (
                item.get("speaker")
                or item.get("character")
                or item.get("name")
                or item.get("char_name")
                or "UNKNOWN"
            )
            text = (
                item.get("text")
                or item.get("line")
                or item.get("dialogue")
                or item.get("content")
                or ""
            )
            character_id = item.get("character_id") or item.get("id")
            emotion = item.get("emotion") or item.get("mood") or item.get("parenthetical")

            speaker_clean = str(speaker).strip()
            text_clean = str(text).strip()

            if not text_clean:
                return None

            return DialogueLine(
                scene_id=scene_id,
                sequence_index=seq_index,
                speaker=speaker_clean if speaker_clean else "UNKNOWN",
                text=text_clean,
                character_id=str(character_id) if character_id else None,
                emotion=str(emotion) if emotion else None,
                metadata={k: v for k, v in item.items() if k not in {
                    "speaker", "character", "name", "text", "line", "dialogue", "emotion"
                }},
            )

        elif isinstance(item, str):
            text_str = item.strip()
            if not text_str:
                return None

            # Check pattern "Speaker: Dialogue" or "SPEAKER - Dialogue"
            match = re.match(r"^([^:\-]+)[:\-]\s*(.+)$", text_str)
            if match:
                speaker = match.group(1).strip()
                dialogue = match.group(2).strip()
                if dialogue:
                    return DialogueLine(
                        scene_id=scene_id,
                        sequence_index=seq_index,
                        speaker=speaker,
                        text=dialogue,
                    )
            return DialogueLine(
                scene_id=scene_id,
                sequence_index=seq_index,
                speaker="UNKNOWN",
                text=text_str,
            )

        return None

    def _parse_script_text(
        self,
        text: str,
        scene_id: str,
        start_index: int,
    ) -> list[DialogueLine]:
        """Parse standard screenplay text blocks into speaker and dialogue lines."""
        lines: list[DialogueLine] = []
        seq = start_index

        # Match blocks:
        # CHARACTER NAME
        # (optional parenthetical)
        # Dialogue text...
        pattern = re.compile(
            r"(?:^|\n)([A-Z0-9\s\.\-\']{2,30})\n(?:\(([^\)]+)\)\n)?([^\n]+(?:\n[^\n]+)*)",
            re.MULTILINE,
        )

        for match in pattern.finditer(text):
            speaker = match.group(1).strip()
            emotion = match.group(2).strip() if match.group(2) else None
            dialogue = match.group(3).strip()

            # Ignore scene headings like "INT. SERVER ROOM"
            if speaker.startswith(("INT.", "EXT.", "SCENE", "ACT")):
                continue

            if dialogue:
                lines.append(
                    DialogueLine(
                        scene_id=scene_id,
                        sequence_index=seq,
                        speaker=speaker,
                        text=dialogue,
                        emotion=emotion,
                    )
                )
                seq += 1

        return lines


def extract_dialogue(screenplay_data: dict[str, Any] | list[Any]) -> list[DialogueLine]:
    """Convenience helper to extract dialogue from screenplay data."""
    extractor = DialogueExtractor()
    return extractor.extract(screenplay_data)
