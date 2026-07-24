from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.services.manifests import SealedManifest


class EvidenceRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def rollback(self) -> None:
        self.connection.rollback()

    def register_artifact(
        self,
        *,
        artifact_kind: str,
        media_type: str,
        schema_version: str,
        storage_uri: str,
        checksum_sha256: str,
        byte_size: int,
        producer_type: str,
        producer_code: str,
        producer_revision: int | None,
        sensitivity: str,
        retention_policy_code: str,
        encryption_key_ref: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM artifact_refs
                WHERE checksum_sha256 = %s AND byte_size = %s AND media_type = %s
                  AND content_addressed = true
                """,
                (checksum_sha256, byte_size, media_type),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                return self._serialize(existing)
            artifact_code = self._next_code(cursor, prefix="ART", object_type="artifact_ref")
            cursor.execute(
                """
                INSERT INTO artifact_refs (
                    artifact_code, artifact_kind, media_type, schema_version,
                    storage_uri, checksum_sha256, byte_size, producer_type,
                    producer_code, producer_revision, sensitivity,
                    retention_policy_code, encryption_key_ref, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    artifact_code,
                    artifact_kind,
                    media_type,
                    schema_version,
                    storage_uri,
                    checksum_sha256,
                    byte_size,
                    producer_type,
                    producer_code,
                    producer_revision,
                    sensitivity,
                    retention_policy_code,
                    encryption_key_ref,
                    Jsonb(metadata),
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def get_artifact(self, artifact_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM artifact_refs WHERE artifact_code = %s", (artifact_code,))
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def link_artifact_input(self, artifact_code: str, input_artifact_code: str, *, relation_type: str) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO artifact_input_refs (artifact_id, input_artifact_id, relation_type)
                SELECT output.id, input.id, %s
                FROM artifact_refs AS output, artifact_refs AS input
                WHERE output.artifact_code = %s AND input.artifact_code = %s
                ON CONFLICT DO NOTHING
                """,
                (relation_type, artifact_code, input_artifact_code),
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    """
                    SELECT count(*) FROM artifact_refs
                    WHERE artifact_code IN (%s, %s)
                    """,
                    (artifact_code, input_artifact_code),
                )
                if cursor.fetchone()[0] != 2:
                    self.connection.rollback()
                    raise KeyError("artifact input link references an unknown artifact")
        self.connection.commit()

    def persist_run_manifest(self, *, run_code: str, sealed: SealedManifest) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM run_manifests WHERE manifest_fingerprint = %s",
                (sealed.manifest_fingerprint,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                return self._serialize(existing)
            cursor.execute(
                "SELECT chain_hash FROM run_manifests ORDER BY sealed_at DESC, id DESC LIMIT 1"
            )
            previous = cursor.fetchone()
            previous_hash = previous["chain_hash"] if previous else None
            chain_hash = hashlib.sha256(
                f"{previous_hash or ''}:{sealed.manifest_fingerprint}:{sealed.signature_value}".encode()
            ).hexdigest()
            manifest_code = self._next_code(cursor, prefix="MANIFEST", object_type="run_manifest")
            cursor.execute(
                """
                INSERT INTO run_manifests (
                    manifest_code, schema_version, run_code, manifest,
                    input_fingerprint, output_fingerprint, manifest_fingerprint,
                    signature_algorithm, signature_key_id, signature_value,
                    previous_chain_hash, chain_hash
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    manifest_code,
                    sealed.schema_version,
                    run_code,
                    Jsonb(sealed.manifest),
                    sealed.input_fingerprint,
                    sealed.output_fingerprint,
                    sealed.manifest_fingerprint,
                    sealed.signature_algorithm,
                    sealed.signature_key_id,
                    sealed.signature_value,
                    previous_hash,
                    chain_hash,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def append_lineage_edge(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO lineage_edges (
                    run_code, source_namespace, source_name, source_version,
                    target_namespace, target_name, target_version, relation_type,
                    schema_version, facets
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    source_namespace, source_name, source_version,
                    target_namespace, target_name, target_version, relation_type
                ) DO NOTHING
                RETURNING *
                """,
                (
                    payload.get("run_code"),
                    payload["source_namespace"],
                    payload["source_name"],
                    payload["source_version"],
                    payload["target_namespace"],
                    payload["target_name"],
                    payload["target_version"],
                    payload["relation_type"],
                    payload.get("schema_version", "lineage-edge.v1"),
                    Jsonb(payload.get("facets") or {}),
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    """
                    SELECT * FROM lineage_edges
                    WHERE source_namespace = %s AND source_name = %s AND source_version = %s
                      AND target_namespace = %s AND target_name = %s AND target_version = %s
                      AND relation_type = %s
                    """,
                    (
                        payload["source_namespace"],
                        payload["source_name"],
                        payload["source_version"],
                        payload["target_namespace"],
                        payload["target_name"],
                        payload["target_version"],
                        payload["relation_type"],
                    ),
                )
                row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def enqueue_outbox(
        self,
        *,
        aggregate_type: str,
        aggregate_code: str,
        aggregate_revision: int | None,
        event_type: str,
        schema_version: str,
        payload: dict[str, Any],
        occurred_at: datetime,
        trace_id: str | None,
        event_id: UUID | None = None,
    ) -> UUID:
        outbox_id = event_id or uuid4()
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO transactional_outbox_events (
                    event_id, aggregate_type, aggregate_code, aggregate_revision,
                    event_type, schema_version, payload, trace_id, occurred_at,
                    next_attempt_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    outbox_id,
                    aggregate_type,
                    aggregate_code,
                    aggregate_revision,
                    event_type,
                    schema_version,
                    Jsonb(payload),
                    trace_id,
                    occurred_at,
                ),
            )
        return outbox_id

    def claim_outbox_batch(self, *, limit: int, max_attempts: int = 10) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH claimed AS (
                    SELECT id FROM transactional_outbox_events
                    WHERE published_at IS NULL AND dead_lettered_at IS NULL
                      AND COALESCE(next_attempt_at, now()) <= now()
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE transactional_outbox_events AS event
                SET publish_attempts = publish_attempts + 1,
                    next_attempt_at = now() + make_interval(
                        secs => LEAST(300, power(2, LEAST(publish_attempts, 8))::integer)
                    ),
                    dead_lettered_at = CASE
                        WHEN publish_attempts + 1 >= %s THEN now()
                        ELSE dead_lettered_at
                    END
                FROM claimed WHERE event.id = claimed.id
                RETURNING event.*
                """,
                (limit, max_attempts),
            )
            rows = cursor.fetchall()
        self.connection.commit()
        return [self._serialize(row) for row in rows]

    def mark_outbox_published(self, event_id: str) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE transactional_outbox_events
                SET published_at = COALESCE(published_at, now()), last_error_code = NULL
                WHERE event_id = %s AND dead_lettered_at IS NULL
                """,
                (event_id,),
            )
            updated = cursor.rowcount > 0
        self.connection.commit()
        return updated

    def record_outbox_failure(self, event_id: str, *, error_code: str, retry_after: timedelta) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE transactional_outbox_events
                SET last_error_code = %s, next_attempt_at = now() + %s
                WHERE event_id = %s AND published_at IS NULL AND dead_lettered_at IS NULL
                """,
                (error_code, retry_after, event_id),
            )
            updated = cursor.rowcount > 0
        self.connection.commit()
        return updated

    def advance_projection_checkpoint(
        self,
        *,
        projection_name: str,
        projection_version: str,
        event_id: str,
        watermark_occurred_at: datetime,
        lag_seconds: int,
    ) -> dict[str, Any]:
        status = "current" if lag_seconds == 0 else "lagging"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO projection_checkpoints (
                    projection_name, projection_version, last_event_id,
                    watermark_occurred_at, status, lag_seconds
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (projection_name) DO UPDATE
                SET projection_version = EXCLUDED.projection_version,
                    last_event_id = EXCLUDED.last_event_id,
                    watermark_occurred_at = GREATEST(
                        projection_checkpoints.watermark_occurred_at,
                        EXCLUDED.watermark_occurred_at
                    ),
                    status = EXCLUDED.status,
                    lag_seconds = EXCLUDED.lag_seconds,
                    updated_at = now()
                WHERE projection_checkpoints.watermark_occurred_at IS NULL
                   OR projection_checkpoints.watermark_occurred_at <= EXCLUDED.watermark_occurred_at
                RETURNING *
                """,
                (
                    projection_name,
                    projection_version,
                    event_id,
                    watermark_occurred_at,
                    status,
                    lag_seconds,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT * FROM projection_checkpoints WHERE projection_name = %s",
                    (projection_name,),
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
    def _next_code(cursor: Any, *, prefix: str, object_type: str) -> str:
        sequence_date = datetime.now(UTC).date()
        cursor.execute(
            """
            INSERT INTO domain_sequences (sequence_date, object_type, current_value)
            VALUES (%s, %s, 1)
            ON CONFLICT (sequence_date, object_type)
            DO UPDATE SET current_value = domain_sequences.current_value + 1, updated_at = now()
            RETURNING current_value
            """,
            (sequence_date, object_type),
        )
        sequence = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{sequence:06d}"
