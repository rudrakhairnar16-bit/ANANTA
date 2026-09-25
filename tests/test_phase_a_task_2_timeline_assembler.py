from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.timeline_assembler import (
    AudioTrack,
    FFmpegUnavailableError,
    TimelineAssembler,
    TimelineClip,
    TimelineManifest,
    TimelineValidationError,
    format_srt_timestamp,
)


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """Fixture providing temporary test directory with sample placeholder image and wav file."""
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    img_path = tmp_path / "sample_placeholder.bmp"
    TimelineAssembler.generate_placeholder_image(
        img_path,
        label="TEST SCENE",
        resolution=(640, 360),
    )

    # Generate a dummy wav file with RIFF header
    dummy_header = (
        b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )
    wav_path = tmp_path / "sample_dialogue.wav"
    wav_path.write_bytes(dummy_header)

    return {
        "root": tmp_path,
        "output_dir": output_dir,
        "img_path": img_path,
        "wav_path": wav_path,
    }


def test_srt_timestamp_formatting():
    """Verify SRT timestamp formatting HH:MM:SS,mmm across various durations."""
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(1.5) == "00:00:01,500"
    assert format_srt_timestamp(65.25) == "00:01:05,250"
    assert format_srt_timestamp(3661.123) == "01:01:01,123"
    assert format_srt_timestamp(-5.0) == "00:00:00,000"


def test_timeline_manifest_serialization(temp_workspace):
    """Verify manifest serialization to/from dictionary and duration calculation."""
    img_path = str(temp_workspace["img_path"])
    wav_path = str(temp_workspace["wav_path"])

    clip1 = TimelineClip(
        clip_id="clip_001",
        scene_id="SCENE_01",
        shot_id="SHOT_01",
        image_path=img_path,
        duration_seconds=2.5,
        dialogue_audio_path=wav_path,
        subtitles="First line of dialogue.",
        speaker="MAYA",
    )
    clip2 = TimelineClip(
        clip_id="clip_002",
        scene_id="SCENE_01",
        shot_id="SHOT_02",
        image_path=img_path,
        duration_seconds=3.5,
        dialogue_audio_path=wav_path,
        subtitles="Second line of dialogue.",
        speaker="ANANTA",
    )
    track = AudioTrack(
        track_id="bgm_001",
        audio_path=wav_path,
        track_type="bgm",
        start_time_seconds=0.0,
        duration_seconds=6.0,
        volume=0.3,
    )

    manifest = TimelineManifest(
        episode_id="EP_TEST_001",
        title="Test Episode",
        resolution=(1280, 720),
        fps=24,
        clips=[clip1, clip2],
        audio_tracks=[track],
        is_prototype=True,
    )

    assert manifest.total_duration_seconds == 6.0
    data = manifest.to_dict()
    assert data["episode_id"] == "EP_TEST_001"
    assert len(data["clips"]) == 2
    assert len(data["audio_tracks"]) == 1

    restored = TimelineManifest.from_dict(data)
    assert restored.episode_id == manifest.episode_id
    assert restored.total_duration_seconds == 6.0
    assert len(restored.clips) == 2
    assert restored.clips[0].speaker == "MAYA"
    assert restored.clips[1].speaker == "ANANTA"


def test_manifest_validation_scene_ordering_and_missing_files(temp_workspace):
    """Test validation detects empty episode IDs, invalid durations, and missing files."""
    img_path = str(temp_workspace["img_path"])

    # Empty episode ID
    bad_ep = TimelineManifest(episode_id="", clips=[TimelineClip("c1", "s1", img_path, 2.0)])
    with pytest.raises(TimelineValidationError, match="non-empty episode_id"):
        bad_ep.validate(check_files_exist=False)

    # Empty clips
    empty_clips = TimelineManifest(episode_id="EP_01", clips=[])
    with pytest.raises(TimelineValidationError, match="at least one timeline clip"):
        empty_clips.validate(check_files_exist=False)

    # Negative duration
    bad_dur = TimelineManifest(
        episode_id="EP_01",
        clips=[TimelineClip("c1", "s1", img_path, -1.0)],
    )
    with pytest.raises(TimelineValidationError, match="invalid duration"):
        bad_dur.validate(check_files_exist=False)

    # Missing image file
    non_existent_img = str(temp_workspace["root"] / "missing.bmp")
    missing_file_manifest = TimelineManifest(
        episode_id="EP_01",
        clips=[TimelineClip("c1", "s1", non_existent_img, 2.0)],
    )
    with pytest.raises(FileNotFoundError, match="Image file not found"):
        missing_file_manifest.validate(check_files_exist=True)


