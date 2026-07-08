from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from app.services.code_generator import BusinessObjectType, format_business_code


class VideoSegmentRepository:
    writable_fields = (
        "live_id",
        "asset_id",
        "asset_code",
        "live_code",
        "title",
        "start_time_seconds",
        "end_time_seconds",
        "transcript",
        "product_id",
        "digital_human_id",
        "voice_profile_id",
        "script_block_id",
        "quality_score",
        "reuse_score",
        "status",
    )

    def __init__(self, connection: Connection):
        self.connection = connection

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._filter_writable(payload)
        data["segment_code"] = self._next_segment_code()
        fields = tuple(data.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                INSERT INTO video_segments ({columns})
                VALUES ({placeholders})
                RETURNING *
                """,
                tuple(data[field] for field in fields),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_ids(row)

    def list(self, live_code: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        where = ""
        params: list[Any] = []
        if live_code is not None:
            where = "WHERE live_code = %s"
            params.append(live_code)
        params.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM video_segments
                {where}
                ORDER BY live_code ASC, start_time_seconds ASC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return [self._stringify_ids(row) for row in rows]

    def get_by_code(self, segment_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM video_segments
                WHERE segment_code = %s
                """,
                (segment_code,),
            )
            row = cursor.fetchone()
        return self._stringify_ids(row) if row else None

    def _next_segment_code(self) -> str:
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
                (sequence_date, BusinessObjectType.VIDEO_SEGMENT.value),
            )
            sequence = cursor.fetchone()[0]
        return format_business_code(BusinessObjectType.VIDEO_SEGMENT, sequence_date, sequence)

    def _filter_writable(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {field: payload[field] for field in self.writable_fields if field in payload}

    @staticmethod
    def _stringify_ids(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in (
            "id",
            "live_id",
            "asset_id",
            "product_id",
            "digital_human_id",
            "voice_profile_id",
            "script_block_id",
        ):
            if field in converted and converted[field] is not None:
                converted[field] = str(converted[field])
        return converted
