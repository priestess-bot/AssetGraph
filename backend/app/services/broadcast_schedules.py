from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint


class BroadcastScheduleService:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                schedule_code = self._next(cursor)
                cursor.execute(
                    """INSERT INTO broadcast_schedules (schedule_code, title, current_revision_number)
                       VALUES (%s, %s, 1) RETURNING id""",
                    (schedule_code, payload["title"].strip()),
                )
                schedule_id = cursor.fetchone()["id"]
                row = self._insert_revision(
                    cursor,
                    schedule_id=schedule_id,
                    schedule_code=schedule_code,
                    revision_number=1,
                    payload=payload,
                    status="draft",
                    release_fingerprint=None,
                    validation_result={"state": "not_validated", "go_live_capability": "disabled"},
                )
                row["title"] = payload["title"].strip()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return row

    def list(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT revision.*, schedule.title FROM broadcast_schedules AS schedule
                   JOIN broadcast_schedule_revisions AS revision
                     ON revision.schedule_id = schedule.id
                    AND revision.revision_number = schedule.current_revision_number
                   ORDER BY revision.starts_at, revision.schedule_code"""
            )
            return [dict(row) for row in cursor.fetchall()]

    def get(self, schedule_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT revision.*, schedule.title FROM broadcast_schedules AS schedule
                   JOIN broadcast_schedule_revisions AS revision
                     ON revision.schedule_id = schedule.id
                    AND revision.revision_number = schedule.current_revision_number
                   WHERE schedule.schedule_code = %s""",
                (schedule_code,),
            )
            row = cursor.fetchone()
        return dict(row) if row else None

    def validate(self, schedule_code: str) -> dict[str, Any] | None:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM broadcast_schedules WHERE schedule_code = %s FOR UPDATE",
                    (schedule_code,),
                )
                schedule = cursor.fetchone()
                if schedule is None:
                    self.connection.rollback()
                    return None
                cursor.execute(
                    """SELECT * FROM broadcast_schedule_revisions
                       WHERE schedule_id = %s AND revision_number = %s""",
                    (schedule["id"], schedule["current_revision_number"]),
                )
                current = cursor.fetchone()
                cursor.execute(
                    """SELECT release_code, status, release_fingerprint
                       FROM releases WHERE release_code = %s""",
                    (current["release_code"],),
                )
                release = cursor.fetchone()
                blocked_reasons: list[str] = []
                warnings: list[str] = []
                if release is None:
                    blocked_reasons.append("RELEASE_NOT_FOUND")
                elif release["status"] in {"revoked", "failed", "delivery_failed", "reconcile_required"}:
                    blocked_reasons.append("RELEASE_UNAVAILABLE")
                elif release["status"] not in {"approved", "delivered"}:
                    warnings.append("RELEASE_APPROVAL_REQUIRED")

                cursor.execute(
                    """SELECT DISTINCT revision.schedule_code
                       FROM broadcast_schedules AS candidate
                       JOIN broadcast_schedule_revisions AS revision
                         ON revision.schedule_id = candidate.id
                        AND revision.revision_number = candidate.current_revision_number
                       WHERE revision.schedule_code <> %s
                         AND revision.target_room_id = %s
                         AND revision.status IN ('validated', 'approval_required', 'approved', 'active')
                         AND revision.starts_at < %s
                         AND revision.ends_at > %s
                       ORDER BY revision.schedule_code""",
                    (
                        schedule_code,
                        current["target_room_id"],
                        current["ends_at"],
                        current["starts_at"],
                    ),
                )
                conflicts = [str(row["schedule_code"]) for row in cursor.fetchall()]
                if conflicts:
                    blocked_reasons.append("TARGET_ROOM_TIME_CONFLICT")

                status = "draft" if blocked_reasons else "approval_required" if warnings else "validated"
                validation_result = {
                    "state": "blocked" if blocked_reasons else "warning" if warnings else "passed",
                    "blocked_reasons": blocked_reasons,
                    "warnings": warnings,
                    "conflicting_schedule_codes": conflicts,
                    "release_status": release["status"] if release else None,
                    "go_live_capability": "disabled",
                }
                payload = self._payload(current)
                row = self._insert_revision(
                    cursor,
                    schedule_id=schedule["id"],
                    schedule_code=schedule_code,
                    revision_number=int(current["revision_number"]) + 1,
                    payload=payload,
                    status=status,
                    release_fingerprint=release["release_fingerprint"] if release else None,
                    validation_result=validation_result,
                )
                row["title"] = schedule["title"]
                cursor.execute(
                    "UPDATE broadcast_schedules SET current_revision_number = %s, updated_at = now() WHERE id = %s",
                    (row["revision_number"], schedule["id"]),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return row

    def _insert_revision(
        self,
        cursor: Any,
        *,
        schedule_id: Any,
        schedule_code: str,
        revision_number: int,
        payload: dict[str, Any],
        status: str,
        release_fingerprint: str | None,
        validation_result: dict[str, Any],
    ) -> dict[str, Any]:
        fingerprint = canonical_fingerprint(
            {
                "schedule_code": schedule_code,
                "revision_number": revision_number,
                "payload": payload,
                "status": status,
                "release_fingerprint_sha256": release_fingerprint,
                "validation_result": validation_result,
            }
        )
        cursor.execute(
            """INSERT INTO broadcast_schedule_revisions
               (schedule_id,schedule_code,revision_number,status,release_code,release_fingerprint_sha256,
                target_account_id,target_room_id,platform,timezone,starts_at,ends_at,owner,
                promotion_dependencies,inventory_dependencies,conflict_strategy,stop_conditions,
                validation_result,fingerprint_sha256)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               RETURNING *""",
            (
                schedule_id,
                schedule_code,
                revision_number,
                status,
                payload["release_code"],
                release_fingerprint,
                payload["target_account_id"],
                payload["target_room_id"],
                payload["platform"],
                payload["timezone"],
                payload["starts_at"],
                payload["ends_at"],
                payload["owner"],
                Jsonb(payload["promotion_dependencies"]),
                Jsonb(payload["inventory_dependencies"]),
                payload["conflict_strategy"],
                Jsonb(payload["stop_conditions"]),
                Jsonb(validation_result),
                fingerprint,
            ),
        )
        return dict(cursor.fetchone())

    @staticmethod
    def _payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "release_code": row["release_code"],
            "target_account_id": row["target_account_id"],
            "target_room_id": row["target_room_id"],
            "platform": row["platform"],
            "timezone": row["timezone"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "owner": row["owner"],
            "promotion_dependencies": row["promotion_dependencies"] or [],
            "inventory_dependencies": row["inventory_dependencies"] or [],
            "conflict_strategy": row["conflict_strategy"],
            "stop_conditions": row["stop_conditions"] or [],
        }

    @staticmethod
    def _next(cursor: Any) -> str:
        date = datetime.now(UTC).date()
        cursor.execute(
            """INSERT INTO domain_sequences(sequence_date,object_type,current_value)
               VALUES(%s,'broadcast_schedule',1)
               ON CONFLICT(sequence_date,object_type)
               DO UPDATE SET current_value=domain_sequences.current_value+1
               RETURNING current_value""",
            (date,),
        )
        return f"SCHEDULE-{date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"
