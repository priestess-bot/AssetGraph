from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.video_productions import VideoProductionArtifactRegistration
from app.domain.contracts import canonical_fingerprint
from app.services.video_production_models import ArtifactStore, VideoProductionError
from app.services.video_production_pipeline import (
    VideoProductionPipeline,
    build_render_manifest,
    build_render_manifest_difference,
)
from app.services.video_production_preset import (
    DEFAULT_TOPIC,
    PRODUCT_FACTS,
    generate_commercial_script,
    generate_story_brief,
    plan_shots,
)
from app.services.video_production_subtitles import build_ass_subtitles


def test_demo_preset_generates_verified_script_and_six_contiguous_shots() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)

    assert brief["verified_facts"] == list(PRODUCT_FACTS)
    assert brief["content_rules"]["topic_is_not_a_fact_source"] is True
    assert 190 <= script["quality_report"]["chinese_character_count"] <= 230
    assert script["quality_report"]["promotion_free"] is True
    assert script["section_count"] == 6
    assert "P R O" in script["sections"][1]["tts_text"]
    assert shot_list["shot_count"] == 6
    assert shot_list["duration_seconds"] == 55
    assert [shot["asset_code"] for shot in shot_list["shots"]] == [
        "MT-VID-0027",
        "MT-VID-0016",
        "MT-VID-0027",
        "MT-VID-0016",
        "MT-VID-0024",
        "MT-VID-0016",
    ]
    assert shot_list["shots"][0]["start_seconds"] == 0
    assert shot_list["shots"][-1]["end_seconds"] == 55
    assert [shot["transition"] for shot in shot_list["shots"]] == [
        "cut",
        "cut",
        "cut",
        "cut",
        "cut",
        "fade_out",
    ]
    assert all(
        left["end_seconds"] == right["start_seconds"]
        for left, right in zip(shot_list["shots"], shot_list["shots"][1:])
    )


def test_topic_changes_angle_but_never_becomes_a_product_fact() -> None:
    topic = "送礼场景，限量库存第一名"
    brief = generate_story_brief(topic)
    script = generate_commercial_script(brief)

    assert brief["creative_angle"] == "gift"
    assert script["title"] == topic
    assert topic not in script["spoken_script"]
    assert not any(term in script["spoken_script"] for term in ("限量", "库存", "第一"))


def test_preset_rejects_unknown_domain_and_unsupported_duration() -> None:
    with pytest.raises(VideoProductionError, match="unsupported preset"):
        generate_story_brief("主题", preset_code="unknown")
    with pytest.raises(VideoProductionError, match="between 30 and 120"):
        generate_story_brief("主题", target_duration_seconds=15)


def test_ass_subtitles_are_complete_monotonic_and_stay_within_safe_lines() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)

    content, manifest = build_ass_subtitles(shot_list)

    assert content.startswith("[Script Info]")
    assert "Noto Sans CJK SC" in content
    assert manifest["headline_event_count"] == 6
    assert manifest["text_complete"] is True
    assert manifest["truncated_event_count"] == 0
    assert "…" not in content
    captions = [event for event in manifest["events"] if event["kind"] == "caption"]
    assert captions
    assert all(event["start_seconds"] < event["end_seconds"] for event in captions)
    assert all(
        len(lines) <= 2
        and all(
            len(re.findall(r".", line)) <= (19 if event["kind"] == "caption" else 16)
            for line in lines
        )
        for event in manifest["events"]
        for lines in [event["text"].splitlines()]
    )
    for shot in shot_list["shots"]:
        rendered = "".join(
            event["source_text"]
            for event in captions
            if event["shot_index"] == shot["shot_index"]
        )
        assert re.sub(r"\s+", "", rendered) == re.sub(r"\s+", "", shot["narration"])


def test_ass_subtitles_stop_at_real_speech_duration() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)
    voice_manifest = {
        "segments": [
            {"shot_index": shot["shot_index"], "speech_duration_seconds": 4.25}
            for shot in shot_list["shots"]
        ]
    }

    _, manifest = build_ass_subtitles(shot_list, voice_manifest)

    for shot in shot_list["shots"]:
        captions = [
            event
            for event in manifest["events"]
            if event["kind"] == "caption" and event["shot_index"] == shot["shot_index"]
        ]
        assert captions[-1]["end_seconds"] == pytest.approx(shot["start_seconds"] + 4.25, abs=0.001)


