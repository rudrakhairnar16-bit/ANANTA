import math
import os
import re
import struct
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.dialogue_extractor import DialogueLine
from providers.base_v2 import (
    BaseProviderV2,
    ProviderConfig,
    ProviderResponse,
    ProviderUnavailableError,
)


@dataclass
class AudioMetadata:
    """Structured metadata record describing a generated speech audio file."""

    episode_id: str
    scene_id: str
    sequence_index: int
    speaker: str
    voice_id: str
    file_path: str
    format: str = "wav"
    sample_rate: int = 24000
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    provider_name: str = "BaseTTSProvider"
    provider_type: str = "tts"

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "scene_id": self.scene_id,
            "sequence_index": self.sequence_index,
            "speaker": self.speaker,
            "voice_id": self.voice_id,
            "file_path": self.file_path,
            "format": self.format,
            "sample_rate": self.sample_rate,
            "duration_seconds": self.duration_seconds,
            "file_size_bytes": self.file_size_bytes,
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AudioMetadata":
        return cls(
            episode_id=data.get("episode_id", "UNKNOWN"),
            scene_id=data.get("scene_id", "scene_001"),
            sequence_index=data.get("sequence_index", 1),
            speaker=data.get("speaker", "UNKNOWN"),
            voice_id=data.get("voice_id", "default"),
            file_path=data.get("file_path", ""),
            format=data.get("format", "wav"),
            sample_rate=data.get("sample_rate", 24000),
            duration_seconds=data.get("duration_seconds", 0.0),
            file_size_bytes=data.get("file_size_bytes", 0),
            provider_name=data.get("provider_name", "BaseTTSProvider"),
            provider_type=data.get("provider_type", "tts"),
        )


