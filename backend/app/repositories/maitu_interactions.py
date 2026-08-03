from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class MaituInteractionConflictError(RuntimeError):
    pass


class MaituInteractionLeaseError(RuntimeError):
    pass


class MaituAccountMismatchError(MaituInteractionConflictError):
    pass


class MaituInteractionsRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    @staticmethod
    def _code(prefix: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"{prefix}-{stamp}-{uuid4().hex[:12].upper()}"

    @classmethod
    def _serialize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls._serialize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._serialize(item) for item in value]
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, time):
            return value.isoformat(timespec="minutes")
        return value

    @staticmethod
    def _next_daily_sync(now: datetime, timezone_name: str, daily_sync_time: time) -> datetime:
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone)
        candidate = datetime.combine(local_now.date(), daily_sync_time, tzinfo=zone)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    def ensure_source(self) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_interaction_sources (source_code, source_system, next_sync_at)
                VALUES ('maitu-primary', 'maitu', now())
                ON CONFLICT (source_code) DO UPDATE SET source_code = EXCLUDED.source_code
                RETURNING *
                """
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def get_source(self) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM maitu_interaction_sources WHERE source_code = 'maitu-primary'"
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def ensure_due_sync_job(self, *, now: datetime | None = None) -> dict[str, Any] | None:
        current = now or datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('maitu-interaction-sync-scheduler-v1'))")
            cursor.execute(
                """
                INSERT INTO maitu_interaction_sources (source_code, source_system, next_sync_at)
                VALUES ('maitu-primary', 'maitu', %s)
                ON CONFLICT (source_code) DO NOTHING
                """,
                (current,),
            )
            cursor.execute(
                "SELECT * FROM maitu_interaction_sources WHERE source_code = 'maitu-primary' FOR UPDATE"
            )
            source = cursor.fetchone()
            cursor.execute(
                """
                SELECT * FROM maitu_interaction_sync_jobs
                WHERE source_id = %s AND status IN ('queued', 'running', 'waiting_login')
                ORDER BY created_at LIMIT 1
                """,
                (source["id"],),
            )
            active = cursor.fetchone()
            if active is not None:
                self.connection.commit()
                return self._serialize(active)

            mode: str | None = None
            idempotency_key: str | None = None
            if source["last_full_sync_at"] is None:
                mode = "full"
                idempotency_key = f"{source['source_code']}:initial-full"
            elif source["next_sync_at"] is None or source["next_sync_at"] <= current:
                mode = "incremental"
                local_day = current.astimezone(ZoneInfo(source["timezone"])).date().isoformat()
                idempotency_key = f"{source['source_code']}:daily:{local_day}"
            if mode is None:
                self.connection.commit()
                return None

            cursor.execute(
                "SELECT * FROM maitu_interaction_sync_jobs WHERE idempotency_key = %s FOR UPDATE",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.commit()
                return self._serialize(existing)

            run_code = self._code("MT-INT-SYNC")
            cursor.execute(
                """
                INSERT INTO maitu_interaction_sync_jobs (
                    run_code, source_id, sync_mode, status, idempotency_key,
                    requested_by, scheduled_for
                ) VALUES (%s, %s, %s, 'queued', %s, 'system-scheduler', %s)
                RETURNING *
                """,
                (run_code, source["id"], mode, idempotency_key, current),
            )
            job = cursor.fetchone()
            if mode == "incremental":
                next_sync = self._next_daily_sync(
                    current,
                    source["timezone"],
                    source["daily_sync_time"],
                )
                cursor.execute(
                    "UPDATE maitu_interaction_sources SET next_sync_at = %s, updated_at = now() WHERE id = %s",
                    (next_sync, source["id"]),
                )
        self.connection.commit()
        return self._serialize(job)

    def create_sync_run(
        self,
        *,
        sync_mode: str,
        target_external_session_id: int | None,
        requested_by: str,
    ) -> dict[str, Any]:
        source = self.get_source() or self.ensure_source()
        run_code = self._code("MT-INT-SYNC")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_interaction_sync_jobs (
                    run_code, source_id, sync_mode, target_external_session_id,
                    status, requested_by, scheduled_for
                ) VALUES (%s, %s, %s, %s, 'queued', %s, now())
                RETURNING *
                """,
                (
                    run_code,
                    source["id"],
                    sync_mode,
                    target_external_session_id,
                    requested_by,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def claim_next_sync_job(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        self.ensure_due_sync_job()
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT job.*
                FROM maitu_interaction_sync_jobs AS job
                WHERE (
                    job.status IN ('queued', 'waiting_login')
                    AND (job.retry_after IS NULL OR job.retry_after <= now())
                ) OR (
                    job.status = 'running' AND job.lease_expires_at < now()
                )
                ORDER BY
                    CASE WHEN job.status = 'running' THEN 0 ELSE 1 END,
                    job.created_at
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
                UPDATE maitu_interaction_sync_jobs
                SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                    lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), retry_after = NULL, attempt = attempt + 1,
                    started_at = COALESCE(started_at, now()), completed_at = NULL,
                    error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, lease_seconds, candidate["id"]),
            )
            claimed = cursor.fetchone()
            cursor.execute(
                "SELECT * FROM maitu_interaction_sources WHERE id = %s",
                (claimed["source_id"],),
            )
            claimed["source"] = cursor.fetchone()
        self.connection.commit()
        return self._serialize(claimed)

    def _lock_sync_job(
        self,
        cursor: Any,
        run_code: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        try:
            token = UUID(lease_token)
        except ValueError as exc:
            raise MaituInteractionLeaseError("Sync lease token is invalid") from exc
        cursor.execute(
            """
            SELECT * FROM maitu_interaction_sync_jobs
            WHERE run_code = %s AND status = 'running' AND claimed_by = %s
              AND lease_token = %s AND lease_expires_at > now()
            FOR UPDATE
            """,
            (run_code, worker_id, token),
        )
        job = cursor.fetchone()
        if job is None:
            raise MaituInteractionLeaseError("Sync lease is not active")
        return job

    def heartbeat_sync_job(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_sync_job(cursor, run_code, worker_id, lease_token)
            cursor.execute(
                """
                UPDATE maitu_interaction_sync_jobs
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (lease_seconds, job["id"]),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def write_sync_catalog(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_sync_job(cursor, run_code, worker_id, lease_token)
            cursor.execute(
                "SELECT * FROM maitu_interaction_sources WHERE id = %s FOR UPDATE",
                (job["source_id"],),
            )
            source = cursor.fetchone()
            external_account_id = int(payload["external_account_id"])
            if (
                source["external_account_id"] is not None
                and source["external_account_id"] != external_account_id
            ):
                cursor.execute(
                    """
                    UPDATE maitu_interaction_sources
                    SET status = 'account_mismatch', last_error_code = 'ACCOUNT_MISMATCH',
                        last_error_message = 'The visible Maitu account differs from the bound account.',
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (source["id"],),
                )
                self.connection.commit()
                raise MaituAccountMismatchError("The visible Maitu account differs from the bound account")

            cursor.execute(
                """
                UPDATE maitu_interaction_sources
                SET external_account_id = COALESCE(external_account_id, %s),
                    account_name = %s, status = 'active', retry_after = NULL,
                    last_error_code = NULL, last_error_message = NULL, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (external_account_id, payload.get("account_name"), source["id"]),
            )
            source = cursor.fetchone()
            cursor.execute(
                "UPDATE maitu_interaction_platforms SET is_available = FALSE, updated_at = now() WHERE source_id = %s",
                (source["id"],),
            )
            platform_ids: dict[int, UUID] = {}
            for platform in payload.get("platforms") or []:
                cursor.execute(
                    """
                    INSERT INTO maitu_interaction_platforms (
                        source_id, external_platform_id, platform_code, platform_name,
                        is_available, first_seen_at, last_seen_at
                    ) VALUES (%s, %s, %s, %s, TRUE, now(), now())
                    ON CONFLICT (source_id, external_platform_id) DO UPDATE SET
                        platform_code = EXCLUDED.platform_code,
                        platform_name = EXCLUDED.platform_name,
                        is_available = TRUE, last_seen_at = now(), updated_at = now()
                    RETURNING id
                    """,
                    (
                        source["id"],
                        platform["external_platform_id"],
                        platform["platform_code"],
                        platform["platform_name"],
                    ),
                )
                platform_ids[int(platform["external_platform_id"])] = cursor.fetchone()["id"]

            seen_session_ids: list[int] = []
            for session in payload.get("sessions") or []:
                external_platform_id = int(session["external_platform_id"])
                platform_id = platform_ids.get(external_platform_id)
                if platform_id is None:
                    raise MaituInteractionConflictError(
                        f"Session references unavailable platform {external_platform_id}"
                    )
                seen_session_ids.append(int(session["external_session_id"]))
                cursor.execute(
                    """
                    INSERT INTO maitu_live_sessions (
                        source_id, platform_id, external_session_id, external_live_room_id,
                        platform_live_id, title, live_room_type, source_status,
                        started_at, ended_at, duration_seconds, source_created_at,
                        source_updated_at, source_payload, source_fingerprint,
                        first_seen_at, last_seen_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        now(), now()
                    )
                    ON CONFLICT (source_id, external_session_id) DO UPDATE SET
                        platform_id = EXCLUDED.platform_id,
                        external_live_room_id = EXCLUDED.external_live_room_id,
                        platform_live_id = EXCLUDED.platform_live_id,
                        title = EXCLUDED.title,
                        live_room_type = EXCLUDED.live_room_type,
                        source_status = EXCLUDED.source_status,
                        started_at = EXCLUDED.started_at,
                        ended_at = EXCLUDED.ended_at,
                        duration_seconds = EXCLUDED.duration_seconds,
                        source_created_at = EXCLUDED.source_created_at,
                        source_updated_at = EXCLUDED.source_updated_at,
                        source_payload = EXCLUDED.source_payload,
                        is_sync_complete = CASE
                            WHEN maitu_live_sessions.source_fingerprint <> EXCLUDED.source_fingerprint THEN FALSE
                            ELSE maitu_live_sessions.is_sync_complete
                        END,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        last_seen_at = now(), updated_at = now()
                    """,
                    (
                        source["id"],
                        platform_id,
                        session["external_session_id"],
                        session["external_live_room_id"],
                        session.get("platform_live_id"),
                        session["title"],
                        session.get("live_room_type"),
                        session.get("source_status", 2),
                        session["started_at"],
                        session["ended_at"],
                        session.get("duration_seconds", 0),
                        session.get("source_created_at"),
                        session.get("source_updated_at"),
                        Jsonb(session.get("source_payload") or {}),
                        session["source_fingerprint"],
                    ),
                )

            targets: list[dict[str, Any]] = []
            if seen_session_ids:
                target_clause = "TRUE"
                params: list[Any] = [source["id"], seen_session_ids]
                if job["sync_mode"] == "incremental":
                    target_clause = "(NOT session.is_sync_complete OR session.ended_at >= now() - (%s * interval '1 day'))"
                    params.append(source["rescan_days"])
                elif job["sync_mode"] == "session":
                    target_clause = "session.external_session_id = %s"
                    params.append(job["target_external_session_id"])
                cursor.execute(
                    f"""
                    SELECT session.*, platform.external_platform_id
                    FROM maitu_live_sessions AS session
                    JOIN maitu_interaction_platforms AS platform ON platform.id = session.platform_id
                    WHERE session.source_id = %s
                      AND session.external_session_id = ANY(%s)
                      AND {target_clause}
                    ORDER BY session.started_at, session.external_session_id
                    """,
                    tuple(params),
                )
                for row in cursor.fetchall():
                    targets.append(
                        {
                            "external_session_id": row["external_session_id"],
                            "external_live_room_id": row["external_live_room_id"],
                            "external_platform_id": row["external_platform_id"],
                            "platform_live_id": row["platform_live_id"],
                            "title": row["title"],
                            "live_room_type": row["live_room_type"],
                            "source_status": row["source_status"],
                            "started_at": row["started_at"],
                            "ended_at": row["ended_at"],
                            "duration_seconds": row["duration_seconds"],
                            "source_created_at": row["source_created_at"],
                            "source_updated_at": row["source_updated_at"],
                            "source_payload": row["source_payload"],
                            "source_fingerprint": row["source_fingerprint"],
                        }
                    )
        self.connection.commit()
        return self._serialize(
            {
                "source_code": source["source_code"],
                "session_count": len(seen_session_ids),
                "sessions_to_sync": targets,
            }
        )

    def write_interaction_batch(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_sync_job(cursor, run_code, worker_id, lease_token)
            cursor.execute(
                """
                SELECT * FROM maitu_live_sessions
                WHERE source_id = %s AND external_session_id = %s
                FOR UPDATE
                """,
                (job["source_id"], payload["external_session_id"]),
            )
            session = cursor.fetchone()
            if session is None:
                raise MaituInteractionConflictError("Interaction batch references an unknown session")
            for item in payload.get("items") or []:
                cursor.execute(
                    """
                    INSERT INTO maitu_live_interactions (
                        source_id, session_id, external_interaction_id, live_room_id,
                        platform, platform_live_id, request_id, interaction_type,
                        content, normalized_content, is_arrival, publisher_name,
                        publisher_role, item_id, published_at, digital_reply_type,
                        digital_reply_status, digital_reply_content, digital_replied_at,
                        bullet_reply_type, bullet_reply_status, bullet_reply_content,
                        bullet_replied_at, reply_decision_code, bullet_reply_decision_code,
                        source_created_at, source_updated_at, source_payload,
                        source_fingerprint, analysis_input_fingerprint, last_seen_run_code,
                        first_seen_at, last_seen_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        now(), now()
                    )
                    ON CONFLICT (source_id, session_id, external_interaction_id) DO UPDATE SET
                        live_room_id = EXCLUDED.live_room_id,
                        platform = EXCLUDED.platform,
                        platform_live_id = EXCLUDED.platform_live_id,
                        request_id = EXCLUDED.request_id,
                        interaction_type = EXCLUDED.interaction_type,
                        content = EXCLUDED.content,
                        normalized_content = EXCLUDED.normalized_content,
                        is_arrival = EXCLUDED.is_arrival,
                        publisher_name = EXCLUDED.publisher_name,
                        publisher_role = EXCLUDED.publisher_role,
                        item_id = EXCLUDED.item_id,
                        published_at = EXCLUDED.published_at,
                        digital_reply_type = EXCLUDED.digital_reply_type,
                        digital_reply_status = EXCLUDED.digital_reply_status,
                        digital_reply_content = EXCLUDED.digital_reply_content,
                        digital_replied_at = EXCLUDED.digital_replied_at,
                        bullet_reply_type = EXCLUDED.bullet_reply_type,
                        bullet_reply_status = EXCLUDED.bullet_reply_status,
                        bullet_reply_content = EXCLUDED.bullet_reply_content,
                        bullet_replied_at = EXCLUDED.bullet_replied_at,
                        reply_decision_code = EXCLUDED.reply_decision_code,
                        bullet_reply_decision_code = EXCLUDED.bullet_reply_decision_code,
                        source_created_at = EXCLUDED.source_created_at,
                        source_updated_at = EXCLUDED.source_updated_at,
                        source_payload = EXCLUDED.source_payload,
                        source_fingerprint = EXCLUDED.source_fingerprint,
                        analysis_input_fingerprint = EXCLUDED.analysis_input_fingerprint,
                        last_seen_run_code = EXCLUDED.last_seen_run_code,
                        last_seen_at = now(), updated_at = now()
                    """,
                    (
                        job["source_id"],
                        session["id"],
                        item["external_interaction_id"],
                        item["live_room_id"],
                        item.get("platform"),
                        item.get("platform_live_id"),
                        item.get("request_id"),
                        item.get("interaction_type", 0),
                        item.get("content", ""),
                        item["normalized_content"],
                        item["is_arrival"],
                        item.get("publisher_name"),
                        item.get("publisher_role"),
                        item.get("item_id"),
                        item.get("published_at"),
                        item.get("digital_reply_type"),
                        item.get("digital_reply_status"),
                        item.get("digital_reply_content"),
                        item.get("digital_replied_at"),
                        item.get("bullet_reply_type"),
                        item.get("bullet_reply_status"),
                        item.get("bullet_reply_content"),
                        item.get("bullet_replied_at"),
                        item.get("reply_decision_code"),
                        item.get("bullet_reply_decision_code"),
                        item.get("source_created_at"),
                        item.get("source_updated_at"),
                        Jsonb(item.get("source_payload") or {}),
                        item["source_fingerprint"],
                        item["analysis_input_fingerprint"],
                        run_code,
                    ),
                )

            seen_count = None
            stored_count = None
            if payload.get("final_page"):
                cursor.execute(
                    """
                    SELECT
                        count(*) FILTER (WHERE last_seen_run_code = %s)::integer AS seen_count,
                        count(*)::integer AS stored_count
                    FROM maitu_live_interactions WHERE session_id = %s
                    """,
                    (run_code, session["id"]),
                )
                counts = cursor.fetchone()
                seen_count = counts["seen_count"]
                stored_count = counts["stored_count"]
                cursor.execute(
                    """
                    UPDATE maitu_live_sessions
                    SET source_interaction_count = %s, stored_interaction_count = %s,
                        is_sync_complete = %s, last_interaction_sync_at = now(), updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        payload["source_total"],
                        stored_count,
                        seen_count == payload["source_total"],
                        session["id"],
                    ),
                )
        self.connection.commit()
        return {
            "accepted_count": len(payload.get("items") or []),
            "seen_count": seen_count,
            "stored_count": stored_count,
            "source_total": payload["source_total"],
        }

    def complete_sync_job(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        *,
        summary: dict[str, Any],
        partial: bool,
    ) -> dict[str, Any]:
        current = datetime.now(UTC)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_sync_job(cursor, run_code, worker_id, lease_token)
            cursor.execute(
                "SELECT * FROM maitu_interaction_sources WHERE id = %s FOR UPDATE",
                (job["source_id"],),
            )
            source = cursor.fetchone()
            if not partial:
                if job["sync_mode"] == "session":
                    target_sql = "source_id = %s AND external_session_id = %s"
                    target_params = (job["source_id"], job["target_external_session_id"])
                elif job["sync_mode"] == "incremental":
                    target_sql = "source_id = %s AND (NOT is_sync_complete OR ended_at >= now() - (%s * interval '1 day'))"
                    target_params = (job["source_id"], source["rescan_days"])
                else:
                    target_sql = "source_id = %s"
                    target_params = (job["source_id"],)
                cursor.execute(
                    f"""
                    SELECT count(*)::integer AS target_count,
                           count(*) FILTER (WHERE NOT is_sync_complete)::integer AS incomplete_count
                    FROM maitu_live_sessions WHERE {target_sql}
                    """,
                    target_params,
                )
                completion = cursor.fetchone()
                if job["sync_mode"] == "session" and completion["target_count"] != 1:
                    raise MaituInteractionConflictError("Session sync target is not present in the Maitu catalog")
                if completion["incomplete_count"]:
                    raise MaituInteractionConflictError(
                        f"Cannot complete sync while {completion['incomplete_count']} target sessions are incomplete"
                    )
            next_sync = source["next_sync_at"]
            if next_sync is None or next_sync <= current:
                next_sync = self._next_daily_sync(
                    current,
                    source["timezone"],
                    source["daily_sync_time"],
                )
            status = "partial" if partial else "succeeded"
            cursor.execute(
                """
                UPDATE maitu_interaction_sync_jobs
                SET status = %s, result_summary = %s, claimed_by = NULL,
                    lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = NULL, error_message = NULL, completed_at = now(), updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (status, Jsonb(summary), job["id"]),
            )
            completed = cursor.fetchone()
            full_at = current if job["sync_mode"] == "full" and not partial else source["last_full_sync_at"]
            incremental_at = (
                current
                if job["sync_mode"] in {"incremental", "session"} and not partial
                else source["last_incremental_sync_at"]
            )
            cursor.execute(
                """
                UPDATE maitu_interaction_sources
                SET status = 'active', last_full_sync_at = %s,
                    last_incremental_sync_at = %s, next_sync_at = %s,
                    retry_after = NULL, last_error_code = NULL,
                    last_error_message = NULL, updated_at = now()
                WHERE id = %s
                """,
                (full_at, incremental_at, next_sync, source["id"]),
            )
        self.connection.commit()
        return self._serialize(completed)

    def fail_sync_job(
        self,
        run_code: str,
        worker_id: str,
        lease_token: str,
        *,
        error_code: str,
        error_message: str,
        retry_kind: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_sync_job(cursor, run_code, worker_id, lease_token)
            if retry_kind == "login":
                job_status = "waiting_login"
                source_status = "waiting_login"
                retry_after = datetime.now(UTC) + timedelta(minutes=30)
            elif retry_kind == "network" and job["attempt"] < 5:
                job_status = "queued"
                source_status = "error"
                retry_after = datetime.now(UTC) + timedelta(minutes=min(30, 2 ** job["attempt"]))
            elif retry_kind == "account":
                job_status = "failed"
                source_status = "account_mismatch"
                retry_after = None
            else:
                job_status = "failed"
                source_status = "error"
                retry_after = None
            cursor.execute(
                """
                UPDATE maitu_interaction_sync_jobs
                SET status = %s, retry_after = %s, error_code = %s, error_message = %s,
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = CASE WHEN %s = 'failed' THEN now() ELSE NULL END,
                    updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (
                    job_status,
                    retry_after,
                    error_code,
                    error_message,
                    job_status,
                    job["id"],
                ),
            )
            failed = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_interaction_sources
                SET status = %s, retry_after = %s, last_error_code = %s,
                    last_error_message = %s, updated_at = now()
                WHERE id = %s
                """,
                (source_status, retry_after, error_code, error_message, job["source_id"]),
            )
        self.connection.commit()
        return self._serialize(failed)

    def list_sync_runs(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM maitu_interaction_sync_jobs
                ORDER BY created_at DESC, run_code DESC LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def list_platforms(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT platform.external_platform_id, platform.platform_code,
                       platform.platform_name, platform.is_available,
                       count(DISTINCT session.id)::integer AS session_count,
                       count(interaction.id)::integer AS interaction_count,
                       count(interaction.id) FILTER (WHERE interaction.is_arrival)::integer AS arrival_count,
                       count(interaction.id) FILTER (WHERE NOT interaction.is_arrival)::integer AS effective_count,
                       max(session.started_at) AS last_session_at
                FROM maitu_interaction_platforms AS platform
                LEFT JOIN maitu_live_sessions AS session ON session.platform_id = platform.id
                LEFT JOIN maitu_live_interactions AS interaction ON interaction.session_id = session.id
                GROUP BY platform.id
                ORDER BY platform.external_platform_id
                """
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def list_sessions(
        self,
        *,
        platform_id: int | None,
        search: str | None,
        limit: int,
        offset: int,
        external_session_id: int | None = None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if external_session_id is not None:
            clauses.append("session.external_session_id = %s")
            params.append(external_session_id)
        if platform_id is not None:
            clauses.append("platform.external_platform_id = %s")
            params.append(platform_id)
        if search:
            clauses.append(
                "(session.title ILIKE %s OR session.platform_live_id ILIKE %s "
                "OR session.external_session_id::text = %s)"
            )
            pattern = f"%{search}%"
            params.extend((pattern, pattern, search))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT count(*)::integer AS total
                FROM maitu_live_sessions AS session
                JOIN maitu_interaction_platforms AS platform ON platform.id = session.platform_id
                {where}
                """,
                tuple(params),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT session.id, session.external_session_id,
                       session.external_live_room_id, platform.external_platform_id,
                       platform.platform_code, platform.platform_name,
                       session.platform_live_id, session.title, session.live_room_type,
                       session.started_at, session.ended_at, session.duration_seconds,
                       session.source_interaction_count, session.stored_interaction_count,
                       session.is_sync_complete, session.last_interaction_sync_at,
                       count(interaction.id) FILTER (WHERE interaction.is_arrival)::integer AS arrival_count,
                       count(interaction.id) FILTER (WHERE NOT interaction.is_arrival)::integer AS effective_count,
                       count(interaction.id) FILTER (
                           WHERE NOT interaction.is_arrival
                             AND NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NOT NULL
                       )::integer AS answered_count,
                       count(interaction.id) FILTER (
                           WHERE NOT interaction.is_arrival
                             AND NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NULL
                       )::integer AS unanswered_count
                FROM maitu_live_sessions AS session
                JOIN maitu_interaction_platforms AS platform ON platform.id = session.platform_id
                LEFT JOIN maitu_live_interactions AS interaction ON interaction.session_id = session.id
                {where}
                GROUP BY session.id, platform.id
                ORDER BY session.started_at DESC, session.external_session_id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([*params, limit, offset]),
            )
            rows = cursor.fetchall()
        return self._serialize({"items": rows, "total": total, "limit": limit, "offset": offset})

    def get_session(self, external_session_id: int) -> dict[str, Any] | None:
        result = self.list_sessions(
            platform_id=None,
            search=None,
            limit=1,
            offset=0,
            external_session_id=external_session_id,
        )
        return next(
            (item for item in result["items"] if item["external_session_id"] == external_session_id),
            None,
        )

    @staticmethod
    def _analysis_join() -> str:
        return """
            LEFT JOIN LATERAL (
                SELECT result.* FROM maitu_interaction_analysis_results AS result
                WHERE result.interaction_id = interaction.id
                  AND result.analyzer_version = %s
                  AND result.input_fingerprint = interaction.analysis_input_fingerprint
                ORDER BY result.created_at DESC LIMIT 1
            ) AS analysis ON TRUE
        """

    def list_interactions(
        self,
        *,
        analyzer_version: str,
        external_session_id: int | None,
        platform_id: int | None,
        include_arrivals: bool,
        answered: bool | None,
        interaction_form: str | None,
        business_intent: str | None,
        overall_grade: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if external_session_id is not None:
            clauses.append("session.external_session_id = %s")
            params.append(external_session_id)
        if platform_id is not None:
            clauses.append("platform.external_platform_id = %s")
            params.append(platform_id)
        if not include_arrivals:
            clauses.append("NOT interaction.is_arrival")
        if answered is not None:
            expression = "NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NOT NULL"
            clauses.append(expression if answered else f"NOT ({expression})")
        if interaction_form:
            clauses.append("analysis.interaction_form = %s")
            params.append(interaction_form)
        if business_intent:
            clauses.append("analysis.business_intent = %s")
            params.append(business_intent)
        if overall_grade:
            clauses.append("analysis.overall_grade = %s")
            params.append(overall_grade)
        if search:
            clauses.append(
                "(interaction.content ILIKE %s OR interaction.publisher_name ILIKE %s OR interaction.digital_reply_content ILIKE %s)"
            )
            pattern = f"%{search}%"
            params.extend((pattern, pattern, pattern))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        analysis_join = self._analysis_join()
        base = f"""
            FROM maitu_live_interactions AS interaction
            JOIN maitu_live_sessions AS session ON session.id = interaction.session_id
            JOIN maitu_interaction_platforms AS platform ON platform.id = session.platform_id
            {analysis_join}
            {where}
        """
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT count(*)::integer AS total {base}",
                tuple([analyzer_version, *params]),
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"""
                SELECT interaction.id, interaction.external_interaction_id,
                       session.external_session_id, session.title AS session_title,
                       platform.external_platform_id, platform.platform_name,
                       interaction.interaction_type, interaction.content,
                       interaction.normalized_content, interaction.is_arrival,
                       interaction.publisher_name, interaction.publisher_role,
                       interaction.item_id, interaction.published_at,
                       interaction.digital_reply_content, interaction.digital_replied_at,
                       interaction.bullet_reply_content, interaction.bullet_replied_at,
                       NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NOT NULL AS is_answered,
                       CASE
                           WHEN interaction.is_arrival THEN 'excluded'
                           WHEN analysis.id IS NOT NULL THEN 'succeeded'
                           WHEN EXISTS (
                               SELECT 1 FROM maitu_interaction_analysis_jobs AS job
                               WHERE job.interaction_id = interaction.id
                                 AND job.analyzer_version = %s
                                 AND job.input_fingerprint = interaction.analysis_input_fingerprint
                                 AND job.status = 'failed'
                           ) THEN 'failed'
                           ELSE 'pending'
                       END AS analysis_status,
                       CASE WHEN analysis.id IS NULL THEN NULL ELSE jsonb_build_object(
                           'analyzer_version', analysis.analyzer_version,
                           'interaction_form', analysis.interaction_form,
                           'business_intent', analysis.business_intent,
                           'relevance_grade', analysis.relevance_grade,
                           'completeness_grade', analysis.completeness_grade,
                           'resolution_grade', analysis.resolution_grade,
                           'overall_grade', analysis.overall_grade,
                           'confidence', analysis.confidence,
                           'reason', analysis.reason,
                           'created_at', analysis.created_at
                       ) END AS analysis
                {base}
                ORDER BY interaction.published_at DESC NULLS LAST, interaction.id DESC
                LIMIT %s OFFSET %s
                """,
                tuple([analyzer_version, analyzer_version, *params, limit, offset]),
            )
            rows = cursor.fetchall()
        return self._serialize({"items": rows, "total": total, "limit": limit, "offset": offset})

    def analysis_summary(self, analyzer_version: str) -> dict[str, Any]:
        join = self._analysis_join()
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT count(*)::integer AS total,
                       count(analysis.id)::integer AS analyzed,
                       (count(*) - count(analysis.id))::integer AS pending,
                       count(*) FILTER (
                           WHERE NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NOT NULL
                       )::integer AS answered,
                       count(*) FILTER (
                           WHERE NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NULL
                       )::integer AS unanswered
                FROM maitu_live_interactions AS interaction
                {join}
                WHERE NOT interaction.is_arrival
                """,
                (analyzer_version,),
            )
            summary = cursor.fetchone()
            dimensions: dict[str, dict[str, int]] = {}
            for name, column in (
                ("forms", "interaction_form"),
                ("intents", "business_intent"),
                ("grades", "overall_grade"),
            ):
                cursor.execute(
                    f"""
                    SELECT analysis.{column} AS key, count(*)::integer AS count
                    FROM maitu_live_interactions AS interaction
                    {join}
                    WHERE NOT interaction.is_arrival AND analysis.id IS NOT NULL
                    GROUP BY analysis.{column}
                    """,
                    (analyzer_version,),
                )
                dimensions[name] = {row["key"]: row["count"] for row in cursor.fetchall()}
        return self._serialize({**summary, **dimensions})

    def synchronize_analysis_jobs(self, analyzer_version: str, strategy_revision: str) -> int:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO maitu_interaction_analysis_jobs (
                    analysis_code, interaction_id, analyzer_version,
                    strategy_revision, input_fingerprint, status
                )
                SELECT 'MT-INT-AN-' || upper(replace(gen_random_uuid()::text, '-', '')),
                       interaction.id, %s, %s, interaction.analysis_input_fingerprint, 'queued'
                FROM maitu_live_interactions AS interaction
                WHERE NOT interaction.is_arrival
                  AND NOT EXISTS (
                      SELECT 1 FROM maitu_interaction_analysis_results AS result
                      WHERE result.interaction_id = interaction.id
                        AND result.analyzer_version = %s
                        AND result.input_fingerprint = interaction.analysis_input_fingerprint
                  )
                ON CONFLICT (interaction_id, analyzer_version, input_fingerprint) DO NOTHING
                """,
                (analyzer_version, strategy_revision, analyzer_version),
            )
            inserted = cursor.rowcount
            cursor.execute(
                """
                UPDATE maitu_interaction_analysis_jobs
                SET status = 'queued', retry_after = NULL, error_code = NULL,
                    error_message = NULL, updated_at = now()
                FROM maitu_live_interactions AS interaction
                WHERE maitu_interaction_analysis_jobs.interaction_id = interaction.id
                  AND NOT interaction.is_arrival
                  AND analyzer_version = %s AND status = 'failed' AND attempt < 3
                  AND (retry_after IS NULL OR retry_after <= now())
                """,
                (analyzer_version,),
            )
        self.connection.commit()
        return inserted

    def claim_analysis_job(
        self,
        analyzer_version: str,
        worker_id: str,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT job.* FROM maitu_interaction_analysis_jobs AS job
                JOIN maitu_live_interactions AS interaction
                  ON interaction.id = job.interaction_id AND NOT interaction.is_arrival
                WHERE job.analyzer_version = %s AND (
                    (job.status = 'queued' AND (job.retry_after IS NULL OR job.retry_after <= now()))
                    OR (job.status = 'running' AND job.lease_expires_at < now())
                )
                ORDER BY CASE WHEN job.status = 'running' THEN 0 ELSE 1 END, job.created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                (analyzer_version,),
            )
            candidate = cursor.fetchone()
            if candidate is None:
                self.connection.commit()
                return None
            cursor.execute(
                """
                UPDATE maitu_interaction_analysis_jobs
                SET status = 'running', claimed_by = %s, lease_token = gen_random_uuid(),
                    lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), attempt = attempt + 1,
                    started_at = COALESCE(started_at, now()), completed_at = NULL,
                    error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (worker_id, lease_seconds, candidate["id"]),
            )
            claimed = cursor.fetchone()
            cursor.execute(
                """
                SELECT interaction.content, interaction.normalized_content,
                       interaction.digital_reply_content,
                       NULLIF(btrim(COALESCE(interaction.digital_reply_content, '')), '') IS NOT NULL AS is_answered
                FROM maitu_live_interactions AS interaction WHERE interaction.id = %s
                """,
                (claimed["interaction_id"],),
            )
            claimed["interaction"] = cursor.fetchone()
        self.connection.commit()
        return self._serialize(claimed)

    def _lock_analysis_job(
        self,
        cursor: Any,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
    ) -> dict[str, Any]:
        try:
            token = UUID(lease_token)
        except ValueError as exc:
            raise MaituInteractionLeaseError("Analysis lease token is invalid") from exc
        cursor.execute(
            """
            SELECT * FROM maitu_interaction_analysis_jobs
            WHERE analysis_code = %s AND status = 'running' AND claimed_by = %s
              AND lease_token = %s AND lease_expires_at > now()
            FOR UPDATE
            """,
            (analysis_code, worker_id, token),
        )
        job = cursor.fetchone()
        if job is None:
            raise MaituInteractionLeaseError("Analysis lease is not active")
        return job

    def heartbeat_analysis_job(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> bool:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_analysis_job(cursor, analysis_code, worker_id, lease_token)
            cursor.execute(
                """
                UPDATE maitu_interaction_analysis_jobs
                SET lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (lease_seconds, job["id"]),
            )
        self.connection.commit()
        return True

    def complete_analysis_job(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_analysis_job(cursor, analysis_code, worker_id, lease_token)
            cursor.execute(
                """
                INSERT INTO maitu_interaction_analysis_results (
                    analysis_code, interaction_id, analyzer_version, strategy_revision,
                    input_fingerprint, output_fingerprint, invocation_evidence_ref,
                    interaction_form, business_intent, relevance_grade,
                    completeness_grade, resolution_grade, overall_grade,
                    confidence, reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (interaction_id, analyzer_version, input_fingerprint) DO UPDATE SET
                    output_fingerprint = EXCLUDED.output_fingerprint,
                    invocation_evidence_ref = EXCLUDED.invocation_evidence_ref,
                    interaction_form = EXCLUDED.interaction_form,
                    business_intent = EXCLUDED.business_intent,
                    relevance_grade = EXCLUDED.relevance_grade,
                    completeness_grade = EXCLUDED.completeness_grade,
                    resolution_grade = EXCLUDED.resolution_grade,
                    overall_grade = EXCLUDED.overall_grade,
                    confidence = EXCLUDED.confidence,
                    reason = EXCLUDED.reason,
                    created_at = now()
                RETURNING *
                """,
                (
                    analysis_code,
                    job["interaction_id"],
                    job["analyzer_version"],
                    job["strategy_revision"],
                    job["input_fingerprint"],
                    payload["output_fingerprint"],
                    payload["invocation_evidence_ref"],
                    payload["interaction_form"],
                    payload["business_intent"],
                    payload["relevance_grade"],
                    payload["completeness_grade"],
                    payload["resolution_grade"],
                    payload["overall_grade"],
                    payload["confidence"],
                    payload["reason"],
                ),
            )
            result = cursor.fetchone()
            cursor.execute(
                """
                UPDATE maitu_interaction_analysis_jobs
                SET status = 'succeeded', result_id = %s, claimed_by = NULL,
                    lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = NULL, error_message = NULL, completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (result["id"], job["id"]),
            )
        self.connection.commit()
        return self._serialize(result)

    def fail_analysis_job(
        self,
        analysis_code: str,
        worker_id: str,
        lease_token: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            job = self._lock_analysis_job(cursor, analysis_code, worker_id, lease_token)
            retry = job["attempt"] < 3
            cursor.execute(
                """
                UPDATE maitu_interaction_analysis_jobs
                SET status = %s, retry_after = %s, claimed_by = NULL,
                    lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = %s, error_message = %s,
                    completed_at = CASE WHEN %s THEN NULL ELSE now() END,
                    updated_at = now()
                WHERE id = %s
                """,
                (
                    "queued" if retry else "failed",
                    datetime.now(UTC) + timedelta(minutes=job["attempt"]) if retry else None,
                    error_code,
                    error_message,
                    retry,
                    job["id"],
                ),
            )
        self.connection.commit()
