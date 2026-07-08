from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from app.services.code_generator import AssetType, format_asset_code


class AssetRepository:
    writable_fields = (
        "asset_type",
        "title",
        "original_filename",
        "file_ext",
        "mime_type",
        "file_size",
        "checksum_sha256",
        "status",
        "project_id",
        "description",
        "display_code",
        "local_file_code",
        "entity_code",
        "source_system",
        "source_type",
        "maitu_category",
        "maitu_type",
        "maitu_subtype",
        "usage",
        "subject",
        "file_role",
        "browser_use_hint",
        "local_relative_path",
        "duplicate_group",
        "duplicate_rank",
        "duplicate_count",
        "duplicate_primary_local_file_code",
        "duplicate_primary_asset_code",
        "maitu_project_code",
        "maitu_scene_name",
        "maitu_scene_index",
        "maitu_layer_name",
        "maitu_layer_index",
        "maitu_slot_name",
        "maitu_slot_code",
        "layer_left",
        "layer_top",
        "layer_width",
        "layer_height",
        "layer_z_index",
        "replacement_policy",
    )

    def __init__(self, connection: Connection):
        self.connection = connection

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._filter_writable(payload)
        data["asset_type"] = AssetType(data["asset_type"]).value
        data["asset_code"] = self._next_asset_code(data["asset_type"])
        fields = tuple(data.keys())
        columns = ", ".join(fields)
        placeholders = ", ".join(["%s"] * len(fields))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                INSERT INTO assets ({columns})
                VALUES ({placeholders})
                RETURNING *
                """,
                tuple(data[field] for field in fields),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_ids(row)

    def get_by_code(self, asset_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (asset_code,),
            )
            row = cursor.fetchone()
        return self._stringify_ids(row) if row else None

    def list(
        self,
        *,
        asset_type: str | None = None,
        maitu_category: str | None = None,
        local_file_code: str | None = None,
        entity_code: str | None = None,
        maitu_type: str | None = None,
        usage: str | None = None,
        subject: str | None = None,
        maitu_project_code: str | None = None,
        maitu_scene_name: str | None = None,
        maitu_slot_name: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where_clauses = ["deleted_at IS NULL"]
        values: list[Any] = []

        if asset_type is not None:
            where_clauses.append("asset_type = %s")
            values.append(AssetType(asset_type).value)
        if maitu_category is not None:
            where_clauses.append("maitu_category = %s")
            values.append(maitu_category)
        if local_file_code is not None:
            where_clauses.append("local_file_code = %s")
            values.append(local_file_code)
        if entity_code is not None:
            where_clauses.append("entity_code = %s")
            values.append(entity_code)
        if maitu_type is not None:
            where_clauses.append("maitu_type = %s")
            values.append(maitu_type)
        if usage is not None:
            where_clauses.append("usage = %s")
            values.append(usage)
        if subject is not None:
            where_clauses.append("subject ILIKE %s")
            values.append(f"%{subject}%")
        if maitu_project_code is not None:
            where_clauses.append("maitu_project_code = %s")
            values.append(maitu_project_code)
        if maitu_scene_name is not None:
            where_clauses.append("maitu_scene_name = %s")
            values.append(maitu_scene_name)
        if maitu_slot_name is not None:
            where_clauses.append("maitu_slot_name = %s")
            values.append(maitu_slot_name)
        if q:
            where_clauses.append(
                "("
                "asset_code ILIKE %s OR display_code ILIKE %s OR local_file_code ILIKE %s "
                "OR entity_code ILIKE %s OR title ILIKE %s OR original_filename ILIKE %s "
                "OR description ILIKE %s OR usage ILIKE %s OR subject ILIKE %s "
                "OR file_role ILIKE %s OR browser_use_hint ILIKE %s"
                ")"
            )
            pattern = f"%{q}%"
            values.extend([pattern] * 11)

        values.extend([limit, offset])
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM assets
                WHERE {' AND '.join(where_clauses)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(values),
            )
            rows = cursor.fetchall()
        return [self._stringify_ids(row) for row in rows]

    def _next_asset_code(self, asset_type: str) -> str:
        sequence_date = datetime.now(UTC).date()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO asset_sequences (sequence_date, asset_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, asset_type)
                DO UPDATE SET current_value = asset_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, asset_type),
            )
            sequence = cursor.fetchone()[0]
        return format_asset_code(asset_type, sequence_date, sequence)

    def _filter_writable(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {field: payload[field] for field in self.writable_fields if field in payload}

    @staticmethod
    def _stringify_ids(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        for field in ("id", "project_id", "created_by"):
            if field in converted and converted[field] is not None:
                converted[field] = str(converted[field])
        return converted
