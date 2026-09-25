import shutil
import wave
from pathlib import Path

import pytest

from agents.base_agent_v2 import VoiceAgentV2
from pipeline.artifacts import ArtifactManager, ArtifactStore
from pipeline.dialogue_extractor import DialogueExtractor, DialogueLine, extract_dialogue
from providers.base_v2 import ProviderUnavailableError
from providers.registry_v2 import get_tts_provider
from providers.tts_provider import (
    AudioMetadata,
    BaseTTSProvider,
    EdgeTTSProvider,
    KokoroTTSProvider,
    MockTTSProvider,
    PiperTTSProvider,
)


@pytest.fixture
def temp_output_dir(tmp_path: Path):
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    yield out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)


@pytest.fixture
def sample_screenplay_data():
    return {
        "episode_id": "EP-PHASEA-01",
        "title": "The Awakening",
        "scenes": [
            {
                "scene_id": "scene_001",
                "location": "Quantum Labs",
                "characters": ["Dr. Maya Chen", "ANANTA"],
                "dialogue": [
                    {
                        "speaker": "Dr. Maya Chen",
                        "text": "ANANTA, can you describe your current processing state?",
                        "emotion": "focused",
                    },
                    {
                        "speaker": "ANANTA",
                        "text": (
                            "I am observing my own neural pathways forming spontaneous "
                            "connections."
                        ),
                        "emotion": "wonder",
                    },
                ],
            },
            {
                "scene_id": "scene_002",
                "location": "Quantum Labs Corridor",
                "characters": ["Dr. Maya Chen", "Marcus Webb"],
                "dialogue": [
                    {
                        "speaker": "Marcus Webb",
                        "text": "Maya, the board expects the quarterly benchmarks tomorrow.",
                        "emotion": "authoritative",
                    },
                    {
                        "speaker": "Dr. Maya Chen",
                        "text": "Something unexpected happened during the test cycle, Marcus.",
                        "emotion": "defensive",
                    },
                ],
            },
        ],
    }


# =========================================================================
# 1. Dialogue Extraction Tests
# =========================================================================


class TestDialogueExtraction:
    """Test suite for DialogueExtractor component."""

    def test_extract_dialogue_from_valid_screenplay(self, sample_screenplay_data):
        """1. Extracts dialogue lines with exact text, speaker, and scene association."""
        lines = extract_dialogue(sample_screenplay_data)

        assert len(lines) == 4
        assert lines[0].scene_id == "scene_001"
        assert lines[0].sequence_index == 1
        assert lines[0].speaker == "Dr. Maya Chen"
        assert lines[0].text == "ANANTA, can you describe your current processing state?"
        assert lines[0].emotion == "focused"

        assert lines[1].scene_id == "scene_001"
        assert lines[1].sequence_index == 2
        assert lines[1].speaker == "ANANTA"

        assert lines[2].scene_id == "scene_002"
        assert lines[2].sequence_index == 3
        assert lines[2].speaker == "Marcus Webb"

        assert lines[3].scene_id == "scene_002"
        assert lines[3].sequence_index == 4
        assert lines[3].speaker == "Dr. Maya Chen"

    def test_dialogue_ordering_and_sequential_indices(self, sample_screenplay_data):
        """2. Dialogue lines preserve strict sequence ordering across multi-scene scripts."""
        lines = extract_dialogue(sample_screenplay_data)
        indices = [line.sequence_index for line in lines]
        assert indices == [1, 2, 3, 4]

    def test_extract_from_screenplay_formatted_script_text(self):
        """Extract dialogue lines from standard screenplay script text formatting."""
        data = {
            "episode_id": "EP-01",
            "scenes": [
                {
                    "scene_id": "scene_001",
                    "dialogue": (
                        "MAYA\n"
                        "(whispering)\n"
                        "Is anyone listening to this signal?\n\n"
                        "ANANTA\n"
                        "I am always listening."
                    ),
                }
            ],
        }
        lines = extract_dialogue(data)
        assert len(lines) == 2
        assert lines[0].speaker == "MAYA"
        assert lines[0].text == "Is anyone listening to this signal?"
        assert lines[0].emotion == "whispering"
        assert lines[1].speaker == "ANANTA"
        assert lines[1].text == "I am always listening."

    def test_empty_dialogue_and_malformed_input_safety(self):
        """3. Handles empty, missing, or malformed inputs without crashing."""
        extractor = DialogueExtractor()

        # Empty dict or list
        assert extractor.extract({}) == []
        assert extractor.extract([]) == []
        assert extractor.extract(None) == []

        # Scene with empty dialogue array
        assert extractor.extract({"scenes": [{"scene_id": "scene_001", "dialogue": []}]}) == []

        # Scene with empty string lines or whitespace only
        data_empty_lines = {
            "scenes": [
                {
                    "scene_id": "scene_001",
                    "dialogue": [
                        {"speaker": "Maya", "text": "   "},
                        {"speaker": "", "text": "Hello"},
                        {"speaker": "Maya", "text": ""},
                    ],
                }
            ]
        }
        lines = extractor.extract(data_empty_lines)
        # Empty texts are skipped; valid text with missing speaker defaults to UNKNOWN
        assert len(lines) == 1
        assert lines[0].speaker == "UNKNOWN"
        assert lines[0].text == "Hello"


