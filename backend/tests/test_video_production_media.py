from __future__ import annotations

import wave
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.video_production_media import (
    AudioProcessor,
    AssetSelector,
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


def test_asset_selector_uses_a_checksummed_library_video_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "video" / "selected.mp4"
    source.parent.mkdir()
    source.write_bytes(b"selected library video")
    for relative_path in (
        "装饰/MT-DEC-0003_装饰_品牌Logo_logo.png",
        "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png",
    ):
        overlay = tmp_path / relative_path
        overlay.parent.mkdir(exist_ok=True)
        overlay.write_bytes(b"overlay")
    checksum = sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "app.services.video_production_media.probe_media",
        lambda *_args: {
            "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920}],
            "format": {"duration": "8"},
        },
    )
    shot_list = {
        "shots": [
            {
                "shot_index": 0,
                "shot_code": "SHOT-01",
                "asset_code": "AG-VID-000001",
                "asset_relative_path": "video/selected.mp4",
                "asset_expected_checksum": checksum,
                "source_start_seconds": 0,
                "source_end_seconds": 6,
                "fit": "cover",
                "playback_rate": 1,
                "visual_role": "selected_library_video",
                "overlay_roles": [],
            }
        ]
    }

    plan = AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)

    assert plan["source"] == "asset_library_local_video_asset_plan_v1"
    assert plan["assets"][0]["checksum_sha256"] == checksum
    assert plan["shot_assets"][0]["relative_path"] == "video/selected.mp4"
    assert plan["shot_assets"][0]["selection_reason"] == "operator-selected material-library video"

    shot_list["shots"][0]["asset_expected_checksum"] = "0" * 64
    with pytest.raises(VideoProductionError) as error:
        AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)
    assert error.value.error_code == "SOURCE_ASSET_CHECKSUM_MISMATCH"


def test_asset_selector_freezes_a_checksummed_background_music_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "audio" / "selected.mp3"
    source.parent.mkdir()
    source.write_bytes(b"selected library audio")
    for relative_path in (
        "装饰/MT-DEC-0003_装饰_品牌Logo_logo.png",
        "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png",
    ):
        overlay = tmp_path / relative_path
        overlay.parent.mkdir(exist_ok=True)
        overlay.write_bytes(b"overlay")
    checksum = sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "app.services.video_production_media.probe_media",
        lambda *_args: {
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
            "format": {"duration": "8"},
        },
    )
    shot_list = {
        "shots": [],
        "background_music": {
            "asset_code": "AG-AUD-000001",
            "asset_relative_path": "audio/selected.mp3",
            "asset_expected_checksum": checksum,
            "gain_db": -20,
        },
    }

    plan = AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)

    assert plan["source"] == "asset_library_local_audio_asset_plan_v1"
    assert plan["background_music"] == {
        "asset_code": "AG-AUD-000001",
        "relative_path": "audio/selected.mp3",
        "file_size": len(b"selected library audio"),
        "checksum_sha256": checksum,
        "duration_seconds": 8.0,
        "gain_db": -20.0,
    }
    assert plan["assets"][-1]["media_type"] == "audio"

    shot_list["background_music"]["asset_expected_checksum"] = "0" * 64
    with pytest.raises(VideoProductionError) as error:
        AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)
    assert error.value.error_code == "BACKGROUND_MUSIC_CHECKSUM_MISMATCH"


def test_asset_selector_freezes_a_checksummed_sound_effect_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "audio" / "effect.mp3"
    source.parent.mkdir()
    source.write_bytes(b"selected sound effect")
    for relative_path in (
        "装饰/MT-DEC-0003_装饰_品牌Logo_logo.png",
        "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png",
    ):
        overlay = tmp_path / relative_path
        overlay.parent.mkdir(exist_ok=True)
        overlay.write_bytes(b"overlay")
    checksum = sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(
        "app.services.video_production_media.probe_media",
        lambda *_args: {
            "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
            "format": {"duration": "1.5"},
        },
    )

    plan = AssetSelector(tmp_path, SimpleNamespace()).select(
        {
            "shots": [],
            "sound_effect": {
                "asset_code": "AG-AUD-000002",
                "asset_relative_path": "audio/effect.mp3",
                "asset_expected_checksum": checksum,
                "gain_db": -9,
            },
        }
    )

    assert plan["sound_effect"] == {
        "asset_code": "AG-AUD-000002",
        "relative_path": "audio/effect.mp3",
        "file_size": len(b"selected sound effect"),
        "checksum_sha256": checksum,
        "duration_seconds": 1.5,
        "gain_db": -9.0,
    }
    assert plan["assets"][-1]["asset_code"] == "AG-AUD-000002"


def test_asset_selector_uses_a_checksummed_local_product_sticker(
    tmp_path: Path,
) -> None:
    sticker = tmp_path / "image" / "product.png"
    sticker.parent.mkdir()
    sticker.write_bytes(b"selected product sticker")
    for relative_path in (
        "装饰/MT-DEC-0003_装饰_品牌Logo_logo.png",
        "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png",
    ):
        overlay = tmp_path / relative_path
        overlay.parent.mkdir(exist_ok=True)
        overlay.write_bytes(b"overlay")
    checksum = sha256(sticker.read_bytes()).hexdigest()
    shot_list = {
        "shots": [],
        "product_sticker": {
            "asset_code": "AG-IMG-000001",
            "asset_relative_path": "image/product.png",
            "asset_expected_checksum": checksum,
        },
    }

    plan = AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)

    assert plan["source"] == "asset_library_local_overlay_asset_plan_v1"
    assert plan["overlays"]["product_sticker"] == "image/product.png"
    assert plan["product_sticker"] == {
        "asset_code": "AG-IMG-000001",
        "relative_path": "image/product.png",
        "file_size": len(b"selected product sticker"),
        "checksum_sha256": checksum,
    }
    assert plan["assets"][-1]["asset_code"] == "AG-IMG-000001"

    shot_list["product_sticker"]["asset_expected_checksum"] = "0" * 64
    with pytest.raises(VideoProductionError) as error:
        AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)
    assert error.value.error_code == "PRODUCT_STICKER_CHECKSUM_MISMATCH"


