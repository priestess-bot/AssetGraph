from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.services.live_observations import LiveObservationConflictError


class LiveObservationRepository:
    REQUIRED_CHUNK_ANALYSES = (
        "frame_sampling",
        "asr",
        "ocr",
        "layout_inference",
    )
    CODE_PREFIXES = {
        "watch_target": "LR-WATCH",
        "capture_session": "LR-CAP",
        "capture_channel": "LR-CHAN",
        "capture_chunk": "LR-CHUNK",
        "event_batch": "LR-EVENT",
        "clip_job": "LR-CLIP",
        "analysis_run": "LR-ANL",
        "room_template": "LR-TPL",
        "publication": "LR-PUB",
    }

    def __init__(self, connection: Connection):
        self.connection = connection

    def overview(self) -> dict[str, int]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM live_watch_targets WHERE deleted_at IS NULL) AS watch_targets_total,
                    (SELECT count(*) FROM live_watch_targets WHERE deleted_at IS NULL AND status = 'enabled') AS watch_targets_enabled,
                    (SELECT count(*) FROM live_watch_targets WHERE deleted_at IS NULL AND status = 'blocked') AS watch_targets_blocked,
                    (SELECT count(*) FROM live_capture_sessions WHERE status IN ('starting', 'recording', 'finalizing')) AS active_capture_sessions,
                    (SELECT count(*) FROM live_capture_sessions WHERE status = 'completed') AS completed_capture_sessions,
                    (SELECT count(*) FROM live_capture_chunks WHERE status = 'finalized') AS finalized_chunks,
                    (SELECT count(*) FROM live_raw_event_batches WHERE status = 'finalized') AS raw_event_batches,
                    (SELECT count(*) FROM live_clip_jobs WHERE status = 'queued') AS queued_clip_jobs,
                    (SELECT count(*) FROM live_analysis_runs WHERE status = 'queued') AS queued_analysis_runs,
                    (SELECT count(*) FROM live_analysis_runs WHERE status = 'running') AS running_analysis_runs,
                    (SELECT count(*) FROM live_analysis_runs WHERE status = 'failed') AS failed_analysis_runs,
                    (SELECT count(DISTINCT session_id) FROM live_analysis_runs WHERE status = 'failed') AS analysis_blocked_sessions,
                    (SELECT count(*) FROM live_room_templates WHERE status = 'published') AS published_templates,
                    (SELECT count(*) FROM live_room_templates WHERE status = 'draft') AS draft_templates,
                    (
                        SELECT count(*) FROM live_capture_chunks
                        WHERE status = 'finalized' AND legal_hold = false
                          AND retention_expires_at > now()
                          AND retention_expires_at <= now() + interval '7 days'
                    ) AS expiring_capture_chunks,
                    (SELECT count(*) FROM live_research_projection_ready WHERE projection_ready = true) AS projection_ready_templates
                """
            )
            return dict(cursor.fetchone())

    def create_watch_target(self, payload: dict[str, Any]) -> dict[str, Any]:
        target_code = self._next_code("watch_target")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO live_watch_targets (
                    target_code, platform, room_url, canonical_room_id, display_name,
                    recorder_engine, preferred_quality, poll_interval_seconds,
                    retention_days, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    target_code,
                    payload.get("platform", "douyin"),
                    str(payload["room_url"]),
                    payload.get("canonical_room_id"),
                    payload["display_name"],
                    payload.get("recorder_engine", "streamcap"),
                    payload.get("preferred_quality", "720p"),
                    payload.get("poll_interval_seconds", 180),
                    payload.get("retention_days", 30),
                    Jsonb(payload.get("metadata") or {}),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._target(row)

    def list_watch_targets(
        self, *, status: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        clauses = ["deleted_at IS NULL"]
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *, lease_expires_at IS NOT NULL AND lease_expires_at > now() AS lease_active
                FROM live_watch_targets
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC, target_code DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            return [self._target(row) for row in cursor.fetchall()]

    def get_watch_target(self, target_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *, lease_expires_at IS NOT NULL AND lease_expires_at > now() AS lease_active
                FROM live_watch_targets
                WHERE target_code = %s AND deleted_at IS NULL
                """,
                (target_code,),
            )
            row = cursor.fetchone()
        return self._target(row) if row else None

    def update_watch_target(
        self, target_code: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {
            "display_name",
            "canonical_room_id",
            "status",
            "preferred_quality",
            "poll_interval_seconds",
            "metadata",
        }
        data = {key: value for key, value in payload.items() if key in allowed}
        if not data:
            return self.get_watch_target(target_code)
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in data.items():
            assignments.append(f"{key} = %s")
            values.append(Jsonb(value) if key == "metadata" else value)
        if data.get("status") == "deleted":
            assignments.extend(
                [
                    "deleted_at = now()",
                    "claimed_by = NULL",
                    "claim_token = NULL",
                    "lease_expires_at = NULL",
                    "heartbeat_at = NULL",
                ]
            )
        assignments.append("updated_at = now()")
        values.append(target_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE live_watch_targets
                SET {', '.join(assignments)}
                WHERE target_code = %s AND deleted_at IS NULL
                RETURNING *, lease_expires_at IS NOT NULL AND lease_expires_at > now() AS lease_active
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._target(row) if row else None

    def claim_watch_target(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_capture_sessions AS session
                SET status = 'abandoned', observed_ended_at = greatest(session.observed_started_at, now()),
                    failure_code = 'CAPTURE_LEASE_EXPIRED',
                    failure_message = 'The owning watch-target lease expired before capture finalization',
                    metadata = session.metadata || '{"recovery":"stale_session_abandoned"}'::jsonb,
                    ended_at = now(), updated_at = now()
                FROM live_watch_targets AS target
                WHERE session.target_id = target.id
                  AND session.status IN ('starting', 'recording', 'finalizing')
                  AND (target.lease_expires_at IS NULL OR target.lease_expires_at <= now())
                """
            )
            cursor.execute(
                """
                WITH candidate AS (
                    SELECT target.id
                    FROM live_watch_targets AS target
                    WHERE target.deleted_at IS NULL
                      AND target.status = 'enabled'
                      AND target.next_check_at <= now()
                      AND (target.lease_expires_at IS NULL OR target.lease_expires_at < now())
                      AND NOT EXISTS (
                          SELECT 1 FROM live_capture_sessions
                          WHERE status IN ('starting', 'recording', 'finalizing')
                      )
                    ORDER BY target.next_check_at, target.created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE live_watch_targets AS target
                SET claimed_by = %s, claim_token = gen_random_uuid(),
                    lease_version = target.lease_version + 1,
                    lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), last_observed_at = now(), updated_at = now()
                FROM candidate
                WHERE target.id = candidate.id
                RETURNING target.*, true AS lease_active
                """,
                (worker_id, lease_seconds),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._target(row, include_claim=True) if row else None

    def heartbeat_watch_target(
        self,
        target_code: str,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        token = self._uuid(claim_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_watch_targets
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE target_code = %s AND claimed_by = %s AND claim_token = %s
                  AND lease_version = %s AND lease_expires_at > now()
                  AND status = 'enabled' AND deleted_at IS NULL
                RETURNING *, true AS lease_active
                """,
                (lease_seconds, target_code, worker_id, token, lease_version),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._target(row, include_claim=True) if row else None

    def release_watch_target(
        self, target_code: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        token = self._uuid(payload["claim_token"])
        if token is None:
            return None
        outcome = payload["outcome"]
        status_value = "blocked" if outcome == "blocked" else "enabled"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_watch_targets
                SET status = %s,
                    next_check_at = now() + (%s * interval '1 second'),
                    consecutive_failures = CASE WHEN %s = 'failed' THEN consecutive_failures + 1 ELSE 0 END,
                    last_error_code = CASE WHEN %s IN ('failed', 'blocked') THEN %s ELSE NULL END,
                    last_error_message = CASE WHEN %s IN ('failed', 'blocked') THEN %s ELSE NULL END,
                    claimed_by = NULL, claim_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, updated_at = now()
                WHERE target_code = %s AND claimed_by = %s AND claim_token = %s
                  AND lease_version = %s AND lease_expires_at > now() AND deleted_at IS NULL
                RETURNING *, false AS lease_active
                """,
                (
                    status_value,
                    payload["next_check_seconds"],
                    outcome,
                    outcome,
                    payload.get("error_code"),
                    outcome,
                    payload.get("error_message"),
                    target_code,
                    payload["worker_id"],
                    token,
                    payload["lease_version"],
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._target(row) if row else None

    def create_capture_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = self._uuid(payload["claim_token"])
        if token is None:
            raise LiveObservationConflictError("capture claim token is invalid")
        session_code = self._next_code("capture_session")
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM live_watch_targets
                    WHERE target_code = %s AND claimed_by = %s AND claim_token = %s
                      AND lease_version = %s AND lease_expires_at > now()
                      AND status = 'enabled' AND deleted_at IS NULL
                    FOR UPDATE
                    """,
                    (
                        payload["target_code"],
                        payload["worker_id"],
                        token,
                        payload["lease_version"],
                    ),
                )
                target = cursor.fetchone()
                if target is None:
                    raise LiveObservationConflictError("capture claim is missing, expired, or fenced")
                cursor.execute(
                    """
                    INSERT INTO live_capture_sessions (
                        session_code, target_id, target_code, platform, source_live_session_id,
                        recorder_engine, recorder_version, recorder_build_fingerprint,
                        event_adapter, event_adapter_version, status, observed_started_at,
                        monotonic_started_ns, capture_boot_id, timeline_origin_at, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'recording', %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        session_code,
                        target["id"],
                        target["target_code"],
                        target["platform"],
                        payload.get("source_live_session_id"),
                        payload["recorder_engine"],
                        payload["recorder_version"],
                        payload["recorder_build_fingerprint"],
                        payload.get("event_adapter", "douyinlive"),
                        payload.get("event_adapter_version", "v2.0.24"),
                        payload["observed_started_at"],
                        payload.get("monotonic_started_ns"),
                        payload.get("capture_boot_id"),
                        payload["observed_started_at"],
                        Jsonb(payload.get("metadata") or {}),
                    ),
                )
                cursor.execute(
                    """
                    UPDATE live_watch_targets
                    SET last_live_at = %s, last_capture_session_code = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (payload["observed_started_at"], session_code, target["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get_capture_session(session_code, include_children=True)

    def finish_capture_session(
        self,
        session_code: str,
        payload: dict[str, Any],
        *,
        analysis_specs: list[dict[str, Any]] | None = None,
        aggregation_spec: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_capture_sessions
                SET status = %s, observed_ended_at = %s, monotonic_ended_ns = %s,
                    failure_code = %s, failure_message = %s,
                    metadata = metadata || %s, ended_at = now(), updated_at = now()
                WHERE session_code = %s AND status IN ('starting', 'recording', 'finalizing')
                RETURNING *
                """,
                (
                    payload["status"],
                    payload["observed_ended_at"],
                    payload.get("monotonic_ended_ns"),
                    payload.get("failure_code"),
                    payload.get("failure_message"),
                    Jsonb(payload.get("metadata") or {}),
                    session_code,
                ),
            )
            row = cursor.fetchone()
            if row is not None and payload["status"] == "completed":
                self._enqueue_session_analysis_dag(
                    cursor,
                    row,
                    analysis_specs or [],
                )
                if aggregation_spec:
                    self._enqueue_ready_template_aggregation(
                        cursor,
                        row,
                        aggregation_spec,
                    )
        self.connection.commit()
        return self.get_capture_session(session_code, include_children=True) if row else None

    def list_capture_sessions(
        self,
        *,
        target_code: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        clauses = ["true"]
        params: list[Any] = []
        if target_code is not None:
            clauses.append("session.target_code = %s")
            params.append(target_code)
        if status is not None:
            clauses.append("session.status = %s")
            params.append(status)
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT session.*,
                       (SELECT count(*) FROM live_capture_chunks chunk WHERE chunk.session_id = session.id) AS chunk_count,
                       (SELECT coalesce(sum(batch.event_count), 0) FROM live_raw_event_batches batch WHERE batch.session_id = session.id) AS event_count,
                       (SELECT max(span.global_end_seconds) FROM live_timeline_spans span WHERE span.session_id = session.id) AS timeline_duration_seconds,
                       (
                           SELECT coalesce(jsonb_object_agg(counts.status, counts.total), '{{}}'::jsonb)
                           FROM (
                               SELECT run.status, count(*) AS total
                               FROM live_analysis_runs AS run
                               WHERE run.session_id = session.id
                               GROUP BY run.status
                           ) AS counts
                       ) AS analysis_status_counts,
                       (
                           SELECT coalesce(jsonb_agg(jsonb_build_object(
                               'analysis_run_code', failed.analysis_run_code,
                               'chunk_code', failed.chunk_code,
                               'analysis_type', failed.analysis_type,
                               'error_code', failed.error_code,
                               'error_message', failed.error_message,
                               'attempt_count', failed.attempt_count,
                               'max_attempts', failed.max_attempts
                           ) ORDER BY failed.created_at), '[]'::jsonb)
                           FROM live_analysis_runs AS failed
                           WHERE failed.session_id = session.id AND failed.status = 'failed'
                             AND failed.analysis_type = ANY(%s)
                             AND NOT EXISTS (
                                 SELECT 1 FROM live_analysis_runs AS recovered
                                 WHERE recovered.session_id = failed.session_id
                                   AND recovered.chunk_id IS NOT DISTINCT FROM failed.chunk_id
                                   AND recovered.analysis_type = failed.analysis_type
                                   AND recovered.status = 'succeeded'
                             )
                       ) AS analysis_blockers
                FROM live_capture_sessions AS session
                WHERE {' AND '.join(clauses)}
                ORDER BY session.observed_started_at DESC, session.session_code DESC
                LIMIT %s OFFSET %s
                """,
                (list(self.REQUIRED_CHUNK_ANALYSES), *params),
            )
            return [self._session(row) for row in cursor.fetchall()]

    def get_capture_session(
        self, session_code: str, *, include_children: bool
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT session.*,
                       (SELECT count(*) FROM live_capture_chunks chunk WHERE chunk.session_id = session.id) AS chunk_count,
                       (SELECT coalesce(sum(batch.event_count), 0) FROM live_raw_event_batches batch WHERE batch.session_id = session.id) AS event_count,
                       (SELECT max(span.global_end_seconds) FROM live_timeline_spans span WHERE span.session_id = session.id) AS timeline_duration_seconds,
                       (
                           SELECT coalesce(jsonb_object_agg(counts.status, counts.total), '{}'::jsonb)
                           FROM (
                               SELECT run.status, count(*) AS total
                               FROM live_analysis_runs AS run
                               WHERE run.session_id = session.id
                               GROUP BY run.status
                           ) AS counts
                       ) AS analysis_status_counts,
                       (
                           SELECT coalesce(jsonb_agg(jsonb_build_object(
                               'analysis_run_code', failed.analysis_run_code,
                               'chunk_code', failed.chunk_code,
                               'analysis_type', failed.analysis_type,
                               'error_code', failed.error_code,
                               'error_message', failed.error_message,
                               'attempt_count', failed.attempt_count,
                               'max_attempts', failed.max_attempts
                           ) ORDER BY failed.created_at), '[]'::jsonb)
                           FROM live_analysis_runs AS failed
                           WHERE failed.session_id = session.id AND failed.status = 'failed'
                             AND failed.analysis_type = ANY(%s)
                             AND NOT EXISTS (
                                 SELECT 1 FROM live_analysis_runs AS recovered
                                 WHERE recovered.session_id = failed.session_id
                                   AND recovered.chunk_id IS NOT DISTINCT FROM failed.chunk_id
                                   AND recovered.analysis_type = failed.analysis_type
                                   AND recovered.status = 'succeeded'
                             )
                       ) AS analysis_blockers
                FROM live_capture_sessions AS session
                WHERE session.session_code = %s
                """,
                (list(self.REQUIRED_CHUNK_ANALYSES), session_code),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            result = self._session(row)
            if not include_children:
                return result
            cursor.execute(
                "SELECT * FROM live_capture_channels WHERE session_id = %s ORDER BY media_kind, stream_index",
                (row["id"],),
            )
            result["channels"] = [self._row(item) for item in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM live_capture_chunks WHERE session_id = %s ORDER BY part_index",
                (row["id"],),
            )
            result["chunks"] = [self._row(item) for item in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM live_raw_event_batches WHERE session_id = %s ORDER BY batch_index",
                (row["id"],),
            )
            result["raw_event_batches"] = [self._row(item) for item in cursor.fetchall()]
            cursor.execute(
                "SELECT * FROM live_timeline_spans WHERE session_id = %s ORDER BY span_index",
                (row["id"],),
            )
            result["timeline"] = [self._row(item) for item in cursor.fetchall()]
            return result

    def add_capture_channel(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        channel_code = self._next_code("capture_channel")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            session = self._session_by_code(cursor, session_code)
            if session is None:
                raise LiveObservationConflictError("capture session does not exist")
            cursor.execute(
                """
                INSERT INTO live_capture_channels (
                    channel_code, session_id, session_code, channel_key, media_kind,
                    stream_index, codec_name, time_base, language, sample_rate,
                    channels, width, height, average_frame_rate, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, channel_key) DO UPDATE
                SET codec_name = EXCLUDED.codec_name, time_base = EXCLUDED.time_base,
                    language = EXCLUDED.language, sample_rate = EXCLUDED.sample_rate,
                    channels = EXCLUDED.channels, width = EXCLUDED.width,
                    height = EXCLUDED.height, average_frame_rate = EXCLUDED.average_frame_rate,
                    metadata = EXCLUDED.metadata
                RETURNING *
                """,
                (
                    channel_code,
                    session["id"],
                    session_code,
                    payload["channel_key"],
                    payload["media_kind"],
                    payload["stream_index"],
                    payload.get("codec_name"),
                    payload.get("time_base"),
                    payload.get("language"),
                    payload.get("sample_rate"),
                    payload.get("channels"),
                    payload.get("width"),
                    payload.get("height"),
                    payload.get("average_frame_rate"),
                    Jsonb(payload.get("metadata") or {}),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row)

    def finalize_capture_chunk(
        self,
        session_code: str,
        payload: dict[str, Any],
        *,
        analysis_specs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        chunk_code = self._next_code("capture_chunk")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            session = self._session_by_code(cursor, session_code, lock=True)
            if session is None or session["status"] not in {"starting", "recording", "finalizing"}:
                raise LiveObservationConflictError("capture session is not accepting chunks")
            cursor.execute(
                """
                SELECT * FROM live_capture_chunks
                WHERE session_id = %s AND part_index = %s
                FOR UPDATE
                """,
                (session["id"], payload["part_index"]),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if (
                    existing["relative_path"] == payload["relative_path"]
                    and existing["checksum_sha256"] == payload["checksum_sha256"]
                    and existing["file_size"] == payload["file_size"]
                ):
                    self._enqueue_chunk_analysis_dag(
                        cursor,
                        session,
                        existing,
                        analysis_specs or [],
                    )
                    self.connection.commit()
                    return self._row(existing)
                raise LiveObservationConflictError("capture part index already has different content")
            cursor.execute(
                """
                INSERT INTO live_capture_chunks (
                    chunk_code, session_id, session_code, part_index, relative_path,
                    container_format, status, file_size, checksum_sha256,
                    capture_started_at, capture_ended_at, finalized_at,
                    retention_expires_at, source_start_seconds, source_end_seconds,
                    decoded_duration_seconds, stream_timing, media_probe,
                    discontinuity_kind, discontinuity_milliseconds
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, 'finalized', %s, %s, %s, %s,
                    now(), now() + interval '30 days', %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    chunk_code,
                    session["id"],
                    session_code,
                    payload["part_index"],
                    payload["relative_path"],
                    payload.get("container_format", "mpegts"),
                    payload["file_size"],
                    payload["checksum_sha256"],
                    payload["capture_started_at"],
                    payload["capture_ended_at"],
                    payload.get("source_start_seconds"),
                    payload.get("source_end_seconds"),
                    payload["decoded_duration_seconds"],
                    Jsonb(payload.get("stream_timing") or {}),
                    Jsonb(payload.get("media_probe") or {}),
                    payload.get("discontinuity_kind", "none"),
                    payload.get("discontinuity_milliseconds", 0),
                ),
            )
            row = cursor.fetchone()
            cursor.execute(
                """
                UPDATE live_capture_sessions
                SET status = 'recording', timeline_origin_at = coalesce(timeline_origin_at, %s),
                    updated_at = now()
                WHERE id = %s
                """,
                (payload["capture_started_at"], session["id"]),
            )
            self._enqueue_chunk_analysis_dag(
                cursor,
                session,
                row,
                analysis_specs or [],
            )
        self.connection.commit()
        return self._row(row)

    def register_raw_event_batch(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        batch_code = self._next_code("event_batch")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            session = self._session_by_code(cursor, session_code, lock=True)
            if session is None:
                raise LiveObservationConflictError("capture session does not exist")
            cursor.execute(
                "SELECT * FROM live_raw_event_batches WHERE session_id = %s AND batch_index = %s FOR UPDATE",
                (session["id"], payload["batch_index"]),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if (
                    existing["relative_path"] == payload["relative_path"]
                    and existing["checksum_sha256"] == payload["checksum_sha256"]
                    and existing["file_size"] == payload["file_size"]
                ):
                    self.connection.commit()
                    return self._row(existing)
                raise LiveObservationConflictError("event batch index already has different content")
            cursor.execute(
                """
                INSERT INTO live_raw_event_batches (
                    batch_code, session_id, session_code, batch_index, relative_path,
                    schema_version, content_encoding, file_mode, file_size, checksum_sha256,
                    event_count, event_types, first_server_at, last_server_at,
                    first_received_at, last_received_at, finalized_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    batch_code,
                    session["id"],
                    session_code,
                    payload["batch_index"],
                    payload["relative_path"],
                    payload["schema_version"],
                    payload.get("content_encoding", "gzip"),
                    payload.get("file_mode", 384),
                    payload["file_size"],
                    payload["checksum_sha256"],
                    payload["event_count"],
                    Jsonb(payload.get("event_types") or {}),
                    payload.get("first_server_at"),
                    payload.get("last_server_at"),
                    payload["first_received_at"],
                    payload["last_received_at"],
                    payload["finalized_at"],
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row)

    def list_timeline(self, session_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM live_timeline_spans WHERE session_code = %s ORDER BY span_index",
                (session_code,),
            )
            return [self._row(row) for row in cursor.fetchall()]

    def list_interaction_batch_summaries(self, session_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT event_count, event_types, first_received_at, last_received_at
                FROM live_raw_event_batches
                WHERE session_code = %s AND status = 'finalized'
                ORDER BY batch_index
                """,
                (session_code,),
            )
            return [self._row(row) for row in cursor.fetchall()]

    def append_timeline_span(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            session = self._session_by_code(cursor, session_code, lock=True)
            if session is None:
                raise LiveObservationConflictError("capture session does not exist")
            cursor.execute(
                """
                SELECT * FROM live_capture_chunks
                WHERE session_id = %s AND chunk_code = %s AND status = 'finalized'
                FOR UPDATE
                """,
                (session["id"], payload["chunk_code"]),
            )
            chunk = cursor.fetchone()
            if chunk is None:
                raise LiveObservationConflictError("timeline chunk is missing or not finalized")
            cursor.execute(
                """
                INSERT INTO live_timeline_spans (
                    session_id, session_code, chunk_id, chunk_code, span_index,
                    contract_version, global_start_seconds, global_end_seconds,
                    chunk_start_seconds, chunk_end_seconds, wall_start_at, wall_end_at,
                    mapping_slope, confidence, discontinuity_before, mapping
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    session["id"],
                    session_code,
                    chunk["id"],
                    chunk["chunk_code"],
                    payload["span_index"],
                    payload.get("contract_version", "media-timeline.v1"),
                    payload["global_start_seconds"],
                    payload["global_end_seconds"],
                    payload["chunk_start_seconds"],
                    payload["chunk_end_seconds"],
                    payload.get("wall_start_at"),
                    payload.get("wall_end_at"),
                    payload.get("mapping_slope", 1),
                    payload.get("confidence", 1),
                    payload.get("discontinuity_before", "none"),
                    Jsonb(payload.get("mapping") or {}),
                ),
            )
            row = cursor.fetchone()
            cursor.execute(
                "UPDATE live_capture_chunks SET timeline_ready = true, updated_at = now() WHERE id = %s",
                (chunk["id"],),
            )
        self.connection.commit()
        return self._row(row)

    def create_clip_job(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        job_code = self._next_code("clip_job")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            session = self._session_by_code(cursor, session_code)
            if session is None:
                raise LiveObservationConflictError("capture session does not exist")
            cursor.execute(
                """
                SELECT string_agg(checksum_sha256, '' ORDER BY part_index) AS hashes
                FROM live_capture_chunks
                WHERE session_id = %s AND status = 'finalized' AND timeline_ready = true
                """,
                (session["id"],),
            )
            hashes = cursor.fetchone()["hashes"]
            if not hashes:
                raise LiveObservationConflictError("capture session has no timeline-ready chunks")
            source_fingerprint = hashlib.sha256(hashes.encode("ascii")).hexdigest()
            cursor.execute(
                """
                INSERT INTO live_clip_jobs (
                    clip_job_code, session_id, session_code, title,
                    requested_start_seconds, requested_end_seconds, cut_mode, source_fingerprint
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    job_code,
                    session["id"],
                    session_code,
                    payload.get("title"),
                    payload["requested_start_seconds"],
                    payload["requested_end_seconds"],
                    payload.get("cut_mode", "exact_reencode"),
                    source_fingerprint,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row)

    def list_clip_jobs(
        self,
        *,
        session_code: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        clauses = ["true"]
        params: list[Any] = []
        if session_code:
            clauses.append("session_code = %s")
            params.append(session_code)
        if status:
            clauses.append("status = %s")
            params.append(status)
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT * FROM live_clip_jobs WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                tuple(params),
            )
            return [self._row(row) for row in cursor.fetchall()]

    def claim_clip_job(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        return self._claim_work("live_clip_jobs", "clip_job_code", worker_id, lease_seconds)

    def complete_clip_job(
        self, job_code: str, worker_id: str, lease_token: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        token = self._uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_clip_jobs
                SET status = 'succeeded', actual_start_seconds = %s, actual_end_seconds = %s,
                    output_relative_path = %s, output_file_size = %s,
                    output_checksum_sha256 = %s, ffmpeg_version = %s,
                    ffmpeg_arguments = %s, completed_at = now(), updated_at = now(),
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                WHERE clip_job_code = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (
                    payload["actual_start_seconds"],
                    payload["actual_end_seconds"],
                    payload["output_relative_path"],
                    payload["output_file_size"],
                    payload["output_checksum_sha256"],
                    payload["ffmpeg_version"],
                    Jsonb(payload["ffmpeg_arguments"]),
                    job_code,
                    worker_id,
                    token,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row) if row else None

    def create_analysis_run(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        legacy_contract = payload.get("strategy_revision") is None
        strategy_revision = (
            "legacy.live-analysis.v1"
            if legacy_contract
            else str(payload["strategy_revision"])
        )
        model_provider = payload.get("model_provider") if legacy_contract else None
        model_version = payload.get("model_version") if legacy_contract else None
        run_code = self._next_code("analysis_run")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            session = self._session_by_code(cursor, session_code)
            if session is None:
                raise LiveObservationConflictError("capture session does not exist")
            chunk = None
            if payload.get("chunk_code"):
                cursor.execute(
                    "SELECT * FROM live_capture_chunks WHERE session_id = %s AND chunk_code = %s",
                    (session["id"], payload["chunk_code"]),
                )
                chunk = cursor.fetchone()
                if chunk is None:
                    raise LiveObservationConflictError("analysis chunk does not belong to capture session")
            cursor.execute(
                """
                INSERT INTO live_analysis_runs (
                    analysis_run_code, session_id, session_code, chunk_id, chunk_code,
                    analysis_type, input_fingerprint, strategy_revision,
                    model_provider, model_version, parameters
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING *
                """,
                (
                    run_code,
                    session["id"],
                    session_code,
                    chunk["id"] if chunk else None,
                    chunk["chunk_code"] if chunk else None,
                    payload["analysis_type"],
                    payload["input_fingerprint"],
                    strategy_revision,
                    model_provider,
                    model_version,
                    Jsonb(payload.get("parameters") or {}),
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    SELECT * FROM live_analysis_runs
                    WHERE session_id = %s AND chunk_id IS NOT DISTINCT FROM %s
                      AND analysis_type = %s AND input_fingerprint = %s
                      AND strategy_revision = %s
                    """,
                    (
                        session["id"],
                        chunk["id"] if chunk else None,
                        payload["analysis_type"],
                        payload["input_fingerprint"],
                        strategy_revision,
                    ),
                )
                row = cursor.fetchone()
        self.connection.commit()
        return self._row(row)

    def _enqueue_chunk_analysis_dag(
        self,
        cursor: Any,
        session: dict[str, Any],
        chunk: dict[str, Any],
        specs: list[dict[str, Any]],
    ) -> None:
        for spec in specs:
            analysis_type = str(spec["analysis_type"])
            if analysis_type not in self.REQUIRED_CHUNK_ANALYSES:
                raise ValueError(f"unsupported automatic chunk analysis: {analysis_type}")
            parameters = dict(spec.get("parameters") or {})
            parameters["_dag"] = {
                "auto_created": True,
                "pipeline_version": "live-observation-dag.v1",
            }
            fingerprint = self._fingerprint(
                {
                    "chunk_checksum_sha256": chunk["checksum_sha256"],
                    "analysis_type": analysis_type,
                    "strategy_revision": spec["strategy_revision"],
                    "parameters": parameters,
                }
            )
            cursor.execute(
                """
                INSERT INTO live_analysis_runs (
                    analysis_run_code, session_id, session_code, chunk_id, chunk_code,
                    analysis_type, input_fingerprint, strategy_revision, parameters
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    self._next_code("analysis_run"),
                    session["id"],
                    session["session_code"],
                    chunk["id"],
                    chunk["chunk_code"],
                    analysis_type,
                    fingerprint,
                    spec["strategy_revision"],
                    Jsonb(parameters),
                ),
            )

    def _enqueue_session_analysis_dag(
        self,
        cursor: Any,
        session: dict[str, Any],
        specs: list[dict[str, Any]],
    ) -> None:
        cursor.execute(
            """
            SELECT * FROM live_capture_chunks
            WHERE session_id = %s AND status IN ('finalized', 'delete_candidate')
            ORDER BY part_index
            """,
            (session["id"],),
        )
        for chunk in cursor.fetchall():
            self._enqueue_chunk_analysis_dag(cursor, session, chunk, specs)

    def _enqueue_ready_template_aggregation(
        self,
        cursor: Any,
        session: dict[str, Any],
        spec: dict[str, str],
    ) -> None:
        if session["status"] != "completed":
            return
        cursor.execute(
            """
            SELECT id, chunk_code, checksum_sha256
            FROM live_capture_chunks
            WHERE session_id = %s AND status IN ('finalized', 'delete_candidate')
            ORDER BY part_index
            """,
            (session["id"],),
        )
        chunks = cursor.fetchall()
        if not chunks:
            return
        chunk_ids = [chunk["id"] for chunk in chunks]
        cursor.execute(
            """
            SELECT DISTINCT ON (chunk_id, analysis_type)
                   id, analysis_run_code, chunk_id, chunk_code, analysis_type,
                   output_payload, output_checksum_sha256, strategy_revision,
                   invocation_evidence_ref,
                   completed_at
            FROM live_analysis_runs
            WHERE session_id = %s AND chunk_id = ANY(%s)
              AND analysis_type = ANY(%s) AND status = 'succeeded'
            ORDER BY chunk_id, analysis_type, completed_at DESC, analysis_run_code DESC
            """,
            (session["id"], chunk_ids, list(self.REQUIRED_CHUNK_ANALYSES)),
        )
        completed = {
            (row["chunk_id"], row["analysis_type"]): row for row in cursor.fetchall()
        }
        if any(
            (chunk["id"], analysis_type) not in completed
            for chunk in chunks
            for analysis_type in self.REQUIRED_CHUNK_ANALYSES
        ):
            return
        observations: list[dict[str, Any]] = []
        upstream: list[dict[str, Any]] = []
        for chunk in chunks:
            for analysis_type in self.REQUIRED_CHUNK_ANALYSES:
                run = completed[(chunk["id"], analysis_type)]
                observations.append(
                    {
                        "chunk_code": chunk["chunk_code"],
                        "analysis_type": analysis_type,
                        "analysis_run_code": run["analysis_run_code"],
                        "output": run["output_payload"],
                    }
                )
                upstream.append(
                    {
                        "analysis_run_code": run["analysis_run_code"],
                        "output_checksum_sha256": run["output_checksum_sha256"],
                        "strategy_revision": run["strategy_revision"],
                        "invocation_evidence_ref": run["invocation_evidence_ref"],
                    }
                )
        fingerprint = self._fingerprint(
            {
                "pipeline_version": "live-observation-dag.v1",
                "session_code": session["session_code"],
                "source_chunks": [
                    {
                        "chunk_code": chunk["chunk_code"],
                        "checksum_sha256": chunk["checksum_sha256"],
                    }
                    for chunk in chunks
                ],
                "upstream": upstream,
                "strategy_revision": spec["strategy_revision"],
            }
        )
        parameters = {
            "observations": observations,
            "upstream_run_codes": [item["analysis_run_code"] for item in upstream],
            "source_session_codes": [session["session_code"]],
            "_dag": {
                "auto_created": True,
                "pipeline_version": "live-observation-dag.v1",
            },
        }
        cursor.execute(
            """
            INSERT INTO live_analysis_runs (
                analysis_run_code, session_id, session_code, chunk_id, chunk_code,
                analysis_type, input_fingerprint, strategy_revision, parameters
            )
            VALUES (%s, %s, %s, NULL, NULL, 'template_aggregation', %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                self._next_code("analysis_run"),
                session["id"],
                session["session_code"],
                fingerprint,
                spec["strategy_revision"],
                Jsonb(parameters),
            ),
        )

    def list_analysis_runs(
        self,
        *,
        session_code: str | None,
        analysis_type: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        clauses = ["true"]
        params: list[Any] = []
        for column, value in (
            ("session_code", session_code),
            ("analysis_type", analysis_type),
            ("status", status),
        ):
            if value:
                clauses.append(f"{column} = %s")
                params.append(value)
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT * FROM live_analysis_runs WHERE {' AND '.join(clauses)} "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                tuple(params),
            )
            return [self._row(row) for row in cursor.fetchall()]

    def claim_analysis_run(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        return self._claim_work("live_analysis_runs", "analysis_run_code", worker_id, lease_seconds)

    def complete_analysis_run(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
        *,
        aggregation_spec: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        token = self._uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_analysis_runs
                SET status = 'succeeded', output_payload = %s, output_relative_path = %s,
                    output_checksum_sha256 = %s, invocation_evidence_ref = %s,
                    completed_at = now(), updated_at = now(),
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                WHERE analysis_run_code = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (
                    Jsonb(payload.get("output_payload") or {}),
                    payload.get("output_relative_path"),
                    payload.get("output_checksum_sha256"),
                    payload.get("invocation_evidence_ref"),
                    run_code,
                    worker_id,
                    token,
                ),
            )
            row = cursor.fetchone()
            if row is not None and aggregation_spec:
                session = self._session_by_code(cursor, row["session_code"])
                if session is not None:
                    self._enqueue_ready_template_aggregation(
                        cursor,
                        session,
                        aggregation_spec,
                    )
        self.connection.commit()
        return self._row(row) if row else None

    def fail_work(
        self,
        *,
        table: str,
        code_column: str,
        code: str,
        worker_id: str,
        lease_token: str,
        error_code: str,
        error_message: str,
        retryable: bool = False,
        retry_delay_seconds: int = 60,
    ) -> dict[str, Any] | None:
        allowed = {
            ("live_clip_jobs", "clip_job_code"),
            ("live_analysis_runs", "analysis_run_code"),
        }
        if (table, code_column) not in allowed:
            raise ValueError("unsupported work table")
        token = self._uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            if table == "live_analysis_runs":
                cursor.execute(
                    """
                    UPDATE live_analysis_runs
                    SET status = CASE
                            WHEN %s AND attempt_count < max_attempts THEN 'queued'
                            ELSE 'failed'
                        END,
                        error_code = %s, error_message = %s,
                        next_attempt_at = CASE
                            WHEN %s AND attempt_count < max_attempts
                            THEN now() + (%s * interval '1 second')
                            ELSE next_attempt_at
                        END,
                        completed_at = CASE
                            WHEN %s AND attempt_count < max_attempts THEN NULL
                            ELSE now()
                        END,
                        updated_at = now(), claimed_by = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE analysis_run_code = %s AND status = 'running' AND claimed_by = %s
                      AND lease_token = %s AND lease_expires_at > now()
                    RETURNING *
                    """,
                    (
                        retryable,
                        error_code,
                        error_message,
                        retryable,
                        retry_delay_seconds,
                        retryable,
                        code,
                        worker_id,
                        token,
                    ),
                )
            else:
                cursor.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'failed', error_code = %s, error_message = %s,
                        completed_at = now(), updated_at = now(), claimed_by = NULL,
                        lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE {code_column} = %s AND status = 'running' AND claimed_by = %s
                      AND lease_token = %s AND lease_expires_at > now()
                    RETURNING *
                    """,
                    (error_code, error_message, code, worker_id, token),
                )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row) if row else None

    def retry_analysis_run(
        self,
        run_code: str,
        worker_id: str,
        reason: str,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE live_analysis_runs
                SET status = 'queued', next_attempt_at = now(), completed_at = NULL,
                    retry_history = retry_history || jsonb_build_array(jsonb_build_object(
                        'requested_at', now(),
                        'requested_by', %s::text,
                        'reason', %s::text,
                        'previous_error_code', error_code,
                        'previous_error_message', error_message,
                        'attempt_count', attempt_count
                    )),
                    error_code = NULL, error_message = NULL, updated_at = now(),
                    claimed_by = NULL, lease_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL
                WHERE analysis_run_code = %s AND status = 'failed'
                  AND attempt_count < max_attempts
                RETURNING *
                """,
                (worker_id, reason, run_code),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row) if row else None

    def heartbeat_work(
        self,
        *,
        table: str,
        code_column: str,
        code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        allowed = {
            ("live_clip_jobs", "clip_job_code"),
            ("live_analysis_runs", "analysis_run_code"),
        }
        if (table, code_column) not in allowed:
            raise ValueError("unsupported work table")
        token = self._uuid(lease_token)
        if token is None:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE {table}
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE {code_column} = %s AND status = 'running' AND claimed_by = %s
                  AND lease_token = %s AND lease_expires_at > now()
                RETURNING *
                """,
                (lease_seconds, code, worker_id, token),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row) if row else None

    def create_room_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        template_code = self._next_code("room_template")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            target_id = None
            target_code = payload.get("source_target_code")
            if target_code:
                cursor.execute(
                    "SELECT id FROM live_watch_targets WHERE target_code = %s AND deleted_at IS NULL",
                    (target_code,),
                )
                target = cursor.fetchone()
                if target is None:
                    raise LiveObservationConflictError("source watch target does not exist")
                target_id = target["id"]
            cursor.execute(
                """
                INSERT INTO live_room_templates (
                    template_code, name, description, source_target_id, source_target_code, template_kind
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    template_code, payload["name"], payload.get("description"), target_id,
                    target_code, payload.get("template_kind", "layout_hypothesis"),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        result = self._template(row)
        result["revisions"] = []
        return result

    def list_room_templates(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT template.*, revision.revision_number AS published_revision_number,
                       revision.content_readiness AS published_content_readiness,
                       revision.layout_fidelity AS published_layout_fidelity,
                       revision.buildability AS published_buildability,
                       (
                           SELECT max(latest_revision.revision_number)
                           FROM live_room_template_revisions AS latest_revision
                           WHERE latest_revision.template_id = template.id
                       ) AS latest_revision_number,
                       publication.projection_ready,
                       coalesce(publication.manual_review_required, true) AS manual_review_required
                FROM live_room_templates AS template
                LEFT JOIN live_room_template_revisions AS revision
                  ON revision.id = template.published_revision_id
                LEFT JOIN live_room_template_publications AS publication
                  ON publication.revision_id = revision.id AND publication.retracted_at IS NULL
                WHERE template.archived_at IS NULL
                ORDER BY template.updated_at DESC, template.template_code DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [self._template(row) for row in cursor.fetchall()]

    def get_room_template(
        self, template_code: str, *, include_revisions: bool
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT template.*, revision.revision_number AS published_revision_number,
                       revision.content_readiness AS published_content_readiness,
                       revision.layout_fidelity AS published_layout_fidelity,
                       revision.buildability AS published_buildability,
                       (
                           SELECT max(latest_revision.revision_number)
                           FROM live_room_template_revisions AS latest_revision
                           WHERE latest_revision.template_id = template.id
                       ) AS latest_revision_number,
                       publication.projection_ready,
                       coalesce(publication.manual_review_required, true) AS manual_review_required
                FROM live_room_templates AS template
                LEFT JOIN live_room_template_revisions AS revision
                  ON revision.id = template.published_revision_id
                LEFT JOIN live_room_template_publications AS publication
                  ON publication.revision_id = revision.id AND publication.retracted_at IS NULL
                WHERE template.template_code = %s AND template.archived_at IS NULL
                """,
                (template_code,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            result = self._template(row)
            if include_revisions:
                cursor.execute(
                    """
                    SELECT * FROM live_room_template_revisions
                    WHERE template_id = %s ORDER BY revision_number DESC
                    """,
                    (row["id"],),
                )
                result["revisions"] = [self._revision(cursor, item) for item in cursor.fetchall()]
            return result

    def create_room_template_revision(
        self, template_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM live_room_templates WHERE template_code = %s AND archived_at IS NULL FOR UPDATE",
                (template_code,),
            )
            template = cursor.fetchone()
            if template is None:
                raise LiveObservationConflictError("room template does not exist")
            source_sessions = self._resolve_template_source_sessions(cursor, template, payload)
            first_session = source_sessions[0] if source_sessions else None
            cursor.execute(
                "SELECT coalesce(max(revision_number), 0) + 1 AS next_revision FROM live_room_template_revisions WHERE template_id = %s",
                (template["id"],),
            )
            revision_number = cursor.fetchone()["next_revision"]
            cursor.execute(
                """
                INSERT INTO live_room_template_revisions (
                    template_id, template_code, revision_number, source_session_id,
                    source_session_code, contract_version, canvas, scenes, components,
                    audio_policy, provenance, content_readiness, layout_fidelity,
                    buildability, content_strategy, layout_reference, confidence,
                    content_fingerprint, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    template["id"],
                    template_code,
                    revision_number,
                    first_session["id"] if first_session else None,
                    first_session["session_code"] if first_session else None,
                    payload.get("contract_version", "layout-hypothesis.v1"),
                    Jsonb(payload["canvas"]),
                    Jsonb(payload.get("scenes") or []),
                    Jsonb(payload.get("components") or []),
                    Jsonb(payload.get("audio_policy") or {}),
                    Jsonb(payload.get("provenance") or {}),
                    payload.get("content_readiness", "review_required"),
                    payload.get("layout_fidelity", "approximate"),
                    payload.get("buildability", "reference_only"),
                    Jsonb(payload.get("content_strategy") or {}),
                    Jsonb(payload.get("layout_reference") or {}),
                    payload["confidence"],
                    payload["content_fingerprint"],
                    payload.get("created_by"),
                ),
            )
            row = cursor.fetchone()
            self._insert_template_revision_source_sessions(cursor, row["id"], source_sessions)
            cursor.execute(
                """
                UPDATE live_room_templates
                SET status = 'draft', updated_at = now()
                WHERE id = %s
                """,
                (template["id"],),
            )
            result = self._revision(cursor, row)
        self.connection.commit()
        return result

    def publish_room_template_revision(
        self,
        template_code: str,
        revision_number: int,
        payload: dict[str, Any],
        projection: dict[str, Any],
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        publication_code = self._next_code("publication")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM live_room_templates WHERE template_code = %s AND archived_at IS NULL FOR UPDATE",
                (template_code,),
            )
            template = cursor.fetchone()
            if template is None:
                raise LiveObservationConflictError("room template does not exist")
            cursor.execute(
                "SELECT MAX(revision_number) AS latest_revision FROM live_room_template_revisions WHERE template_id = %s",
                (template["id"],),
            )
            latest_revision = cursor.fetchone()["latest_revision"]
            if latest_revision is None or int(latest_revision) != revision_number:
                raise LiveObservationConflictError("only the latest room template revision can be published")
            cursor.execute(
                """
                SELECT * FROM live_room_template_revisions
                WHERE template_id = %s AND revision_number = %s
                FOR UPDATE
                """,
                (template["id"], revision_number),
            )
            revision = cursor.fetchone()
            if revision is None or revision["status"] not in {"draft", "rejected"}:
                raise LiveObservationConflictError("room template revision is not publishable")
            cursor.execute(
                """
                UPDATE live_room_template_revisions
                SET status = 'superseded', updated_at = now()
                WHERE template_id = %s AND status = 'published'
                """,
                (template["id"],),
            )
            cursor.execute(
                """
                UPDATE live_room_template_revisions
                SET status = 'published', review_status = 'accepted', review_notes = %s,
                    reviewed_by = %s, reviewed_at = now(), published_at = now(), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (payload["review_notes"], payload["reviewed_by"], revision["id"]),
            )
            revision = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO live_room_template_publications (
                    publication_code, template_id, template_code, revision_id,
                    revision_number, projection_payload, projection_fingerprint,
                    projection_ready, manual_review_required, published_by, publication_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    publication_code,
                    template["id"],
                    template_code,
                    revision["id"],
                    revision_number,
                    Jsonb(projection),
                    projection["projection_fingerprint"],
                    projection["projection_ready"],
                    projection["manual_review_required"],
                    payload["published_by"],
                    payload.get("publication_reason"),
                ),
            )
            publication = cursor.fetchone()
            cursor.execute(
                """
                UPDATE live_room_templates
                SET status = 'published', published_revision_id = %s, updated_at = now()
                WHERE id = %s
                """,
                (revision["id"], template["id"]),
            )
        if commit:
            self.connection.commit()
        return self._projection(publication, template)

    def get_room_template_projection(self, template_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT publication.*, template.name AS template_name
                FROM live_room_template_publications AS publication
                JOIN live_room_templates AS template ON template.id = publication.template_id
                WHERE publication.template_code = %s AND publication.retracted_at IS NULL
                  AND template.published_revision_id = publication.revision_id
                ORDER BY publication.published_at DESC
                LIMIT 1
                """,
                (template_code,),
            )
            row = cursor.fetchone()
        return self._projection(row, None) if row else None

    def claim_retention_candidates(
        self,
        worker_id: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT chunk.id
                FROM live_capture_chunks AS chunk
                WHERE (
                    chunk.status = 'finalized'
                    OR (
                        chunk.status = 'delete_candidate'
                        AND (
                            chunk.delete_claim_expires_at IS NULL
                            OR chunk.delete_claim_expires_at <= now()
                        )
                    )
                  )
                  AND chunk.retention_expires_at <= now()
                  AND chunk.legal_hold = false
                  AND (chunk.pinned_until IS NULL OR chunk.pinned_until < now())
                  AND NOT EXISTS (
                      SELECT 1 FROM live_clip_jobs job
                      WHERE job.session_id = chunk.session_id AND job.status IN ('queued', 'running')
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM live_analysis_runs run
                      WHERE run.session_id = chunk.session_id AND run.status IN ('queued', 'running')
                  )
                ORDER BY chunk.retention_expires_at, chunk.part_index
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (limit,),
            )
            chunk_ids = [row["id"] for row in cursor.fetchall()]
            if chunk_ids:
                cursor.execute(
                    """
                    UPDATE live_capture_chunks
                    SET status = 'delete_candidate', delete_marked_at = coalesce(delete_marked_at, now()),
                        delete_claimed_by = %s, delete_claim_token = gen_random_uuid(),
                        delete_claim_expires_at = now() + (%s * interval '1 second'),
                        delete_heartbeat_at = now(), updated_at = now()
                    WHERE id = ANY(%s)
                    RETURNING id, chunk_code AS entity_code, relative_path, checksum_sha256,
                              delete_marked_at, delete_claimed_by AS claimed_by,
                              delete_claim_token AS claim_token,
                              delete_claim_expires_at AS claim_expires_at
                    """,
                    (worker_id, lease_seconds, chunk_ids),
                )
                for row in cursor.fetchall():
                    candidates.append({"entity_type": "capture_chunk", **self._row(row), "entity_id": str(row["id"])})
        self.connection.commit()
        for candidate in candidates:
            candidate.pop("id", None)
        return candidates

    def complete_retention(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        entity_type = payload["entity_type"]
        if entity_type != "capture_chunk":
            return None
        table, code_column = "live_capture_chunks", "chunk_code"
        entity_id = self._uuid(payload["entity_id"])
        attempt_id = self._uuid(payload["deletion_attempt_id"])
        claim_token = self._uuid(payload["claim_token"])
        worker_id = str(payload.get("worker_id") or "")
        if entity_id is None or attempt_id is None or claim_token is None or not worker_id:
            return None
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM live_retention_tombstones
                WHERE entity_type = %s AND entity_id = %s
                """,
                (entity_type, entity_id),
            )
            existing_tombstone = cursor.fetchone()
            if existing_tombstone is not None:
                self.connection.commit()
                if existing_tombstone["deletion_attempt_id"] == attempt_id:
                    return self._row(existing_tombstone)
                return None
            cursor.execute(
                f"""
                SELECT * FROM {table}
                WHERE id = %s AND status = 'delete_candidate' AND legal_hold = false
                  AND delete_claimed_by = %s AND delete_claim_token = %s
                  AND delete_claim_expires_at > now()
                FOR UPDATE
                """,
                (entity_id, worker_id, claim_token),
            )
            entity = cursor.fetchone()
            if entity is None:
                self.connection.rollback()
                return None
            tombstone = {
                "deletion_attempt_id": str(attempt_id),
                "reason": payload["deletion_reason"],
                "details": payload.get("details") or {},
            }
            cursor.execute(
                """
                INSERT INTO live_retention_tombstones (
                    entity_type, entity_id, entity_code, relative_path, checksum_sha256,
                    deletion_reason, deletion_attempt_id, marked_at, deleted_at, details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), %s)
                ON CONFLICT (entity_type, entity_id) DO NOTHING
                RETURNING *
                """,
                (
                    entity_type,
                    entity["id"],
                    entity[code_column],
                    entity["relative_path"],
                    entity.get("checksum_sha256"),
                    payload["deletion_reason"],
                    attempt_id,
                    entity["delete_marked_at"],
                    Jsonb(payload.get("details") or {}),
                ),
            )
            result = cursor.fetchone()
            if result is None:
                self.connection.rollback()
                return None
            cursor.execute(
                f"""
                UPDATE {table}
                SET status = 'deleted', deleted_at = now(), tombstone = %s,
                    delete_claimed_by = NULL, delete_claim_token = NULL,
                    delete_claim_expires_at = NULL, delete_heartbeat_at = NULL,
                    updated_at = now()
                WHERE id = %s
                """,
                (Jsonb(tombstone), entity["id"]),
            )
        self.connection.commit()
        return self._row(result)

    def _claim_work(
        self, table: str, code_column: str, worker_id: str, lease_seconds: int
    ) -> dict[str, Any] | None:
        allowed = {
            ("live_clip_jobs", "clip_job_code"),
            ("live_analysis_runs", "analysis_run_code"),
        }
        if (table, code_column) not in allowed:
            raise ValueError("unsupported work table")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            if table == "live_analysis_runs":
                cursor.execute(
                    """
                    UPDATE live_analysis_runs
                    SET status = 'failed', completed_at = now(), updated_at = now(),
                        error_code = coalesce(error_code, 'LEASE_ATTEMPTS_EXHAUSTED'),
                        error_message = coalesce(
                            error_message,
                            'Analysis lease expired after the maximum number of attempts'
                        ),
                        claimed_by = NULL, lease_token = NULL,
                        lease_expires_at = NULL, heartbeat_at = NULL
                    WHERE status = 'running' AND lease_expires_at <= now()
                      AND attempt_count >= max_attempts
                    """
                )
                cursor.execute(
                    """
                    WITH candidate AS (
                        SELECT id FROM live_analysis_runs
                        WHERE (
                            status = 'queued' AND next_attempt_at <= now()
                            OR status = 'running' AND lease_expires_at <= now()
                        )
                          AND attempt_count < max_attempts
                        ORDER BY next_attempt_at, created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE live_analysis_runs AS work
                    SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                        lease_expires_at = now() + (%s * interval '1 second'),
                        heartbeat_at = now(), started_at = coalesce(started_at, now()),
                        attempt_count = work.attempt_count + 1, updated_at = now()
                    FROM candidate
                    WHERE work.id = candidate.id
                    RETURNING work.*
                    """,
                    (worker_id, lease_seconds),
                )
            else:
                cursor.execute(
                    f"""
                    WITH candidate AS (
                        SELECT id FROM {table}
                        WHERE status = 'queued'
                           OR (status = 'running' AND lease_expires_at < now())
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE {table} AS work
                    SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                        lease_expires_at = now() + (%s * interval '1 second'),
                        heartbeat_at = now(), started_at = coalesce(started_at, now()), updated_at = now()
                    FROM candidate
                    WHERE work.id = candidate.id
                    RETURNING work.*
                    """,
                    (worker_id, lease_seconds),
                )
            row = cursor.fetchone()
        self.connection.commit()
        return self._row(row) if row else None

    def _next_code(self, object_type: str) -> str:
        prefix = self.CODE_PREFIXES[object_type]
        sequence_date = datetime.now(UTC).date()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO live_research_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = live_research_sequences.current_value + 1,
                              updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return f"{prefix}-{sequence_date:%Y%m%d}-{sequence:06d}"

    def _resolve_template_source_sessions(
        self, cursor: Any, template: dict[str, Any], payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        codes = list(
            dict.fromkeys(
                str(code).strip()
                for code in [payload.get("source_session_code"), *(payload.get("source_session_codes") or [])]
                if str(code or "").strip()
            )
        )
        contract_version = str(payload.get("contract_version") or "layout-hypothesis.v1")
        if contract_version == "content-strategy.v2" and not codes:
            raise LiveObservationConflictError("content-strategy templates require source capture sessions")
        if not codes:
            return []
        cursor.execute(
            """
            SELECT session.id, session.session_code, session.target_id, session.target_code, session.status
            FROM live_capture_sessions AS session
            WHERE session.session_code = ANY(%s)
            """,
            (codes,),
        )
        by_code = {row["session_code"]: row for row in cursor.fetchall()}
        missing = [code for code in codes if code not in by_code]
        if missing:
            raise LiveObservationConflictError(
                f"source capture sessions do not exist: {', '.join(missing)}"
            )
        sessions = [by_code[code] for code in codes]
        if contract_version != "content-strategy.v2":
            return sessions
        incomplete = [row["session_code"] for row in sessions if row["status"] != "completed"]
        if incomplete:
            raise LiveObservationConflictError(
                f"content-strategy source sessions must be completed: {', '.join(incomplete)}"
            )
        target_codes = {str(row["target_code"]) for row in sessions}
        if len(target_codes) != 1:
            raise LiveObservationConflictError(
                "CONTENT_STRATEGY_CROSS_ROOM_SOURCE: split source sessions into separate templates"
            )
        target = sessions[0]
        configured_target = template.get("source_target_code")
        if configured_target and configured_target != target["target_code"]:
            raise LiveObservationConflictError(
                "CONTENT_STRATEGY_SOURCE_TARGET_MISMATCH: template and source sessions must belong to one room"
            )
        if not configured_target:
            cursor.execute(
                """
                UPDATE live_room_templates
                SET source_target_id = %s, source_target_code = %s, updated_at = now()
                WHERE id = %s
                """,
                (target["target_id"], target["target_code"], template["id"]),
            )
            template["source_target_id"] = target["target_id"]
            template["source_target_code"] = target["target_code"]
        return sessions

    @staticmethod
    def _insert_template_revision_source_sessions(
        cursor: Any, revision_id: Any, sessions: list[dict[str, Any]]
    ) -> None:
        if not sessions:
            return
        cursor.executemany(
            """
            INSERT INTO live_room_template_revision_source_sessions (
                revision_id, session_id, session_code, target_id, target_code
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (revision_id, row["id"], row["session_code"], row["target_id"], row["target_code"])
                for row in sessions
            ],
        )

    def _revision(self, cursor: Any, row: dict[str, Any]) -> dict[str, Any]:
        result = self._row(row)
        cursor.execute(
            """
            SELECT session_code FROM live_room_template_revision_source_sessions
            WHERE revision_id = %s ORDER BY session_code
            """,
            (row["id"],),
        )
        source_session_codes = [str(item["session_code"]) for item in cursor.fetchall()]
        result["source_session_codes"] = source_session_codes
        if result.get("source_session_code") is None and source_session_codes:
            result["source_session_code"] = source_session_codes[0]
        return result

    @staticmethod
    def _session_by_code(
        cursor: Any, session_code: str, *, lock: bool = False
    ) -> dict[str, Any] | None:
        cursor.execute(
            f"SELECT * FROM live_capture_sessions WHERE session_code = %s{' FOR UPDATE' if lock else ''}",
            (session_code,),
        )
        return cursor.fetchone()

    @staticmethod
    def _uuid(value: Any) -> UUID | None:
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _fingerprint(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _row(cls, row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for key, value in tuple(converted.items()):
            if isinstance(value, UUID):
                converted[key] = str(value)
        return converted

    @classmethod
    def _target(
        cls, row: dict[str, Any], *, include_claim: bool = False
    ) -> dict[str, Any]:
        converted = cls._row(row)
        converted["lease_active"] = bool(converted.get("lease_active"))
        if not include_claim:
            for key in ("claimed_by", "claim_token", "lease_version", "lease_expires_at", "heartbeat_at"):
                converted.pop(key, None)
        return converted

    @classmethod
    def _session(cls, row: dict[str, Any]) -> dict[str, Any]:
        converted = cls._row(row)
        converted["chunk_count"] = int(converted.get("chunk_count") or 0)
        converted["event_count"] = int(converted.get("event_count") or 0)
        return converted

    @classmethod
    def _template(cls, row: dict[str, Any]) -> dict[str, Any]:
        converted = cls._row(row)
        converted["projection_ready"] = bool(converted.get("projection_ready"))
        converted["manual_review_required"] = bool(
            converted.get("manual_review_required", True)
        )
        return converted

    @classmethod
    def _projection(
        cls, publication: dict[str, Any], template: dict[str, Any] | None
    ) -> dict[str, Any]:
        payload = dict(publication.get("projection_payload") or {})
        payload.update(
            {
                "template_code": publication["template_code"],
                "template_name": publication.get("template_name")
                or (template or {}).get("name")
                or payload.get("template_name"),
                "revision_number": int(publication["revision_number"]),
                "publication_code": publication["publication_code"],
                "projection_contract": publication["projection_contract"],
                "projection_fingerprint": publication["projection_fingerprint"],
                "projection_ready": bool(publication["projection_ready"]),
                "manual_review_required": bool(publication["manual_review_required"]),
                "published_at": publication["published_at"],
            }
        )
        return payload
