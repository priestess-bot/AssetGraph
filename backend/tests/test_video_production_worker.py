from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.services.video_production_models import (
    ArtifactStore,
    VIDEO_PRODUCTION_STAGES,
    VideoProductionError,
    VideoProductionStage,
)
from app.services.video_production_pipeline import (
    StageExecutionResult,
    VideoProductionPipeline,
    VideoProductionWorker,
)


class FakeRepository:
    def __init__(self) -> None:
        self.job = {
            "job_code": "AG-VJOB-20260717-000001",
            "topic": "流程验证",
            "preset_code": "zhangyu_wine_demo_v1",
            "target_duration_seconds": 70,
            "attempt": 1,
            "current_stage": "brief_generation",
            "lease_token": str(uuid4()),
            "story_brief": {},
            "script": {},
            "shot_list": {},
            "asset_plan": {},
            "quality_report": {},
        }
        self.stage_calls: list[tuple[str, str]] = []
        self.completed_asset_id: str | None = None
        self.failed: tuple[str, str] | None = None

    def claim_next(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        return dict(self.job)

    def renew_lease(self, *args: Any) -> dict[str, Any]:
        return dict(self.job)

    def start_stage(self, job_code: str, stage_name: str, *args: Any) -> dict[str, Any]:
        self.stage_calls.append(("start", stage_name))
        return {"stage_name": stage_name, "status": "running"}

    def complete_stage(
        self,
        job_code: str,
        stage_name: str,
        output_payload: dict[str, Any],
        artifacts: list[dict[str, Any]],
        *args: Any,
    ) -> dict[str, Any]:
        self.stage_calls.append(("complete", stage_name))
        assert all(not Path(item["relative_path"]).is_absolute() for item in artifacts)
        return dict(self.job)

    def fail_stage(
        self,
        job_code: str,
        stage_name: str,
        error_code: str,
        error_message: str,
        *args: Any,
    ) -> dict[str, Any]:
        self.failed = (error_code, stage_name)
        return dict(self.job)

    def complete_job(self, job_code: str, final_asset_id: str, *args: Any) -> dict[str, Any]:
        self.completed_asset_id = final_asset_id
        return dict(self.job)

    def fail_job(
        self,
        job_code: str,
        error_code: str,
        error_message: str,
        *args: Any,
    ) -> dict[str, Any]:
        self.failed = (error_code, str(self.job["current_stage"]))
        return dict(self.job)


class FakePipeline:
    def __init__(self, tmp_path: Path, *, fail_stage: VideoProductionStage | None = None) -> None:
        self.output_root = tmp_path
        self.runner = SimpleNamespace(heartbeat=None)
        self.fail_stage = fail_stage

    def new_context(self, job: dict[str, Any]) -> dict[str, Any]:
        return {"job": job, "store": ArtifactStore(self.output_root, str(job["job_code"]), 1)}

    def hydrate_for_resume(self, first_stage: VideoProductionStage, context: dict[str, Any]) -> None:
        return None

    def execute_stage(
        self,
        stage: VideoProductionStage,
        context: dict[str, Any],
    ) -> StageExecutionResult:
        if stage is self.fail_stage:
            raise VideoProductionError("EXPECTED_STAGE_FAILURE", "expected test failure")
        store: ArtifactStore = context["store"]
        key_by_stage = {
            VideoProductionStage.BRIEF_GENERATION: "story_brief",
            VideoProductionStage.SCRIPT_GENERATION: "script",
            VideoProductionStage.SHOT_PLANNING: "shot_list",
            VideoProductionStage.ASSET_SELECTION: "asset_plan",
            VideoProductionStage.VOICE_SYNTHESIS: "voice",
            VideoProductionStage.SUBTITLE_GENERATION: "subtitles",
            VideoProductionStage.RENDERING: "video",
            VideoProductionStage.QUALITY_CHECK: "quality_report",
        }
        key = key_by_stage[stage]
        if stage is VideoProductionStage.RENDERING:
            video_path = store.path("final.mp4")
            video_path.write_bytes(b"fake mp4")
            artifact = store.describe("video", video_path, mime_type="video/mp4")
            context["video_path"] = video_path
            context["video_artifact"] = artifact
        else:
            artifact = store.write_json(key, f"{key}.json", {"stage": stage.value})
        output = {"passed": True} if stage is VideoProductionStage.QUALITY_CHECK else {"stage": stage.value}
        context["quality_report"] = output if stage is VideoProductionStage.QUALITY_CHECK else {}
        return StageExecutionResult(output, [artifact])


class FakeRegistrar:
    def __init__(self) -> None:
        self.asset_id = str(uuid4())

    def register(self, **kwargs: Any) -> str:
        assert kwargs["video_path"].is_file()
        assert kwargs["quality_report"]["passed"] is True
        return self.asset_id


class FakeTTS:
    voice = "zm_yunyang"
    model = "fake-kokoro"

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def synthesize(self, text: str, destination: Path, *, speed: float = 1.0) -> Path:
        sample_rate = 24000
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            samples = (
                struct.pack("<h", round(6000 * math.sin(2 * math.pi * 440 * index / sample_rate)))
                for index in range(sample_rate * 5)
            )
            wav.writeframes(b"".join(samples))
        return destination


class FakeAssetSelector:
    def select(self, shot_list: dict[str, Any]) -> dict[str, Any]:
        return {
            "source": "test",
            "assets": [],
            "shot_assets": [
                {"shot_index": shot["shot_index"], "asset_code": shot["asset_code"]}
                for shot in shot_list["shots"]
            ],
            "overlays": {},
        }


def test_worker_executes_all_stages_and_completes_with_registered_asset(tmp_path: Path) -> None:
    repository = FakeRepository()
    registrar = FakeRegistrar()
    worker = VideoProductionWorker(
        repository=repository,
        pipeline=FakePipeline(tmp_path),  # type: ignore[arg-type]
        final_asset_registrar=registrar,
        worker_id="test-worker",
        heartbeat_seconds=1,
    )

    assert worker.run_once() is True

    assert [name for action, name in repository.stage_calls if action == "start"] == [
        stage.value for stage in VIDEO_PRODUCTION_STAGES
    ]
    assert repository.completed_asset_id == registrar.asset_id
    assert repository.failed is None


def test_worker_fails_the_current_stage_and_stops_downstream_work(tmp_path: Path) -> None:
    repository = FakeRepository()
    worker = VideoProductionWorker(
        repository=repository,
        pipeline=FakePipeline(tmp_path, fail_stage=VideoProductionStage.SCRIPT_GENERATION),  # type: ignore[arg-type]
        final_asset_registrar=FakeRegistrar(),
        worker_id="test-worker",
        heartbeat_seconds=1,
    )

    assert worker.run_once() is True

    assert repository.failed == ("EXPECTED_STAGE_FAILURE", "script_generation")
    assert repository.completed_asset_id is None
    assert ("start", "shot_planning") not in repository.stage_calls


def test_real_pipeline_reaches_subtitle_stage_with_fake_tts(tmp_path: Path) -> None:
    pipeline = VideoProductionPipeline(
        assets_root=tmp_path / "materials",
        output_root=tmp_path / "outputs",
        tts=FakeTTS(),
        enforce_demo_duration=False,
    )
    pipeline.asset_selector = FakeAssetSelector()  # type: ignore[assignment]
    job = {
        "job_code": "AG-VJOB-20260717-000099",
        "topic": "流程验证",
        "preset_code": "zhangyu_wine_demo_v1",
        "target_duration_seconds": 55,
        "attempt": 1,
    }
    context = pipeline.new_context(job)

    for stage in VIDEO_PRODUCTION_STAGES[:6]:
        result = pipeline.execute_stage(stage, context)
        assert result.artifacts

    assert context["story_brief"]["format"]["shot_count"] == 6
    assert context["script"]["quality_report"]["promotion_free"] is True
    assert len(context["voice_manifest"]["segments"]) == 6
    assert context["subtitles_path"].is_file()
    assert all(not Path(item["relative_path"]).is_absolute() for item in context["voice_manifest"]["segments"])
