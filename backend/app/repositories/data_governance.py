from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.errors import DomainConflictError


class DataGovernanceRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def put_data_contract(
        self,
        *,
        contract_code: str,
        revision_number: int,
        status: str,
        owner_principal: str,
        definition: dict[str, Any],
        fingerprint_sha256: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM data_contracts
                WHERE contract_code = %s AND revision_number = %s FOR UPDATE
                """,
                (contract_code, revision_number),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                if existing["fingerprint_sha256"] != fingerprint_sha256:
                    raise DomainConflictError(
                        "DATA_CONTRACT_REVISION_CONFLICT",
                        "Data contract revision already exists with different content",
                    )
                return self._serialize(existing)
            if status == "active":
                cursor.execute(
                    """
                    UPDATE data_contracts SET status = 'superseded'
                    WHERE contract_code = %s AND status = 'active'
                    """,
                    (contract_code,),
                )
            cursor.execute(
                """
                INSERT INTO data_contracts (
                    contract_code, revision_number, status, owner_principal,
                    source_system, schema_version, json_schema, event_id_path,
                    event_time_path, operation_path, upsert_delete_semantics,
                    lateness_policy, compatibility_window, fingerprint_sha256,
                    primary_key_paths, enum_mappings, field_classifications,
                    expected_volume, quality_slo
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    contract_code,
                    revision_number,
                    status,
                    owner_principal,
                    definition["source_system"],
                    definition["schema_version"],
                    Jsonb(definition["json_schema"]),
                    definition["event_id_path"],
                    definition.get("event_time_path"),
                    definition.get("operation_path"),
                    Jsonb(definition["upsert_delete_semantics"]),
                    Jsonb(definition["lateness_policy"]),
                    Jsonb(definition["compatibility_window"]),
                    fingerprint_sha256,
                    Jsonb(definition["primary_key_paths"]),
                    Jsonb(definition["enum_mappings"]),
                    Jsonb(definition["field_classifications"]),
                    Jsonb(definition["expected_volume"]),
                    Jsonb(definition["quality_slo"]),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def get_active_contract(self, contract_code: str, revision_number: int) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM data_contracts
                WHERE contract_code = %s AND revision_number = %s AND status = 'active'
                """,
                (contract_code, revision_number),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def put_metric_revision(
        self,
        *,
        metric_code: str,
        expected_revision: int,
        owner_principal: str,
        definition: dict[str, Any],
        fingerprint_sha256: str,
        activate: bool,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM metric_definitions WHERE metric_code = %s FOR UPDATE",
                (metric_code,),
            )
            metric = cursor.fetchone()
            if metric is None:
                if expected_revision != 0:
                    self.connection.rollback()
                    raise DomainConflictError(
                        "METRIC_REVISION_CONFLICT",
                        "New metric definitions must start at expected revision zero",
                    )
                cursor.execute(
                    """
                    INSERT INTO metric_definitions (
                        metric_code, owner_principal, current_revision_number, status
                    ) VALUES (%s, %s, 0, 'draft') RETURNING *
                    """,
                    (metric_code, owner_principal),
                )
                metric = cursor.fetchone()
            if int(metric["current_revision_number"]) != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "METRIC_REVISION_CONFLICT",
                    "Metric definition changed since it was loaded",
                    details={
                        "expected_revision": expected_revision,
                        "actual_revision": int(metric["current_revision_number"]),
                    },
                )
            next_revision = expected_revision + 1
            if activate:
                cursor.execute(
                    """
                    UPDATE metric_definition_revisions SET status = 'superseded'
                    WHERE metric_id = %s AND status = 'active'
                    """,
                    (metric["id"],),
                )
            cursor.execute(
                """
                INSERT INTO metric_definition_revisions (
                    metric_id, metric_code, revision_number, status, name,
                    description, unit, value_type, aggregation,
                    numerator_expression, denominator_expression, dimensions,
                    event_contract_refs, fingerprint_sha256, effective_at,
                    grain, currency, event_time_field, timezone,
                    business_day_boundary, deduplication_keys,
                    refund_window_days, null_rule, outlier_rule,
                    schema_compatibility, quality_slo
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s)
                RETURNING *
                """,
                (
                    metric["id"],
                    metric_code,
                    next_revision,
                    "active" if activate else "draft",
                    definition["name"],
                    definition["description"],
                    definition["unit"],
                    definition["value_type"],
                    definition["aggregation"],
                    definition.get("numerator_expression"),
                    definition.get("denominator_expression"),
                    Jsonb(definition["dimensions"]),
                    Jsonb(definition["event_contract_refs"]),
                    fingerprint_sha256,
                    definition.get("effective_at"),
                    definition["grain"],
                    definition.get("currency"),
                    definition["event_time_field"],
                    definition["timezone"],
                    definition["business_day_boundary"],
                    Jsonb(definition["deduplication_keys"]),
                    definition.get("refund_window_days"),
                    Jsonb(definition["null_rule"]),
                    Jsonb(definition["outlier_rule"]),
                    Jsonb(definition["schema_compatibility"]),
                    Jsonb(definition["quality_slo"]),
                ),
            )
            revision = cursor.fetchone()
            cursor.execute(
                """
                UPDATE metric_definitions
                SET current_revision_number = %s,
                    status = CASE WHEN %s THEN 'active' ELSE status END,
                    updated_at = now()
                WHERE id = %s
                """,
                (next_revision, activate, metric["id"]),
            )
        self.connection.commit()
        return self._serialize(revision)

    def ingest_standard_event(
        self,
        *,
        contract_id: str,
        envelope: dict[str, Any],
        entity_type: str,
        entity_id: str,
        payload_fingerprint: str,
        quality_status: str,
        quarantine_reason: str | None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM standard_events
                WHERE source_system = %s AND source_event_id = %s
                """,
                (envelope["source_system"], envelope["source_event_id"]),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                if existing["payload_fingerprint"] != payload_fingerprint:
                    raise DomainConflictError(
                        "SOURCE_EVENT_ID_REUSED",
                        "Source event id was reused with different content",
                    )
                return self._serialize(existing)
            cursor.execute(
                """
                INSERT INTO standard_events (
                    event_id, source_system, source_event_id, contract_id,
                    operation, entity_type, entity_id, event_time,
                    processing_time, payload, payload_fingerprint, tombstone,
                    quality_status, quarantine_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    envelope["event_id"],
                    envelope["source_system"],
                    envelope["source_event_id"],
                    contract_id,
                    envelope["operation"],
                    entity_type,
                    entity_id,
                    envelope["event_time"],
                    envelope["processing_time"],
                    Jsonb(envelope["payload"]),
                    payload_fingerprint,
                    envelope["tombstone"],
                    quality_status,
                    quarantine_reason,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result

    @staticmethod
    def next_batch_code(cursor: Any) -> str:
        sequence_date = datetime.now(UTC).date()
        cursor.execute(
            """
            INSERT INTO domain_sequences (sequence_date, object_type, current_value)
            VALUES (%s, 'data_quality_batch', 1)
            ON CONFLICT (sequence_date, object_type)
            DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now()
            RETURNING current_value
            """,
            (sequence_date,),
        )
        return f"DQB-{sequence_date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"
