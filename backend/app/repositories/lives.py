from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from app.services.code_generator import format_live_code


class LiveSessionRepository:
    writable_fields = (
        "title",
        "platform",
        "streamer_name",
        "status",
        "project_id",
        "digital_human_id",
        "voice_profile_id",
        "script_id",
        "description",
    )

    def __init__(self, connection: Connection):
        self.connection = connection

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._filter_writable(payload)
        data["live_code"] = self._next_live_code()
        fields = tuple(data.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                INSERT INTO live_sessions ({columns})
                VALUES ({placeholders})
                RETURNING *
                """,
                tuple(data[field] for field in fields),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_ids(row)

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM live_sessions
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cursor.fetchall()
        return [self._stringify_ids(row) for row in rows]

    def get_by_code(self, live_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM live_sessions
                WHERE live_code = %s AND deleted_at IS NULL
                """,
                (live_code,),
            )
            row = cursor.fetchone()
        return self._stringify_ids(row) if row else None

    def link_asset(self, live_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        live = self.get_by_code(live_code)
        if live is None:
            return None

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (payload["asset_code"],),
            )
            asset = cursor.fetchone()
            if asset is None:
                return None

            cursor.execute(
                """
                INSERT INTO live_assets (
                    live_id, asset_id, live_code, asset_code, relation_type,
                    sort_order, start_time_seconds, end_time_seconds, segment_label,
                    maitu_scene_name, maitu_layer_name, maitu_slot_name, replacement_policy
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (live_id, asset_id, relation_type)
                DO UPDATE SET
                    sort_order = EXCLUDED.sort_order,
                    start_time_seconds = EXCLUDED.start_time_seconds,
                    end_time_seconds = EXCLUDED.end_time_seconds,
                    segment_label = EXCLUDED.segment_label,
                    maitu_scene_name = EXCLUDED.maitu_scene_name,
                    maitu_layer_name = EXCLUDED.maitu_layer_name,
                    maitu_slot_name = EXCLUDED.maitu_slot_name,
                    replacement_policy = EXCLUDED.replacement_policy
                RETURNING asset_code, relation_type, sort_order, start_time_seconds, end_time_seconds,
                    segment_label, maitu_scene_name, maitu_layer_name, maitu_slot_name, replacement_policy
                """,
                (
                    live["id"],
                    asset["id"],
                    live_code,
                    payload["asset_code"],
                    payload["relation_type"],
                    payload.get("sort_order", 0),
                    payload.get("start_time_seconds"),
                    payload.get("end_time_seconds"),
                    payload.get("segment_label"),
                    payload.get("maitu_scene_name"),
                    payload.get("maitu_layer_name"),
                    payload.get("maitu_slot_name"),
                    payload.get("replacement_policy"),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    def list_assets(self, live_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT asset_code, relation_type, sort_order, start_time_seconds, end_time_seconds,
                    segment_label, maitu_scene_name, maitu_layer_name, maitu_slot_name, replacement_policy
                FROM live_assets
                WHERE live_code = %s
                ORDER BY sort_order ASC, created_at ASC
                """,
                (live_code,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _next_live_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO live_sequences (sequence_date, current_value)
                VALUES (%s, 1)
                ON CONFLICT (sequence_date)
                DO UPDATE SET current_value = live_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date,),
            )
            sequence = cursor.fetchone()[0]
        return format_live_code(sequence_date, sequence)

    def _filter_writable(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {field: payload[field] for field in self.writable_fields if field in payload}

    @staticmethod
    def _stringify_ids(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in (
            "id",
            "project_id",
            "digital_human_id",
            "voice_profile_id",
            "script_id",
            "created_by",
        ):
            if field in converted and converted[field] is not None:
                converted[field] = str(converted[field])
        return converted
