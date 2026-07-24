from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint, canonical_json_bytes
from app.domain.errors import DomainConflictError


class IntegrityRepository:
    """Durable integrity checks, alert deduplication and projection consumption ledger."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def record_alert(
        self,
        *,
        alert_type: str,
        severity: str,
        subject_type: str,
        subject_code: str,
        reason_code: str,
        dedupe_key: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = self._upsert_alert(
                cursor,
                alert_type=alert_type,
                severity=severity,
                subject_type=subject_type,
                subject_code=subject_code,
                reason_code=reason_code,
                dedupe_key=dedupe_key,
                evidence=evidence,
            )
        self.connection.commit()
        return self._serialize(row)

    def list_alerts(self, *, include_resolved: bool = False) -> list[dict[str, Any]]:
        clause = "" if include_resolved else "WHERE status <> 'resolved'"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT * FROM evidence_integrity_alerts
                {clause}
                ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                         last_detected_at DESC
                """
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def resolve_alert(
        self,
        alert_code: str,
        *,
        actor_id: str,
        resolution: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE evidence_integrity_alerts
                SET status = 'resolved', resolved_by = %s, resolved_at = now(), resolution = %s
                WHERE alert_code = %s AND status <> 'resolved'
                RETURNING *
                """,
                (actor_id, Jsonb(resolution), alert_code),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row) if row else None

    def consume_projection_event(
        self,
        *,
        projection_name: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload_fingerprint = canonical_fingerprint(payload)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO projection_event_consumptions (
                    projection_name, event_id, payload_fingerprint
                ) VALUES (%s, %s, %s)
                ON CONFLICT (projection_name, event_id) DO NOTHING
                RETURNING *
                """,
                (projection_name, event_id, payload_fingerprint),
            )
            row = cursor.fetchone()
            duplicate = row is None
            if duplicate:
                cursor.execute(
                    """
                    UPDATE projection_event_consumptions
                    SET duplicate_count = duplicate_count + 1, last_seen_at = now()
                    WHERE projection_name = %s AND event_id = %s
                    RETURNING *
                    """,
                    (projection_name, event_id),
                )
                row = cursor.fetchone()
                conflict = row["payload_fingerprint"] != payload_fingerprint
                self._upsert_alert(
                    cursor,
                    alert_type="projection_consumption",
                    severity="critical" if conflict else "warning",
                    subject_type="projection",
                    subject_code=projection_name,
                    reason_code=(
                        "PROJECTION_EVENT_PAYLOAD_CONFLICT"
                        if conflict
                        else "DUPLICATE_EVENT_CONSUMPTION"
                    ),
                    dedupe_key=f"projection:{projection_name}:event:{event_id}",
                    evidence={
                        "event_id": event_id,
                        "stored_payload_fingerprint": row["payload_fingerprint"],
                        "observed_payload_fingerprint": payload_fingerprint,
                        "duplicate_count": row["duplicate_count"],
                    },
                )
        self.connection.commit()
        return {**self._serialize(row), "duplicate": duplicate}

    def scan_operational_integrity(
        self,
        *,
        outbox_replay_threshold: int,
        projection_lag_threshold_seconds: int,
    ) -> dict[str, int]:
        counts = {"outbox": 0, "projection": 0}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM transactional_outbox_events
                WHERE dead_lettered_at IS NOT NULL OR publish_attempts >= %s
                """,
                (outbox_replay_threshold,),
            )
            for event in cursor.fetchall():
                dead = event["dead_lettered_at"] is not None
                self._upsert_alert(
                    cursor,
                    alert_type="outbox_delivery",
                    severity="critical" if dead else "warning",
                    subject_type="outbox_event",
                    subject_code=str(event["event_id"]),
                    reason_code="OUTBOX_DEAD_LETTERED" if dead else "OUTBOX_REPLAY_THRESHOLD_EXCEEDED",
                    dedupe_key=f"outbox:{event['event_id']}",
                    evidence={
                        "publish_attempts": event["publish_attempts"],
                        "last_error_code": event["last_error_code"],
                        "dead_lettered_at": (
                            event["dead_lettered_at"].isoformat()
                            if event["dead_lettered_at"]
                            else None
                        ),
                    },
                )
                counts["outbox"] += 1
            cursor.execute(
                """
                SELECT * FROM projection_checkpoints
                WHERE status IN ('lagging', 'failed') OR lag_seconds >= %s
                """,
                (projection_lag_threshold_seconds,),
            )
            for checkpoint in cursor.fetchall():
                self._upsert_alert(
                    cursor,
                    alert_type="projection_health",
                    severity="critical" if checkpoint["status"] == "failed" else "warning",
                    subject_type="projection",
                    subject_code=checkpoint["projection_name"],
                    reason_code=(
                        "PROJECTION_FAILED"
                        if checkpoint["status"] == "failed"
                        else "PROJECTION_LAG_THRESHOLD_EXCEEDED"
                    ),
                    dedupe_key=f"projection:{checkpoint['projection_name']}:health",
                    evidence={
                        "projection_version": checkpoint["projection_version"],
                        "status": checkpoint["status"],
                        "lag_seconds": checkpoint["lag_seconds"],
                        "watermark_occurred_at": (
                            checkpoint["watermark_occurred_at"].isoformat()
                            if checkpoint["watermark_occurred_at"]
                            else None
                        ),
                    },
                )
                counts["projection"] += 1
            self._record_check(
                cursor,
                check_type="operational_integrity",
                checked_count=counts["outbox"] + counts["projection"],
                failure_count=counts["outbox"] + counts["projection"],
                details=counts,
            )
        self.connection.commit()
        return counts

    def verify_hash_chains(self) -> dict[str, int]:
        report = {"authorization_checked": 0, "effect_checked": 0, "failures": 0}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM execution_authorization_history
                ORDER BY authorization_id, revision, id
                """
            )
            previous_by_authorization: dict[UUID, str | None] = {}
            claim_by_authorization: dict[UUID, str] = {}
            for event in cursor.fetchall():
                previous = previous_by_authorization.get(event["authorization_id"])
                expected = hashlib.sha256(
                    f"{previous or ''}:{event['event_fingerprint']}".encode("utf-8")
                ).hexdigest()
                valid = (
                    event["previous_chain_hash"] == previous
                    and hmac.compare_digest(event["chain_hash"], expected)
                    and claim_by_authorization.get(event["authorization_id"], event["claim_fingerprint"])
                    == event["claim_fingerprint"]
                )
                if not valid:
                    report["failures"] += 1
                    self._upsert_alert(
                        cursor,
                        alert_type="hash_chain",
                        severity="critical",
                        subject_type="execution_authorization",
                        subject_code=event["authorization_code"],
                        reason_code="AUTHORIZATION_HASH_CHAIN_INVALID",
                        dedupe_key=f"authorization:{event['authorization_code']}:hash-chain",
                        evidence={"revision": event["revision"]},
                    )
                previous_by_authorization[event["authorization_id"]] = event["chain_hash"]
                claim_by_authorization.setdefault(event["authorization_id"], event["claim_fingerprint"])
                report["authorization_checked"] += 1

            cursor.execute(
                """
                SELECT history.*, effect.effect_code
                FROM workflow_external_effect_history AS history
                JOIN workflow_external_effects AS effect ON effect.id = history.effect_id
                ORDER BY history.effect_id, history.revision, history.id
                """
            )
            previous_by_effect: dict[UUID, str | None] = {}
            for event in cursor.fetchall():
                previous = previous_by_effect.get(event["effect_id"])
                expected = hashlib.sha256(
                    f"{previous or ''}:{event['event_fingerprint']}".encode("utf-8")
                ).hexdigest()
                valid = event["previous_chain_hash"] == previous and hmac.compare_digest(
                    event["chain_hash"], expected
                )
                if not valid:
                    report["failures"] += 1
                    self._upsert_alert(
                        cursor,
                        alert_type="hash_chain",
                        severity="critical",
                        subject_type="workflow_external_effect",
                        subject_code=event["effect_code"],
                        reason_code="EXTERNAL_EFFECT_HASH_CHAIN_INVALID",
                        dedupe_key=f"effect:{event['effect_code']}:hash-chain",
                        evidence={"revision": event["revision"]},
                    )
                previous_by_effect[event["effect_id"]] = event["chain_hash"]
                report["effect_checked"] += 1
            checked = report["authorization_checked"] + report["effect_checked"]
            self._record_check(
                cursor,
                check_type="append_only_hash_chains",
                checked_count=checked,
                failure_count=report["failures"],
                details=report,
            )
        self.connection.commit()
        return report

    def verify_signed_manifests(self, *, signing_keys: dict[str, bytes]) -> dict[str, int]:
        report = {"run_manifests": 0, "release_manifests": 0, "failures": 0}
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM run_manifests ORDER BY sealed_at, id")
            previous_chain_hash: str | None = None
            for manifest in cursor.fetchall():
                signed_payload = {
                    "schema_version": manifest["schema_version"],
                    "manifest": manifest["manifest"],
                    "input_fingerprint": manifest["input_fingerprint"],
                    "output_fingerprint": manifest["output_fingerprint"],
                }
                key = signing_keys.get(manifest["signature_key_id"])
                expected_chain = hashlib.sha256(
                    f"{previous_chain_hash or ''}:{manifest['manifest_fingerprint']}:{manifest['signature_value']}".encode()
                ).hexdigest()
                valid = bool(
                    key
                    and manifest["previous_chain_hash"] == previous_chain_hash
                    and hmac.compare_digest(manifest["manifest_fingerprint"], canonical_fingerprint(signed_payload))
                    and hmac.compare_digest(
                        manifest["signature_value"],
                        hmac.new(key, canonical_json_bytes(signed_payload), hashlib.sha256).hexdigest(),
                    )
                    and hmac.compare_digest(manifest["chain_hash"], expected_chain)
                )
                if not valid:
                    report["failures"] += 1
                    self._upsert_alert(
                        cursor,
                        alert_type="manifest_signature",
                        severity="critical",
                        subject_type="run_manifest",
                        subject_code=manifest["manifest_code"],
                        reason_code="RUN_MANIFEST_INTEGRITY_INVALID",
                        dedupe_key=f"run-manifest:{manifest['manifest_code']}:integrity",
                        evidence={"signature_key_id": manifest["signature_key_id"]},
                    )
                previous_chain_hash = manifest["chain_hash"]
                report["run_manifests"] += 1

            cursor.execute("SELECT * FROM release_manifests ORDER BY sealed_at, id")
            for manifest in cursor.fetchall():
                payload = {
                    "schema_version": manifest["schema_version"],
                    "carrier_kind": manifest["carrier_kind"],
                    "subject_refs": manifest["subject_refs"],
                    "artifact_refs": manifest["artifact_refs"],
                    "rights_snapshot": manifest["rights_snapshot"],
                    "quality_snapshot": manifest["quality_snapshot"],
                    "lineage_snapshot": manifest["lineage_snapshot"],
                    "carrier_facet": manifest["carrier_facet"],
                }
                key = signing_keys.get(manifest["signature_key_id"])
                valid = bool(
                    key
                    and hmac.compare_digest(manifest["manifest_fingerprint"], canonical_fingerprint(payload))
                    and hmac.compare_digest(
                        manifest["signature_value"],
                        hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest(),
                    )
                )
                if not valid:
                    report["failures"] += 1
                    self._upsert_alert(
                        cursor,
                        alert_type="manifest_signature",
                        severity="critical",
                        subject_type="release_manifest",
                        subject_code=manifest["manifest_code"],
                        reason_code="RELEASE_MANIFEST_SIGNATURE_INVALID",
                        dedupe_key=f"release-manifest:{manifest['manifest_code']}:integrity",
                        evidence={"signature_key_id": manifest["signature_key_id"]},
                    )
                report["release_manifests"] += 1
            checked = report["run_manifests"] + report["release_manifests"]
            self._record_check(
                cursor,
                check_type="signed_manifests",
                checked_count=checked,
                failure_count=report["failures"],
                details=report,
            )
        self.connection.commit()
        return report

    def _upsert_alert(
        self,
        cursor: Any,
        *,
        alert_type: str,
        severity: str,
        subject_type: str,
        subject_code: str,
        reason_code: str,
        dedupe_key: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        alert_code = self._next_code(cursor, "INTEGRITY", "integrity_alert")
        cursor.execute(
            """
            INSERT INTO evidence_integrity_alerts (
                alert_code, alert_type, severity, subject_type, subject_code,
                reason_code, dedupe_key, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedupe_key) DO UPDATE SET
                severity = EXCLUDED.severity,
                status = 'open',
                reason_code = EXCLUDED.reason_code,
                evidence = EXCLUDED.evidence,
                occurrence_count = evidence_integrity_alerts.occurrence_count + 1,
                last_detected_at = now(),
                acknowledged_by = NULL,
                acknowledged_at = NULL,
                resolved_by = NULL,
                resolved_at = NULL,
                resolution = NULL
            RETURNING *
            """,
            (
                alert_code,
                alert_type,
                severity,
                subject_type,
                subject_code,
                reason_code,
                dedupe_key,
                Jsonb(evidence),
            ),
        )
        return cursor.fetchone()

    def _record_check(
        self,
        cursor: Any,
        *,
        check_type: str,
        checked_count: int,
        failure_count: int,
        details: dict[str, Any],
    ) -> None:
        check_code = self._next_code(cursor, "CHECK", "integrity_check")
        status = "passed" if failure_count == 0 else "failed"
        cursor.execute(
            """
            INSERT INTO integrity_check_runs (
                check_code, check_type, status, checked_count, failure_count,
                watermark, details
            ) VALUES (%s, %s, %s, %s, %s, now(), %s)
            """,
            (check_code, check_type, status, checked_count, failure_count, Jsonb(details)),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result

    @staticmethod
    def _next_code(cursor: Any, prefix: str, object_type: str) -> str:
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
        value = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{value:06d}"


def assert_projection_event_is_new(consumption: dict[str, Any]) -> None:
    if consumption["duplicate"]:
        raise DomainConflictError(
            "PROJECTION_EVENT_ALREADY_CONSUMED",
            "Projection event has already been consumed; the duplicate was recorded",
            details={
                "projection_name": consumption["projection_name"],
                "event_id": consumption["event_id"],
                "duplicate_count": consumption["duplicate_count"],
            },
        )
