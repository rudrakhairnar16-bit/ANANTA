import logging
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FFmpegUnavailableError(RuntimeError):
    """Raised when FFmpeg execution is requested but FFmpeg is not installed or not in PATH."""


class TimelineValidationError(ValueError):
    """Raised when timeline manifest validation fails."""


@dataclass
class TimelineClip:
    """Represents a visual shot/clip in chronological timeline sequence."""

    clip_id: str
    scene_id: str
    image_path: str
    duration_seconds: float
    shot_id: str | None = None
    dialogue_audio_path: str | None = None
    subtitles: str | None = None
    speaker: str | None = None
    transition: str = "cut"
    transition_duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "scene_id": self.scene_id,
            "shot_id": self.shot_id,
            "image_path": self.image_path,
            "duration_seconds": self.duration_seconds,
            "dialogue_audio_path": self.dialogue_audio_path,
            "subtitles": self.subtitles,
            "speaker": self.speaker,
            "transition": self.transition,
            "transition_duration": self.transition_duration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimelineClip":
        return cls(
            clip_id=str(data.get("clip_id", "clip_000")),
            scene_id=str(data.get("scene_id", "scene_001")),
            image_path=str(data.get("image_path", "")),
            duration_seconds=float(data.get("duration_seconds", 3.0)),
            shot_id=data.get("shot_id"),
            dialogue_audio_path=data.get("dialogue_audio_path"),
            subtitles=data.get("subtitles"),
            speaker=data.get("speaker"),
            transition=str(data.get("transition", "cut")),
            transition_duration=float(data.get("transition_duration", 0.0)),
        )


@dataclass
class AudioTrack:
    """Represents an audio track (dialogue, BGM, SFX) placed on the timeline."""

    track_id: str
    audio_path: str
    track_type: str = "dialogue"  # "dialogue", "bgm", "sfx"
    start_time_seconds: float = 0.0
    duration_seconds: float | None = None
    volume: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "audio_path": self.audio_path,
            "track_type": self.track_type,
            "start_time_seconds": self.start_time_seconds,
            "duration_seconds": self.duration_seconds,
            "volume": self.volume,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AudioTrack":
        raw_dur = data.get("duration_seconds")
        return cls(
            track_id=str(data.get("track_id", "track_000")),
            audio_path=str(data.get("audio_path", "")),
            track_type=str(data.get("track_type", "dialogue")),
            start_time_seconds=float(data.get("start_time_seconds", 0.0)),
            duration_seconds=float(raw_dur) if raw_dur is not None else None,
            volume=float(data.get("volume", 1.0)),
        )


@dataclass
class TimelineManifest:
    """Structured timeline manifest for assembling an episode video."""

    episode_id: str
    title: str = "ANANTA Episode"
    resolution: tuple[int, int] = (1280, 720)
    fps: int = 24
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    clips: list[TimelineClip] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    subtitles_path: str | None = None
    output_path: str | None = None
    is_prototype: bool = True
    has_mock_audio: bool = True
    has_placeholder_visuals: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_duration_seconds(self) -> float:
        return sum(clip.duration_seconds for clip in self.clips)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "title": self.title,
            "resolution": list(self.resolution),
            "fps": self.fps,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "total_duration_seconds": self.total_duration_seconds,
            "clips": [c.to_dict() for c in self.clips],
            "audio_tracks": [a.to_dict() for a in self.audio_tracks],
            "subtitles_path": self.subtitles_path,
            "output_path": self.output_path,
            "is_prototype": self.is_prototype,
            "has_mock_audio": self.has_mock_audio,
            "has_placeholder_visuals": self.has_placeholder_visuals,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimelineManifest":
        res_raw = data.get("resolution", [1280, 720])
        resolution = (int(res_raw[0]), int(res_raw[1])) if len(res_raw) >= 2 else (1280, 720)
        clips = [TimelineClip.from_dict(c) for c in data.get("clips", [])]
        audio_tracks = [AudioTrack.from_dict(a) for a in data.get("audio_tracks", [])]
        return cls(
            episode_id=str(data.get("episode_id", "UNKNOWN")),
            title=str(data.get("title", "ANANTA Episode")),
            resolution=resolution,
            fps=int(data.get("fps", 24)),
            video_codec=str(data.get("video_codec", "libx264")),
            audio_codec=str(data.get("audio_codec", "aac")),
            clips=clips,
            audio_tracks=audio_tracks,
            subtitles_path=data.get("subtitles_path"),
            output_path=data.get("output_path"),
            is_prototype=bool(data.get("is_prototype", True)),
            has_mock_audio=bool(data.get("has_mock_audio", True)),
            has_placeholder_visuals=bool(data.get("has_placeholder_visuals", True)),
            metadata=data.get("metadata", {}),
        )

    def validate(self, check_files_exist: bool = True) -> None:
        """Validate manifest data integrity and file existence."""
        if not self.episode_id or self.episode_id.strip() == "":
            raise TimelineValidationError("Manifest requires a non-empty episode_id.")
        if not self.clips:
            raise TimelineValidationError("Manifest must contain at least one timeline clip.")

        for i, clip in enumerate(self.clips):
            if clip.duration_seconds <= 0:
                raise TimelineValidationError(
                    f"Clip {clip.clip_id} at idx {i} invalid duration: {clip.duration_seconds}s"
                )
            if check_files_exist:
                if not clip.image_path:
                    raise TimelineValidationError(f"Clip {clip.clip_id} is missing image_path.")
                if not Path(clip.image_path).exists():
                    raise FileNotFoundError(
                        f"Image file not found for clip {clip.clip_id}: {clip.image_path}"
                    )
                if clip.dialogue_audio_path and not Path(clip.dialogue_audio_path).exists():
                    raise FileNotFoundError(
                        f"Dialogue audio not found: {clip.dialogue_audio_path}"
                    )

        if check_files_exist:
            for track in self.audio_tracks:
                if not Path(track.audio_path).exists():
                    raise FileNotFoundError(
                        f"Audio track file not found for track {track.track_id}: {track.audio_path}"
                    )