class BaseTTSProvider(BaseProviderV2, ABC):
    """Abstract Base Class for Text-to-Speech audio generation providers."""

    def __init__(
        self,
        config: ProviderConfig | None = None,
        voice_map: dict[str, str] | None = None,
        output_dir: str | Path = "outputs",
        default_voice: str = "default",
    ):
        config = config or ProviderConfig(name=type(self).__name__)
        super().__init__(config)
        self.voice_map = dict(voice_map or {})
        self.output_dir = Path(output_dir)
        self.default_voice = default_voice

    @property
    @abstractmethod
    def provider_type(self) -> str:
        return "tts"

    def get_voice_for_speaker(self, speaker: str) -> str:
        """Map character or speaker name to configured voice ID."""
        clean = speaker.strip()
        if clean in self.voice_map:
            return self.voice_map[clean]
        for k, v in self.voice_map.items():
            if k.lower() == clean.lower():
                return v
        return self.default_voice

    def get_output_path(
        self,
        episode_id: str,
        scene_id: str,
        sequence_index: int,
        speaker: str,
        ext: str = "wav",
    ) -> Path:
        """Deterministically resolve destination audio path under outputs/{episode_id}/voice/."""
        speaker_slug = re.sub(r"[^\w]+", "_", speaker.lower()).strip("_") or "speaker"
        scene_slug = re.sub(r"[^\w]+", "_", scene_id.lower()).strip("_") or "scene"
        filename = f"{episode_id}_{scene_slug}_{sequence_index:03d}_{speaker_slug}.{ext}"
        target_dir = self.output_dir / episode_id / "voice"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / filename

    @abstractmethod
    def synthesize_line(
        self,
        line: DialogueLine,
        episode_id: str,
        voice: str | None = None,
        overwrite: bool = True,
    ) -> AudioMetadata:
        """Synthesize an individual dialogue line to a playable audio file."""
        pass

    def synthesize_dialogue(
        self,
        dialogue_lines: list[DialogueLine],
        episode_id: str,
        overwrite: bool = True,
    ) -> list[AudioMetadata]:
        """Synthesize an ordered list of dialogue lines into corresponding audio files."""
        results: list[AudioMetadata] = []
        for line in dialogue_lines:
            voice = self.get_voice_for_speaker(line.speaker)
            meta = self.synthesize_line(
                line,
                episode_id=episode_id,
                voice=voice,
                overwrite=overwrite,
            )
            results.append(meta)
        return results

    def generate_sync(self, inputs: dict[str, Any], **kwargs) -> ProviderResponse:
        """Standard provider execution interface accepting dialogue_lines or screenplay."""
        import time

        start = time.perf_counter()
        episode_id = inputs.get("episode_id", "UNKNOWN")

        # 1. Check for pre-extracted dialogue lines
        lines_raw = inputs.get("dialogue_lines")
        dialogue_lines: list[DialogueLine] = []
        if isinstance(lines_raw, list):
            for item in lines_raw:
                if isinstance(item, DialogueLine):
                    dialogue_lines.append(item)
                elif isinstance(item, dict):
                    dialogue_lines.append(DialogueLine.from_dict(item))

        # 2. If not provided directly, extract from inputs/screenplay
        if not dialogue_lines:
            from pipeline.dialogue_extractor import extract_dialogue

            dialogue_lines = extract_dialogue(inputs)

        try:
            audio_manifest = self.synthesize_dialogue(dialogue_lines, episode_id=episode_id)
            latency_ms = (time.perf_counter() - start) * 1000
            self.metrics.record_success(latency_ms)

            response_data = {
                "episode_id": episode_id,
                "stage": "voice",
                "audio_files": [a.to_dict() for a in audio_manifest],
                "total_lines": len(dialogue_lines),
                "total_duration_seconds": sum(a.duration_seconds for a in audio_manifest),
                "metadata": {
                    "provider_name": self.config.name,
                    "provider_type": self.provider_type,
                    "is_fallback": getattr(self, "is_fallback", False),
                },
            }
            return ProviderResponse.success_response(
                data=response_data,
                provider_name=self.config.name,
                metrics=self.metrics,
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            self.metrics.record_error(str(e))
            return ProviderResponse.error_response(
                error=str(e),
                provider_name=self.config.name,
                metrics=self.metrics,
            )


class MockTTSProvider(BaseTTSProvider):
    """Deterministic, zero-dependency TTS provider generating valid playable PCM WAV files."""

    def __init__(
        self,
        voice_map: dict[str, str] | None = None,
        output_dir: str | Path = "outputs",
        sample_rate: int = 24000,
        is_fallback: bool = False,
    ):
        config = ProviderConfig(name="MockTTSProvider")
        super().__init__(
            config=config,
            voice_map=voice_map or {
                "Dr. Maya Chen": "maya_voice",
                "ANANTA": "ananta_synth",
                "Marcus Webb": "marcus_voice",
            },
            output_dir=output_dir,
            default_voice="mock_default",
        )
        self.sample_rate = sample_rate
        self.is_fallback = is_fallback

    @property
    def provider_type(self) -> str:
        return "mock_tts"

    def health_check(self) -> bool:
        return True

    def synthesize_line(
        self,
        line: DialogueLine,
        episode_id: str,
        voice: str | None = None,
        overwrite: bool = True,
    ) -> AudioMetadata:
        voice_id = voice or self.get_voice_for_speaker(line.speaker)
        target_path = self.get_output_path(
            episode_id=episode_id,
            scene_id=line.scene_id,
            sequence_index=line.sequence_index,
            speaker=line.speaker,
            ext="wav",
        )

        if not overwrite and target_path.exists():
            file_size = os.path.getsize(target_path)
            duration = self._read_wav_duration(target_path)
            return AudioMetadata(
                episode_id=episode_id,
                scene_id=line.scene_id,
                sequence_index=line.sequence_index,
                speaker=line.speaker,
                voice_id=voice_id,
                file_path=str(target_path),
                format="wav",
                sample_rate=self.sample_rate,
                duration_seconds=duration,
                file_size_bytes=file_size,
                provider_name=self.config.name,
                provider_type=self.provider_type,
            )

        # Generate playable PCM WAV audio
        pitch = self._get_speaker_pitch(line.speaker)
        duration = self._write_pcm_wav(target_path, line.text, pitch=pitch)
        file_size = os.path.getsize(target_path)

        return AudioMetadata(
            episode_id=episode_id,
            scene_id=line.scene_id,
            sequence_index=line.sequence_index,
            speaker=line.speaker,
            voice_id=voice_id,
            file_path=str(target_path),
            format="wav",
            sample_rate=self.sample_rate,
            duration_seconds=duration,
            file_size_bytes=file_size,
            provider_name=self.config.name,
            provider_type=self.provider_type,
        )

    def _get_speaker_pitch(self, speaker: str) -> float:
        """Assign distinct characteristic acoustic pitch per character."""
        name = speaker.lower()
        if "maya" in name:
            return 240.0  # Higher pitch (Maya)
        elif "ananta" in name:
            return 320.0  # Ethereal/synthetic higher harmonic (ANANTA)
        elif "marcus" in name:
            return 160.0  # Lower baritone pitch (Marcus)
        return 200.0

    def _write_pcm_wav(
        self,
        file_path: Path,
        text: str,
        pitch: float = 220.0,
    ) -> float:
        """Generate a valid, playable 16-bit mono PCM WAV file with speech-cadenced duration."""
        words = len(text.split()) if text.strip() else 1
        # Calculate duration based on conversational speech rate (~150 WPM / 0.4s per word)
        duration = max(0.5, words * 0.4)
        total_samples = int(self.sample_rate * duration)

        with wave.open(str(file_path), "wb") as wav_out:
            wav_out.setnchannels(1)  # Mono
            wav_out.setsampwidth(2)  # 16-bit
            wav_out.setframerate(self.sample_rate)

            # Generate smooth harmonic speech cadence with attack/release envelopes
            frames = bytearray()
            for i in range(total_samples):
                t = float(i) / self.sample_rate

                # Envelope for click-free audio transitions
                envelope = 1.0
                ramp_samples = int(self.sample_rate * 0.04)
                if i < ramp_samples:
                    envelope = i / float(ramp_samples)
                elif i > total_samples - ramp_samples:
                    envelope = (total_samples - i) / float(ramp_samples)

                # Gentle cadence frequency modulation
                freq = pitch + 18.0 * math.sin(2.0 * math.pi * 3.5 * t)
                harmonic = 0.5 * math.sin(2.0 * math.pi * freq * 2.0 * t)
                wave_sum = math.sin(2.0 * math.pi * freq * t) + harmonic
                sample_val = int(envelope * 6500.0 * wave_sum)
                frames.extend(struct.pack("<h", max(-32768, min(32767, sample_val))))

            wav_out.writeframes(frames)

        return duration

    def _read_wav_duration(self, path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as w:
                return float(w.getnframes()) / float(w.getframerate())
        except Exception:
            return 0.0


class EdgeTTSProvider(BaseTTSProvider):
    """Microsoft Edge High-Quality Neural TTS Provider Adapter."""

    def __init__(
        self,
        voice_map: dict[str, str] | None = None,
        output_dir: str | Path = "outputs",
        default_voice: str = "en-US-JennyNeural",
    ):
        config = ProviderConfig(name="EdgeTTSProvider")
        super().__init__(
            config=config,
            voice_map=voice_map or {
                "Dr. Maya Chen": "en-US-JennyNeural",
                "ANANTA": "en-US-AriaNeural",
                "Marcus Webb": "en-US-GuyNeural",
            },
            output_dir=output_dir,
            default_voice=default_voice,
        )

    @property
    def provider_type(self) -> str:
        return "edge_tts"

    def health_check(self) -> bool:
        try:
            import edge_tts  # noqa: F401

            return True
        except ImportError:
            return False

    def synthesize_line(
        self,
        line: DialogueLine,
        episode_id: str,
        voice: str | None = None,
        overwrite: bool = True,
    ) -> AudioMetadata:
        if not self.health_check():
            raise ProviderUnavailableError(
                "edge-tts package is not installed. Install with: pip install edge-tts"
            )

        import asyncio

        import edge_tts

        voice_id = voice or self.get_voice_for_speaker(line.speaker)
        target_path = self.get_output_path(
            episode_id=episode_id,
            scene_id=line.scene_id,
            sequence_index=line.sequence_index,
            speaker=line.speaker,
            ext="mp3",
        )

        if not overwrite and target_path.exists():
            file_size = os.path.getsize(target_path)
            return AudioMetadata(
                episode_id=episode_id,
                scene_id=line.scene_id,
                sequence_index=line.sequence_index,
                speaker=line.speaker,
                voice_id=voice_id,
                file_path=str(target_path),
                format="mp3",
                sample_rate=24000,
                duration_seconds=0.0,
                file_size_bytes=file_size,
                provider_name=self.config.name,
                provider_type=self.provider_type,
            )

        async def _synthesize():
            communicate = edge_tts.Communicate(line.text, voice_id)
            await communicate.save(str(target_path))

        asyncio.run(_synthesize())
        file_size = os.path.getsize(target_path) if target_path.exists() else 0

        return AudioMetadata(
            episode_id=episode_id,
            scene_id=line.scene_id,
            sequence_index=line.sequence_index,
            speaker=line.speaker,
            voice_id=voice_id,
            file_path=str(target_path),
            format="mp3",
            sample_rate=24000,
            duration_seconds=0.0,
            file_size_bytes=file_size,
            provider_name=self.config.name,
            provider_type=self.provider_type,
        )


class KokoroTTSProvider(BaseTTSProvider):
    """Kokoro-82M Lightweight Local Neural TTS Provider Adapter."""

    def __init__(
        self,
        voice_map: dict[str, str] | None = None,
        output_dir: str | Path = "outputs",
        default_voice: str = "af_sarah",
    ):
        config = ProviderConfig(name="KokoroTTSProvider")
        super().__init__(
            config=config,
            voice_map=voice_map or {
                "Dr. Maya Chen": "af_sarah",
                "ANANTA": "af_bella",
                "Marcus Webb": "am_michael",
            },
            output_dir=output_dir,
            default_voice=default_voice,
        )

    @property
    def provider_type(self) -> str:
        return "kokoro"

    def health_check(self) -> bool:
        try:
            import kokoro_onnx  # noqa: F401

            return True
        except ImportError:
            return False

    def synthesize_line(
        self,
        line: DialogueLine,
        episode_id: str,
        voice: str | None = None,
        overwrite: bool = True,
    ) -> AudioMetadata:
        if not self.health_check():
            raise ProviderUnavailableError(
                "kokoro-onnx is not installed. Install with: pip install kokoro-onnx soundfile"
            )
        raise NotImplementedError(
            "KokoroTTS runtime integration requires kokoro-onnx model weights"
        )


class PiperTTSProvider(BaseTTSProvider):
    """Piper Fast Offline Neural TTS Provider Adapter."""

    def __init__(
        self,
        voice_map: dict[str, str] | None = None,
        output_dir: str | Path = "outputs",
        default_voice: str = "en_US-lessac-medium",
    ):
        config = ProviderConfig(name="PiperTTSProvider")
        super().__init__(
            config=config,
            voice_map=voice_map or {
                "Dr. Maya Chen": "en_US-lessac-medium",
                "ANANTA": "en_US-amy-medium",
                "Marcus Webb": "en_US-ryan-medium",
            },
            output_dir=output_dir,
            default_voice=default_voice,
        )

    @property
    def provider_type(self) -> str:
        return "piper"

    def health_check(self) -> bool:
        try:
            import piper  # noqa: F401

            return True
        except ImportError:
            return False

    def synthesize_line(
        self,
        line: DialogueLine,
        episode_id: str,
        voice: str | None = None,
        overwrite: bool = True,
    ) -> AudioMetadata:
        if not self.health_check():
            raise ProviderUnavailableError(
                "piper-tts is not installed. Install with: pip install piper-tts"
            )
        raise NotImplementedError("PiperTTS runtime integration requires piper voice ONNX model")
