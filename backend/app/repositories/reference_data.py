from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row

from app.services.code_generator import BusinessObjectType, format_business_code


@dataclass(frozen=True)
class ReferenceTableConfig:
    table_name: str
    code_field: str
    object_type: BusinessObjectType
    writable_fields: tuple[str, ...]


DIGITAL_HUMAN_TABLE = ReferenceTableConfig(
    table_name="digital_humans",
    code_field="digital_human_code",
    object_type=BusinessObjectType.DIGITAL_HUMAN,
    writable_fields=("name", "persona", "gender", "style", "version", "provider", "description"),
)

VOICE_PROFILE_TABLE = ReferenceTableConfig(
    table_name="voice_profiles",
    code_field="voice_code",
    object_type=BusinessObjectType.VOICE_PROFILE,
    writable_fields=("name", "provider", "gender", "style", "speed", "emotion", "description"),
)

PRODUCT_TABLE = ReferenceTableConfig(
    table_name="products",
    code_field="product_code",
    object_type=BusinessObjectType.PRODUCT,
    writable_fields=("name", "brand", "category", "selling_points", "pain_points", "description"),
)


class ReferenceDataRepository:
    def __init__(self, connection: Connection, config: ReferenceTableConfig):
        self.connection = connection
        self.config = config

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = self._next_code()
        data = self._filter_writable(payload)
        data[self.config.code_field] = code
        fields = tuple(data.keys())
        placeholders = ", ".join(["%s"] * len(fields))
        columns = ", ".join(fields)

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                INSERT INTO {self.config.table_name} ({columns})
                VALUES ({placeholders})
                RETURNING *
                """,
                tuple(data[field] for field in fields),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_id(row)

    def list(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.config.table_name}
                WHERE deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cursor.fetchall()
        return [self._stringify_id(row) for row in rows]

    def get_by_code(self, code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT *
                FROM {self.config.table_name}
                WHERE {self.config.code_field} = %s AND deleted_at IS NULL
                """,
                (code,),
            )
            row = cursor.fetchone()
        return self._stringify_id(row) if row else None

    def update(self, code: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        data = self._filter_writable(payload)
        if not data:
            return self.get_by_code(code)

        assignments = ", ".join([f"{field} = %s" for field in data])
        values: list[Any] = list(data.values())
        values.append(code)

        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE {self.config.table_name}
                SET {assignments}, updated_at = now()
                WHERE {self.config.code_field} = %s AND deleted_at IS NULL
                RETURNING *
                """,
                tuple(values),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._stringify_id(row) if row else None

    def soft_delete(self, code: str) -> bool:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                UPDATE {self.config.table_name}
                SET deleted_at = now(), updated_at = now()
                WHERE {self.config.code_field} = %s AND deleted_at IS NULL
                RETURNING id
                """,
                (code,),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return row is not None

    def _next_code(self) -> str:
        sequence_date = datetime.now(UTC).date()
        object_type = self.config.object_type.value
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_sequences (sequence_date, object_type, current_value)
                VALUES (%s, %s, 1)
                ON CONFLICT (sequence_date, object_type)
                DO UPDATE SET current_value = business_sequences.current_value + 1, updated_at = now()
                RETURNING current_value
                """,
                (sequence_date, object_type),
            )
            sequence = cursor.fetchone()[0]
        return format_business_code(self.config.object_type, sequence_date, sequence)

    def _filter_writable(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {field: payload[field] for field in self.config.writable_fields if field in payload}

    @staticmethod
    def _stringify_id(row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        converted = dict(row)
        if "id" in converted:
            converted["id"] = str(converted["id"])
        return converted
