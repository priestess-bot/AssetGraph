from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.schemas.video_productions import (
    VIDEO_PRODUCTION_STAGES,
    VideoProductionArtifactRegistration,
)
from app.services.code_generator import (
    BusinessObjectType,
    format_video_production_job_code,
)


class VideoProductionRetryConflictError(RuntimeError):
    """A video production job cannot be retried from its current state."""


class VideoProductionRepository:
    STAGES = VIDEO_PRODUCTION_STAGES
    STAGE_OUTPUT_COLUMNS = {
        "brief_generation": "story_brief",
        "script_generation": "script",
        "shot_planning": "shot_list",
        "asset_selection": "asset_plan",
        "quality_check": "quality_report",
    }

    def __init__(self, connection: Connection):
        self.connection = connection

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_code = self._next_job_code()
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO video_production_jobs (
                    job_code, topic, preset_code, target_duration_seconds, current_stage
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    job_code,
                    payload["topic"],
                    payload.get("preset_code", "zhangyu_wine_demo_v1"),
                    payload.get("target_duration_seconds", 55),
                    self.STAGES[0],
                ),
            )
            job_id = cursor.fetchone()["id"]
            for stage_order, stage_name in enumerate(self.STAGES, start=1):
                cursor.execute(
                    """
                    INSERT INTO video_production_stages (
                        job_id, job_code, stage_name, stage_order
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (job_id, job_code, stage_name, stage_order),
                )
        self.connection.commit()
        return self.get_by_code(job_code)

    def seed_content_project_job(
        self,
        job_code: str,
        *,
        story_brief: dict[str, Any],
        script: dict[str, Any],
        shot_list: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Pre-compute immutable content stages before the media worker claims a job."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM video_production_jobs WHERE job_code = %s FOR UPDATE",
                (job_code,),
            )
            job = cursor.fetchone()
            if job is None:
                self.connection.rollback()
                return None
            if job["status"] != "queued" or job["claimed_by"] is not None:
                self.connection.rollback()
                raise VideoProductionRetryConflictError("Only an unclaimed queued job can be seeded from a content project")
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'succeeded', output_payload = %s, completed_at = now(), updated_at = now()
                WHERE job_id = %s AND stage_name = %s
                """,
                (Jsonb(story_brief), job["id"], "brief_generation"),
            )
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'succeeded', output_payload = %s, completed_at = now(), updated_at = now()
                WHERE job_id = %s AND stage_name = %s
                """,
                (Jsonb(script), job["id"], "script_generation"),
            )
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'succeeded', output_payload = %s, completed_at = now(), updated_at = now()
                WHERE job_id = %s AND stage_name = %s
                """,
                (Jsonb(shot_list), job["id"], "shot_planning"),
            )
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET story_brief = %s, script = %s, shot_list = %s,
                    current_stage = 'asset_selection', progress_percent = %s, updated_at = now()
                WHERE id = %s
                """,
                (Jsonb(story_brief), Jsonb(script), Jsonb(shot_list), (3 * 100) // len(self.STAGES), job["id"]),
            )
        self.connection.commit()
        return self.get_by_code(job_code)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        if status is not None:
            where = "WHERE status = %s"
            params.append(status)
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM video_production_jobs
                {where}
                ORDER BY created_at DESC, job_code DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return [self._serialize_job(row) for row in rows]

    def get_by_code(self, job_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM video_production_jobs WHERE job_code = %s",
                (job_code,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            job = self._serialize_job(row)
            cursor.execute(
                """
                SELECT *
                FROM video_production_stages
                WHERE job_id = %s
                ORDER BY stage_order
                """,
                (row["id"],),
            )
            job["stages"] = [self._serialize_stage(stage) for stage in cursor.fetchall()]
            cursor.execute(
                """
                SELECT artifact.*, stage.stage_name
                FROM video_production_artifacts AS artifact
                JOIN video_production_stages AS stage ON stage.id = artifact.stage_id
                WHERE artifact.job_id = %s
                ORDER BY artifact.created_at, artifact.artifact_key
                """,
                (row["id"],),
            )
            job["artifacts"] = [self._serialize_artifact(artifact) for artifact in cursor.fetchall()]
        return job

    def get_artifact(self, job_code: str, artifact_key: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT artifact.*, stage.stage_name
                FROM video_production_artifacts AS artifact
                JOIN video_production_jobs AS job ON job.id = artifact.job_id
                JOIN video_production_stages AS stage ON stage.id = artifact.stage_id
                WHERE job.job_code = %s AND artifact.artifact_key = %s
                """,
                (job_code, artifact_key),
            )
            row = cursor.fetchone()
        return self._serialize_artifact(row) if row else None

    def retry(self, job_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM video_production_jobs WHERE job_code = %s FOR UPDATE",
                (job_code,),
            )
            job = cursor.fetchone()
            if job is None:
                self.connection.rollback()
                return None
            if job["status"] != "failed":
                self.connection.rollback()
                raise VideoProductionRetryConflictError("Only failed video production jobs can be retried")

            if job.get("error_code") == "QUALITY_GATE_FAILED":
                cursor.execute(
                    """
                    SELECT stage_order, stage_name
                    FROM video_production_stages
                    WHERE job_id = %s AND stage_name = 'rendering'
                    """,
                    (job["id"],),
                )
                reset_stage = cursor.fetchone()
            else:
                cursor.execute(
                    """
                    SELECT stage_order, stage_name
                    FROM video_production_stages
                    WHERE job_id = %s AND status = 'failed'
                    ORDER BY stage_order
                    LIMIT 1
                    """,
                    (job["id"],),
                )
                reset_stage = cursor.fetchone()
            if reset_stage is None:
                cursor.execute(
                    """
                    SELECT stage_order, stage_name
                    FROM video_production_stages
                    WHERE job_id = %s AND status <> 'succeeded'
                    ORDER BY stage_order
                    LIMIT 1
                    """,
                    (job["id"],),
                )
                reset_stage = cursor.fetchone()
            if reset_stage is None:
                reset_stage = {"stage_order": len(self.STAGES), "stage_name": self.STAGES[-1]}

            new_attempt = job["attempt"] + 1
            reset_order = reset_stage["stage_order"]
            cursor.execute(
                """
                DELETE FROM video_production_artifacts
                WHERE job_id = %s
                  AND stage_id IN (
                      SELECT id FROM video_production_stages
                      WHERE job_id = %s AND stage_order >= %s
                  )
                """,
                (job["id"], job["id"], reset_order),
            )
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'pending', attempt = %s, input_payload = '{}'::jsonb,
                    output_payload = '{}'::jsonb, error_code = NULL, error_message = NULL,
                    started_at = NULL, completed_at = NULL, updated_at = now()
                WHERE job_id = %s AND stage_order >= %s
                """,
                (new_attempt, job["id"], reset_order),
            )

            cleared_columns = [
                column
                for stage_name, column in self.STAGE_OUTPUT_COLUMNS.items()
                if self.STAGES.index(stage_name) + 1 >= reset_order
            ]
            json_resets = ", ".join(f"{column} = '{{}}'::jsonb" for column in cleared_columns)
            if json_resets:
                json_resets = ", " + json_resets
            progress = ((reset_order - 1) * 100) // len(self.STAGES)
            cursor.execute(
                f"""
                UPDATE video_production_jobs
                SET status = 'queued', current_stage = %s, progress_percent = %s,
                    attempt = %s, final_asset_id = NULL, error_code = NULL, error_message = NULL,
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, started_at = NULL, completed_at = NULL,
                    updated_at = now(){json_resets}
                WHERE id = %s
                """,
                (reset_stage["stage_name"], progress, new_attempt, job["id"]),
            )
        self.connection.commit()
        return self.get_by_code(job_code)

    def claim_next(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker_id and a positive lease_seconds value are required")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id, status
                FROM video_production_jobs
                WHERE status = 'queued'
                   OR (status = 'running' AND lease_expires_at < now())
                ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
            candidate = cursor.fetchone()
            if candidate is None:
                self.connection.commit()
                return None
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                    lease_expires_at = now() + (%s * interval '1 second'), heartbeat_at = now(),
                    attempt = attempt + CASE WHEN %s = 'running' THEN 1 ELSE 0 END,
                    started_at = COALESCE(started_at, now()), completed_at = NULL, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, lease_seconds, candidate["status"], candidate["id"]),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize_job(row)

    def renew_lease(
        self,
        job_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None or lease_seconds < 1:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE job_code = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (lease_seconds, job_code, worker_id, token),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize_job(row) if row else None

    def start_stage(
        self,
        job_code: str,
        stage_name: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(cursor, job_code, worker_id, lease_token)
            if job is None:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                SELECT * FROM video_production_stages
                WHERE job_id = %s AND stage_name = %s
                FOR UPDATE
                """,
                (job["id"], stage_name),
            )
            stage = cursor.fetchone()
            if stage is None:
                self.connection.rollback()
                return None
            if stage["status"] == "succeeded":
                self.connection.commit()
                return self._serialize_stage(stage)
            if stage["status"] not in {"pending", "running"}:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                SELECT count(*)
                FROM video_production_stages
                WHERE job_id = %s AND stage_order < %s AND status <> 'succeeded'
                """,
                (job["id"], stage["stage_order"]),
            )
            if cursor.fetchone()["count"]:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'running', attempt = %s, started_at = now(),
                    completed_at = NULL, error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (job["attempt"], stage["id"]),
            )
            updated = cursor.fetchone()
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET current_stage = %s, error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s
                """,
                (stage_name, job["id"]),
            )
        self.connection.commit()
        return self._serialize_stage(updated)

    def complete_stage(
        self,
        job_code: str,
        stage_name: str,
        output_payload: dict[str, Any],
        artifacts: list[dict[str, Any]],
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        registrations = [
            VideoProductionArtifactRegistration.model_validate(artifact).model_dump(mode="python")
            for artifact in artifacts
        ]
        artifact_keys = [artifact["artifact_key"] for artifact in registrations]
        if len(artifact_keys) != len(set(artifact_keys)):
            raise ValueError("artifact_key values must be unique within a stage completion")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(cursor, job_code, worker_id, lease_token)
            if job is None:
                self.connection.rollback()
                return None
            expected_prefix = f"{job_code}/attempt-{int(job['attempt'])}/"
            if any(
                not str(artifact["relative_path"]).startswith(expected_prefix)
                for artifact in registrations
            ):
                self.connection.rollback()
                raise ValueError("artifact relative_path must belong to the current job attempt")
            cursor.execute(
                """
                SELECT * FROM video_production_stages
                WHERE job_id = %s AND stage_name = %s
                FOR UPDATE
                """,
                (job["id"], stage_name),
            )
            stage = cursor.fetchone()
            if stage is None or stage["status"] not in {"running", "succeeded"}:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'succeeded', output_payload = %s, error_code = NULL,
                    error_message = NULL, completed_at = COALESCE(completed_at, now()), updated_at = now()
                WHERE id = %s
                """,
                (Jsonb(output_payload), stage["id"]),
            )
            registered_artifacts: dict[str, dict[str, Any]] = {}
            for artifact in registrations:
                cursor.execute(
                    """
                    INSERT INTO video_production_artifacts (
                        job_id, stage_id, job_code, artifact_key, relative_path, mime_type,
                        file_size, checksum_sha256, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id, artifact_key)
                    DO UPDATE SET
                        stage_id = EXCLUDED.stage_id,
                        relative_path = EXCLUDED.relative_path,
                        mime_type = EXCLUDED.mime_type,
                        file_size = EXCLUDED.file_size,
                        checksum_sha256 = EXCLUDED.checksum_sha256,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    RETURNING id
                    """,
                    (
                        job["id"],
                        stage["id"],
                        job_code,
                        artifact["artifact_key"],
                        artifact["relative_path"],
                        artifact.get("mime_type"),
                        artifact.get("file_size"),
                        artifact.get("checksum_sha256"),
                        Jsonb(artifact.get("metadata") or {}),
                    ),
                )
                registered_artifacts[artifact["artifact_key"]] = {
                    **artifact,
                    "id": cursor.fetchone()["id"],
                }

            self._persist_functional_timeline_execution_artifacts(
                cursor,
                job=job,
                stage_name=stage_name,
                output_payload=output_payload,
                artifacts=registered_artifacts,
            )

            output_column = self.STAGE_OUTPUT_COLUMNS.get(stage_name)
            if output_column:
                cursor.execute(
                    f"UPDATE video_production_jobs SET {output_column} = %s WHERE id = %s",
                    (Jsonb(output_payload), job["id"]),
                )
            cursor.execute(
                "SELECT count(*) FROM video_production_stages WHERE job_id = %s AND status = 'succeeded'",
                (job["id"],),
            )
            completed_count = cursor.fetchone()["count"]
            cursor.execute(
                """
                SELECT stage_name FROM video_production_stages
                WHERE job_id = %s AND status = 'pending'
                ORDER BY stage_order LIMIT 1
                """,
                (job["id"],),
            )
            next_stage = cursor.fetchone()
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET progress_percent = %s, current_stage = %s, updated_at = now()
                WHERE id = %s
                """,
                (
                    (completed_count * 100) // len(self.STAGES),
                    next_stage["stage_name"] if next_stage else stage_name,
                    job["id"],
                ),
            )
        self.connection.commit()
        return self.get_by_code(job_code)

    @staticmethod
    def _persist_functional_timeline_execution_artifacts(
        cursor: Any,
        *,
        job: dict[str, Any],
        stage_name: str,
        output_payload: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
    ) -> None:
        if stage_name == "rendering":
            VideoProductionRepository._persist_functional_timeline_render_artifacts(
                cursor,
                job=job,
                output_payload=output_payload,
                artifacts=artifacts,
            )
            return
        if stage_name not in {"voice_synthesis", "subtitle_generation"}:
            return
        artifact_key = "voice" if stage_name == "voice_synthesis" else "subtitles"
        artifact = artifacts.get(artifact_key)
        if artifact is None:
            return
        checksum = str(artifact.get("checksum_sha256") or "")
        relative_path = str(artifact.get("relative_path") or "")
        if not VideoProductionRepository._valid_checksum(checksum) or not relative_path:
            return
        cursor.execute(
            """SELECT segment.id, segment.clip_code, segment.timeline_start_ms,
                      segment.timeline_end_ms
               FROM functional_video_timeline_segments AS segment
               JOIN functional_video_plans AS plan ON plan.id = segment.plan_id
               WHERE plan.video_job_code = %s
                 AND segment.timeline_revision = plan.timeline_revision""",
            (job["job_code"],),
        )
        timeline_segments = cursor.fetchall()
        if not timeline_segments:
            return
        shot_codes = {
            int(shot["shot_index"]): str(shot.get("shot_code") or "")
            for shot in (job.get("shot_list") or {}).get("shots") or []
            if isinstance(shot, dict) and isinstance(shot.get("shot_index"), int)
        }
        if stage_name == "voice_synthesis":
            role = "voice_segment"
            evidence_by_shot: dict[str, dict[str, Any]] = {}
            for voice_segment in output_payload.get("segments") or []:
                if not isinstance(voice_segment, dict):
                    continue
                shot_code = str(voice_segment.get("shot_code") or "")
                if not shot_code and isinstance(voice_segment.get("shot_index"), int):
                    shot_code = shot_codes.get(int(voice_segment["shot_index"]), "")
                if not shot_code or not VideoProductionRepository._valid_checksum(
                    str(voice_segment.get("checksum_sha256") or "")
                ):
                    continue
                evidence_by_shot[shot_code] = {
                    "schema_version": "functional-video-voice-segment-evidence.v1",
                    "voice_relative_path": str(voice_segment.get("relative_path") or ""),
                    "voice_checksum_sha256": str(voice_segment.get("checksum_sha256") or ""),
                    "voice": str(voice_segment.get("voice") or ""),
                    "gain_db": voice_segment.get("gain_db"),
                    "target_duration_seconds": voice_segment.get("target_duration_seconds"),
                }
        else:
            role = "subtitle_track"
            events_by_shot: dict[str, list[dict[str, Any]]] = {}
            for event in output_payload.get("events") or []:
                if not isinstance(event, dict) or not isinstance(event.get("shot_index"), int):
                    continue
                shot_code = shot_codes.get(int(event["shot_index"]))
                if not shot_code:
                    continue
                events_by_shot.setdefault(shot_code, []).append(
                    {
                        "kind": str(event.get("kind") or "caption"),
                        "start_seconds": event.get("start_seconds"),
                        "end_seconds": event.get("end_seconds"),
                    }
                )
            evidence_by_shot = {
                shot_code: {
                    "schema_version": "functional-video-subtitle-track-evidence.v1",
                    "event_count": len(events),
                    "events": events,
                    "text_complete": output_payload.get("text_complete") is True,
                }
                for shot_code, events in events_by_shot.items()
            }
        for timeline_segment in timeline_segments:
            evidence = evidence_by_shot.get(str(timeline_segment["clip_code"]))
            if evidence is None:
                continue
            cursor.execute(
                """INSERT INTO functional_video_timeline_segment_execution_artifacts (
                       timeline_segment_id, video_artifact_id, job_attempt,
                       artifact_role, artifact_key, relative_path,
                       checksum_sha256, evidence
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (timeline_segment_id, job_attempt, artifact_role) DO NOTHING""",
                (
                    timeline_segment["id"],
                    artifact["id"],
                    int(job["attempt"]),
                    role,
                    artifact_key,
                    relative_path,
                    checksum,
                    Jsonb(evidence),
                ),
            )

    @staticmethod
    def _persist_functional_timeline_render_artifacts(
        cursor: Any,
        *,
        job: dict[str, Any],
        output_payload: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
    ) -> None:
        cursor.execute(
            """SELECT segment.id, segment.segment_code, segment.timeline_start_ms,
                      segment.timeline_end_ms
               FROM functional_video_timeline_segments AS segment
               JOIN functional_video_plans AS plan ON plan.id = segment.plan_id
               WHERE plan.video_job_code = %s
                 AND segment.timeline_revision = plan.timeline_revision""",
            (job["job_code"],),
        )
        timeline_segments = cursor.fetchall()
        if not timeline_segments:
            return
        manifest_fingerprint = str(output_payload.get("manifest_fingerprint") or "")
        if not VideoProductionRepository._valid_checksum(manifest_fingerprint):
            manifest_fingerprint = ""
        poster_seconds = VideoProductionRepository._render_poster_seconds(output_payload)
        for artifact_role, artifact_key in (
            ("render_manifest", "render_manifest"),
            ("rendered_video", "video"),
            ("poster", "poster"),
        ):
            artifact = artifacts.get(artifact_key)
            if artifact is None:
                continue
            checksum = str(artifact.get("checksum_sha256") or "")
            relative_path = str(artifact.get("relative_path") or "")
            if not VideoProductionRepository._valid_checksum(checksum) or not relative_path:
                continue
            for timeline_segment in timeline_segments:
                if artifact_role == "poster" and not VideoProductionRepository._segment_contains_seconds(
                    timeline_segment, poster_seconds
                ):
                    continue
                evidence = {
                    "schema_version": "functional-video-render-artifact-evidence.v1",
                    "timeline_segment_code": str(timeline_segment["segment_code"]),
                    "render_manifest_fingerprint": manifest_fingerprint or None,
                }
                if artifact_role == "poster":
                    evidence["poster_time_seconds"] = poster_seconds
                cursor.execute(
                    """INSERT INTO functional_video_timeline_segment_execution_artifacts (
                           timeline_segment_id, video_artifact_id, job_attempt,
                           artifact_role, artifact_key, relative_path,
                           checksum_sha256, evidence
                       ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (timeline_segment_id, job_attempt, artifact_role) DO NOTHING""",
                    (
                        timeline_segment["id"],
                        artifact["id"],
                        int(job["attempt"]),
                        artifact_role,
                        artifact_key,
                        relative_path,
                        checksum,
                        Jsonb(evidence),
                    ),
                )

    @staticmethod
    def _render_poster_seconds(output_payload: dict[str, Any]) -> float | None:
        output = output_payload.get("outputs")
        poster = output.get("poster") if isinstance(output, dict) else None
        value = poster.get("at_seconds") if isinstance(poster, dict) else None
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
        ):
            return float(value)
        return None

    @staticmethod
    def _segment_contains_seconds(segment: dict[str, Any], seconds: float | None) -> bool:
        if seconds is None:
            return False
        milliseconds = int(seconds * 1000)
        return int(segment["timeline_start_ms"]) <= milliseconds < int(
            segment["timeline_end_ms"]
        )

    @staticmethod
    def _valid_checksum(value: str) -> bool:
        return len(value) == 64 and all(character in "0123456789abcdef" for character in value)

    def fail_stage(
        self,
        job_code: str,
        stage_name: str,
        error_code: str,
        error_message: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(cursor, job_code, worker_id, lease_token)
            if job is None:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'failed', error_code = %s, error_message = %s,
                    completed_at = now(), updated_at = now()
                WHERE job_id = %s AND stage_name = %s AND status IN ('pending', 'running')
                RETURNING id
                """,
                (error_code, error_message, job["id"], stage_name),
            )
            if cursor.fetchone() is None:
                self.connection.rollback()
                return None
            self._mark_job_failed(cursor, job["id"], stage_name, error_code, error_message)
        self.connection.commit()
        return self.get_by_code(job_code)

    def complete_job(
        self,
        job_code: str,
        final_asset_id: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        final_asset_uuid = self._parse_uuid(final_asset_id)
        if final_asset_uuid is None:
            raise ValueError("final_asset_id must be a UUID")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(cursor, job_code, worker_id, lease_token)
            if job is None:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                SELECT count(*) FROM video_production_stages
                WHERE job_id = %s AND status <> 'succeeded'
                """,
                (job["id"],),
            )
            if cursor.fetchone()["count"]:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                SELECT 1
                FROM assets AS asset
                JOIN video_production_artifacts AS artifact
                  ON artifact.job_id = %s AND artifact.artifact_key = 'video'
                WHERE asset.id = %s
                  AND asset.source_system = 'video_production'
                  AND asset.local_file_code = %s
                  AND asset.status = 'ready'
                  AND asset.checksum_sha256 = artifact.checksum_sha256
                  AND asset.file_size = artifact.file_size
                """,
                (job["id"], final_asset_uuid, job_code),
            )
            if cursor.fetchone() is None:
                self.connection.rollback()
                return None
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET status = 'succeeded', progress_percent = 100, final_asset_id = %s,
                    error_code = NULL, error_message = NULL, claimed_by = NULL,
                    lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (final_asset_uuid, job["id"]),
            )
        self.connection.commit()
        return self.get_by_code(job_code)

    def fail_job(
        self,
        job_code: str,
        error_code: str,
        error_message: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_owned_job(cursor, job_code, worker_id, lease_token)
            if job is None:
                self.connection.rollback()
                return None
            stage_name = job.get("current_stage") or self.STAGES[0]
            cursor.execute(
                """
                UPDATE video_production_stages
                SET status = 'failed', error_code = %s, error_message = %s,
                    completed_at = now(), updated_at = now()
                WHERE job_id = %s AND stage_name = %s AND status IN ('pending', 'running')
                """,
                (error_code, error_message, job["id"], stage_name),
            )
            self._mark_job_failed(cursor, job["id"], stage_name, error_code, error_message)
        self.connection.commit()
        return self.get_by_code(job_code)

    def _lock_owned_job(
        self,
        cursor: Any,
        job_code: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any] | None:
        token = self._parse_uuid(lease_token)
        if token is None:
            return None
        cursor.execute(
            """
            SELECT * FROM video_production_jobs
            WHERE job_code = %s AND status = 'running' AND claimed_by = %s
              AND lease_token = %s AND lease_expires_at > now()
            FOR UPDATE
            """,
            (job_code, worker_id, token),
        )
        return cursor.fetchone()

    @staticmethod
    def _mark_job_failed(
        cursor: Any,
        job_id: Any,
        stage_name: str,
        error_code: str,
        error_message: str,
    ) -> None:
        cursor.execute(
            """
            UPDATE video_production_jobs
            SET status = 'failed', current_stage = %s, error_code = %s, error_message = %s,
                claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                heartbeat_at = NULL, completed_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (stage_name, error_code, error_message, job_id),
        )

    def _next_job_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, BusinessObjectType.VIDEO_PRODUCTION_JOB.value),
            )
            sequence = cursor.fetchone()[0]
        return format_video_production_job_code(sequence_date, sequence)

    @staticmethod
    def _parse_uuid(value: str) -> UUID | None:
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _serialize_job(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in ("id", "final_asset_id", "lease_token"):
            if converted.get(field) is not None:
                converted[field] = str(converted[field])
        return converted

    @staticmethod
    def _serialize_stage(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in ("id", "job_id"):
            if converted.get(field) is not None:
                converted[field] = str(converted[field])
        return converted

    @staticmethod
    def _serialize_artifact(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in ("id", "job_id", "stage_id"):
            if converted.get(field) is not None:
                converted[field] = str(converted[field])
        return converted