@dataclass
class RenderResult:
    """Result returned after video timeline assembly or command generation."""

    video_path: str
    duration_seconds: float
    resolution: tuple[int, int]
    fps: int
    is_prototype: bool = True
    has_mock_audio: bool = True
    has_placeholder_visuals: bool = True
    subtitles_path: str | None = None
    command_executed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_path": self.video_path,
            "duration_seconds": self.duration_seconds,
            "resolution": list(self.resolution),
            "fps": self.fps,
            "is_prototype": self.is_prototype,
            "has_mock_audio": self.has_mock_audio,
            "has_placeholder_visuals": self.has_placeholder_visuals,
            "subtitles_path": self.subtitles_path,
            "command_executed": self.command_executed,
        }


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into standard SRT timestamp HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    hrs = int(seconds // 3600)
    rem = seconds % 3600
    mins = int(rem // 60)
    secs = rem % 60
    s = int(secs)
    millis = int(round((secs - s) * 1000))
    if millis >= 1000:
        s += 1
        millis = 0
    return f"{hrs:02d}:{mins:02d}:{s:02d},{millis:03d}"


class TimelineAssembler:
    """FFmpeg-based timeline assembler for multi-clip video generation with audio & subtitles."""

    def __init__(
        self,
        ffmpeg_path: str | Path | None = None,
        default_output_dir: str | Path = "outputs",
    ):
        self.ffmpeg_path = str(ffmpeg_path) if ffmpeg_path else shutil.which("ffmpeg")
        self.default_output_dir = Path(default_output_dir)

    def is_ffmpeg_available(self) -> bool:
        """Check if FFmpeg binary is available on the host system."""
        if not self.ffmpeg_path:
            return False
        try:
            res = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                check=False,
                timeout=5,
            )
            return res.returncode == 0
        except Exception:
            return False

    def get_ffmpeg_version(self) -> str | None:
        """Retrieve FFmpeg version string if available."""
        if not self.ffmpeg_path:
            return None
        try:
            res = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout:
                first_line = res.stdout.splitlines()[0]
                return first_line.strip()
        except Exception:
            pass
        return None

    @staticmethod
    def generate_placeholder_image(
        path: str | Path,
        label: str = "PROTOTYPE",
        resolution: tuple[int, int] = (1280, 720),
        bg_color: tuple[int, int, int] = (24, 32, 48),
    ) -> Path:
        """Generate a valid 24-bit uncompressed BMP placeholder image using standard Python.

        This creates a fully compliant graphic asset usable by FFmpeg and image viewers
        without external graphics dependencies (e.g. Pillow).
        """
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        width, height = resolution
        r, g, b = bg_color

        row_bytes = width * 3
        padding = (4 - (row_bytes % 4)) % 4
        padded_row_bytes = row_bytes + padding
        image_size = padded_row_bytes * height
        file_size = 54 + image_size

        # BMP Header (14 bytes)
        bmp_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
        # DIB Header - BITMAPINFOHEADER (40 bytes)
        dib_header = struct.pack(
            "<IIIHHIIIIII", 40, width, height, 1, 24, 0, image_size, 2835, 2835, 0, 0
        )

        pixel_row = (bytes([b, g, r]) * width) + (b"\x00" * padding)
        all_pixels = pixel_row * height

        with open(target_path, "wb") as f:
            f.write(bmp_header)
            f.write(dib_header)
            f.write(all_pixels)

        return target_path

    def generate_subtitles_srt(
        self,
        manifest: TimelineManifest,
        output_path: str | Path | None = None,
    ) -> Path:
        """Generate a standard .srt subtitle file from timeline clips with dialogue/subtitles."""
        ep_id = manifest.episode_id
        if output_path:
            srt_file = Path(output_path)
        else:
            srt_file = self.default_output_dir / ep_id / "subtitles.srt"

        srt_file.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        current_time = 0.0
        subtitle_index = 1

        for clip in manifest.clips:
            clip_start = current_time
            clip_end = current_time + clip.duration_seconds
            current_time = clip_end

            sub_text = clip.subtitles
            if sub_text and sub_text.strip():
                speaker_prefix = f"[{clip.speaker}] " if clip.speaker else ""
                formatted_text = f"{speaker_prefix}{sub_text.strip()}"

                start_ts = format_srt_timestamp(clip_start)
                end_ts = format_srt_timestamp(clip_end)

                lines.append(str(subtitle_index))
                lines.append(f"{start_ts} --> {end_ts}")
                lines.append(formatted_text)
                lines.append("")
                subtitle_index += 1

        srt_file.write_text("\n".join(lines), encoding="utf-8")
        return srt_file

    def build_concat_script(
        self,
        manifest: TimelineManifest,
        script_path: str | Path,
    ) -> Path:
        """Create an FFmpeg concat demuxer script listing image clips and durations."""
        target_path = Path(script_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        content: list[str] = ["ffconcat version 1.0"]
        for clip in manifest.clips:
            safe_img_path = str(Path(clip.image_path).resolve()).replace("\\", "/")
            content.append(f"file '{safe_img_path}'")
            content.append(f"duration {clip.duration_seconds:.4f}")

        # FFmpeg concat demuxer requires repeating the last file entry to hold the last duration
        if manifest.clips:
            safe_last = str(Path(manifest.clips[-1].image_path).resolve()).replace("\\", "/")
            content.append(f"file '{safe_last}'")

        target_path.write_text("\n".join(content), encoding="utf-8")
        return target_path

    def build_manifest_from_episode(
        self,
        episode_id: str,
        screenplay_data: dict[str, Any],
        voice_audio_files: list[dict[str, Any]] | None = None,
        default_clip_duration: float = 3.0,
        generate_placeholders: bool = True,
    ) -> TimelineManifest:
        """Convenience builder to convert screenplay & voice audio into a TimelineManifest."""
        from pipeline.dialogue_extractor import DialogueExtractor

        extractor = DialogueExtractor()
        dialogue_lines = extractor.extract(screenplay_data)

        audio_by_key: dict[tuple[str, int], dict[str, Any]] = {}
        if voice_audio_files:
            for item in voice_audio_files:
                sc_id = str(item.get("scene_id", ""))
                seq = int(item.get("sequence_index", 0))
                audio_by_key[(sc_id, seq)] = item

        clips: list[TimelineClip] = []
        audio_tracks: list[AudioTrack] = []
        placeholder_dir = self.default_output_dir / episode_id / "placeholders"

        if dialogue_lines:
            running_time = 0.0
            for idx, line in enumerate(dialogue_lines):
                clip_id = f"clip_{idx:03d}"
                scene_id = line.scene_id
                audio_match = audio_by_key.get((scene_id, line.sequence_index))

                audio_path = None
                duration = default_clip_duration

                if audio_match:
                    audio_path = audio_match.get("file_path") or audio_match.get("audio_path")
                    matched_dur = float(audio_match.get("duration_seconds", 0.0))
                    if matched_dur > 0:
                        duration = max(matched_dur + 0.5, default_clip_duration)

                img_path = placeholder_dir / f"{episode_id}_{scene_id}_{idx:03d}.bmp"
                if generate_placeholders and not img_path.exists():
                    self.generate_placeholder_image(
                        img_path,
                        label=f"{scene_id} - {line.speaker}",
                        bg_color=(20 + (idx * 15) % 80, 30 + (idx * 20) % 80, 50),
                    )

                clip = TimelineClip(
                    clip_id=clip_id,
                    scene_id=scene_id,
                    image_path=str(img_path),
                    duration_seconds=duration,
                    dialogue_audio_path=audio_path,
                    subtitles=line.text,
                    speaker=line.speaker,
                )
                clips.append(clip)

                if audio_path:
                    audio_tracks.append(
                        AudioTrack(
                            track_id=f"dialogue_{idx:03d}",
                            audio_path=audio_path,
                            track_type="dialogue",
                            start_time_seconds=running_time,
                            duration_seconds=duration,
                            volume=1.0,
                        )
                    )

                running_time += duration
        else:
            img_path = placeholder_dir / f"{episode_id}_scene_001.bmp"
            if generate_placeholders and not img_path.exists():
                self.generate_placeholder_image(img_path, label=f"{episode_id} PROTOTYPE")

            clips.append(
                TimelineClip(
                    clip_id="clip_000",
                    scene_id="scene_001",
                    image_path=str(img_path),
                    duration_seconds=default_clip_duration,
                    subtitles="[ANANTA Engine Prototype]",
                    speaker="ANANTA",
                )
            )

        manifest = TimelineManifest(
            episode_id=episode_id,
            title=str(screenplay_data.get("title", f"Episode {episode_id}")),
            clips=clips,
            audio_tracks=audio_tracks,
            is_prototype=True,
            has_mock_audio=True,
            has_placeholder_visuals=generate_placeholders,
        )
        return manifest

    def build_ffmpeg_command(
        self,
        manifest: TimelineManifest,
        output_file: str | Path | None = None,
        concat_script_path: str | Path | None = None,
        overwrite: bool = False,
    ) -> list[str]:
        """Construct the FFmpeg command list for rendering the timeline manifest."""
        ffmpeg_bin = self.ffmpeg_path or "ffmpeg"
        ep_id = manifest.episode_id

        if output_file:
            out_path = Path(output_file)
        else:
            out_path = self.default_output_dir / ep_id / "prototype_episode.mp4"

        if concat_script_path:
            concat_path = Path(concat_script_path)
        else:
            concat_path = self.default_output_dir / ep_id / "timeline_concat.txt"

        cmd = [
            ffmpeg_bin,
            "-y" if overwrite else "-n",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path).replace("\\", "/"),
        ]

        has_audio = len(manifest.audio_tracks) > 0
        if has_audio:
            for track in manifest.audio_tracks:
                cmd.extend(["-i", str(Path(track.audio_path).resolve()).replace("\\", "/")])

            if len(manifest.audio_tracks) == 1:
                cmd.extend(["-c:a", manifest.audio_codec, "-b:a", "192k"])
            else:
                filter_complex = f"amix=inputs={len(manifest.audio_tracks)}:duration=longest"
                cmd.extend(
                    [
                        "-filter_complex",
                        filter_complex,
                        "-c:a",
                        manifest.audio_codec,
                        "-b:a",
                        "192k",
                    ]
                )
        else:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
            cmd.extend(["-c:a", manifest.audio_codec, "-shortest"])

        cmd.extend(
            [
                "-c:v",
                manifest.video_codec,
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(manifest.fps),
                "-s",
                f"{manifest.resolution[0]}x{manifest.resolution[1]}",
                str(out_path).replace("\\", "/"),
            ]
        )

        return cmd

    def render(
        self,
        manifest: TimelineManifest,
        output_file: str | Path | None = None,
        overwrite: bool = False,
        timeout_seconds: int = 120,
    ) -> RenderResult:
        """Assemble and render timeline clips into an MP4 video file using FFmpeg."""
        manifest.validate(check_files_exist=True)

        ep_id = manifest.episode_id
        if output_file:
            final_out = Path(output_file)
        else:
            final_out = self.default_output_dir / ep_id / "prototype_episode.mp4"

        if final_out.exists() and not overwrite:
            raise FileExistsError(
                f"Output video already exists at {final_out}. Pass overwrite=True to overwrite."
            )

        final_out.parent.mkdir(parents=True, exist_ok=True)

        srt_path = self.generate_subtitles_srt(manifest)
        manifest.subtitles_path = str(srt_path)

        concat_path = self.default_output_dir / ep_id / "timeline_concat.txt"
        self.build_concat_script(manifest, concat_path)

        if not self.is_ffmpeg_available():
            raise FFmpegUnavailableError(
                "FFmpeg is not installed or not accessible in system PATH. "
                "Please install FFmpeg (e.g. 'winget install Gyan.FFmpeg' or https://ffmpeg.org) "
                "to enable MP4 video timeline rendering."
            )

        cmd = self.build_ffmpeg_command(
            manifest=manifest,
            output_file=final_out,
            concat_script_path=concat_path,
            overwrite=overwrite,
        )

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,
            )
            logger.info("FFmpeg render completed successfully for %s", ep_id)
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr or e.stdout or str(e)
            raise RuntimeError(f"FFmpeg rendering failed: {err_msg}") from e

        return RenderResult(
            video_path=str(final_out),
            duration_seconds=manifest.total_duration_seconds,
            resolution=manifest.resolution,
            fps=manifest.fps,
            is_prototype=manifest.is_prototype,
            has_mock_audio=manifest.has_mock_audio,
            has_placeholder_visuals=manifest.has_placeholder_visuals,
            subtitles_path=str(srt_path),
            command_executed=cmd,
        )
