from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.services.code_generator import AssetType, format_asset_code


class AssetBindingLeaseConflictError(RuntimeError):
    """An active retry worker lease freezes the asset's Maitu binding."""


class AssetBindingReceiptReplayError(RuntimeError):
    """A signed Maitu inventory receipt nonce was already consumed."""


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
        "media_kind",
        "material_roles",
        "execution_capability",
        "rights_status",
        "rights_note",
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
        "maitu_material_id",
        "source_material_type",
        "source_material_url",
        "source_cover_url",
        "speaker_id",
        "digital_human_image_id",
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

    def create(self, payload: dict[str, Any], *, commit: bool = True) -> dict[str, Any]:
        tags = self._normalize_tags(payload.get("tags") or [])
        data = self._filter_writable(payload)
        data["material_roles"] = Jsonb(self._normalize_json_array(data.get("material_roles") or []))
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
            if tags and row is not None:
                self._attach_tags(cursor, row["id"], tags)
        if commit:
            self.connection.commit()
        result = self._stringify_ids(row)
        result["tags"] = tags
        return result

    @staticmethod
    def _normalize_json_array(values: list[Any]) -> list[str]:
        return list(dict.fromkeys(str(value) for value in values if str(value).strip()))

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

    def stats(self) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH duplicate_local_codes AS (
                    SELECT local_file_code
                    FROM assets
                    WHERE deleted_at IS NULL AND local_file_code IS NOT NULL
                    GROUP BY local_file_code
                    HAVING COUNT(*) > 1
                )
                SELECT
                    COUNT(*) AS total_assets,
                    (SELECT COUNT(*) FROM asset_files) AS asset_file_count,
                    COUNT(DISTINCT duplicate_group) FILTER (WHERE duplicate_group IS NOT NULL) AS duplicate_group_count,
                    COUNT(*) FILTER (WHERE duplicate_group IS NOT NULL) AS duplicate_asset_count,
                    (SELECT COUNT(*) FROM duplicate_local_codes) AS local_file_code_duplicate_groups,
                    (SELECT COUNT(*) FROM tags) AS tag_count,
                    (SELECT COUNT(DISTINCT asset_id) FROM asset_tags) AS tagged_asset_count,
                    (SELECT COUNT(*) FROM asset_tags) AS asset_tag_relation_count,
                    COUNT(*) FILTER (WHERE local_file_code IS NULL OR local_file_code = '') AS missing_local_file_code,
                    COUNT(*) FILTER (WHERE display_code IS NULL OR display_code = '') AS missing_display_code,
                    COUNT(*) FILTER (WHERE title IS NULL OR title = '') AS missing_title,
                    COUNT(*) FILTER (WHERE maitu_category IS NULL OR maitu_category = '') AS missing_maitu_category,
                    COUNT(*) FILTER (WHERE maitu_type IS NULL OR maitu_type = '') AS missing_maitu_type,
                    COUNT(*) FILTER (WHERE usage IS NULL OR usage = '') AS missing_usage,
                    COUNT(*) FILTER (WHERE subject IS NULL OR subject = '') AS missing_subject,
                    COUNT(*) FILTER (WHERE browser_use_hint IS NULL OR browser_use_hint = '') AS missing_browser_use_hint
                FROM assets
                WHERE deleted_at IS NULL
                """
            )
            summary = cursor.fetchone()
            by_asset_type = self._count_by(cursor, "asset_type")
            by_maitu_category = self._count_by(cursor, "maitu_category")
            by_maitu_type = self._count_by(cursor, "maitu_type")
            by_usage = self._count_by(cursor, "usage")

        return {
            "total_assets": int(summary["total_assets"] or 0),
            "asset_file_count": int(summary["asset_file_count"] or 0),
            "duplicate_group_count": int(summary["duplicate_group_count"] or 0),
            "duplicate_asset_count": int(summary["duplicate_asset_count"] or 0),
            "local_file_code_duplicate_groups": int(summary["local_file_code_duplicate_groups"] or 0),
            "tag_count": int(summary["tag_count"] or 0),
            "tagged_asset_count": int(summary["tagged_asset_count"] or 0),
            "asset_tag_relation_count": int(summary["asset_tag_relation_count"] or 0),
            "by_asset_type": by_asset_type,
            "by_maitu_category": by_maitu_category,
            "by_maitu_type": by_maitu_type,
            "by_usage": by_usage,
            "missing_fields": {
                "local_file_code": int(summary["missing_local_file_code"] or 0),
                "display_code": int(summary["missing_display_code"] or 0),
                "title": int(summary["missing_title"] or 0),
                "maitu_category": int(summary["missing_maitu_category"] or 0),
                "maitu_type": int(summary["missing_maitu_type"] or 0),
                "usage": int(summary["missing_usage"] or 0),
                "subject": int(summary["missing_subject"] or 0),
                "browser_use_hint": int(summary["missing_browser_use_hint"] or 0),
            },
        }

    def get_by_local_file_code(self, source_system: str, local_file_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM assets
                WHERE source_system = %s
                  AND local_file_code = %s
                  AND deleted_at IS NULL
                """,
                (source_system, local_file_code),
            )
            row = cursor.fetchone()
        return self._stringify_ids(row) if row else None

    def create_file_record(
        self,
        asset_code: str,
        payload: dict[str, Any],
        *,
        commit: bool = True,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT id
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                """,
                (asset_code,),
            )
            asset = cursor.fetchone()
            if asset is None:
                return None

            data = {
                "asset_id": asset["id"],
                "asset_code": asset_code,
                "file_role": payload.get("file_role", "original"),
                "bucket_name": payload["bucket_name"],
                "object_key": payload["object_key"],
                "mime_type": payload.get("mime_type"),
                "file_size": payload.get("file_size"),
                "checksum_sha256": payload.get("checksum_sha256"),
                "width": payload.get("width"),
                "height": payload.get("height"),
                "duration_seconds": payload.get("duration_seconds"),
                "source_relative_path": payload.get("source_relative_path"),
                "local_file_code": payload.get("local_file_code"),
                "storage_status": payload.get("storage_status", "stored"),
            }
            fields = tuple(data.keys())
            columns = ", ".join(fields)
            placeholders = ", ".join(["%s"] * len(fields))
            cursor.execute(
                f"""
                INSERT INTO asset_files ({columns})
                VALUES ({placeholders})
                ON CONFLICT (asset_id, file_role)
                DO UPDATE SET
                    bucket_name = EXCLUDED.bucket_name,
                    object_key = EXCLUDED.object_key,
                    mime_type = EXCLUDED.mime_type,
                    file_size = EXCLUDED.file_size,
                    checksum_sha256 = EXCLUDED.checksum_sha256,
                    width = EXCLUDED.width,
                    height = EXCLUDED.height,
                    duration_seconds = EXCLUDED.duration_seconds,
                    source_relative_path = EXCLUDED.source_relative_path,
                    local_file_code = EXCLUDED.local_file_code,
                    storage_status = EXCLUDED.storage_status
                RETURNING *
                """,
                tuple(data[field] for field in fields),
            )
            row = cursor.fetchone()
        if commit:
            self.connection.commit()
        return self._stringify_ids(row) if row else None

    def list_file_records(self, asset_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM asset_files
                WHERE asset_code = %s
                ORDER BY created_at DESC
                """,
                (asset_code,),
            )
            rows = cursor.fetchall()
        return [self._stringify_ids(row) for row in rows]

    def update_status(self, asset_code: str, status: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE assets
                SET status = %s, updated_at = now()
                WHERE asset_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                (status, asset_code),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_ids(row) if row else None

    def update_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        fields = (
            "maitu_material_id",
            "source_material_type",
            "source_material_url",
            "source_cover_url",
            "speaker_id",
            "digital_human_image_id",
            "maitu_binding_verification_source",
            "maitu_binding_verified_at",
            "maitu_binding_scope",
            "maitu_binding_inventory_fingerprint",
            "maitu_binding_readback_nonce",
            "maitu_binding_attestation",
        )
        data = {field: payload[field] for field in fields if field in payload}
        if not data:
            return self.get_by_code(asset_code)
        verification_fields = (
            "maitu_binding_verification_source",
            "maitu_binding_verified_at",
            "maitu_binding_scope",
            "maitu_binding_inventory_fingerprint",
            "maitu_binding_readback_nonce",
            "maitu_binding_attestation",
        )
        supplied_verification = set(verification_fields).intersection(payload)
        if supplied_verification:
            if supplied_verification != set(verification_fields):
                raise ValueError("authoritative Maitu binding receipt fields must be supplied together")
        else:
            data.update({field: None for field in verification_fields})
        assignments = ", ".join(f"{field} = %s" for field in data)
        values = [data[field] for field in data]
        values.append(asset_code)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT retry_task_code, status,
                       status = 'in_progress' AND claim_expires_at >= now() AS lease_active
                FROM maitu_execution_retry_tasks
                WHERE asset_code = %s
                  AND deleted_at IS NULL
                ORDER BY retry_task_code
                FOR UPDATE
                """,
                (asset_code,),
            )
            retry_tasks = cursor.fetchall()
            if any(task.get("lease_active") is True for task in retry_tasks):
                self.connection.rollback()
                raise AssetBindingLeaseConflictError(
                    "asset Maitu material binding cannot change during an active retry worker lease"
                )
            cursor.execute(
                """
                SELECT maitu_binding_readback_nonce
                FROM assets
                WHERE asset_code = %s AND deleted_at IS NULL
                FOR UPDATE
                """,
                (asset_code,),
            )
            current_asset = cursor.fetchone()
            if current_asset is None:
                self.connection.commit()
                return None
            supplied_nonce = data.get("maitu_binding_readback_nonce")
            if supplied_nonce is not None and str(current_asset.get("maitu_binding_readback_nonce")) == str(
                supplied_nonce
            ):
                self.connection.rollback()
                raise AssetBindingReceiptReplayError("Maitu binding readback receipt nonce was already consumed")
            cursor.execute(
                f"""
                UPDATE assets
                SET {assignments}, updated_at = now()
                WHERE asset_code = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_ids(row) if row else None

    @staticmethod
    def _normalize_tags(tags: list[Any]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in tags:
            value = str(tag).strip()
            if not value or value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        return normalized

    @staticmethod
    def _attach_tags(cursor: Any, asset_id: Any, tags: list[str]) -> None:
        for tag in tags:
            cursor.execute(
                """
                INSERT INTO tags (name, tag_type)
                VALUES (%s, 'imported')
                ON CONFLICT (name) DO NOTHING
                """,
                (tag,),
            )
            cursor.execute(
                """
                INSERT INTO asset_tags (asset_id, tag_id, source)
                SELECT %s, id, 'inventory'
                FROM tags
                WHERE name = %s
                ON CONFLICT DO NOTHING
                """,
                (asset_id, tag),
            )

    @staticmethod
    def _count_by(cursor: Any, column: str) -> dict[str, int]:
        allowed_columns = {"asset_type", "maitu_category", "maitu_type", "usage"}
        if column not in allowed_columns:
            raise ValueError(f"unsupported stats column: {column}")
        cursor.execute(
            f"""
            SELECT {column} AS key, COUNT(*) AS count
            FROM assets
            WHERE deleted_at IS NULL AND {column} IS NOT NULL AND {column} <> ''
            GROUP BY {column}
            ORDER BY count DESC, key ASC
            """
        )
        return {str(row["key"]): int(row["count"] or 0) for row in cursor.fetchall()}

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
        for field in ("id", "project_id", "created_by", "asset_id"):
            if field in converted and converted[field] is not None:
                converted[field] = str(converted[field])
        return converted
