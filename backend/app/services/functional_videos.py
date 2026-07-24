from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.errors import DomainValidationError
from app.repositories.content_production import ContentProductionRepository
from app.repositories.video_productions import VideoProductionRepository
from app.services.functional_content import FunctionalContentService


class FunctionalVideoService:
    """Creates a rendered-video variant whose queued worker job consumes ContentProject text."""

    def __init__(self, connection: Connection):
        self.connection = connection
        self.content = FunctionalContentService(connection)
        self.production = ContentProductionRepository(connection)
        self.videos = VideoProductionRepository(connection)

    def create_plan(self, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        detail = self.content.get_detail(payload["project_code"])
        if detail is None:
            raise KeyError(payload["project_code"])
        if not detail["generated"] or not detail["story_brief"] or not detail["script"] or not detail["shot_list"]:
            raise DomainValidationError("VIDEO_CONTENT_CHAIN_REQUIRED", "Generate the ContentProject before creating a video plan")
        duration = int(payload["target_duration_seconds"])
        story, script, shots, timeline = self._compile_content(detail, duration)
        variant = self.production.create_production_variant(
            project_code=detail["project_code"], project_revision=int(detail["revision_number"]),
            story_brief_code=detail["story_brief"]["story_brief_code"], story_brief_revision=int(detail["story_brief"]["revision_number"]),
            script_revision_code=detail["script"]["script_revision_code"], shot_list_revision_code=detail["shot_list"]["shot_list_revision_code"],
            carrier_kind="rendered_video",
            branch_target={"delivery": "local_render", "title": payload.get("title") or detail["title"]},
            configuration={"canvas": {"width": 1080, "height": 1920, "fps": 30}, "target_duration_seconds": duration},
            material_snapshot_ref={"source": "baseline_verified_video_assets.v1", "asset_codes": [shot["asset_code"] for shot in shots["shots"]]},
            constraint_snapshot_ref={"source": "functional-content-timeline.v1"},
            actor_id=actor_id, producer_strategy_revision="functional-video.v1",
        )
        variant = self.production.confirm_production_variant_revision(variant["variant_code"], revision_number=int(variant["revision_number"]), actor_id=actor_id)
        job = self.videos.create({"topic": detail["generation_goal"], "target_duration_seconds": duration})
        seeded = self.videos.seed_content_project_job(job["job_code"], story_brief=story, script=script, shot_list=shots)
        if seeded is None:
            raise RuntimeError("created video job cannot be seeded")
        self.production.bind_video_production_job(job_code=job["job_code"], variant_code=variant["variant_code"], variant_revision=int(variant["revision_number"]), actor_id=actor_id)
        render_profile = {
            "schema_version": "functional-render-profile.v1", "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "subtitle": "ass", "audio": "local_tts", "visual_asset_mode": "baseline_verified_video_assets", "target_duration_seconds": duration,
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            code = self._next_code(cursor)
            cursor.execute(
                """INSERT INTO functional_video_plans (plan_code, project_code, variant_code, video_job_code, title, production_timeline, render_profile)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                (code, detail["project_code"], variant["variant_code"], job["job_code"], payload.get("title") or detail["title"], Jsonb(timeline), Jsonb(render_profile)),
            )
            row = cursor.fetchone()
            cursor.execute(
                """INSERT INTO functional_video_timeline_revisions
                   (plan_id, revision_number, production_timeline, actor_id)
                   VALUES (%s, %s, %s, %s)""",
                (row["id"], int(row["timeline_revision"]), Jsonb(timeline), actor_id),
            )
        self.connection.commit()
        return self._enrich(row)

    def list_plans(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_video_plans ORDER BY updated_at DESC, plan_code")
            rows = cursor.fetchall()
        return [self._enrich(row) for row in rows]

    def get_plan(self, plan_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_video_plans WHERE plan_code = %s", (plan_code,))
            row = cursor.fetchone()
        return self._enrich(row) if row else None

    def list_timeline_revisions(self, plan_code: str) -> list[dict[str, Any]] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT id FROM functional_video_plans WHERE plan_code = %s",
                (plan_code,),
            )
            plan = cursor.fetchone()
            if plan is None:
                return None
            cursor.execute(
                """SELECT revision_number, production_timeline, actor_id, created_at
                   FROM functional_video_timeline_revisions
                   WHERE plan_id = %s
                   ORDER BY revision_number DESC""",
                (plan["id"],),
            )
            return [dict(row) for row in cursor.fetchall()]

    def retry(self, plan_code: str) -> dict[str, Any] | None:
        plan = self.get_plan(plan_code)
        if plan is None:
            return None
        self.videos.retry(plan["video_job_code"])
        return self.get_plan(plan_code)

    def update_timeline(self, plan_code: str, payload: dict[str, Any], *, actor_id: str) -> dict[str, Any] | None:
        """Apply a constrained edit and update the queued worker input atomically."""
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT * FROM functional_video_plans WHERE plan_code = %s FOR UPDATE", (plan_code,))
                plan = cursor.fetchone()
                if plan is None:
                    self.connection.rollback()
                    return None
                expected_revision = int(payload["expected_revision"])
                actual_revision = int(plan["timeline_revision"])
                if expected_revision != actual_revision:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_REVISION_CONFLICT",
                        "Timeline changed since it was loaded",
                        details={"expected_revision": expected_revision, "actual_revision": actual_revision},
                    )
                cursor.execute("SELECT * FROM video_production_jobs WHERE job_code = %s FOR UPDATE", (plan["video_job_code"],))
                job = cursor.fetchone()
                if job is None:
                    raise DomainValidationError("VIDEO_TIMELINE_JOB_MISSING", "The associated render job no longer exists")
                if job["status"] != "queued" or job["claimed_by"] is not None:
                    raise DomainValidationError(
                        "VIDEO_TIMELINE_EDIT_NOT_ALLOWED",
                        "Only an unclaimed queued render plan can be edited; create a new branch after rendering begins",
                        details={"job_status": job["status"]},
                    )
                timeline = self._apply_timeline_update(dict(plan["production_timeline"] or {}), payload["video_clips"])
                shot_list = self._timeline_shot_list(dict(job["shot_list"] or {}), timeline)
                total_seconds = timeline["global_end_ms"] / 1000
                profile = deepcopy(dict(plan["render_profile"] or {}))
                profile["target_duration_seconds"] = total_seconds
                next_revision = actual_revision + 1
                cursor.execute(
                    """UPDATE functional_video_plans
                       SET production_timeline = %s, render_profile = %s, timeline_revision = %s, updated_at = now()
                       WHERE id = %s""",
                    (Jsonb(timeline), Jsonb(profile), next_revision, plan["id"]),
                )
                cursor.execute(
                    """INSERT INTO functional_video_timeline_revisions
                       (plan_id, revision_number, production_timeline, actor_id)
                       VALUES (%s, %s, %s, %s)""",
                    (plan["id"], next_revision, Jsonb(timeline), actor_id),
                )
                cursor.execute(
                    """UPDATE video_production_jobs
                       SET shot_list = %s, target_duration_seconds = %s, updated_at = now()
                       WHERE id = %s""",
                    (Jsonb(shot_list), round(total_seconds), job["id"]),
                )
                cursor.execute(
                    """UPDATE video_production_stages
                       SET output_payload = %s, updated_at = now()
                       WHERE job_id = %s AND stage_name = 'shot_planning'""",
                    (Jsonb(shot_list), job["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_plan(plan_code)

    def _enrich(self, row: dict[str, Any]) -> dict[str, Any]:
        plan = dict(row)
        job = self.videos.get_by_code(plan["video_job_code"])
        if job is None:
            raise RuntimeError("functional video plan refers to a missing job")
        plan.update(
            {
                "job_status": job["status"],
                "current_stage": job.get("current_stage"),
                "progress_percent": job["progress_percent"],
                "error_message": job.get("error_message"),
                "final_asset_id": job.get("final_asset_id"),
                "quality_report": dict(job.get("quality_report") or {}),
                "workflow_stages": [
                    {
                        "stage_name": stage.get("stage_name"),
                        "stage_order": stage.get("stage_order"),
                        "status": stage.get("status"),
                        "attempt": stage.get("attempt"),
                        "error_code": stage.get("error_code"),
                        "error_message": stage.get("error_message"),
                    }
                    for stage in job.get("stages") or []
                ],
            }
        )
        plan["artifacts"] = [
            {
                **artifact,
                "download_url": f"/api/video-productions/{job['job_code']}/artifacts/{artifact['artifact_key']}",
            }
            for artifact in job.get("artifacts") or []
        ]
        return plan

    @staticmethod
    def _apply_timeline_update(timeline: dict[str, Any], updates: list[dict[str, Any]]) -> dict[str, Any]:
        result = deepcopy(timeline)
        tracks = result.get("tracks") or []
        video = next((track for track in tracks if track.get("track_kind") == "video"), None)
        if not isinstance(video, dict):
            raise DomainValidationError("VIDEO_TIMELINE_VIDEO_TRACK_MISSING", "Timeline has no editable video track")
        clips = list(video.get("clips") or [])
        current_codes = [str(clip.get("clip_code") or "") for clip in clips]
        update_codes = [str(update.get("clip_code") or "") for update in updates]
        if set(current_codes) != set(update_codes) or len(current_codes) != len(update_codes):
            raise DomainValidationError(
                "VIDEO_TIMELINE_CLIP_SET_MISMATCH",
                "Timeline edits must retain the complete current video clip set",
                details={"expected_clip_codes": current_codes},
            )
        current_by_code = {str(clip["clip_code"]): clip for clip in clips}
        cursor = 0
        ordered_clips: list[dict[str, Any]] = []
        for update in updates:
            clip = deepcopy(current_by_code[str(update["clip_code"])])
            duration = int(update["duration_ms"])
            transition = str(update.get("transition") or "cut")
            if duration < 250 or duration > 120_000 or transition not in {"cut", "fade", "fade_out"}:
                raise DomainValidationError("VIDEO_TIMELINE_INVALID_CLIP", "Timeline clip duration or transition is invalid")
            clip["timeline_range"] = {"start_ms": cursor, "duration_ms": duration}
            clip["transition"] = transition
            cursor += duration
            ordered_clips.append(clip)
        if not 30_000 <= cursor <= 120_000:
            raise DomainValidationError(
                "VIDEO_TIMELINE_DURATION_OUT_OF_RANGE",
                "Edited timeline duration must remain between 30 and 120 seconds",
                details={"duration_ms": cursor},
            )
        result["global_start_ms"] = 0
        result["global_end_ms"] = cursor
        video["clips"] = ordered_clips
        for track in tracks:
            if track.get("track_kind") != "audio":
                continue
            audio_by_video_code = {
                str(clip.get("clip_code") or "").removeprefix("VOICE-"): clip
                for clip in track.get("clips") or []
                if str(clip.get("clip_code") or "").removeprefix("VOICE-") in current_by_code
            }
            ordered_audio = []
            for video_clip in ordered_clips:
                audio_clip = audio_by_video_code.get(str(video_clip["clip_code"]))
                if audio_clip is None:
                    continue
                ordered_audio.append({**deepcopy(audio_clip), "timeline_range": dict(video_clip["timeline_range"])})
            unlinked_audio = [
                deepcopy(clip)
                for clip in track.get("clips") or []
                if str(clip.get("clip_code") or "").removeprefix("VOICE-") not in current_by_code
            ]
            track["clips"] = [*ordered_audio, *unlinked_audio]
        return result

    @staticmethod
    def _timeline_shot_list(shot_list: dict[str, Any], timeline: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(shot_list)
        video_track = next((track for track in timeline.get("tracks") or [] if track.get("track_kind") == "video"), None)
        if not isinstance(video_track, dict):
            raise DomainValidationError("VIDEO_TIMELINE_VIDEO_TRACK_MISSING", "Timeline has no editable video track")
        clips = {str(clip["clip_code"]): clip for clip in video_track.get("clips") or []}
        shots = list(result.get("shots") or [])
        if {str(shot.get("shot_code") or "") for shot in shots} != set(clips):
            raise DomainValidationError("VIDEO_TIMELINE_SHOT_MAPPING_INVALID", "Timeline clips no longer match the fixed ShotList")
        shots_by_code = {str(shot["shot_code"]): shot for shot in shots}
        ordered_shots: list[dict[str, Any]] = []
        for clip_code in [str(clip["clip_code"]) for clip in video_track.get("clips") or []]:
            shot = deepcopy(shots_by_code[clip_code])
            clip = clips[clip_code]
            timing = clip["timeline_range"]
            start = int(timing["start_ms"]) / 1000
            duration = int(timing["duration_ms"]) / 1000
            shot["start_seconds"] = start
            shot["end_seconds"] = start + duration
            shot["duration_seconds"] = duration
            shot["transition"] = clip.get("transition") or "cut"
            ordered_shots.append(shot)
        result["shots"] = ordered_shots
        result["duration_seconds"] = timeline["global_end_ms"] / 1000
        result["timeline_revision"] = timeline.get("timeline_revision")
        return result

    @staticmethod
    def _compile_content(detail: dict[str, Any], duration: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        source_blocks = detail["script"]["blocks"]
        text = [str(block["content"]) for block in source_blocks]
        chunks = FunctionalVideoService._chunks(text, 6)
        durations = [round(duration / 6, 3) for _ in range(6)]
        durations[-1] = round(duration - sum(durations[:-1]), 3)
        clip_specs = (("MT-VID-0027", 0.0, 6.0, "contain"), ("MT-VID-0016", 0.0, 12.0, "cover"), ("MT-VID-0027", 30.0, 42.0, "contain"), ("MT-VID-0016", 12.0, 25.0, "cover"), ("MT-VID-0024", 0.0, 6.0, "cover"), ("MT-VID-0016", 25.0, 38.0, "cover"))
        cursor = 0.0
        compiled: list[dict[str, Any]] = []
        for index, (chunk, item_duration, clip) in enumerate(zip(chunks, durations, clip_specs, strict=True)):
            asset_code, source_start, source_end, fit = clip
            end = round(cursor + item_duration, 3)
            compiled.append({"shot_index": index, "shot_code": f"SHOT-{index + 1:02d}", "start_seconds": cursor, "end_seconds": end, "duration_seconds": item_duration, "goal": "content_project", "narration": chunk, "tts_text": chunk.replace("PRO", "P R O"), "screen_text": chunk[:28], "asset_code": asset_code, "source_start_seconds": source_start, "source_end_seconds": source_end, "source_available_seconds": source_end - source_start, "fit": fit, "visual_role": "baseline_visual", "transition": "fade_out" if index == 5 else "cut", "overlay_roles": ["brand_logo"] if index in {0, 5} else []})
            cursor = end
        story = {"source": "content_project_revision", "project_code": detail["project_code"], "objective": detail["generation_goal"], "content": detail["story_brief"]["content"], "format": {"orientation": "vertical", "width": 1080, "height": 1920, "target_duration_seconds": duration, "shot_count": 6}}
        script = {"source": "content_project_revision", "title": detail["title"], "spoken_script": "".join(chunks), "sections": [{"section_index": index, "section_type": "content_project", "narration": chunk, "tts_text": chunk.replace("PRO", "P R O"), "screen_text": chunk[:28]} for index, chunk in enumerate(chunks)], "section_count": len(chunks)}
        shots = {"source": "content_project_revision", "canvas": {"width": 1080, "height": 1920, "fps": 30}, "duration_seconds": duration, "shot_count": len(compiled), "shots": compiled}
        timeline = {"schema_version": "otio-compatible-production-timeline.v1", "global_start_ms": 0, "global_end_ms": duration * 1000, "tracks": [{"track_kind": "video", "clips": [{"clip_code": shot["shot_code"], "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}, "source_range": {"asset_code": shot["asset_code"], "start_seconds": shot["source_start_seconds"], "end_seconds": shot["source_end_seconds"]}, "transition": shot["transition"]} for shot in compiled]}, {"track_kind": "audio", "clips": [{"clip_code": f"VOICE-{shot['shot_code']}", "timeline_range": {"start_ms": int(shot["start_seconds"] * 1000), "duration_ms": int(shot["duration_seconds"] * 1000)}} for shot in compiled]}]}
        return story, script, shots, timeline

    @staticmethod
    def _chunks(blocks: list[str], count: int) -> list[str]:
        source = "".join(blocks).strip() or "请根据内容项目完成本次讲述。"
        size = max(1, (len(source) + count - 1) // count)
        chunks = [source[index:index + size] for index in range(0, len(source), size)]
        return (chunks + ["继续围绕当前主题说明关键信息。"] * count)[:count]

    @staticmethod
    def _next_code(cursor: Any) -> str:
        date = datetime.now(UTC).date()
        cursor.execute("""INSERT INTO domain_sequences (sequence_date, object_type, current_value) VALUES (%s, 'functional_video_plan', 1) ON CONFLICT (sequence_date, object_type) DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now() RETURNING current_value""", (date,))
        return f"VIDPLAN-{date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"