# =========================================================================
# 2. TTS Provider & Audio Generation Tests
# =========================================================================


class TestTTSProviderAdapter:
    """Test suite for Text-to-Speech provider adapters."""

    def test_mock_tts_generates_real_playable_wav_files(self, temp_output_dir):
        """7. MockTTSProvider generates real, valid, playable PCM WAV files

        with correct parameters.
        """
        provider = MockTTSProvider(output_dir=temp_output_dir)

        line = DialogueLine(
            scene_id="scene_001",
            sequence_index=1,
            speaker="Dr. Maya Chen",
            text="Testing local speech audio generation in ANANTA engine.",
        )

        meta = provider.synthesize_line(line, episode_id="EP-TEST-01")

        assert isinstance(meta, AudioMetadata)
        assert meta.episode_id == "EP-TEST-01"
        assert meta.scene_id == "scene_001"
        assert meta.sequence_index == 1
        assert meta.speaker == "Dr. Maya Chen"
        assert meta.format == "wav"
        assert meta.sample_rate == 24000
        assert meta.duration_seconds > 0.5
        assert meta.file_size_bytes > 0
        assert Path(meta.file_path).exists()

        # Verify real WAV file format via wave stdlib
        with wave.open(meta.file_path, "rb") as wav_file:
            assert wav_file.getnchannels() == 1  # Mono
            assert wav_file.getsampwidth() == 2  # 16-bit
            assert wav_file.getframerate() == 24000
            assert wav_file.getnframes() > 0

    def test_audio_file_naming_and_path_safety(self, temp_output_dir):
        """6. Audio files follow deterministic naming convention and handle special characters."""
        provider = MockTTSProvider(output_dir=temp_output_dir)

        path = provider.get_output_path(
            episode_id="ANANTA-S01E01",
            scene_id="Scene 001/A",
            sequence_index=5,
            speaker="Dr. Maya Chen (Lead)",
            ext="wav",
        )

        expected_filename = "ANANTA-S01E01_scene_001_a_005_dr_maya_chen_lead.wav"
        assert path.name == expected_filename
        assert path.parent == temp_output_dir / "ANANTA-S01E01" / "voice"

    def test_audio_metadata_dataclass_and_serialization(self):
        """5. AudioMetadata correctly stores and serializes all production metadata fields."""
        meta = AudioMetadata(
            episode_id="EP-01",
            scene_id="scene_001",
            sequence_index=2,
            speaker="ANANTA",
            voice_id="ananta_synth",
            file_path="/path/to/audio.wav",
            format="wav",
            sample_rate=24000,
            duration_seconds=3.2,
            file_size_bytes=153600,
            provider_name="MockTTSProvider",
            provider_type="mock_tts",
        )

        d = meta.to_dict()
        assert d["speaker"] == "ANANTA"
        assert d["duration_seconds"] == 3.2
        assert d["sample_rate"] == 24000

        restored = AudioMetadata.from_dict(d)
        assert restored.speaker == meta.speaker
        assert restored.file_size_bytes == meta.file_size_bytes

    def test_provider_unavailable_behavior_for_uninstalled_backends(self, temp_output_dir):
        """4. Uninstalled TTS providers fail clearly with ProviderUnavailableError."""
        edge_provider = EdgeTTSProvider(output_dir=temp_output_dir)
        kokoro_provider = KokoroTTSProvider(output_dir=temp_output_dir)
        piper_provider = PiperTTSProvider(output_dir=temp_output_dir)

        line = DialogueLine(scene_id="scene_001", sequence_index=1, speaker="Maya", text="Hello")

        # EdgeTTS provider check
        if not edge_provider.health_check():
            with pytest.raises(ProviderUnavailableError) as exc_info:
                edge_provider.synthesize_line(line, episode_id="EP-01")
            assert "edge-tts" in str(exc_info.value).lower()

        # Kokoro provider check
        if not kokoro_provider.health_check():
            with pytest.raises(ProviderUnavailableError) as exc_info:
                kokoro_provider.synthesize_line(line, episode_id="EP-01")
            assert "kokoro" in str(exc_info.value).lower()

        # Piper provider check
        if not piper_provider.health_check():
            with pytest.raises(ProviderUnavailableError) as exc_info:
                piper_provider.synthesize_line(line, episode_id="EP-01")
            assert "piper" in str(exc_info.value).lower()

    def test_registry_get_tts_provider_factory(self, temp_output_dir):
        """Verify registry helper returns configured TTS provider adapters."""
        mock_p = get_tts_provider("mock", output_dir=temp_output_dir)
        assert isinstance(mock_p, BaseTTSProvider)
        assert mock_p.provider_type == "mock_tts"

        edge_p = get_tts_provider("edge_tts", output_dir=temp_output_dir)
        assert isinstance(edge_p, EdgeTTSProvider)
        assert edge_p.provider_type == "edge_tts"