def test_ass_subtitles_freeze_source_blocks_and_estimated_word_timing() -> None:
    shot_list = {
        "shots": [
            {
                "shot_index": 0,
                "shot_code": "SHOT-01",
                "source_shot_code": "CONTENT-SHOT-01",
                "source_script_block_codes": ["BLOCK-001", "BLOCK-002"],
                "start_seconds": 0.0,
                "end_seconds": 4.0,
                "narration": "你好 world！",
                "screen_text": "标题",
            }
        ]
    }

    _, manifest = build_ass_subtitles(shot_list)

    caption = next(event for event in manifest["events"] if event["kind"] == "caption")
    timing = caption["word_timing"]
    assert caption["source_shot_code"] == "CONTENT-SHOT-01"
    assert caption["source_script_block_codes"] == ["BLOCK-001", "BLOCK-002"]
    assert caption["timing_source"] == "text_weight_estimate_v1"
    assert "".join(item["text"] for item in timing) == "你好world！"
    assert timing[0]["start_seconds"] == 0.0
    assert timing[-1]["end_seconds"] == 4.0
    assert all(
        left["end_seconds"] <= right["start_seconds"]
        for left, right in zip(timing, timing[1:])
    )
    assert manifest["word_timing_source"] == "text_weight_estimate_v1"
    assert manifest["word_timing_count"] == len(timing)


def test_ass_subtitles_honor_the_fixed_caption_position() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)
    shot_list["shots"][0]["caption_position"] = "center"

    content, manifest = build_ass_subtitles(shot_list)

    first_caption = next(event for event in manifest["events"] if event["kind"] == "caption")
    assert first_caption["caption_position"] == "center"
    assert manifest["caption_position_counts"]["center"] > 0
    assert ",CaptionCenter," in content


def test_ass_subtitles_honor_the_frozen_preset_and_safe_bottom_margin() -> None:
    brief = generate_story_brief(DEFAULT_TOPIC)
    script = generate_commercial_script(brief)
    shot_list = plan_shots(brief, script)
    shot_list["subtitle_style"] = {"preset": "large", "safe_bottom_px": 240}

    content, manifest = build_ass_subtitles(shot_list)

    assert "Style: Caption,Noto Sans CJK SC,62," in content
    assert ",72,72,240,1" in content
    assert manifest["subtitle_style"] == {"preset": "large", "safe_bottom_px": 240}
    assert manifest["safe_margins"]["bottom"] == 240


