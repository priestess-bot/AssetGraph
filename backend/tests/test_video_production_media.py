from __future__ import annotations

import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.video_production_media import (
    AudioProcessor,
    FFmpegRenderer,
    NARRATION_AUDIO_FILTER,
    SubprocessRunner,
    VideoQualityInspector,
    _atempo_filters,
    _source_range_filter,
    probe_media,
)
from app.services.video_production_models import ArtifactStore, VideoProductionError


def _write_wav(path: Path, seconds: float = 0.5) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * round(24000 * seconds))


def test_artifact_store_writes_atomically_and_blocks_path_escape(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, "AG-VJOB-20260717-000001", 1)
    artifact = store.write_json("script", "script.json", {"text": "内容"})

    assert artifact.relative_path.endswith("attempt-1/script.json")
    assert len(artifact.checksum_sha256) == 64
    with pytest.raises(VideoProductionError) as error:
        store.path("../../../outside.txt")
    assert error.value.error_code == "UNSAFE_ARTIFACT_PATH"


def test_subprocess_runner_uses_argument_array_and_reports_failure() -> None:
    runner = SubprocessRunner()
    result = runner.run(["/bin/sh", "-c", "printf ok"])
    assert result.stdout == "ok"
    assert runner.records[0]["args"] == ["/bin/sh", "-c", "printf ok"]

    with pytest.raises(VideoProductionError) as error:
        runner.run(["/bin/sh", "-c", "exit 7"], error_code="EXPECTED_FAILURE")
    assert error.value.error_code == "EXPECTED_FAILURE"