def test_placeholder_image_generation(tmp_path: Path):
    """Verify BMP placeholder image generation produces valid file headers and data."""
    target_img = tmp_path / "test_bmp.bmp"
    generated = TimelineAssembler.generate_placeholder_image(
        target_img,
        label="TEST SCENE",
        resolution=(320, 240),
        bg_color=(50, 100, 150),
    )

    assert generated.exists()
    assert generated.stat().st_size > 0
    with open(generated, "rb") as f:
        header = f.read(2)
        assert header == b"BM"


def test_subtitle_srt_generation(temp_workspace):
    """Verify SRT generation writes sequential subtitles with speaker tags and timecodes."""
    img_path = str(temp_workspace["img_path"])
    assembler = TimelineAssembler(default_output_dir=temp_workspace["output_dir"])

    manifest = TimelineManifest(
        episode_id="EP_SUB_TEST",
        clips=[
            TimelineClip("c1", "s1", img_path, 2.0, subtitles="Initiating engine.", speaker="MAYA"),
            TimelineClip("c2", "s1", img_path, 3.0, subtitles="Engine active.", speaker="ANANTA"),
            TimelineClip("c3", "s2", img_path, 1.5, subtitles=None),  # Silent clip
        ],
    )

    srt_path = assembler.generate_subtitles_srt(manifest)
    assert srt_path.exists()

    content = srt_path.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:02,000\n[MAYA] Initiating engine." in content
    assert "2\n00:00:02,000 --> 00:00:05,000\n[ANANTA] Engine active." in content
    assert "3\n" not in content


def test_concat_script_generation(temp_workspace):
    """Verify FFmpeg concat demuxer script generation formatting."""
    img_path = str(temp_workspace["img_path"])
    assembler = TimelineAssembler(default_output_dir=temp_workspace["output_dir"])

    manifest = TimelineManifest(
        episode_id="EP_CONCAT_TEST",
        clips=[
            TimelineClip("c1", "s1", img_path, 2.5),
            TimelineClip("c2", "s2", img_path, 4.0),
        ],
    )

    concat_file = temp_workspace["output_dir"] / "concat.txt"
    assembler.build_concat_script(manifest, concat_file)

    assert concat_file.exists()
    lines = concat_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "ffconcat version 1.0"
    assert "duration 2.5000" in lines[2]
    assert "duration 4.0000" in lines[4]


def test_build_manifest_from_screenplay_and_voice(temp_workspace):
    """Verify automatic construction of TimelineManifest from screenplay data and audio outputs."""
    assembler = TimelineAssembler(default_output_dir=temp_workspace["output_dir"])
    wav_path = str(temp_workspace["wav_path"])

    screenplay_data = {
        "title": "Quantum Horizon",
        "scenes": [
            {
                "scene_id": "SCENE_01",
                "dialogue": [
                    {"speaker": "MAYA", "text": "The timeline is stable."},
                    {"speaker": "ANANTA", "text": "Confirmed. Proceed to warp."},
                ],
            }
        ],
    }
    voice_audio = [
        {
            "scene_id": "SCENE_01",
            "sequence_index": 1,
            "speaker": "MAYA",
            "audio_path": wav_path,
            "duration_seconds": 2.2,
        },
        {
            "scene_id": "SCENE_01",
            "sequence_index": 2,
            "speaker": "ANANTA",
            "audio_path": wav_path,
            "duration_seconds": 3.1,
        },
    ]

    manifest = assembler.build_manifest_from_episode(
        episode_id="EP_BUILD_001",
        screenplay_data=screenplay_data,
        voice_audio_files=voice_audio,
    )

    assert manifest.episode_id == "EP_BUILD_001"
    assert len(manifest.clips) == 2
    assert manifest.clips[0].speaker == "MAYA"
    assert manifest.clips[0].subtitles == "The timeline is stable."
    assert manifest.clips[1].speaker == "ANANTA"
    assert len(manifest.audio_tracks) == 2
    assert manifest.is_prototype is True