def test_render_manifest_fixes_input_and_output_checksums_without_local_paths(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "output", "VIDJOB-000001", 1)
    store.write_text("subtitles", "subtitles/subtitles.ass", "[Events]\n", mime_type="text/x-ssa")
    commands = store.write_json("render_log", "render/commands.json", {"commands": []})
    video = store.path("final.mp4")
    poster = store.path("poster.jpg")
    contact_sheet = store.path("contact-sheet.jpg")
    video.write_bytes(b"video")
    poster.write_bytes(b"poster")
    contact_sheet.write_bytes(b"contact-sheet")
    shot_list = {
        "duration_seconds": 55,
        "poster_time_seconds": 7.5,
        "shots": [{"shot_code": "SHOT-01"}],
    }
    asset_plan = {"assets": [{"asset_code": "ASSET-01", "relative_path": "videos/a.mp4", "checksum_sha256": "a" * 64}]}
    voice_manifest = {"segments": [{"shot_index": 0, "relative_path": "VIDJOB-000001/attempt-1/voice/1.wav", "checksum_sha256": "b" * 64}]}

    manifest = build_render_manifest(
        render_result={"source": "ffmpeg_render_v1", "video": {"codec_name": "h264"}, "encoding": {"audio_codec": "aac"}},
        shot_list=shot_list,
        asset_plan=asset_plan,
        voice_manifest=voice_manifest,
        subtitle_manifest={"font": "Noto Sans CJK SC"},
        subtitles_path=store.job_root / "subtitles/subtitles.ass",
        video_path=video,
        poster_path=poster,
        poster_time_seconds=7.5,
        contact_sheet_path=contact_sheet,
        contact_sheet_metadata={
            "sample_count": 6,
            "sample_times_seconds": [0, 11, 22, 33, 44, 55],
            "sampling_rule": "equal_interval_fps_3x2",
            "grid": {"columns": 3, "rows": 2},
        },
        command_log=commands,
        toolchain={"ffmpeg": "ffmpeg version fixture", "ffprobe": "ffprobe version fixture"},
        store=store,
    )

    assert manifest["schema_version"] == "render-manifest.v1"
    assert manifest["timeline"]["source"] == "worker_shot_list.v1"
    assert manifest["timeline"]["fingerprint_sha256"] == canonical_fingerprint(shot_list)
    assert manifest["timeline"]["fingerprint_sha256"]
    assert manifest["inputs"]["assets"][0]["checksum_sha256"] == "a" * 64
    assert manifest["outputs"]["video"]["relative_path"].startswith("VIDJOB-000001/")
    assert manifest["toolchain"]["ffmpeg"] == "ffmpeg version fixture"
    assert manifest["outputs"]["poster"]["at_seconds"] == 7.5
    assert manifest["outputs"]["contact_sheet"]["sample_count"] == 6
    assert str(tmp_path) not in str(manifest)
    assert VideoProductionArtifactRegistration(
        artifact_key="render_manifest",
        relative_path="VIDJOB-000001/attempt-1/render/manifest.json",
        mime_type="application/json",
        file_size=1,
        checksum_sha256="c" * 64,
    ).artifact_key == "render_manifest"


def test_render_manifest_freezes_functional_production_timeline(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "output", "VIDJOB-000001", 1)
    store.write_text("subtitles", "subtitles/subtitles.ass", "[Events]\n", mime_type="text/x-ssa")
    commands = store.write_json("render_log", "render/commands.json", {"commands": []})
    video = store.path("final.mp4")
    poster = store.path("poster.jpg")
    contact_sheet = store.path("contact-sheet.jpg")
    video.write_bytes(b"video")
    poster.write_bytes(b"poster")
    contact_sheet.write_bytes(b"contact-sheet")
    production_timeline = {
        "schema_version": "otio-compatible-production-timeline.v2",
        "editorial_time_rate": 1000,
        "global_time_range": {
            "start_time": {"value": 0, "rate": 1000},
            "duration": {"value": 55_000, "rate": 1000},
        },
        "tracks": [],
    }
    shot_list = {
        "duration_seconds": 55,
        "shots": [{"shot_code": "SHOT-01"}],
        "production_timeline": production_timeline,
    }

    manifest = build_render_manifest(
        render_result={"source": "ffmpeg_render_v1"},
        shot_list=shot_list,
        asset_plan={"assets": []},
        voice_manifest={"segments": []},
        subtitle_manifest={},
        subtitles_path=store.job_root / "subtitles/subtitles.ass",
        video_path=video,
        poster_path=poster,
        poster_time_seconds=1.0,
        contact_sheet_path=contact_sheet,
        contact_sheet_metadata={},
        command_log=commands,
        toolchain={},
        store=store,
    )

    assert manifest["timeline"] == {
        "source": "functional_production_timeline.v2",
        "shot_count": 1,
        "duration_seconds": 55.0,
        "fingerprint_sha256": canonical_fingerprint(production_timeline),
        "shot_list_fingerprint_sha256": canonical_fingerprint(shot_list),
        "document": production_timeline,
    }