def test_asset_selector_uses_a_checksummed_local_brand_logo(tmp_path: Path) -> None:
    logo = tmp_path / "image" / "brand.png"
    logo.parent.mkdir()
    logo.write_bytes(b"selected brand logo")
    for relative_path in (
        "装饰/MT-DEC-0003_装饰_品牌Logo_logo.png",
        "装饰/MT-DEC-0024_装饰_商品贴片_品酒大师PRO.png",
    ):
        overlay = tmp_path / relative_path
        overlay.parent.mkdir(exist_ok=True)
        overlay.write_bytes(b"overlay")
    checksum = sha256(logo.read_bytes()).hexdigest()
    shot_list = {
        "shots": [],
        "brand_logo": {
            "asset_code": "AG-IMG-000002",
            "asset_relative_path": "image/brand.png",
            "asset_expected_checksum": checksum,
        },
    }

    plan = AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)

    assert plan["source"] == "asset_library_local_overlay_asset_plan_v1"
    assert plan["overlays"]["brand_logo"] == "image/brand.png"
    assert plan["brand_logo"] == {
        "asset_code": "AG-IMG-000002",
        "relative_path": "image/brand.png",
        "file_size": len(b"selected brand logo"),
        "checksum_sha256": checksum,
    }
    assert plan["assets"][-1]["asset_code"] == "AG-IMG-000002"

    shot_list["brand_logo"]["asset_expected_checksum"] = "0" * 64
    with pytest.raises(VideoProductionError) as error:
        AssetSelector(tmp_path, SimpleNamespace()).select(shot_list)
    assert error.value.error_code == "BRAND_LOGO_CHECKSUM_MISMATCH"


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
    sticker = tmp_path / "sticker.png"
    destination = tmp_path / "shot.mp4"
    renderer = FFmpegRenderer(tmp_path, runner)  # type: ignore[arg-type]

    renderer._render_shot(
        source,
        logo,
        sticker,
        {
            "shot_code": "SHOT-01",
            "duration_seconds": 5,
            "source_start_seconds": 2,
            "source_end_seconds": 5,
            "source_available_seconds": 3,
            "fit": "cover",
            "crop_x": 0.25,
            "crop_y": 0.75,
            "overlay_roles": ["product_sticker"],
            "transition": "fade",
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
    assert "[1:v]scale=640:640:force_original_aspect_ratio=decrease" in filters
    assert "overlay=x=(W-w)/2:y=1020:shortest=1" in filters
    assert "fade=t=in:st=0:d=0.300" in filters
    assert "fade=t=out:st=4.700:d=0.300" in filters
    assert destination.read_bytes() == b"video"


def test_narration_filter_controls_dynamics_before_loudness_normalization() -> None:
    assert NARRATION_AUDIO_FILTER.startswith("acompressor=")
    assert NARRATION_AUDIO_FILTER.endswith("loudnorm=I=-16:TP=-1.5:LRA=11")


def test_background_music_mix_loops_and_trims_to_the_final_timeline(tmp_path: Path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args, **_kwargs):  # type: ignore[no-untyped-def]
            command = [str(value) for value in args]
            self.calls.append(command)
            Path(command[-1]).write_bytes(b"audio")
            return SimpleNamespace(stdout="")

    runner = RecordingRunner()
    destination = tmp_path / "mixed.wav"
    FFmpegRenderer(tmp_path, runner)._mix_background_music(
        tmp_path / "narration.wav",
        tmp_path / "music.mp3",
        destination,
        duration_seconds=55,
        gain_db=-20,
    )

    command = runner.calls[0]
    assert command[command.index("-stream_loop") + 1] == "-1"
    filters = command[command.index("-filter_complex") + 1]
    assert "[1:a]atrim=duration=55.000" in filters
    assert "volume=-20.000dB" in filters
    assert "amix=inputs=2:duration=first" in filters
    assert destination.read_bytes() == b"audio"


def test_sound_effect_mix_delays_each_selected_shot_and_keeps_background_music(tmp_path: Path) -> None:
    class RecordingRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args, **_kwargs):  # type: ignore[no-untyped-def]
            command = [str(value) for value in args]
            self.calls.append(command)
            Path(command[-1]).write_bytes(b"audio")
            return SimpleNamespace(stdout="")

    runner = RecordingRunner()
    destination = tmp_path / "mixed.wav"
    FFmpegRenderer(tmp_path, runner)._mix_audio_layers(
        tmp_path / "narration.wav",
        destination,
        duration_seconds=55,
        background_music=(tmp_path / "music.mp3", -20),
        sound_effect=(tmp_path / "effect.mp3", -9, [0, 30]),
    )

    command = runner.calls[0]
    assert command.count(str(tmp_path / "effect.mp3")) == 2
    filters = command[command.index("-filter_complex") + 1]
    assert "adelay=0:all=1" in filters
    assert "adelay=30000:all=1" in filters
    assert "volume=-9.000dB" in filters
    assert "amix=inputs=4:duration=first" in filters
    assert destination.read_bytes() == b"audio"


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