def test_audio_processor_fits_wav_to_exact_duration(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "fitted.wav"
    _write_wav(source, seconds=0.5)
    runner = SubprocessRunner()

    timing = AudioProcessor(runner).fit_to_duration(source, output, 1.0)
    probe = probe_media(output, runner)

    assert timing["source_duration_seconds"] == pytest.approx(0.5, abs=0.01)
    assert timing["tempo_factor"] == pytest.approx(1.0, abs=0.01)
    assert timing["speech_duration_seconds"] == pytest.approx(0.5, abs=0.01)
    assert float(probe["format"]["duration"]) == pytest.approx(1.0, abs=0.02)
    assert not list(tmp_path.glob("*.part.wav"))


def test_audio_processor_applies_a_bounded_voice_gain(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "fitted.wav"
    _write_wav(source, seconds=0.5)
    runner = SubprocessRunner()

    timing = AudioProcessor(runner).fit_to_duration(source, output, 1.0, gain_db=-6.5)

    assert timing["gain_db"] == -6.5
    assert any("volume=-6.500dB" in argument for argument in runner.records[-1]["args"])
    with pytest.raises(VideoProductionError) as error:
        AudioProcessor(runner).fit_to_duration(source, output, 1.0, gain_db=13)
    assert error.value.error_code == "VOICE_GAIN_INVALID"


def test_atempo_chain_stays_inside_ffmpeg_limits() -> None:
    assert _atempo_filters(4.5) == ["atempo=2.0", "atempo=2.0", "atempo=1.125000"]
    assert _atempo_filters(0.2) == ["atempo=0.5", "atempo=0.5", "atempo=0.800000"]


def test_source_range_filter_crops_before_looping_only_the_selected_window() -> None:
    assert _source_range_filter(3, 5) == (
        "fps=30,trim=duration=3.000,setpts=PTS-STARTPTS,"
        "loop=loop=-1:size=90:start=0,trim=duration=5.000,"
        "setpts=PTS-STARTPTS,setsar=1"
    )
    assert _source_range_filter(5, 3) == (
        "fps=30,trim=duration=5.000,setpts=PTS-STARTPTS,"
        "trim=duration=3.000,setpts=PTS-STARTPTS,setsar=1"
    )
    with pytest.raises(VideoProductionError) as error:
        _source_range_filter(0, 3)
    assert error.value.error_code == "SOURCE_RANGE_INVALID"


def test_source_range_filter_applies_playback_rate_after_looping_only_the_selected_window() -> None:
    assert _source_range_filter(3, 5, 2) == (
        "fps=30,trim=duration=3.000,setpts=PTS-STARTPTS,"
        "loop=loop=-1:size=90:start=0,trim=duration=10.000,"
        "setpts=PTS/2.000000,fps=30,trim=duration=5.000,setpts=PTS-STARTPTS,setsar=1"
    )
    assert _source_range_filter(5, 5, 0.5) == (
        "fps=30,trim=duration=5.000,setpts=PTS-STARTPTS,trim=duration=2.500,"
        "setpts=PTS/0.500000,fps=30,trim=duration=5.000,setpts=PTS-STARTPTS,setsar=1"
    )
    with pytest.raises(VideoProductionError) as error:
        _source_range_filter(3, 5, 2.1)
    assert error.value.error_code == "PLAYBACK_RATE_INVALID"


def test_shot_render_command_honors_source_end_instead_of_looping_the_full_file(tmp_path: Path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args, **_kwargs):  # type: ignore[no-untyped-def]
            command = [str(value) for value in args]
            self.calls.append(command)
            Path(command[-1]).write_bytes(b"video")
            return SimpleNamespace(stdout="")

    runner = RecordingRunner()
    source = tmp_path / "source.mp4"
    logo = tmp_path / "logo.png"
    destination = tmp_path / "shot.mp4"
    renderer = FFmpegRenderer(tmp_path, runner)  # type: ignore[arg-type]

    renderer._render_shot(
        source,
        logo,
        {
            "shot_code": "SHOT-01",
            "duration_seconds": 5,
            "source_start_seconds": 2,
            "source_end_seconds": 5,
            "source_available_seconds": 3,
            "fit": "cover",
            "crop_x": 0.25,
            "crop_y": 0.75,
            "overlay_roles": [],
            "transition": "cut",
        },
        destination,
    )

    command = runner.calls[0]
    assert command[command.index("-ss") + 1] == "2.000"
    assert "-stream_loop" not in command
    filters = command[command.index("-filter_complex") + 1]
    assert "trim=duration=3.000" in filters
    assert "loop=loop=-1:size=90:start=0" in filters
    assert "crop=1080:1920:x=(in_w-out_w)*0.250:y=(in_h-out_h)*0.750" in filters
    assert destination.read_bytes() == b"video"


def test_narration_filter_controls_dynamics_before_loudness_normalization() -> None:
    assert NARRATION_AUDIO_FILTER.startswith("acompressor=")
    assert NARRATION_AUDIO_FILTER.endswith("loudnorm=I=-16:TP=-1.5:LRA=11")


def test_freeze_segments_include_closed_and_end_of_file_ranges() -> None:
    runner = SimpleNamespace(
        run=lambda *_args, **_kwargs: SimpleNamespace(
            stderr=(
                "[freezedetect] lavfi.freezedetect.freeze_start: 1.25\n"
                "[freezedetect] lavfi.freezedetect.freeze_duration: 2.5\n"
                "[freezedetect] lavfi.freezedetect.freeze_end: 3.75\n"
                "[freezedetect] lavfi.freezedetect.freeze_start: 8.0\n"
            )
        )
    )

    segments = VideoQualityInspector(runner)._freeze_segments(Path("demo.mp4"), 10.0)

    assert segments == [
        {"start_seconds": 1.25, "end_seconds": 3.75, "duration_seconds": 2.5},
        {"start_seconds": 8.0, "end_seconds": 10.0, "duration_seconds": 2.0},
    ]


@pytest.mark.parametrize(("duration", "accepted"), [(30.0, True), (120.0, True), (29.9, False), (120.1, False)])
def test_quality_gate_uses_public_demo_duration_contract(
    monkeypatch: pytest.MonkeyPatch,
    duration: float,
    accepted: bool,
) -> None:
    monkeypatch.setattr(
        "app.services.video_production_media.probe_media",
        lambda *_args: {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
            ],
            "format": {"duration": str(duration)},
        },
    )
    inspector = VideoQualityInspector(SimpleNamespace())
    monkeypatch.setattr(inspector, "_black_segments", lambda _video: [])
    monkeypatch.setattr(inspector, "_silence_segments", lambda _video, _duration: [])
    monkeypatch.setattr(inspector, "_freeze_segments", lambda _video, _duration: [])
    monkeypatch.setattr(
        inspector,
        "_loudness",
        lambda _video: {"integrated_lufs": -16.0, "true_peak_db": -1.5, "lra": 4.0},
    )

    result = inspector.inspect(Path("demo.mp4"), target_duration_seconds=duration)

    assert result["checks"]["duration_in_demo_range"] is accepted