def test_render_manifest_retry_diff_separates_input_and_output_changes() -> None:
    previous = {
        "manifest_fingerprint": "a" * 64,
        "renderer": {"source": "ffmpeg_render_v1"},
        "timeline": {"fingerprint_sha256": "b" * 64},
        "inputs": {"asset_plan_fingerprint_sha256": "c" * 64},
        "commands": {"checksum_sha256": "d" * 64},
        "toolchain": {"ffmpeg": "version 1"},
        "encoding": {"audio_codec": "aac"},
        "outputs": {
            "video": {"checksum_sha256": "e" * 64},
            "poster": {"checksum_sha256": "f" * 64},
            "contact_sheet": {"checksum_sha256": "0" * 64},
        },
    }
    current = {
        **previous,
        "manifest_fingerprint": "1" * 64,
        "outputs": {
            **previous["outputs"],
            "video": {"checksum_sha256": "2" * 64},
        },
    }

    diff = build_render_manifest_difference(
        previous,
        current,
        previous_relative_path="VIDJOB-000001/attempt-1/render/manifest.json",
    )

    assert diff == {
        "schema_version": "render-manifest-diff.v1",
        "previous_relative_path": "VIDJOB-000001/attempt-1/render/manifest.json",
        "previous_manifest_fingerprint": "a" * 64,
        "current_manifest_fingerprint": "1" * 64,
        "same_input": True,
        "same_output": False,
        "same_manifest": False,
        "changed_input_sections": [],
        "changed_output_sections": ["video"],
        "classification": "output_changed_with_fixed_inputs",
    }

    changed_input = build_render_manifest_difference(
        previous,
        {**current, "toolchain": {"ffmpeg": "version 2"}},
        previous_relative_path="VIDJOB-000001/attempt-1/render/manifest.json",
    )
    assert changed_input["classification"] == "input_changed"
    assert changed_input["changed_input_sections"] == ["toolchain"]


def test_poster_generation_uses_the_selected_timeline_time(tmp_path: Path) -> None:
    class PosterRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, args, **_kwargs):  # type: ignore[no-untyped-def]
            command = [str(argument) for argument in args]
            self.commands.append(command)
            Path(command[-1]).write_bytes(b"poster")
            return SimpleNamespace(stdout="")

    runner = PosterRunner()
    pipeline = VideoProductionPipeline(
        assets_root=tmp_path / "materials",
        output_root=tmp_path / "output",
        tts=SimpleNamespace(),
        runner=runner,
    )
    store = ArtifactStore(tmp_path / "output", "VIDJOB-000001", 1)

    poster = pipeline._poster(tmp_path / "final.mp4", store, at_seconds=7.5)

    assert poster.read_bytes() == b"poster"
    assert runner.commands[0][runner.commands[0].index("-ss") + 1] == "7.500"


def test_contact_sheet_generation_uses_a_fixed_six_frame_grid(tmp_path: Path) -> None:
    class ContactSheetRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, args, **_kwargs):  # type: ignore[no-untyped-def]
            command = [str(argument) for argument in args]
            self.commands.append(command)
            Path(command[-1]).write_bytes(b"contact-sheet")
            return SimpleNamespace(stdout="")

    runner = ContactSheetRunner()
    pipeline = VideoProductionPipeline(
        assets_root=tmp_path / "materials",
        output_root=tmp_path / "output",
        tts=SimpleNamespace(),
        runner=runner,
    )
    store = ArtifactStore(tmp_path / "output", "VIDJOB-000001", 1)

    contact_sheet, metadata = pipeline._contact_sheet(
        tmp_path / "final.mp4",
        store,
        duration_seconds=55,
    )

    assert contact_sheet.read_bytes() == b"contact-sheet"
    filters = runner.commands[0][runner.commands[0].index("-vf") + 1]
    assert "fps=6/55.000" in filters
    assert "tile=3x2:padding=8:margin=8" in filters
    assert metadata["sample_times_seconds"] == [0.0, 11.0, 22.0, 33.0, 44.0, 55.0]


def test_render_pipeline_caches_its_local_tool_versions(tmp_path: Path) -> None:
    class VersionRunner:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def run(self, args, **_kwargs):  # type: ignore[no-untyped-def]
            tool = str(args[0])
            self.calls.append(tool)
            return SimpleNamespace(stdout=f"{tool} version fixture\n")

    runner = VersionRunner()
    pipeline = VideoProductionPipeline(
        assets_root=tmp_path / "materials",
        output_root=tmp_path / "outputs",
        tts=object(),  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
    )

    assert pipeline._tool_versions() == {
        "ffmpeg": "ffmpeg version fixture",
        "ffprobe": "ffprobe version fixture",
    }
    assert pipeline._tool_versions()["ffmpeg"] == "ffmpeg version fixture"
    assert runner.calls == ["ffmpeg", "ffprobe"]
