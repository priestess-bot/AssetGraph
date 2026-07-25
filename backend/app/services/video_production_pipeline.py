from __future__ import annotations

import json
import math
import mimetypes
import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.domain.contracts import canonical_fingerprint
from app.repositories.assets import AssetRepository
from app.services.video_production_media import (
    AssetSelector,
    AudioProcessor,
    FFmpegRenderer,
    SubprocessRunner,
    VideoQualityInspector,
)
from app.services.video_production_models import (
    Artifact,
    ArtifactStore,
    VIDEO_PRODUCTION_STAGES,
    VideoProductionError,
    VideoProductionStage,
    sha256_file,
)
from app.services.video_production_preset import (
    generate_commercial_script,
    generate_story_brief,
    plan_shots,
)
from app.services.video_production_subtitles import build_ass_subtitles
from app.services.video_production_tts import TTSProvider


class VideoProductionJobRepositoryProtocol(Protocol):
    def claim_next(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None: ...

    def renew_lease(
        self,
        job_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None: ...

    def start_stage(
        self,
        job_code: str,
        stage_name: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None: ...

    def complete_stage(
        self,
        job_code: str,
        stage_name: str,
        output_payload: dict[str, Any],
        artifacts: list[dict[str, Any]],
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None: ...

    def fail_stage(
        self,
        job_code: str,
        stage_name: str,
        error_code: str,
        error_message: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None: ...

    def complete_job(
        self,
        job_code: str,
        final_asset_id: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None: ...

    def fail_job(
        self,
        job_code: str,
        error_code: str,
        error_message: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None: ...


class FinalAssetRegistrar(Protocol):
    def register(
        self,
        *,
        job: dict[str, Any],
        video_path: Path,
        video_artifact: Artifact,
        quality_report: dict[str, Any],
    ) -> str: ...


@dataclass(slots=True)
class DatabaseFinalAssetRegistrar:
    asset_repository: AssetRepository

    def register(
        self,
        *,
        job: dict[str, Any],
        video_path: Path,
        video_artifact: Artifact,
        quality_report: dict[str, Any],
    ) -> str:
        job_code = str(job["job_code"])
        media = quality_report.get("media") or {}
        try:
            asset = self.asset_repository.get_by_local_file_code("video_production", job_code)
            if asset is not None:
                expected = {
                    "file_size": video_artifact.file_size,
                    "checksum_sha256": video_artifact.checksum_sha256,
                    "local_relative_path": video_artifact.relative_path,
                }
                if any(str(asset.get(key)) != str(value) for key, value in expected.items()):
                    raise VideoProductionError(
                        "FINAL_ASSET_CONFLICT",
                        "existing final asset does not match the current rendered video",
                    )
            else:
                asset = self.asset_repository.create(
                    {
                        "asset_type": "VID",
                        "title": f"{job.get('topic') or '商业短视频'} - Demo成片",
                        "original_filename": video_path.name,
                        "file_ext": video_path.suffix.lower(),
                        "mime_type": mimetypes.guess_type(video_path.name)[0] or "video/mp4",
                        "file_size": video_artifact.file_size,
                        "checksum_sha256": video_artifact.checksum_sha256,
                        "status": "ready",
                        "description": "主题驱动商业短视频流水线生成的质检通过成片",
                        "display_code": job_code,
                        "local_file_code": job_code,
                        "source_system": "video_production",
                        "source_type": "rendered_video",
                        "maitu_category": "highlight_clip",
                        "maitu_type": "video",
                        "usage": "commercial_demo_video",
                        "subject": "品酒大师PRO",
                        "file_role": "rendered_master",
                        "browser_use_hint": "商业短视频 Demo 最终成片",
                        "local_relative_path": video_artifact.relative_path,
                        "tags": ["商业短视频", "品酒大师PRO", "Demo", "质检通过"],
                    },
                    commit=False,
                )
            file_record = self.asset_repository.create_file_record(
                str(asset["asset_code"]),
                {
                    "file_role": "rendered_master",
                    "bucket_name": "local-video-productions",
                    "object_key": video_artifact.relative_path,
                    "mime_type": "video/mp4",
                    "file_size": video_artifact.file_size,
                    "checksum_sha256": video_artifact.checksum_sha256,
                    "width": media.get("width"),
                    "height": media.get("height"),
                    "duration_seconds": media.get("duration_seconds"),
                    "source_relative_path": video_artifact.relative_path,
                    "local_file_code": job_code,
                    "storage_status": "stored",
                },
                commit=False,
            )
            if file_record is None:
                raise VideoProductionError("FINAL_ASSET_FILE_MISSING", "could not register final asset file")
            return str(asset["id"])
        except Exception:
            self.asset_repository.connection.rollback()
            raise


@dataclass(slots=True)
class StageExecutionResult:
    output_payload: dict[str, Any]
    artifacts: list[Artifact]


class VideoProductionPipeline:
    def __init__(
        self,
        *,
        assets_root: Path,
        output_root: Path,
        tts: TTSProvider,
        runner: SubprocessRunner | None = None,
        enforce_demo_duration: bool = True,
    ) -> None:
        self.assets_root = assets_root.resolve()
        self.output_root = output_root.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.tts = tts
        self.runner = runner or SubprocessRunner()
        self._tool_versions_cache: dict[str, str] | None = None
        self.asset_selector = AssetSelector(self.assets_root, self.runner)
        self.audio_processor = AudioProcessor(self.runner)
        self.renderer = FFmpegRenderer(self.assets_root, self.runner)
        self.quality_inspector = VideoQualityInspector(self.runner)
        self.enforce_demo_duration = enforce_demo_duration

    def new_context(self, job: dict[str, Any]) -> dict[str, Any]:
        attempt = max(1, int(job.get("attempt") or 1))
        return {
            "job": dict(job),
            "store": ArtifactStore(self.output_root, str(job["job_code"]), attempt),
            "story_brief": dict(job.get("story_brief") or {}),
            "script": dict(job.get("script") or {}),
            "shot_list": dict(job.get("shot_list") or {}),
            "asset_plan": dict(job.get("asset_plan") or {}),
            "quality_report": dict(job.get("quality_report") or {}),
        }

    def execute_stage(
        self,
        stage: VideoProductionStage,
        context: dict[str, Any],
    ) -> StageExecutionResult:
        handlers = {
            VideoProductionStage.BRIEF_GENERATION: self._brief_generation,
            VideoProductionStage.SCRIPT_GENERATION: self._script_generation,
            VideoProductionStage.SHOT_PLANNING: self._shot_planning,
            VideoProductionStage.ASSET_SELECTION: self._asset_selection,
            VideoProductionStage.VOICE_SYNTHESIS: self._voice_synthesis,
            VideoProductionStage.SUBTITLE_GENERATION: self._subtitle_generation,
            VideoProductionStage.RENDERING: self._rendering,
            VideoProductionStage.QUALITY_CHECK: self._quality_check,
        }
        return handlers[stage](context)

    def hydrate_for_resume(self, first_stage: VideoProductionStage, context: dict[str, Any]) -> None:
        index = VIDEO_PRODUCTION_STAGES.index(first_stage)
        required_structured = (
            (VideoProductionStage.SCRIPT_GENERATION, "story_brief"),
            (VideoProductionStage.SHOT_PLANNING, "script"),
            (VideoProductionStage.ASSET_SELECTION, "shot_list"),
            (VideoProductionStage.VOICE_SYNTHESIS, "asset_plan"),
        )
        for required_from_stage, key in required_structured:
            if index >= VIDEO_PRODUCTION_STAGES.index(required_from_stage) and not context.get(key):
                raise VideoProductionError("RESUME_PREREQUISITE_MISSING", f"retry is missing persisted {key}")

        if index > VIDEO_PRODUCTION_STAGES.index(VideoProductionStage.VOICE_SYNTHESIS):
            context["voice_manifest"] = self._load_previous_json(context["store"], "voice/manifest.json")
        if index > VIDEO_PRODUCTION_STAGES.index(VideoProductionStage.SUBTITLE_GENERATION):
            ass_path = context["store"].find_previous("subtitles/subtitles.ass")
            if ass_path is None:
                raise VideoProductionError("RESUME_PREREQUISITE_MISSING", "retry is missing subtitles")
            context["subtitles_path"] = ass_path
            manifest = context["store"].find_previous("subtitles/manifest.json")
            context["subtitle_manifest"] = _load_json_file(manifest) if manifest else {}
        if index > VIDEO_PRODUCTION_STAGES.index(VideoProductionStage.RENDERING):
            video_path = context["store"].find_previous("final.mp4")
            if video_path is None:
                raise VideoProductionError("RESUME_PREREQUISITE_MISSING", "retry is missing rendered video")
            context["video_path"] = video_path
            context["render_manifest"] = self._load_previous_json(context["store"], "render/manifest.json")

    def _brief_generation(self, context: dict[str, Any]) -> StageExecutionResult:
        job = context["job"]
        brief = generate_story_brief(
            str(job.get("topic") or ""),
            preset_code=str(job.get("preset_code") or "zhangyu_wine_demo_v1"),
            target_duration_seconds=int(job.get("target_duration_seconds") or 55),
        )
        context["story_brief"] = brief
        artifact = context["store"].write_json("story_brief", "story_brief.json", brief)
        return StageExecutionResult(brief, [artifact])

    def _script_generation(self, context: dict[str, Any]) -> StageExecutionResult:
        script = generate_commercial_script(context["story_brief"])
        context["script"] = script
        artifact = context["store"].write_json("script", "script.json", script)
        return StageExecutionResult(script, [artifact])

    def _shot_planning(self, context: dict[str, Any]) -> StageExecutionResult:
        shot_list = plan_shots(context["story_brief"], context["script"])
        context["shot_list"] = shot_list
        artifact = context["store"].write_json("shot_list", "shot_list.json", shot_list)
        return StageExecutionResult(shot_list, [artifact])

    def _asset_selection(self, context: dict[str, Any]) -> StageExecutionResult:
        asset_plan = self.asset_selector.select(context["shot_list"])
        context["asset_plan"] = asset_plan
        artifact = context["store"].write_json("asset_plan", "asset_plan.json", asset_plan)
        return StageExecutionResult(asset_plan, [artifact])

    def _voice_synthesis(self, context: dict[str, Any]) -> StageExecutionResult:
        self.tts.health()
        store: ArtifactStore = context["store"]
        segments: list[dict[str, Any]] = []
        for shot in context["shot_list"]["shots"]:
            index = int(shot["shot_index"])
            raw = store.path(f"voice/raw-{index + 1:02d}.wav")
            fitted = store.path(f"voice/segment-{index + 1:02d}.wav")
            self.tts.synthesize(str(shot["tts_text"]), raw, speed=1.0)
            gain_db = float(shot.get("voice_gain_db") or 0)
            timing = self.audio_processor.fit_to_duration(
                raw,
                fitted,
                float(shot["duration_seconds"]),
                gain_db=gain_db,
            )
            if not 0.85 <= float(timing["tempo_factor"]) <= 1.15:
                raise VideoProductionError(
                    "VOICE_PACING_OUT_OF_RANGE",
                    f"shot {index + 1} requires an unacceptable tempo factor",
                )
            segments.append(
                {
                    "shot_index": index,
                    "relative_path": store.relative_to_output_root(fitted),
                    "file_size": fitted.stat().st_size,
                    "checksum_sha256": _sha256(fitted),
                    "voice": self.tts.voice,
                    "gain_db": gain_db,
                    **timing,
                }
            )
        manifest = {
            "source": "kokoro_http_v1",
            "model": getattr(self.tts, "model", "kokoro"),
            "voice": self.tts.voice,
            "sample_rate": 48000,
            "segment_count": len(segments),
            "segments": segments,
        }
        context["voice_manifest"] = manifest
        artifact = store.write_json(
            "voice",
            "voice/manifest.json",
            manifest,
            metadata={"voice": self.tts.voice, "segment_count": len(segments)},
        )
        return StageExecutionResult(manifest, [artifact])

    def _subtitle_generation(self, context: dict[str, Any]) -> StageExecutionResult:
        content, manifest = build_ass_subtitles(context["shot_list"], context["voice_manifest"])
        store: ArtifactStore = context["store"]
        subtitles_path = store.path("subtitles/subtitles.ass")
        artifact = store.write_text(
            "subtitles",
            "subtitles/subtitles.ass",
            content,
            mime_type="text/x-ssa",
            metadata={
                "event_count": manifest["event_count"],
                "font": manifest["font"],
                "format": "ass",
            },
        )
        store.write_json("subtitles", "subtitles/manifest.json", manifest)
        context["subtitles_path"] = subtitles_path
        context["subtitle_manifest"] = manifest
        return StageExecutionResult(manifest, [artifact])

    def _rendering(self, context: dict[str, Any]) -> StageExecutionResult:
        store: ArtifactStore = context["store"]
        video_path, render_result = self.renderer.render(
            shot_list=context["shot_list"],
            asset_plan=context["asset_plan"],
            voice_manifest=context["voice_manifest"],
            subtitles_path=context["subtitles_path"],
            store=store,
        )
        poster_time_seconds = float(context["shot_list"].get("poster_time_seconds") or 0)
        poster_path = self._poster(video_path, store, at_seconds=poster_time_seconds)
        command_log = store.write_json(
            "render_log",
            "render/commands.json",
            {
                "source": "subprocess_argument_array_v1",
                "commands": [
                    _public_command_record(
                        record,
                        assets_root=self.assets_root,
                        output_root=self.output_root,
                    )
                    for record in self.runner.records
                ],
            },
        )
        manifest = build_render_manifest(
            render_result=render_result,
            shot_list=context["shot_list"],
            asset_plan=context["asset_plan"],
            voice_manifest=context["voice_manifest"],
            subtitle_manifest=context.get("subtitle_manifest") or {},
            subtitles_path=context["subtitles_path"],
            video_path=video_path,
            poster_path=poster_path,
            poster_time_seconds=poster_time_seconds,
            command_log=command_log,
            toolchain=self._tool_versions(),
            store=store,
        )
        render_manifest = store.write_json(
            "render_manifest",
            "render/manifest.json",
            manifest,
            metadata={"manifest_fingerprint": manifest["manifest_fingerprint"]},
        )
        context["video_path"] = video_path
        context["render_manifest"] = manifest
        video_artifact = store.describe(
            "video",
            video_path,
            mime_type="video/mp4",
            metadata=manifest["video"],
        )
        poster_artifact = store.describe(
            "poster",
            poster_path,
            mime_type="image/jpeg",
            metadata={"at_seconds": poster_time_seconds},
        )
        context["video_artifact"] = video_artifact
        return StageExecutionResult(
            manifest,
            [video_artifact, poster_artifact, command_log, render_manifest],
        )

    def _poster(self, video: Path, store: ArtifactStore, *, at_seconds: float) -> Path:
        if not math.isfinite(at_seconds) or at_seconds < 0:
            raise VideoProductionError(
                "POSTER_TIME_INVALID",
                "Poster time must be a finite non-negative value",
            )
        destination = store.path("poster.jpg")
        temporary = destination.with_name(f".{destination.stem}.{os.getpid()}.part{destination.suffix}")
        try:
            self.runner.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-y",
                    "-ss",
                    f"{at_seconds:.3f}",
                    "-i",
                    video,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    temporary,
                ],
                timeout_seconds=180,
                error_code="POSTER_GENERATION_FAILED",
            )
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _tool_versions(self) -> dict[str, str]:
        if self._tool_versions_cache is not None:
            return dict(self._tool_versions_cache)
        versions: dict[str, str] = {}
        for tool in ("ffmpeg", "ffprobe"):
            result = self.runner.run(
                [tool, "-version"],
                timeout_seconds=30,
                error_code="RENDER_TOOL_VERSION_UNAVAILABLE",
            )
            first_line = next(
                (line.strip() for line in result.stdout.splitlines() if line.strip()),
                "",
            )
            if not first_line:
                raise VideoProductionError(
                    "RENDER_TOOL_VERSION_UNAVAILABLE",
                    f"{tool} did not return a version identifier",
                )
            versions[tool] = first_line
        self._tool_versions_cache = versions
        return dict(versions)

    def _quality_check(self, context: dict[str, Any]) -> StageExecutionResult:
        job = context["job"]
        report = self.quality_inspector.inspect(
            context["video_path"],
            target_duration_seconds=float(job.get("target_duration_seconds") or 55),
            enforce_demo_duration=self.enforce_demo_duration,
        )
        subtitle_manifest = context.get("subtitle_manifest", {})
        subtitle_passed = bool(subtitle_manifest.get("text_complete")) and not int(
            subtitle_manifest.get("truncated_event_count") or 0
        )
        report["subtitle_layout"] = {
            "passed": subtitle_passed,
            "font": subtitle_manifest.get("font"),
            "safe_margins": subtitle_manifest.get("safe_margins"),
            "event_count": subtitle_manifest.get("event_count"),
            "text_complete": subtitle_manifest.get("text_complete"),
            "truncated_event_count": subtitle_manifest.get("truncated_event_count"),
        }
        report["checks"]["subtitle_text_complete"] = subtitle_passed
        report["passed"] = all(report["checks"].values())
        context["quality_report"] = report
        artifact = context["store"].write_json("quality_report", "quality_report.json", report)
        return StageExecutionResult(report, [artifact])

    @staticmethod
    def _load_previous_json(store: ArtifactStore, relative_path: str) -> dict[str, Any]:
        path = store.find_previous(relative_path)
        if path is None:
            raise VideoProductionError("RESUME_PREREQUISITE_MISSING", f"retry is missing {relative_path}")
        return _load_json_file(path)


class VideoProductionWorker:
    def __init__(
        self,
        *,
        repository: VideoProductionJobRepositoryProtocol,
        pipeline: VideoProductionPipeline,
        final_asset_registrar: FinalAssetRegistrar,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        heartbeat_seconds: int = 30,
    ) -> None:
        self.repository = repository
        self.pipeline = pipeline
        self.final_asset_registrar = final_asset_registrar
        self.worker_id = worker_id or f"video-worker-{socket.gethostname()}-{os.getpid()}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

    def run_once(self) -> bool:
        job = self.repository.claim_next(self.worker_id, self.lease_seconds)
        if job is None:
            return False
        job_code = str(job["job_code"])
        lease_token = str(job["lease_token"])
        current_stage_name = str(job.get("current_stage") or VIDEO_PRODUCTION_STAGES[0].value)
        try:
            first_stage = VideoProductionStage(current_stage_name)
        except ValueError:
            self.repository.fail_job(
                job_code,
                "UNKNOWN_CURRENT_STAGE",
                f"unknown current stage: {current_stage_name}",
                self.worker_id,
                lease_token,
            )
            return True

        last_heartbeat = 0.0
        heartbeat_lock = threading.Lock()

        def heartbeat(*, force: bool = False) -> None:
            nonlocal last_heartbeat
            with heartbeat_lock:
                now = time.monotonic()
                if not force and now - last_heartbeat < self.heartbeat_seconds:
                    return
                renewed = self.repository.renew_lease(
                    job_code,
                    self.worker_id,
                    lease_token,
                    self.lease_seconds,
                )
                if renewed is None:
                    raise VideoProductionError("LEASE_LOST", "video production worker lease was lost")
                last_heartbeat = now

        def execute_with_lease_heartbeat(
            stage: VideoProductionStage,
            context: dict[str, Any],
        ) -> StageExecutionResult:
            stop = threading.Event()
            failures: list[Exception] = []
            interval = max(1.0, min(float(self.heartbeat_seconds), self.lease_seconds / 3))

            def renew_until_stopped() -> None:
                while not stop.wait(interval):
                    try:
                        heartbeat(force=True)
                    except Exception as exc:
                        failures.append(exc)
                        return

            thread = threading.Thread(
                target=renew_until_stopped,
                name=f"{self.worker_id}-{stage.value}-lease",
                daemon=True,
            )
            thread.start()
            try:
                result = self.pipeline.execute_stage(stage, context)
            finally:
                stop.set()
                thread.join(timeout=interval + 1)
            if failures:
                raise failures[0]
            heartbeat(force=True)
            return result

        self.pipeline.runner.heartbeat = heartbeat
        context = self.pipeline.new_context(job)
        try:
            heartbeat()
            self.pipeline.hydrate_for_resume(first_stage, context)
            first_index = VIDEO_PRODUCTION_STAGES.index(first_stage)
            for stage in VIDEO_PRODUCTION_STAGES[first_index:]:
                heartbeat()
                started = self.repository.start_stage(job_code, stage.value, self.worker_id, lease_token)
                if started is None:
                    raise VideoProductionError("LEASE_LOST", f"could not start stage {stage.value}")
                try:
                    result = execute_with_lease_heartbeat(stage, context)
                except Exception as exc:
                    error = _pipeline_error(exc)
                    self.repository.fail_stage(
                        job_code,
                        stage.value,
                        error.error_code,
                        str(error)[:2000],
                        self.worker_id,
                        lease_token,
                    )
                    return True
                completed = self.repository.complete_stage(
                    job_code,
                    stage.value,
                    result.output_payload,
                    [artifact.as_repository_payload() for artifact in result.artifacts],
                    self.worker_id,
                    lease_token,
                )
                if completed is None:
                    raise VideoProductionError("LEASE_LOST", f"could not complete stage {stage.value}")
                if stage is VideoProductionStage.QUALITY_CHECK and not result.output_payload.get("passed"):
                    self.repository.fail_job(
                        job_code,
                        "QUALITY_GATE_FAILED",
                        "rendered video did not pass the quality gate",
                        self.worker_id,
                        lease_token,
                    )
                    return True

            video_artifact = context.get("video_artifact")
            if video_artifact is None:
                video_artifact = context["store"].describe(
                    "video",
                    context["video_path"],
                    mime_type="video/mp4",
                    metadata=(context.get("render_manifest") or {}).get("video") or {},
                )
            final_asset_id = self.final_asset_registrar.register(
                job=job,
                video_path=context["video_path"],
                video_artifact=video_artifact,
                quality_report=context["quality_report"],
            )
            completed_job = self.repository.complete_job(
                job_code,
                final_asset_id,
                self.worker_id,
                lease_token,
            )
            if completed_job is None:
                raise VideoProductionError("JOB_COMPLETION_REJECTED", "repository rejected job completion")
            return True
        except Exception as exc:
            error = _pipeline_error(exc)
            self.repository.fail_job(
                job_code,
                error.error_code,
                str(error)[:2000],
                self.worker_id,
                lease_token,
            )
            return True


def _pipeline_error(exc: Exception) -> VideoProductionError:
    if isinstance(exc, VideoProductionError):
        return exc
    return VideoProductionError("VIDEO_PRODUCTION_INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VideoProductionError("ARTIFACT_INVALID_JSON", f"invalid JSON artifact: {path.name}") from exc
    if not isinstance(document, dict):
        raise VideoProductionError("ARTIFACT_INVALID_JSON", f"JSON artifact is not an object: {path.name}")
    return document


def _sha256(path: Path) -> str:
    from app.services.video_production_models import sha256_file

    return sha256_file(path)


def _public_command_record(
    record: dict[str, Any],
    *,
    assets_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    replacements = (
        (str(assets_root.resolve()), "$MATERIALS_ROOT"),
        (str(output_root.resolve()), "$VIDEO_PRODUCTION_ROOT"),
    )

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            for source, replacement in replacements:
                value = value.replace(source, replacement)
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return {key: redact(value) for key, value in record.items()}


def build_render_manifest(
    *,
    render_result: dict[str, Any],
    shot_list: dict[str, Any],
    asset_plan: dict[str, Any],
    voice_manifest: dict[str, Any],
    subtitle_manifest: dict[str, Any],
    subtitles_path: Path,
    video_path: Path,
    poster_path: Path,
    poster_time_seconds: float,
    command_log: Artifact,
    toolchain: dict[str, str],
    store: ArtifactStore,
) -> dict[str, Any]:
    """Freeze the local render inputs and outputs without machine-local path identities."""
    assets = [
        {
            "asset_code": str(asset.get("asset_code") or ""),
            "relative_path": str(asset.get("relative_path") or ""),
            "checksum_sha256": str(asset.get("checksum_sha256") or ""),
        }
        for asset in asset_plan.get("assets") or []
        if isinstance(asset, dict)
    ]
    voice_segments = [
        {
            "shot_index": int(segment.get("shot_index") or 0),
            "relative_path": str(segment.get("relative_path") or ""),
            "checksum_sha256": str(segment.get("checksum_sha256") or ""),
        }
        for segment in voice_manifest.get("segments") or []
        if isinstance(segment, dict)
    ]
    manifest = {
        "schema_version": "render-manifest.v1",
        "renderer": {"source": str(render_result.get("source") or "ffmpeg_render_v1")},
        "timeline": {
            "source": "worker_shot_list",
            "shot_count": len(shot_list.get("shots") or []),
            "duration_seconds": float(shot_list.get("duration_seconds") or 0),
            "fingerprint_sha256": canonical_fingerprint(shot_list),
        },
        "inputs": {
            "asset_plan_fingerprint_sha256": canonical_fingerprint(asset_plan),
            "assets": assets,
            "voice_manifest_fingerprint_sha256": canonical_fingerprint(voice_manifest),
            "voice_segments": voice_segments,
            "subtitles": {
                "relative_path": store.relative_to_output_root(subtitles_path),
                "checksum_sha256": sha256_file(subtitles_path),
                "manifest_fingerprint_sha256": canonical_fingerprint(subtitle_manifest),
            },
        },
        "commands": {
            "relative_path": command_log.relative_path,
            "checksum_sha256": command_log.checksum_sha256,
        },
        "toolchain": dict(toolchain),
        "outputs": {
            "video": {
                "relative_path": store.relative_to_output_root(video_path),
                "checksum_sha256": sha256_file(video_path),
                **dict(render_result.get("video") or {}),
            },
            "poster": {
                "relative_path": store.relative_to_output_root(poster_path),
                "checksum_sha256": sha256_file(poster_path),
                "at_seconds": poster_time_seconds,
            },
        },
        "video": dict(render_result.get("video") or {}),
        "encoding": dict(render_result.get("encoding") or {}),
    }
    manifest["manifest_fingerprint"] = canonical_fingerprint(manifest)
    return manifest