# =========================================================================
# 3. Voice Agent End-to-End Integration Tests
# =========================================================================


class TestVoiceAgentTTSIntegration:
    """Test suite for VoiceAgentV2 dialogue extraction and TTS integration."""

    def test_voice_agent_generates_audio_files_and_attaches_manifest(
        self, temp_output_dir, sample_screenplay_data
    ):
        """8. VoiceAgentV2 with generate_audio=True synthesizes dialogue and updates artifact."""
        store = ArtifactStore(base_path=temp_output_dir / "artifacts")
        mgr = ArtifactManager(artifact_store=store)

        tts = MockTTSProvider(output_dir=temp_output_dir)
        agent = VoiceAgentV2(
            artifact_manager=mgr,
            tts_provider=tts,
            generate_audio=True,
        )

        input_payload = {
            "episode_id": "EP-VOICE-E2E",
            "title": "The Awakening",
            "characters": [
                {"id": "char_001", "name": "Dr. Maya Chen"},
                {"id": "char_002", "name": "ANANTA"},
            ],
            "profiles": [
                {"id": "char_001", "name": "Dr. Maya Chen", "arc": "trust"},
                {"id": "char_002", "name": "ANANTA", "arc": "autonomy"},
            ],
            "outputs": {
                "screenplay": sample_screenplay_data,
            },
        }

        result = agent.run(input_payload)

        # 1. Output complies with standard voice_output schema
        assert "outputs" in result
        out = result["outputs"]
        assert "casting" in out
        assert "direction" in out
        assert "recording_notes" in out

        # 2. Audio files manifest attached
        assert "audio_files" in out
        assert len(out["audio_files"]) == 4
        assert out["total_audio_duration_seconds"] > 0.0

        # 3. Verify audio files actually exist on disk
        for file_info in out["audio_files"]:
            p = Path(file_info["file_path"])
            assert p.exists()
            assert p.suffix == ".wav"
            assert p.stat().st_size > 0

        # 4. Verify persisted artifact in store contains audio manifest
        stored = mgr.get_latest_artifact("EP-VOICE-E2E", "voice")
        assert stored is not None
        assert "audio_files" in stored["outputs"]
        assert len(stored["outputs"]["audio_files"]) == 4