def test_ffmpeg_command_construction(temp_workspace):
    """Verify generated FFmpeg command includes codec, resolution, and audio mapping."""
    img_path = str(temp_workspace["img_path"])
    wav_path = str(temp_workspace["wav_path"])
    assembler = TimelineAssembler(
        ffmpeg_path="C:/ffmpeg/bin/ffmpeg.exe",
        default_output_dir=temp_workspace["output_dir"],
    )

    manifest = TimelineManifest(
        episode_id="EP_CMD_TEST",
        resolution=(1280, 720),
        fps=24,
        clips=[TimelineClip("c1", "s1", img_path, 3.0)],
        audio_tracks=[AudioTrack("t1", wav_path, "dialogue")],
    )

    cmd = assembler.build_ffmpeg_command(manifest, overwrite=True)

    assert "C:/ffmpeg/bin/ffmpeg.exe" in cmd[0]
    assert "-y" in cmd
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "1280x720" in cmd
    assert "-r" in cmd
    assert "24" in cmd
    assert "-c:a" in cmd
    assert "aac" in cmd


def test_ffmpeg_unavailable_error(temp_workspace):
    """Verify render() raises FFmpegUnavailableError with helpful message when FFmpeg is missing."""
    img_path = str(temp_workspace["img_path"])
    assembler = TimelineAssembler(
        ffmpeg_path="/non_existent/ffmpeg.exe",
        default_output_dir=temp_workspace["output_dir"],
    )

    manifest = TimelineManifest(
        episode_id="EP_UNAVAIL",
        clips=[TimelineClip("c1", "s1", img_path, 2.0)],
    )

    with pytest.raises(FFmpegUnavailableError, match="FFmpeg is not installed or not accessible"):
        assembler.render(manifest)


def test_output_overwrite_protection(temp_workspace):
    """Verify render() raises FileExistsError when output file exists and overwrite=False."""
    img_path = str(temp_workspace["img_path"])
    assembler = TimelineAssembler(default_output_dir=temp_workspace["output_dir"])

    manifest = TimelineManifest(
        episode_id="EP_OVERWRITE",
        clips=[TimelineClip("c1", "s1", img_path, 2.0)],
    )

    out_file = temp_workspace["output_dir"] / "EP_OVERWRITE" / "prototype_episode.mp4"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("existing content", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Output video already exists"):
        assembler.render(manifest, output_file=out_file, overwrite=False)


def test_mocked_ffmpeg_render_execution(temp_workspace):
    """Verify render() executes FFmpeg command via subprocess and returns valid RenderResult."""
    img_path = str(temp_workspace["img_path"])
    wav_path = str(temp_workspace["wav_path"])
    assembler = TimelineAssembler(
        ffmpeg_path="ffmpeg",
        default_output_dir=temp_workspace["output_dir"],
    )

    manifest = TimelineManifest(
        episode_id="EP_MOCK_RENDER",
        resolution=(1280, 720),
        fps=24,
        clips=[TimelineClip("c1", "s1", img_path, 2.5, subtitles="Testing line", speaker="MAYA")],
        audio_tracks=[AudioTrack("t1", wav_path, "dialogue")],
        is_prototype=True,
    )

    with (
        patch.object(assembler, "is_ffmpeg_available", return_value=True),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = assembler.render(manifest, overwrite=True)

        assert result.video_path.endswith("prototype_episode.mp4")
        assert result.duration_seconds == 2.5
        assert result.resolution == (1280, 720)
        assert result.fps == 24
        assert result.is_prototype is True
        assert result.has_mock_audio is True
        assert result.has_placeholder_visuals is True
        assert result.subtitles_path is not None
        assert Path(result.subtitles_path).exists()
        assert mock_run.called
