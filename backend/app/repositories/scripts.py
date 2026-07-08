from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from app.services.code_generator import BusinessObjectType, format_business_code


class ScriptRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        blocks = payload.pop("blocks", [])
        script_code = self._next_script_code()
        data = {
            "script_code": script_code,
            "title": payload["title"],
            "product_id": payload.get("product_id"),
            "script_type": payload.get("script_type", "livestream"),
            "version": payload.get("version"),
            "description": payload.get("description"),
        }
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO scripts (script_code, title, product_id, script_type, version, description)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    data["script_code"],
                    data["title"],
                    data["product_id"],
                    data["script_type"],
                    data["version"],
                    data["description"],
                ),
            )
            script = self._stringify_id(cursor.fetchone())
            script_id = script["id"]
            inserted_blocks = []
            for block in blocks:
                cursor.execute(
                    """
                    INSERT INTO script_blocks (
                        script_id, block_type, content, sort_order, estimated_duration_seconds
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        script_id,
                        block["block_type"],
                        block["content"],
                        block.get("sort_order", 0),
                        block.get("estimated_duration_seconds"),
                    ),
                )
                inserted_blocks.append(self._stringify_id(cursor.fetchone()))
        self.connection.commit()
        script["blocks"] = inserted_blocks
        return script

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM scripts
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            scripts = [self._stringify_id(row) for row in cursor.fetchall()]
            for script in scripts:
                script["blocks"] = self._fetch_blocks(cursor, script["id"])
        return scripts

    def get_by_code(self, script_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM scripts
                WHERE script_code = %s AND deleted_at IS NULL
                """,
                (script_code,),
            )
            script = cursor.fetchone()
            if script is None:
                return None
            result = self._stringify_id(script)
            result["blocks"] = self._fetch_blocks(cursor, result["id"])
            return result

    def _fetch_blocks(self, cursor: Any, script_id: str) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT *
            FROM script_blocks
            WHERE script_id = %s
            ORDER BY sort_order ASC, created_at ASC
            """,
            (script_id,),
        )
        return [self._stringify_id(row) for row in cursor.fetchall()]

    def _next_script_code(self) -> str:
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
                (sequence_date, BusinessObjectType.SCRIPT.value),
            )
            sequence = cursor.fetchone()[0]
        return format_business_code(BusinessObjectType.SCRIPT, sequence_date, sequence)

    @staticmethod
    def _stringify_id(row: dict[str, Any]) -> dict[str, Any]:
        converted = dict(row)
        if "id" in converted:
            converted["id"] = str(converted["id"])
        if "script_id" in converted:
            converted["script_id"] = str(converted["script_id"])
        if "product_id" in converted and converted["product_id"] is not None:
            converted["product_id"] = str(converted["product_id"])
        return converted
