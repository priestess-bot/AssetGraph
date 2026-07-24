from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.errors import DomainValidationError


class FunctionalOperationsService:
    def __init__(self, connection: Connection):
        self.connection = connection

    def import_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["ended_at"] <= payload["started_at"]:
            raise DomainValidationError(
                "OPERATION_SESSION_INTERVAL_INVALID",
                "End time must be after start time",
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            plan = None
            plan_code = payload.get("live_room_plan_code")
            if plan_code:
                cursor.execute(
                    "SELECT plan_code, project_code, variant_code, release_code FROM functional_live_room_plans WHERE plan_code = %s",
                    (plan_code,),
                )
                plan = cursor.fetchone()
                if plan is None:
                    raise DomainValidationError("OPERATION_SESSION_PLAN_NOT_FOUND", "The selected live-room plan does not exist")
                requested_project = payload.get("content_project_code")
                if requested_project and requested_project != plan["project_code"]:
                    raise DomainValidationError("OPERATION_SESSION_PROJECT_PLAN_MISMATCH", "The session project must match its live-room plan")
            code = self._next(cursor, "OPS", "functional_operation_session")
            cursor.execute(
                """INSERT INTO functional_operation_sessions
                   (session_code,title,platform,content_project_code,live_room_plan_code,variant_code,release_code,started_at,ended_at,metrics)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    code,
                    payload["title"],
                    payload["platform"],
                    plan["project_code"] if plan else payload.get("content_project_code"),
                    plan["plan_code"] if plan else None,
                    plan["variant_code"] if plan else None,
                    plan["release_code"] if plan else None,
                    payload["started_at"],
                    payload["ended_at"],
                    Jsonb(payload.get("metrics") or {}),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_operation_sessions ORDER BY started_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def create_exposure(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["ended_at"] <= payload["started_at"]:
            raise DomainValidationError("CONTENT_EXPOSURE_INTERVAL_INVALID", "Exposure end time must be after start time")
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_operation_sessions WHERE session_code = %s FOR UPDATE",
                    (payload["session_code"],),
                )
                session = cursor.fetchone()
                if session is None:
                    raise DomainValidationError("CONTENT_EXPOSURE_SESSION_NOT_FOUND", "The operation session does not exist")
                if payload["started_at"] < session["started_at"] or payload["ended_at"] > session["ended_at"]:
                    raise DomainValidationError("CONTENT_EXPOSURE_OUTSIDE_SESSION", "Exposure must be contained by the operation session interval")
                cursor.execute(
                    "SELECT plan_code, project_code, variant_code, release_code, blueprint FROM functional_live_room_plans WHERE plan_code = %s",
                    (payload["plan_code"],),
                )
                plan = cursor.fetchone()
                if plan is None:
                    raise DomainValidationError("CONTENT_EXPOSURE_PLAN_NOT_FOUND", "The referenced live-room plan does not exist")
                if session.get("live_room_plan_code") and session["live_room_plan_code"] != plan["plan_code"]:
                    raise DomainValidationError("CONTENT_EXPOSURE_SESSION_PLAN_MISMATCH", "Session is bound to a different live-room plan")
                scene_codes = {str(scene.get("scene_code") or "") for scene in (plan["blueprint"] or {}).get("scenes") or []}
                if payload["scene_code"] not in scene_codes:
                    raise DomainValidationError("CONTENT_EXPOSURE_SCENE_NOT_FOUND", "Exposure scene is not in the referenced plan")
                cursor.execute(
                    """SELECT exposure_code FROM functional_content_exposures
                       WHERE session_id = %s AND status = 'active'
                         AND started_at < %s AND ended_at > %s""",
                    (session["id"], payload["ended_at"], payload["started_at"]),
                )
                conflicting = [row["exposure_code"] for row in cursor.fetchall()]
                if conflicting:
                    raise DomainValidationError(
                        "CONTENT_EXPOSURE_OVERLAP_CONFLICT",
                        "An active exposure already covers this session interval",
                        details={"exposure_codes": conflicting},
                    )
                code = self._next(cursor, "EXPOSURE", "functional_content_exposure")
                cursor.execute(
                    """INSERT INTO functional_content_exposures
                       (exposure_code,session_id,session_code,plan_code,variant_code,release_code,scene_code,
                        started_at,ended_at,source_kind,evidence_note,confidence)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        code, session["id"], session["session_code"], plan["plan_code"], plan["variant_code"],
                        plan["release_code"], payload["scene_code"], payload["started_at"], payload["ended_at"],
                        payload["source_kind"], payload["evidence_note"].strip(), payload.get("confidence", 0.5),
                    ),
                )
                row = cursor.fetchone()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return dict(row)

    def list_exposures(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_content_exposures ORDER BY started_at DESC, exposure_code")
            return [dict(row) for row in cursor.fetchall()]

    def create_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        codes = list(dict.fromkeys(payload["session_codes"]))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_operation_sessions WHERE session_code = ANY(%s)",
                (codes,),
            )
            rows = cursor.fetchall()
            if len(rows) != len(codes):
                raise DomainValidationError(
                    "ATTRIBUTION_SESSION_NOT_FOUND",
                    "Every selected operation session must exist",
                )
            values = [
                float((row["metrics"] or {}).get(payload["metric_key"], 0))
                for row in rows
            ]
            grouped: dict[str, list[float]] = {}
            for row, value in zip(rows, values, strict=True):
                grouped.setdefault(
                    row["content_project_code"] or "unlinked", []
                ).append(value)
            results = {
                key: {"average": sum(items) / len(items), "sample_size": len(items)}
                for key, items in grouped.items()
            }
            code = self._next(cursor, "ATTR", "functional_attribution_report")
            cursor.execute(
                "INSERT INTO functional_attribution_reports (report_code,metric_key,session_codes,results) VALUES (%s,%s,%s,%s) RETURNING *",
                (code, payload["metric_key"], Jsonb(codes), Jsonb(results)),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    def list_reports(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_attribution_reports ORDER BY created_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        end = payload["starts_at"] + timedelta(minutes=payload["duration_minutes"])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT schedule_code, starts_at, duration_minutes FROM functional_schedule_plans WHERE target_live_room_id=%s",
                (payload["target_live_room_id"],),
            )
            conflicts = [
                row["schedule_code"]
                for row in cursor.fetchall()
                if payload["starts_at"]
                < row["starts_at"] + timedelta(minutes=row["duration_minutes"])
                and end > row["starts_at"]
            ]
            code = self._next(cursor, "SCHED", "functional_schedule_plan")
            cursor.execute(
                "INSERT INTO functional_schedule_plans (schedule_code,title,target_live_room_id,starts_at,duration_minutes,status,conflict_codes) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    code,
                    payload["title"],
                    payload["target_live_room_id"],
                    payload["starts_at"],
                    payload["duration_minutes"],
                    "conflict" if conflicts else "planned",
                    Jsonb(conflicts),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    def list_schedules(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM functional_schedule_plans ORDER BY starts_at")
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _next(cursor: Any, prefix: str, kind: str) -> str:
        date = datetime.now(UTC).date()
        cursor.execute(
            "INSERT INTO domain_sequences (sequence_date, object_type, current_value) VALUES (%s,%s,1) ON CONFLICT (sequence_date,object_type) DO UPDATE SET current_value=domain_sequences.current_value+1,updated_at=now() RETURNING current_value",
            (date, kind),
        )
        return f"{prefix}-{date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"
