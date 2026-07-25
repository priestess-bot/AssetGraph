from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import math
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainValidationError


class FunctionalOperationsService:
    def __init__(self, connection: Connection):
        self.connection = connection

    @staticmethod
    def _resolve_metric_definition_refs(
        cursor: Any, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Resolve a user-facing metric pin to the immutable catalog revision."""

        resolved: list[dict[str, Any]] = []
        for reference in payload.get("metric_definition_refs") or []:
            cursor.execute(
                """
                SELECT revisions.metric_code, revisions.revision_number, revisions.name,
                       revisions.grain, revisions.unit, revisions.currency,
                       revisions.value_type, revisions.aggregation,
                       revisions.event_time_field, revisions.timezone,
                       revisions.business_day_boundary, revisions.fingerprint_sha256
                FROM metric_definition_revisions AS revisions
                JOIN metric_definitions AS definitions ON definitions.id = revisions.metric_id
                WHERE revisions.metric_code = %s
                  AND revisions.revision_number = %s
                  AND revisions.status = 'active'
                  AND definitions.status = 'active'
                """,
                (reference["metric_code"], reference["revision_number"]),
            )
            revision = cursor.fetchone()
            if revision is None:
                raise DomainValidationError(
                    "OPERATION_SESSION_METRIC_DEFINITION_NOT_ACTIVE",
                    "The selected metric definition revision is not active",
                    details={
                        "metric_key": reference["metric_key"],
                        "metric_code": reference["metric_code"],
                        "revision_number": reference["revision_number"],
                    },
                )
            resolved.append(
                {
                    "metric_key": reference["metric_key"],
                    "metric_code": revision["metric_code"],
                    "revision_number": int(revision["revision_number"]),
                    "name": revision["name"],
                    "grain": revision["grain"],
                    "unit": revision["unit"],
                    "currency": revision["currency"],
                    "value_type": revision["value_type"],
                    "aggregation": revision["aggregation"],
                    "event_time_field": revision["event_time_field"],
                    "timezone": revision["timezone"],
                    "business_day_boundary": revision["business_day_boundary"],
                    "fingerprint_sha256": revision["fingerprint_sha256"],
                }
            )
        return resolved

    def import_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload["ended_at"] <= payload["started_at"]:
            raise DomainValidationError(
                "OPERATION_SESSION_INTERVAL_INVALID",
                "End time must be after start time",
            )
        try:
            ZoneInfo(payload.get("source_timezone") or "UTC")
        except ZoneInfoNotFoundError as exc:
            raise DomainValidationError(
                "OPERATION_SESSION_TIMEZONE_INVALID",
                "Source timezone must be a valid IANA timezone",
            ) from exc
        with self.connection.cursor(row_factory=dict_row) as cursor:
            external_session_id = payload.get("external_session_id")
            if external_session_id:
                cursor.execute(
                    """SELECT * FROM functional_operation_sessions
                       WHERE platform = %s AND external_session_id = %s""",
                    (payload["platform"], external_session_id),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    # A source replay must remain idempotent even when the catalog
                    # has moved its current metric revision since the first import.
                    self.connection.rollback()
                    return dict(existing)
            metric_definition_refs = self._resolve_metric_definition_refs(cursor, payload)
            plan = None
            plan_code = payload.get("live_room_plan_code")
            if plan_code:
                cursor.execute(
                    """SELECT plan_code, project_code, variant_code, release_code, target_live_room_id
                       FROM functional_live_room_plans WHERE plan_code = %s""",
                    (plan_code,),
                )
                plan = cursor.fetchone()
                if plan is None:
                    raise DomainValidationError(
                        "OPERATION_SESSION_PLAN_NOT_FOUND",
                        "The selected live-room plan does not exist",
                    )
                requested_project = payload.get("content_project_code")
                if requested_project and requested_project != plan["project_code"]:
                    raise DomainValidationError(
                        "OPERATION_SESSION_PROJECT_PLAN_MISMATCH",
                        "The session project must match its live-room plan",
                    )
                requested_target = payload.get("target_resource_id")
                if requested_target and requested_target != plan["target_live_room_id"]:
                    raise DomainValidationError(
                        "OPERATION_SESSION_TARGET_PLAN_MISMATCH",
                        "The session target resource must match its live-room plan",
                    )
            code = self._next(cursor, "OPS", "functional_operation_session")
            cursor.execute(
                """INSERT INTO functional_operation_sessions
                   (session_code,title,platform,external_session_id,account_id,target_resource_id,source_timezone,source_evidence,
                    content_project_code,live_room_plan_code,variant_code,release_code,started_at,ended_at,metrics,metric_definition_refs)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (platform, external_session_id) WHERE external_session_id IS NOT NULL DO NOTHING
                   RETURNING *""",
                (
                    code,
                    payload["title"],
                    payload["platform"],
                    external_session_id,
                    payload.get("account_id"),
                    payload.get("target_resource_id")
                    or (plan["target_live_room_id"] if plan else None),
                    payload.get("source_timezone") or "UTC",
                    Jsonb(payload.get("source_evidence") or {}),
                    plan["project_code"]
                    if plan
                    else payload.get("content_project_code"),
                    plan["plan_code"] if plan else None,
                    plan["variant_code"] if plan else None,
                    plan["release_code"] if plan else None,
                    payload["started_at"],
                    payload["ended_at"],
                    Jsonb(payload.get("metrics") or {}),
                    Jsonb(metric_definition_refs),
                ),
            )
            row = cursor.fetchone()
            if row is None and external_session_id:
                # A concurrent adapter import may have won the external identity
                # after the preflight lookup. Resolve that committed source row.
                cursor.execute(
                    """SELECT * FROM functional_operation_sessions
                       WHERE platform = %s AND external_session_id = %s""",
                    (payload["platform"], external_session_id),
                )
                row = cursor.fetchone()
            if row is None:
                raise DomainValidationError(
                    "OPERATION_SESSION_IDEMPOTENCY_CONFLICT",
                    "Operation session could not be created or resolved by its external identity",
                )
        self.connection.commit()
        return dict(row)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_operation_sessions ORDER BY started_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _json_pointer_value(payload: Any, pointer: str) -> Any:
        """Resolve a RFC 6901 JSON Pointer without interpreting expressions."""

        value = payload
        for segment in pointer[1:].split("/"):
            token = segment.replace("~1", "/").replace("~0", "~")
            if isinstance(value, dict) and token in value:
                value = value[token]
            elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
                value = value[int(token)]
            else:
                raise DomainValidationError(
                    "SESSION_METRIC_SNAPSHOT_SELECTOR_MISSING",
                    "A required JSON Pointer value is missing from a source event",
                    details={"json_pointer": pointer},
                )
        return value

    @classmethod
    def _numeric_pointer_value(
        cls, payload: dict[str, Any], pointer: str, *, event_id: str
    ) -> float:
        raw = cls._json_pointer_value(payload, pointer)
        if isinstance(raw, bool):
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_SELECTOR_NOT_NUMERIC",
                "A selected metric value must be numeric",
                details={"json_pointer": pointer, "event_id": event_id},
            )
        try:
            number = float(Decimal(str(raw)))
        except (InvalidOperation, ValueError) as exc:
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_SELECTOR_NOT_NUMERIC",
                "A selected metric value must be numeric",
                details={"json_pointer": pointer, "event_id": event_id},
            ) from exc
        if not math.isfinite(number):
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_SELECTOR_NOT_NUMERIC",
                "A selected metric value must be finite",
                details={"json_pointer": pointer, "event_id": event_id},
            )
        return number

    @staticmethod
    def _metric_snapshot_definition(
        cursor: Any, *, metric_code: str, revision_number: int
    ) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT revisions.metric_code, revisions.revision_number, revisions.name,
                   revisions.grain, revisions.unit, revisions.currency,
                   revisions.value_type, revisions.aggregation,
                   revisions.event_time_field, revisions.timezone,
                   revisions.business_day_boundary, revisions.deduplication_keys,
                   revisions.event_contract_refs,
                   revisions.fingerprint_sha256
            FROM metric_definition_revisions AS revisions
            JOIN metric_definitions AS definitions ON definitions.id = revisions.metric_id
            WHERE revisions.metric_code = %s
              AND revisions.revision_number = %s
              AND revisions.status = 'active'
              AND definitions.status = 'active'
            """,
            (metric_code, revision_number),
        )
        definition = cursor.fetchone()
        if definition is None:
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_DEFINITION_NOT_ACTIVE",
                "The selected metric definition revision is not active",
                details={
                    "metric_code": metric_code,
                    "revision_number": revision_number,
                },
            )
        if definition["grain"] != "live_session":
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_GRAIN_UNSUPPORTED",
                "Only live_session metric definitions can be computed for an operation session",
                details={"grain": definition["grain"]},
            )
        return dict(definition)

    @staticmethod
    def _metric_definition_ref(
        definition: dict[str, Any], *, metric_key: str
    ) -> dict[str, Any]:
        return {
            "metric_key": metric_key,
            "metric_code": definition["metric_code"],
            "revision_number": int(definition["revision_number"]),
            "name": definition["name"],
            "grain": definition["grain"],
            "unit": definition["unit"],
            "currency": definition["currency"],
            "value_type": definition["value_type"],
            "aggregation": definition["aggregation"],
            "event_time_field": definition["event_time_field"],
            "timezone": definition["timezone"],
            "business_day_boundary": definition["business_day_boundary"],
            "fingerprint_sha256": definition["fingerprint_sha256"],
        }

    @staticmethod
    def _metric_source_contract_refs(definition: dict[str, Any]) -> set[tuple[str, int]]:
        refs: set[tuple[str, int]] = set()
        for reference in definition.get("event_contract_refs") or []:
            if not isinstance(reference, dict):
                continue
            code = reference.get("code")
            revision = reference.get("revision")
            if isinstance(code, str) and isinstance(revision, int):
                refs.add((code, revision))
        if not refs:
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_CONTRACTS_MISSING",
                "The selected metric definition has no usable event contract references",
            )
        return refs

    @classmethod
    def _deduplicate_metric_events(
        cls, events: list[dict[str, Any]], deduplication_keys: list[str]
    ) -> tuple[list[dict[str, Any]], int]:
        """Keep the latest accepted operation for each catalog-defined business key."""

        if not deduplication_keys:
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_DEDUPLICATION_MISSING",
                "The selected metric definition has no deduplication keys",
            )
        latest: dict[str, dict[str, Any]] = {}
        for event in events:
            values: list[Any] = []
            for key in deduplication_keys:
                pointer = (
                    key
                    if key.startswith("/")
                    else f"/{key.replace('~', '~0').replace('/', '~1')}"
                )
                try:
                    values.append(cls._json_pointer_value(event["payload"], pointer))
                except DomainValidationError as exc:
                    raise DomainValidationError(
                        "SESSION_METRIC_SNAPSHOT_DEDUPLICATION_KEY_MISSING",
                        "A catalog deduplication key is missing from a source event",
                        details={
                            "deduplication_key": key,
                            "event_id": str(event["event_id"]),
                        },
                    ) from exc
            latest[canonical_fingerprint(values)] = event
        selected = sorted(
            latest.values(), key=lambda event: (event["event_time"], str(event["event_id"]))
        )
        effective = [event for event in selected if not event["tombstone"]]
        return effective, len(selected) - len(effective)

    @classmethod
    def _aggregate_metric_events(
        cls,
        *,
        aggregation: str,
        events: list[dict[str, Any]],
        value_json_pointer: str | None,
        numerator_json_pointer: str | None,
        denominator_json_pointer: str | None,
    ) -> tuple[float | None, str, dict[str, Any]]:
        if not events:
            return None, "insufficient_data", {"reason": "no_accepted_source_events"}
        if aggregation == "count":
            return float(len(events)), "ready", {}
        if aggregation == "ratio":
            if not numerator_json_pointer or not denominator_json_pointer:
                raise DomainValidationError(
                    "SESSION_METRIC_SNAPSHOT_RATIO_SELECTORS_REQUIRED",
                    "Ratio metrics require numerator and denominator JSON Pointer selectors",
                )
            numerators = [
                cls._numeric_pointer_value(
                    event["payload"], numerator_json_pointer, event_id=str(event["event_id"])
                )
                for event in events
            ]
            denominators = [
                cls._numeric_pointer_value(
                    event["payload"], denominator_json_pointer, event_id=str(event["event_id"])
                )
                for event in events
            ]
            denominator = sum(denominators)
            if denominator == 0:
                return None, "insufficient_data", {"reason": "ratio_denominator_is_zero"}
            return sum(numerators) / denominator, "ready", {
                "numerator": sum(numerators),
                "denominator": denominator,
            }
        if not value_json_pointer:
            raise DomainValidationError(
                "SESSION_METRIC_SNAPSHOT_VALUE_SELECTOR_REQUIRED",
                "This metric aggregation requires a value JSON Pointer selector",
                details={"aggregation": aggregation},
            )
        values = [
            cls._numeric_pointer_value(
                event["payload"], value_json_pointer, event_id=str(event["event_id"])
            )
            for event in events
        ]
        if aggregation == "sum":
            return sum(values), "ready", {}
        if aggregation == "min":
            return min(values), "ready", {}
        if aggregation == "max":
            return max(values), "ready", {}
        if aggregation == "average":
            return sum(values) / len(values), "ready", {}
        if aggregation == "last":
            return values[-1], "ready", {}
        raise DomainValidationError(
            "SESSION_METRIC_SNAPSHOT_AGGREGATION_UNSUPPORTED",
            "The selected metric aggregation is not supported",
            details={"aggregation": aggregation},
        )

    @classmethod
    def _metric_event_buckets(
        cls,
        *,
        aggregation: str,
        events: list[dict[str, Any]],
        value_json_pointer: str | None,
        numerator_json_pointer: str | None,
        denominator_json_pointer: str | None,
    ) -> list[dict[str, Any]]:
        """Materialize only the event contributions safe to intersect with content time."""

        buckets: list[dict[str, Any]] = []
        for event in events:
            bucket: dict[str, Any] = {
                "source_event_id": event["event_id"],
                "event_time": event["event_time"],
                "aggregation": aggregation,
                "allocation_status": "allocatable",
                "value": None,
                "numerator": None,
                "denominator": None,
            }
            if aggregation == "count":
                bucket["value"] = 1.0
            elif aggregation == "ratio":
                if not numerator_json_pointer or not denominator_json_pointer:
                    raise DomainValidationError(
                        "SESSION_METRIC_SNAPSHOT_RATIO_SELECTORS_REQUIRED",
                        "Ratio metrics require numerator and denominator JSON Pointer selectors",
                    )
                numerator = cls._numeric_pointer_value(
                    event["payload"],
                    numerator_json_pointer,
                    event_id=str(event["event_id"]),
                )
                denominator = cls._numeric_pointer_value(
                    event["payload"],
                    denominator_json_pointer,
                    event_id=str(event["event_id"]),
                )
                bucket["numerator"] = numerator
                bucket["denominator"] = denominator
                if denominator:
                    bucket["value"] = numerator / denominator
                else:
                    bucket["allocation_status"] = "session_only"
            else:
                if not value_json_pointer:
                    raise DomainValidationError(
                        "SESSION_METRIC_SNAPSHOT_VALUE_SELECTOR_REQUIRED",
                        "This metric aggregation requires a value JSON Pointer selector",
                        details={"aggregation": aggregation},
                    )
                value = cls._numeric_pointer_value(
                    event["payload"], value_json_pointer, event_id=str(event["event_id"])
                )
                bucket["value"] = value
                if aggregation == "average":
                    bucket["numerator"] = value
                    bucket["denominator"] = 1.0
                elif aggregation in {"min", "max", "last"}:
                    bucket["allocation_status"] = "session_only"
            buckets.append(bucket)
        return buckets

    def create_session_metric_snapshot(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Freeze a session metric computed from quality-accepted event batches."""

        event_time_clock = str(payload.get("event_time_clock", "session_utc")).strip()
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_operation_sessions WHERE session_code = %s FOR UPDATE",
                    (session_code,),
                )
                session = cursor.fetchone()
                if session is None:
                    raise DomainValidationError(
                        "SESSION_METRIC_SNAPSHOT_SESSION_NOT_FOUND",
                        "The operation session does not exist",
                        details={"session_code": session_code},
                    )
                definition = self._metric_snapshot_definition(
                    cursor,
                    metric_code=payload["metric_code"],
                    revision_number=payload["revision_number"],
                )
                contract_refs = self._metric_source_contract_refs(definition)
                cursor.execute(
                    """
                    SELECT event.event_id, event.source_event_id, event.event_time,
                           event.payload, event.payload_fingerprint, event.operation, event.tombstone,
                           contract.contract_code, contract.revision_number,
                           batch.batch_code, batch.source_checksum, batch.status AS batch_status
                    FROM standard_events AS event
                    JOIN data_contracts AS contract ON contract.id = event.contract_id
                    JOIN data_quality_batches AS batch ON batch.id = event.quality_batch_id
                    WHERE event.entity_type = 'live_session'
                      AND event.entity_id = %s
                      AND event.event_time >= %s
                      AND event.event_time < %s
                      AND event.quality_status = 'accepted'
                      AND batch.status IN ('accepted', 'partial_failed')
                    ORDER BY event.event_time, event.event_id
                    """,
                    (session_code, session["started_at"], session["ended_at"]),
                )
                candidate_events = [
                    dict(event)
                    for event in cursor.fetchall()
                    if (str(event["contract_code"]), int(event["revision_number"]))
                    in contract_refs
                ]
                events, tombstoned_key_count = self._deduplicate_metric_events(
                    candidate_events, list(definition["deduplication_keys"] or [])
                )
                value, snapshot_status, aggregation_details = self._aggregate_metric_events(
                    aggregation=definition["aggregation"],
                    events=events,
                    value_json_pointer=payload.get("value_json_pointer"),
                    numerator_json_pointer=payload.get("numerator_json_pointer"),
                    denominator_json_pointer=payload.get("denominator_json_pointer"),
                )
                buckets = (
                    self._metric_event_buckets(
                        aggregation=definition["aggregation"],
                        events=events,
                        value_json_pointer=payload.get("value_json_pointer"),
                        numerator_json_pointer=payload.get("numerator_json_pointer"),
                        denominator_json_pointer=payload.get("denominator_json_pointer"),
                    )
                    if snapshot_status == "ready"
                    else []
                )
                batches: dict[str, dict[str, Any]] = {}
                for event in candidate_events:
                    batch = batches.setdefault(
                        str(event["batch_code"]),
                        {
                            "batch_code": event["batch_code"],
                            "source_checksum": event["source_checksum"],
                            "status": event["batch_status"],
                            "included_event_count": 0,
                        },
                    )
                    batch["included_event_count"] += 1
                source_batches = [batches[key] for key in sorted(batches)]
                metric_ref = self._metric_definition_ref(
                    definition, metric_key=payload["metric_key"]
                )
                input_snapshot = {
                    "schema_version": "functional-session-metric-snapshot.v1",
                    "session": {
                        "session_code": session["session_code"],
                        "started_at": session["started_at"],
                        "ended_at": session["ended_at"],
                    },
                    "metric_definition_ref": metric_ref,
                    "event_time_clock": event_time_clock,
                    "selectors": {
                        "value_json_pointer": payload.get("value_json_pointer"),
                        "numerator_json_pointer": payload.get("numerator_json_pointer"),
                        "denominator_json_pointer": payload.get("denominator_json_pointer"),
                    },
                    "source_events": [
                        {
                            "event_id": event["event_id"],
                            "source_event_id": event["source_event_id"],
                            "event_time": event["event_time"],
                            "contract_code": event["contract_code"],
                            "contract_revision": int(event["revision_number"]),
                            "operation": event["operation"],
                            "tombstone": event["tombstone"],
                            "payload_fingerprint": event["payload_fingerprint"],
                            "batch_code": event["batch_code"],
                            "source_checksum": event["source_checksum"],
                        }
                        for event in candidate_events
                    ],
                    "effective_source_event_ids": [
                        event["event_id"] for event in events
                    ],
                }
                quality_summary = {
                    "schema_version": "functional-session-metric-quality.v1",
                    "source_event_count": len(events),
                    "candidate_event_count": len(candidate_events),
                    "deduplicated_event_count": len(candidate_events) - len(events),
                    "tombstoned_key_count": tombstoned_key_count,
                    "metric_bucket_count": len(buckets),
                    "source_batch_count": len(source_batches),
                    "accepted_event_only": True,
                    "batch_statuses": sorted(
                        {str(batch["status"]) for batch in source_batches}
                    ),
                    **aggregation_details,
                }
                fingerprint = canonical_fingerprint(
                    {
                        "input_snapshot": input_snapshot,
                        "source_batches": source_batches,
                        "quality_summary": quality_summary,
                        "status": snapshot_status,
                        "value": value,
                    }
                )
                code = self._next(cursor, "METRIC-SNAP", "functional_session_metric_snapshot")
                cursor.execute(
                    """INSERT INTO functional_session_metric_snapshots
                       (snapshot_code,session_id,session_code,metric_key,metric_code,metric_revision,
                        aggregation,status,value,source_event_count,value_json_pointer,
                        numerator_json_pointer,denominator_json_pointer,source_batches,quality_summary,
                        input_snapshot,fingerprint_sha256)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING *""",
                    (
                        code,
                        session["id"],
                        session["session_code"],
                        payload["metric_key"],
                        definition["metric_code"],
                        definition["revision_number"],
                        definition["aggregation"],
                        snapshot_status,
                        value,
                        len(events),
                        payload.get("value_json_pointer"),
                        payload.get("numerator_json_pointer"),
                        payload.get("denominator_json_pointer"),
                        Jsonb(source_batches),
                        Jsonb(quality_summary),
                        Jsonb(input_snapshot),
                        fingerprint,
                    ),
                )
                row = cursor.fetchone()
                for bucket in buckets:
                    bucket_code = self._next(
                        cursor, "METRIC-BUCKET", "functional_session_metric_bucket"
                    )
                    bucket_fingerprint = canonical_fingerprint(
                        {
                            "snapshot_code": row["snapshot_code"],
                            "snapshot_fingerprint": row["fingerprint_sha256"],
                            "source_event_id": bucket["source_event_id"],
                            "event_time": bucket["event_time"],
                            "aggregation": bucket["aggregation"],
                            "allocation_status": bucket["allocation_status"],
                            "value": bucket["value"],
                            "numerator": bucket["numerator"],
                            "denominator": bucket["denominator"],
                        }
                    )
                    cursor.execute(
                        """INSERT INTO functional_session_metric_buckets
                           (bucket_code,snapshot_id,snapshot_code,session_code,source_event_id,event_time,
                            aggregation,allocation_status,value,numerator,denominator,fingerprint_sha256)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            bucket_code,
                            row["id"],
                            row["snapshot_code"],
                            session["session_code"],
                            bucket["source_event_id"],
                            bucket["event_time"],
                            bucket["aggregation"],
                            bucket["allocation_status"],
                            bucket["value"],
                            bucket["numerator"],
                            bucket["denominator"],
                            bucket_fingerprint,
                        ),
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        result = dict(row)
        result["event_time_clock"] = event_time_clock
        return result

    def list_session_metric_snapshots(self, session_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT 1 FROM functional_operation_sessions WHERE session_code = %s",
                (session_code,),
            )
            if cursor.fetchone() is None:
                raise DomainValidationError(
                    "SESSION_METRIC_SNAPSHOT_SESSION_NOT_FOUND",
                    "The operation session does not exist",
                    details={"session_code": session_code},
                )
            cursor.execute(
                """SELECT * FROM functional_session_metric_snapshots
                   WHERE session_code = %s
                   ORDER BY created_at DESC, snapshot_code DESC""",
                (session_code,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            snapshot_input = row.get("input_snapshot") or {}
            row["event_time_clock"] = (
                snapshot_input.get("event_time_clock", "session_utc")
                if isinstance(snapshot_input, dict)
                else "session_utc"
            )
        return rows

    @staticmethod
    def _apply_ready_metric_snapshots(
        cursor: Any, sessions: list[dict[str, Any]], *, metric_key: str
    ) -> None:
        """Prefer the latest event-derived value without mutating session imports."""

        session_codes = [str(session["session_code"]) for session in sessions]
        if not session_codes:
            return
        cursor.execute(
            """
            SELECT DISTINCT ON (session_code) *
            FROM functional_session_metric_snapshots
            WHERE session_code = ANY(%s) AND metric_key = %s AND status = 'ready'
            ORDER BY session_code, created_at DESC, snapshot_code DESC
            """,
            (session_codes, metric_key),
        )
        snapshots = {
            str(row["session_code"]): dict(row) for row in cursor.fetchall()
        }
        for session in sessions:
            snapshot = snapshots.get(str(session["session_code"]))
            if snapshot is None:
                continue
            metric_ref = (snapshot.get("input_snapshot") or {}).get(
                "metric_definition_ref"
            )
            if not isinstance(metric_ref, dict):
                continue
            metrics = dict(session.get("metrics") or {})
            metrics[metric_key] = float(snapshot["value"])
            pins = [
                pin
                for pin in (session.get("metric_definition_refs") or [])
                if pin.get("metric_key") != metric_key
            ]
            pins.append(metric_ref)
            session["metrics"] = metrics
            session["metric_definition_refs"] = pins
            session["_metric_snapshot"] = {
                key: snapshot.get(key)
                for key in (
                    "snapshot_code",
                    "metric_key",
                    "metric_code",
                    "metric_revision",
                    "aggregation",
                    "status",
                    "value",
                    "source_event_count",
                    "source_batches",
                    "quality_summary",
                    "input_snapshot",
                    "fingerprint_sha256",
                    "created_at",
                )
            }
            session["_metric_snapshot"]["event_time_clock"] = (
                (snapshot.get("input_snapshot") or {}).get("event_time_clock", "session_utc")
                if isinstance(snapshot.get("input_snapshot"), dict)
                else "session_utc"
            )

    def _exposure_context(
        self,
        cursor: Any,
        payload: dict[str, Any],
        *,
        ignored_exposure_codes: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if payload["ended_at"] <= payload["started_at"]:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_INTERVAL_INVALID",
                "Exposure end time must be after start time",
            )
        cursor.execute(
            "SELECT * FROM functional_operation_sessions WHERE session_code = %s FOR UPDATE",
            (payload["session_code"],),
        )
        session = cursor.fetchone()
        if session is None:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_SESSION_NOT_FOUND",
                "The operation session does not exist",
            )
        if payload["started_at"] < session["started_at"] or payload["ended_at"] > session["ended_at"]:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_OUTSIDE_SESSION",
                "Exposure must be contained by the operation session interval",
            )
        cursor.execute(
            "SELECT plan_code, project_code, variant_code, release_code, blueprint FROM functional_live_room_plans WHERE plan_code = %s",
            (payload["plan_code"],),
        )
        plan = cursor.fetchone()
        if plan is None:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_PLAN_NOT_FOUND",
                "The referenced live-room plan does not exist",
            )
        if session.get("live_room_plan_code") and session["live_room_plan_code"] != plan["plan_code"]:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_SESSION_PLAN_MISMATCH",
                "Session is bound to a different live-room plan",
            )
        scene_codes = {
            str(scene.get("scene_code") or "")
            for scene in (plan["blueprint"] or {}).get("scenes") or []
        }
        if payload["scene_code"] not in scene_codes:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_SCENE_NOT_FOUND",
                "Exposure scene is not in the referenced plan",
            )
        statement = """SELECT exposure_code FROM functional_content_exposures
                       WHERE session_id = %s AND status = 'active'
                         AND started_at < %s AND ended_at > %s"""
        parameters: list[Any] = [session["id"], payload["ended_at"], payload["started_at"]]
        if ignored_exposure_codes:
            statement += " AND exposure_code <> ALL(%s)"
            parameters.append(ignored_exposure_codes)
        cursor.execute(statement, parameters)
        conflicting = [row["exposure_code"] for row in cursor.fetchall()]
        if conflicting:
            raise DomainValidationError(
                "CONTENT_EXPOSURE_OVERLAP_CONFLICT",
                "An active exposure already covers this session interval",
                details={"exposure_codes": conflicting},
            )
        return session, plan

    def _insert_exposure(
        self,
        cursor: Any,
        *,
        session: dict[str, Any],
        plan: dict[str, Any],
        payload: dict[str, Any],
        supersedes_exposure_code: str | None = None,
        correction_reason: str | None = None,
    ) -> dict[str, Any]:
        code = self._next(cursor, "EXPOSURE", "functional_content_exposure")
        cursor.execute(
            """INSERT INTO functional_content_exposures
               (exposure_code,session_id,session_code,plan_code,variant_code,release_code,scene_code,
                started_at,ended_at,source_kind,evidence_note,confidence,supersedes_exposure_code,correction_reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                code,
                session["id"],
                session["session_code"],
                plan["plan_code"],
                plan["variant_code"],
                plan["release_code"],
                payload["scene_code"],
                payload["started_at"],
                payload["ended_at"],
                payload["source_kind"],
                payload["evidence_note"].strip(),
                payload.get("confidence", 0.5),
                supersedes_exposure_code,
                correction_reason,
            ),
        )
        return dict(cursor.fetchone())

    def create_exposure(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                session, plan = self._exposure_context(cursor, payload)
                row = self._insert_exposure(cursor, session=session, plan=plan, payload=payload)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return row

    def correct_exposure(self, payload: dict[str, Any]) -> dict[str, Any]:
        reason = str(payload["reason"]).strip()
        actor = str(payload["actor"]).strip()
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_content_exposures WHERE exposure_code = %s FOR UPDATE",
                    (payload["source_exposure_code"],),
                )
                source = cursor.fetchone()
                if source is None:
                    raise DomainValidationError("CONTENT_EXPOSURE_NOT_FOUND", "The source exposure does not exist")
                if source["status"] != "active":
                    raise DomainValidationError(
                        "CONTENT_EXPOSURE_NOT_ACTIVE",
                        "Only an active exposure can be corrected",
                        details={"status": source["status"]},
                    )
                replacement = None
                if payload["correction_kind"] == "supersede":
                    replacement_payload = payload["replacement"]
                    if replacement_payload["session_code"] != source["session_code"]:
                        raise DomainValidationError(
                            "CONTENT_EXPOSURE_CORRECTION_SESSION_MISMATCH",
                            "Replacement exposure must remain in the same operation session",
                        )
                    session, plan = self._exposure_context(
                        cursor,
                        replacement_payload,
                        ignored_exposure_codes=[source["exposure_code"]],
                    )
                    replacement = self._insert_exposure(
                        cursor,
                        session=session,
                        plan=plan,
                        payload=replacement_payload,
                        supersedes_exposure_code=source["exposure_code"],
                        correction_reason=reason,
                    )
                    cursor.execute(
                        """UPDATE functional_content_exposures
                           SET status = 'superseded', superseded_by_exposure_code = %s, correction_reason = %s
                           WHERE id = %s""",
                        (replacement["exposure_code"], reason, source["id"]),
                    )
                    result = replacement
                else:
                    cursor.execute(
                        """UPDATE functional_content_exposures
                           SET status = 'retracted', correction_reason = %s
                           WHERE id = %s RETURNING *""",
                        (reason, source["id"]),
                    )
                    result = dict(cursor.fetchone())
                correction_code = self._next(cursor, "EXPOSURE-CORR", "functional_content_exposure_correction")
                cursor.execute(
                    """INSERT INTO functional_content_exposure_corrections
                       (correction_code, source_exposure_id, replacement_exposure_id, correction_kind, reason, actor)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        correction_code,
                        source["id"],
                        replacement["id"] if replacement else None,
                        payload["correction_kind"],
                        reason,
                        actor,
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return result

    def list_exposures(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_content_exposures ORDER BY started_at DESC, exposure_code"
            )
            return [dict(row) for row in cursor.fetchall()]

    def create_time_mapping(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_operation_sessions WHERE session_code = %s FOR UPDATE",
                    (session_code,),
                )
                session = cursor.fetchone()
                if session is None:
                    raise DomainValidationError(
                        "TIME_MAPPING_SESSION_NOT_FOUND",
                        "The operation session does not exist",
                    )
                session_duration_ms = round(
                    (session["ended_at"] - session["started_at"]).total_seconds() * 1000
                )
                if payload["coverage_end_ms"] > session_duration_ms:
                    raise DomainValidationError(
                        "TIME_MAPPING_COVERAGE_OUTSIDE_SESSION",
                        "Time mapping coverage must be contained by the operation session",
                        details={
                            "coverage_end_ms": payload["coverage_end_ms"],
                            "session_duration_ms": session_duration_ms,
                        },
                    )
                cursor.execute(
                    """SELECT * FROM functional_session_time_mappings
                       WHERE session_id = %s
                       ORDER BY revision_number DESC LIMIT 1 FOR UPDATE""",
                    (session["id"],),
                )
                current = cursor.fetchone()
                current_revision = int(current["revision_number"]) if current else 0
                if payload["expected_revision"] != current_revision:
                    raise DomainValidationError(
                        "TIME_MAPPING_REVISION_CONFLICT",
                        "The time mapping changed since it was loaded",
                        details={
                            "expected_revision": payload["expected_revision"],
                            "actual_revision": current_revision,
                        },
                    )
                if current is not None and current["status"] == "active":
                    cursor.execute(
                        "UPDATE functional_session_time_mappings SET status = 'superseded' WHERE id = %s",
                        (current["id"],),
                    )
                mapping_code = self._next(
                    cursor, "TIME-MAP", "functional_session_time_mapping"
                )
                cursor.execute(
                    """INSERT INTO functional_session_time_mappings
                       (mapping_code,session_id,session_code,revision_number,status,source_clock,
                        source_kind,source_offset_ms,drift_ppm,coverage_start_ms,coverage_end_ms,
                        evidence_note,actor)
                       VALUES (%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING *""",
                    (
                        mapping_code,
                        session["id"],
                        session["session_code"],
                        current_revision + 1,
                        payload["source_clock"].strip(),
                        payload["source_kind"],
                        payload["source_offset_ms"],
                        payload["drift_ppm"],
                        payload["coverage_start_ms"],
                        payload["coverage_end_ms"],
                        payload["evidence_note"].strip(),
                        payload["actor"].strip(),
                    ),
                )
                row = cursor.fetchone()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return dict(row)

    def list_time_mappings(self, session_code: str) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT * FROM functional_session_time_mappings
                   WHERE session_code = %s
                   ORDER BY revision_number DESC""",
                (session_code,),
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _timeline_content_projections(
        cursor: Any, variant_codes: list[str]
    ) -> dict[tuple[str, str], dict[str, Any]]:
        if not variant_codes:
            return {}
        cursor.execute(
            """
            SELECT variant.variant_code, shot.shot_code,
                   segment.segment_code, segment.program_phase, segment.semantic_goal,
                   segment.product_refs, segment.cta_actions,
                   block.block_code, block.module_type, block.product_ref,
                   block.template_sources, block.cta_intent
            FROM production_variant_revisions AS variant
            JOIN shot_list_revisions AS shot_list
              ON shot_list.id = variant.source_shot_list_revision_id
            JOIN shots AS shot ON shot.shot_list_revision_id = shot_list.id
            JOIN program_segments AS segment ON segment.id = shot.program_segment_id
            LEFT JOIN shot_script_block_sources AS source ON source.shot_id = shot.id
            LEFT JOIN content_script_blocks AS block ON block.id = source.script_block_id
            WHERE variant.variant_code = ANY(%s) AND variant.status = 'confirmed'
            ORDER BY variant.variant_code, shot.shot_code, source.source_order
            """,
            (variant_codes,),
        )
        projections: dict[tuple[str, str], dict[str, Any]] = {}
        for row in cursor.fetchall():
            key = (str(row["variant_code"]), str(row["shot_code"]))
            projection = projections.setdefault(
                key,
                {
                    "status": "resolved",
                    "program_segment": {
                        "segment_code": row["segment_code"],
                        "program_phase": row["program_phase"],
                        "semantic_goal": row["semantic_goal"],
                        "product_refs": row["product_refs"] or [],
                        "cta_actions": row["cta_actions"] or [],
                    },
                    "script_blocks": [],
                },
            )
            if row["block_code"] is None:
                continue
            template_modules = [
                {
                    "template_code": source["template_code"],
                    "revision": source.get("revision"),
                    "module_key": row["module_type"],
                }
                for source in row["template_sources"] or []
                if isinstance(source, dict) and source.get("template_code")
            ]
            projection["script_blocks"].append(
                {
                    "block_code": row["block_code"],
                    "module_type": row["module_type"],
                    "product_ref": row["product_ref"],
                    "template_modules": template_modules,
                    "cta_intent": row["cta_intent"] or {},
                }
            )
        return projections

    def get_content_timeline(self, session_code: str) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_operation_sessions WHERE session_code = %s",
                (session_code,),
            )
            session = cursor.fetchone()
            if session is None:
                raise DomainValidationError(
                    "CONTENT_TIMELINE_SESSION_NOT_FOUND",
                    "The operation session does not exist",
                )
            cursor.execute(
                """SELECT * FROM functional_session_time_mappings
                   WHERE session_code = %s AND status = 'active'
                   ORDER BY revision_number DESC LIMIT 1""",
                (session_code,),
            )
            time_mapping = cursor.fetchone()
            cursor.execute(
                """SELECT exposure_code, plan_code, variant_code, release_code, scene_code,
                          started_at, ended_at, source_kind, confidence
                   FROM functional_content_exposures
                   WHERE session_code = %s AND status = 'active'
                   ORDER BY started_at, exposure_code""",
                (session_code,),
            )
            exposures = [dict(row) for row in cursor.fetchall()]
            plan_codes = sorted({item["plan_code"] for item in exposures})
            plans_by_code: dict[str, dict[str, Any]] = {}
            if plan_codes:
                cursor.execute(
                    """SELECT plan_code, blueprint FROM functional_live_room_plans
                       WHERE plan_code = ANY(%s)""",
                    (plan_codes,),
                )
                plans_by_code = {
                    row["plan_code"]: dict(row) for row in cursor.fetchall()
                }
            content_by_variant_shot = self._timeline_content_projections(
                cursor,
                sorted({str(item["variant_code"]) for item in exposures}),
            )

        total_seconds = (session["ended_at"] - session["started_at"]).total_seconds()
        total_milliseconds = round(total_seconds * 1000)
        observed_seconds = 0.0
        missing_plan_codes: list[str] = []
        spans: list[dict[str, Any]] = []
        for exposure in exposures:
            duration_seconds = (
                exposure["ended_at"] - exposure["started_at"]
            ).total_seconds()
            observed_seconds += duration_seconds
            plan = plans_by_code.get(exposure["plan_code"])
            scene: dict[str, Any] = {
                "scene_code": exposure["scene_code"],
                "status": "missing_plan",
            }
            content: dict[str, Any] = {"status": "missing_plan", "script_blocks": []}
            layers: list[dict[str, Any]] = []
            if plan is None:
                if exposure["plan_code"] not in missing_plan_codes:
                    missing_plan_codes.append(exposure["plan_code"])
            else:
                scenes = (plan["blueprint"] or {}).get("scenes") or []
                source_scene = next(
                    (
                        item
                        for item in scenes
                        if isinstance(item, dict)
                        and item.get("scene_code") == exposure["scene_code"]
                    ),
                    None,
                )
                if source_scene is None:
                    scene["status"] = "missing_scene"
                    content = {"status": "missing_scene", "script_blocks": []}
                else:
                    scene = {
                        "scene_code": source_scene.get("scene_code"),
                        "shot_code": source_scene.get("shot_code"),
                        "title": source_scene.get("title"),
                        "estimated_duration_ms": source_scene.get(
                            "estimated_duration_ms"
                        ),
                        "status": "resolved",
                    }
                    content = content_by_variant_shot.get(
                        (str(exposure["variant_code"]), str(source_scene.get("shot_code") or "")),
                        {"status": "missing_source_projection", "script_blocks": []},
                    )
                    layers = [
                        {
                            "layer_blueprint_code": layer.get("layer_blueprint_code"),
                            "role": layer.get("role") or layer.get("material_role"),
                            "asset_code": layer.get("asset_code"),
                            "execution_capability": layer.get("execution_capability")
                            or (layer.get("asset_binding_ref") or {}).get(
                                "execution_capability"
                            ),
                        }
                        for layer in source_scene.get("layers") or []
                        if isinstance(layer, dict)
                    ]
            spans.append(
                {
                    **exposure,
                    "duration_seconds": duration_seconds,
                    "scene": scene,
                    "content": content,
                    "layers": layers,
                }
            )
        observed_seconds = min(total_seconds, observed_seconds)
        mapped_duration_ms = 0
        mapping = dict(time_mapping) if time_mapping is not None else None
        for span in spans:
            if mapping is None:
                span["alignment_status"] = "unmapped"
                continue
            start_ms = round((span["started_at"] - session["started_at"]).total_seconds() * 1000)
            end_ms = round((span["ended_at"] - session["started_at"]).total_seconds() * 1000)
            scale = 1 + float(mapping["drift_ppm"]) / 1_000_000
            span["source_start_ms"] = round(int(mapping["source_offset_ms"]) + start_ms * scale)
            span["source_end_ms"] = round(int(mapping["source_offset_ms"]) + end_ms * scale)
            coverage_start = int(mapping["coverage_start_ms"])
            coverage_end = int(mapping["coverage_end_ms"])
            overlap_ms = max(0, min(end_ms, coverage_end) - max(start_ms, coverage_start))
            mapped_duration_ms += overlap_ms
            if overlap_ms == end_ms - start_ms:
                span["alignment_status"] = "aligned"
            elif overlap_ms:
                span["alignment_status"] = "partially_aligned"
            else:
                span["alignment_status"] = "outside_coverage"
        return {
            "session_code": session_code,
            "started_at": session["started_at"],
            "ended_at": session["ended_at"],
            "total_seconds": total_seconds,
            "observed_seconds": observed_seconds,
            "coverage_ratio": observed_seconds / total_seconds
            if total_seconds
            else 0.0,
            "unobserved_seconds": max(0.0, total_seconds - observed_seconds),
            "status": "partial" if missing_plan_codes else "resolved",
            "missing_plan_codes": missing_plan_codes,
            "spans": spans,
            "time_mapping": mapping,
            "alignment_coverage_ratio": min(1.0, mapped_duration_ms / total_milliseconds)
            if total_milliseconds
            else 0.0,
        }

    def create_report(
        self,
        payload: dict[str, Any],
        *,
        supersedes_report_code: str | None = None,
    ) -> dict[str, Any]:
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
            self._apply_ready_metric_snapshots(
                cursor, rows, metric_key=payload["metric_key"]
            )
            cursor.execute(
                """SELECT * FROM functional_session_time_mappings
                   WHERE session_code = ANY(%s) AND status = 'active'
                   ORDER BY session_code, revision_number DESC""",
                (codes,),
            )
            time_mappings = {
                str(mapping["session_code"]): dict(mapping)
                for mapping in cursor.fetchall()
            }
            for session in rows:
                mapping = time_mappings.get(str(session["session_code"]))
                if mapping is not None:
                    session["_time_mapping"] = mapping
            metric_definition_ref, metric_definition_state = self._attribution_metric_definition_ref(
                rows, payload["metric_key"]
            )
            cursor.execute(
                """SELECT exposure_code, session_code, plan_code, release_code, scene_code,
                          started_at, ended_at, source_kind, confidence
                   FROM functional_content_exposures
                   WHERE session_code = ANY(%s) AND status = 'active'
                   ORDER BY session_code, started_at, exposure_code""",
                (codes,),
            )
            exposures_by_session: dict[str, list[dict[str, Any]]] = {}
            for exposure in cursor.fetchall():
                exposures_by_session.setdefault(exposure["session_code"], []).append(
                    dict(exposure)
                )

            groups: dict[str, dict[str, Any]] = {}
            source_kind_counts: dict[str, int] = {}
            observed_sessions = 0
            release_bound_exposures = 0
            for session in rows:
                session_code = session["session_code"]
                session_exposures = exposures_by_session.get(session_code, [])
                metric_value = float(
                    (session["metrics"] or {}).get(payload["metric_key"], 0)
                )
                plan_codes = sorted({item["plan_code"] for item in session_exposures})
                if len(plan_codes) == 1:
                    group_key = f"plan:{plan_codes[0]}"
                    scope_type = "live_room_plan"
                    scope_code = plan_codes[0]
                    display_label = f"实际展示计划 {plan_codes[0]}"
                    observed_sessions += 1
                elif plan_codes:
                    group_key = f"mixed:{session_code}"
                    scope_type = "mixed_observed_content"
                    scope_code = session_code
                    display_label = f"混合实际内容 {session_code}"
                    observed_sessions += 1
                else:
                    group_key = f"session_only:{session_code}"
                    scope_type = "session_only"
                    scope_code = session_code
                    display_label = f"未登记实际展示 {session_code}"
                group = groups.setdefault(
                    group_key,
                    {
                        "scope_type": scope_type,
                        "scope_code": scope_code,
                        "display_label": display_label,
                        "values": [],
                        "session_codes": [],
                        "source_evidence": {
                            "exposure_count": 0,
                            "release_bound_exposure_count": 0,
                            "coverage_seconds": 0.0,
                            "source_kind_counts": {},
                            "scene_codes": [],
                            "release_codes": [],
                            "confidence_sum": 0.0,
                        },
                    },
                )
                group["values"].append(metric_value)
                group["session_codes"].append(session_code)
                evidence = group["source_evidence"]
                for exposure in session_exposures:
                    source_kind = exposure["source_kind"]
                    source_kind_counts[source_kind] = (
                        source_kind_counts.get(source_kind, 0) + 1
                    )
                    evidence["exposure_count"] += 1
                    evidence["coverage_seconds"] += (
                        exposure["ended_at"] - exposure["started_at"]
                    ).total_seconds()
                    evidence["confidence_sum"] += float(exposure["confidence"])
                    evidence["source_kind_counts"][source_kind] = (
                        evidence["source_kind_counts"].get(source_kind, 0) + 1
                    )
                    if exposure["scene_code"] not in evidence["scene_codes"]:
                        evidence["scene_codes"].append(exposure["scene_code"])
                    if exposure["release_code"]:
                        release_bound_exposures += 1
                        evidence["release_bound_exposure_count"] += 1
                        if exposure["release_code"] not in evidence["release_codes"]:
                            evidence["release_codes"].append(exposure["release_code"])
            materialized_groups: dict[str, dict[str, Any]] = {}
            for group_key, group in groups.items():
                evidence = group["source_evidence"]
                exposure_count = evidence.pop("exposure_count")
                confidence_sum = evidence.pop("confidence_sum")
                materialized_groups[group_key] = {
                    "scope_type": group["scope_type"],
                    "scope_code": group["scope_code"],
                    "display_label": group["display_label"],
                    "average": sum(group["values"]) / len(group["values"]),
                    "sample_size": len(group["values"]),
                    "session_codes": group["session_codes"],
                    "source_evidence": {
                        **evidence,
                        "exposure_count": exposure_count,
                        "average_confidence": confidence_sum / exposure_count
                        if exposure_count
                        else None,
                    },
                    "limitations": [
                        "Metric remains at operation-session grain and is not allocated to individual scenes.",
                        "This descriptive result does not establish causality.",
                    ],
                }
            scene_allocations = self._scene_allocations(
                rows,
                exposures_by_session,
                metric_key=payload["metric_key"],
            )
            measured_scene_allocations, measured_allocation_summary = (
                self._measured_scene_allocations(cursor, rows, exposures_by_session)
            )
            results = {
                "schema_version": "functional-attribution-report.v2",
                "groups": materialized_groups,
                "scene_allocations": scene_allocations,
                "measured_scene_allocations": measured_scene_allocations,
                "measured_scene_allocation_summary": measured_allocation_summary,
                "metadata": {
                    "method": "session_metric_grouped_by_source_backed_exposure",
                    "metric_grain": "operation_session",
                    "selected_session_count": len(rows),
                    "observed_session_count": observed_sessions,
                    "session_only_count": len(rows) - observed_sessions,
                    "source_kind_counts": source_kind_counts,
                    "release_bound_exposure_count": release_bound_exposures,
                    "evidence_level": "descriptive",
                    "metric_definition_state": metric_definition_state,
                    "scene_allocation_method": "proportional_by_active_observed_exposure_duration",
                    "scene_allocation_count": len(scene_allocations),
                },
            }
            input_snapshot = self._attribution_input_snapshot(
                rows,
                exposures_by_session,
                metric_key=payload["metric_key"],
            )
            quality_snapshot, report_status = self._attribution_quality_snapshot(
                metric_definition_state=metric_definition_state,
                selected_session_count=len(rows),
                observed_session_count=observed_sessions,
                release_bound_exposure_count=release_bound_exposures,
                active_exposure_count=sum(
                    len(items) for items in exposures_by_session.values()
                ),
            )
            fingerprint = canonical_fingerprint(
                {
                    "input_snapshot": input_snapshot,
                    "results": results,
                    "quality_snapshot": quality_snapshot,
                    "evidence_level": "descriptive",
                }
            )
            code = self._next(cursor, "ATTR", "functional_attribution_report")
            cursor.execute(
                """INSERT INTO functional_attribution_reports
                   (report_code,metric_key,session_codes,results,metric_definition_ref,status,
                    input_snapshot,quality_snapshot,fingerprint_sha256,supersedes_report_code)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    code,
                    payload["metric_key"],
                    Jsonb(codes),
                    Jsonb(results),
                    Jsonb(metric_definition_ref) if metric_definition_ref else None,
                    report_status,
                    Jsonb(input_snapshot),
                    Jsonb(quality_snapshot),
                    fingerprint,
                    supersedes_report_code,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return dict(row)

    @staticmethod
    def _attribution_input_snapshot(
        sessions: list[dict[str, Any]],
        exposures_by_session: dict[str, list[dict[str, Any]]],
        *,
        metric_key: str,
    ) -> dict[str, Any]:
        """Freeze the persisted facts that determine one attribution computation."""

        frozen_sessions: list[dict[str, Any]] = []
        frozen_exposures: list[dict[str, Any]] = []
        for session in sorted(sessions, key=lambda item: str(item["session_code"])):
            metric_pins = [
                pin
                for pin in (session.get("metric_definition_refs") or [])
                if pin.get("metric_key") == metric_key
            ]
            frozen_session = {
                "session_code": session["session_code"],
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
                "source_kind": session["source_kind"],
                "import_version": session["import_version"],
                "metric_key": metric_key,
                "metric_value": (session.get("metrics") or {}).get(metric_key),
                "metric_definition_refs": metric_pins,
            }
            if session.get("_metric_snapshot") is not None:
                frozen_session["metric_snapshot"] = session["_metric_snapshot"]
            if session.get("_time_mapping") is not None:
                frozen_session["time_mapping"] = session["_time_mapping"]
            frozen_sessions.append(frozen_session)
            for exposure in exposures_by_session.get(session["session_code"], []):
                frozen_exposures.append(
                    {
                        key: exposure.get(key)
                        for key in (
                            "exposure_code",
                            "session_code",
                            "plan_code",
                            "release_code",
                            "scene_code",
                            "started_at",
                            "ended_at",
                            "source_kind",
                            "confidence",
                        )
                    }
                )
        return {
            "schema_version": "functional-attribution-input.v1",
            "metric_key": metric_key,
            "sessions": frozen_sessions,
            "active_exposures": sorted(
                frozen_exposures,
                key=lambda item: (str(item["session_code"]), str(item["exposure_code"])),
            ),
        }

    @staticmethod
    def _attribution_quality_snapshot(
        *,
        metric_definition_state: str,
        selected_session_count: int,
        observed_session_count: int,
        release_bound_exposure_count: int,
        active_exposure_count: int,
    ) -> tuple[dict[str, Any], str]:
        reasons: list[str] = []
        if metric_definition_state != "resolved":
            reasons.append("metric_definition_not_resolved")
        if not active_exposure_count:
            reasons.append("no_active_content_exposure")
        if observed_session_count != selected_session_count:
            reasons.append("some_sessions_have_no_observed_content")
        if not release_bound_exposure_count:
            reasons.append("no_release_bound_exposure")
        report_status = "review_required" if not reasons else "insufficient_data"
        return (
            {
                "schema_version": "functional-attribution-quality.v1",
                "publication_scope": "descriptive_only",
                "metric_definition_state": metric_definition_state,
                "selected_session_count": selected_session_count,
                "observed_session_count": observed_session_count,
                "active_exposure_count": active_exposure_count,
                "release_bound_exposure_count": release_bound_exposure_count,
                "reasons": reasons,
                "eligible_for_descriptive_publication": report_status == "review_required",
            },
            report_status,
        )

    def rerun_report(self, report_code: str) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """SELECT metric_key, session_codes FROM functional_attribution_reports
                   WHERE report_code = %s""",
                (report_code,),
            )
            source = cursor.fetchone()
        if source is None:
            self.connection.rollback()
            raise DomainValidationError(
                "ATTRIBUTION_REPORT_NOT_FOUND",
                "The attribution report does not exist",
                details={"report_code": report_code},
            )
        return self.create_report(
            {
                "metric_key": source["metric_key"],
                "session_codes": list(source["session_codes"] or []),
            },
            supersedes_report_code=report_code,
        )

    def publish_descriptive_report(self, report_code: str, actor: str) -> dict[str, Any]:
        try:
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT * FROM functional_attribution_reports WHERE report_code = %s FOR UPDATE",
                    (report_code,),
                )
                report = cursor.fetchone()
                if report is None:
                    raise DomainValidationError(
                        "ATTRIBUTION_REPORT_NOT_FOUND",
                        "The attribution report does not exist",
                        details={"report_code": report_code},
                    )
                if report["status"] == "published_descriptive":
                    row = report
                elif report["status"] != "review_required":
                    raise DomainValidationError(
                        "ATTRIBUTION_REPORT_NOT_PUBLISHABLE",
                        "Only a report that passed the descriptive evidence check can be published",
                        details={
                            "status": report["status"],
                            "quality_snapshot": report["quality_snapshot"],
                        },
                    )
                else:
                    cursor.execute(
                        """UPDATE functional_attribution_reports
                           SET status = 'published_descriptive', published_by = %s, published_at = now()
                           WHERE id = %s RETURNING *""",
                        (actor.strip(), report["id"]),
                    )
                    row = cursor.fetchone()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return dict(row)

    @staticmethod
    def _scene_allocations(
        sessions: list[dict[str, Any]],
        exposures_by_session: dict[str, list[dict[str, Any]]],
        *,
        metric_key: str,
    ) -> list[dict[str, Any]]:
        """Allocate session-grain metrics over observed active exposure duration only.

        This is an explicit descriptive aid for inspecting a recorded session, not a
        measured scene-level metric or a causal effect estimate.
        """
        grouped: dict[str, dict[str, Any]] = {}
        for session in sessions:
            session_code = str(session["session_code"])
            exposures = exposures_by_session.get(session_code, [])
            timed_exposures = [
                (
                    exposure,
                    max(0.0, (exposure["ended_at"] - exposure["started_at"]).total_seconds()),
                )
                for exposure in exposures
            ]
            observed_seconds = sum(duration for _exposure, duration in timed_exposures)
            if observed_seconds <= 0:
                continue
            metric_value = float((session.get("metrics") or {}).get(metric_key, 0))
            for exposure, duration_seconds in timed_exposures:
                if duration_seconds <= 0:
                    continue
                plan_code = str(exposure["plan_code"])
                scene_code = str(exposure["scene_code"])
                key = f"{plan_code}:{scene_code}"
                allocation_ratio = duration_seconds / observed_seconds
                item = grouped.setdefault(
                    key,
                    {
                        "scope_type": "observed_scene_duration_allocation",
                        "plan_code": plan_code,
                        "scene_code": scene_code,
                        "estimated_metric_value": 0.0,
                        "observed_duration_seconds": 0.0,
                        "source_session_codes": [],
                        "source_kind_counts": {},
                        "release_codes": [],
                        "weighted_confidence_sum": 0.0,
                    },
                )
                item["estimated_metric_value"] += metric_value * allocation_ratio
                item["observed_duration_seconds"] += duration_seconds
                if session_code not in item["source_session_codes"]:
                    item["source_session_codes"].append(session_code)
                source_kind = str(exposure["source_kind"])
                item["source_kind_counts"][source_kind] = (
                    item["source_kind_counts"].get(source_kind, 0) + 1
                )
                release_code = exposure.get("release_code")
                if release_code and release_code not in item["release_codes"]:
                    item["release_codes"].append(release_code)
                item["weighted_confidence_sum"] += float(exposure["confidence"]) * duration_seconds

        materialized: list[dict[str, Any]] = []
        for item in grouped.values():
            duration_seconds = float(item.pop("observed_duration_seconds"))
            weighted_confidence_sum = float(item.pop("weighted_confidence_sum"))
            materialized.append(
                {
                    **item,
                    "estimated_metric_value": round(float(item["estimated_metric_value"]), 6),
                    "observed_duration_seconds": round(duration_seconds, 3),
                    "source_session_count": len(item["source_session_codes"]),
                    "average_confidence": round(weighted_confidence_sum / duration_seconds, 6)
                    if duration_seconds
                    else None,
                    "allocation_basis": "active_observed_exposure_duration_within_each_session",
                    "limitations": [
                        "This proportionally distributes a session-grain metric by observed duration.",
                        "It is descriptive only and is not a measured scene metric or causal effect.",
                    ],
                }
            )
        return sorted(
            materialized,
            key=lambda item: (-float(item["estimated_metric_value"]), item["plan_code"], item["scene_code"]),
        )

    @staticmethod
    def _bucket_allocation_time(
        bucket: dict[str, Any],
        session: dict[str, Any] | None,
        summary: dict[str, int],
    ) -> tuple[datetime | None, str | None, str | None]:
        if session is None:
            summary["time_mapping_missing_bucket_count"] += 1
            return None, None, None
        snapshot = session.get("_metric_snapshot") or {}
        event_time_clock = (
            snapshot.get("event_time_clock", "session_utc")
            if isinstance(snapshot, dict)
            else "session_utc"
        )
        if event_time_clock == "session_utc":
            summary["direct_session_clock_bucket_count"] += 1
            return bucket["event_time"], None, "event_time_session_utc_within_exposure"
        mapping = session.get("_time_mapping")
        if not isinstance(mapping, dict):
            summary["time_mapping_missing_bucket_count"] += 1
            return None, None, None
        if mapping.get("source_clock") != event_time_clock:
            summary["time_mapping_clock_mismatch_bucket_count"] += 1
            return None, None, None
        scale = 1 + float(mapping["drift_ppm"]) / 1_000_000
        source_elapsed_ms = round(
            (bucket["event_time"] - session["started_at"]).total_seconds() * 1000
        )
        session_elapsed_ms = round(
            (source_elapsed_ms - int(mapping["source_offset_ms"])) / scale
        )
        if not (
            int(mapping["coverage_start_ms"])
            <= session_elapsed_ms
            < int(mapping["coverage_end_ms"])
        ):
            summary["outside_time_mapping_coverage_bucket_count"] += 1
            return None, None, None
        summary["time_mapped_bucket_count"] += 1
        return (
            session["started_at"] + timedelta(milliseconds=session_elapsed_ms),
            str(mapping["mapping_code"]),
            "event_time_inverse_active_time_mapping_within_exposure",
        )

    @classmethod
    def _measured_scene_allocations(
        cls,
        cursor: Any,
        sessions: list[dict[str, Any]],
        exposures_by_session: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Intersect frozen event-time buckets with active observed content intervals."""

        snapshot_codes = sorted(
            {
                str(snapshot["snapshot_code"])
                for session in sessions
                if isinstance(session.get("_metric_snapshot"), dict)
                and (snapshot := session["_metric_snapshot"]).get("snapshot_code")
            }
        )
        summary = {
            "candidate_bucket_count": 0,
            "allocated_bucket_count": 0,
            "unallocated_bucket_count": 0,
            "session_only_bucket_count": 0,
            "direct_session_clock_bucket_count": 0,
            "time_mapped_bucket_count": 0,
            "time_mapping_missing_bucket_count": 0,
            "time_mapping_clock_mismatch_bucket_count": 0,
            "outside_time_mapping_coverage_bucket_count": 0,
        }
        if not snapshot_codes:
            return [], summary
        cursor.execute(
            """
            SELECT bucket_code, snapshot_code, session_code, event_time, aggregation,
                   allocation_status, value, numerator, denominator, fingerprint_sha256
            FROM functional_session_metric_buckets
            WHERE snapshot_code = ANY(%s)
            ORDER BY session_code, event_time, bucket_code
            """,
            (snapshot_codes,),
        )
        grouped: dict[str, dict[str, Any]] = {}
        sessions_by_code = {
            str(session["session_code"]): session for session in sessions
        }
        for row in cursor.fetchall():
            bucket = dict(row)
            summary["candidate_bucket_count"] += 1
            if bucket["allocation_status"] != "allocatable":
                summary["session_only_bucket_count"] += 1
                continue
            allocation_time, mapping_code, allocation_basis = cls._bucket_allocation_time(
                bucket,
                sessions_by_code.get(str(bucket["session_code"])),
                summary,
            )
            if allocation_time is None:
                summary["unallocated_bucket_count"] += 1
                continue
            matches = [
                exposure
                for exposure in exposures_by_session.get(bucket["session_code"], [])
                if exposure["started_at"] <= allocation_time < exposure["ended_at"]
            ]
            if len(matches) != 1:
                summary["unallocated_bucket_count"] += 1
                continue
            exposure = matches[0]
            key = f"{exposure['plan_code']}:{exposure['scene_code']}"
            item = grouped.setdefault(
                key,
                {
                    "scope_type": "measured_event_time_bucket",
                    "plan_code": exposure["plan_code"],
                    "scene_code": exposure["scene_code"],
                    "aggregation": bucket["aggregation"],
                    "value_sum": 0.0,
                    "numerator_sum": 0.0,
                    "denominator_sum": 0.0,
                    "event_count": 0,
                    "source_session_codes": [],
                    "source_snapshot_codes": [],
                    "source_bucket_codes": [],
                    "release_codes": [],
                    "source_time_mapping_codes": [],
                    "allocation_bases": [],
                    "source_kind_counts": {},
                    "confidence_sum": 0.0,
                },
            )
            item["event_count"] += 1
            item["value_sum"] += float(bucket["value"] or 0)
            item["numerator_sum"] += float(bucket["numerator"] or 0)
            item["denominator_sum"] += float(bucket["denominator"] or 0)
            if bucket["session_code"] not in item["source_session_codes"]:
                item["source_session_codes"].append(bucket["session_code"])
            if bucket["snapshot_code"] not in item["source_snapshot_codes"]:
                item["source_snapshot_codes"].append(bucket["snapshot_code"])
            item["source_bucket_codes"].append(bucket["bucket_code"])
            if mapping_code and mapping_code not in item["source_time_mapping_codes"]:
                item["source_time_mapping_codes"].append(mapping_code)
            if allocation_basis and allocation_basis not in item["allocation_bases"]:
                item["allocation_bases"].append(allocation_basis)
            release_code = exposure.get("release_code")
            if release_code and release_code not in item["release_codes"]:
                item["release_codes"].append(release_code)
            source_kind = str(exposure["source_kind"])
            item["source_kind_counts"][source_kind] = (
                item["source_kind_counts"].get(source_kind, 0) + 1
            )
            item["confidence_sum"] += float(exposure["confidence"])
            summary["allocated_bucket_count"] += 1

        materialized: list[dict[str, Any]] = []
        for item in grouped.values():
            aggregation = item.pop("aggregation")
            event_count = int(item.pop("event_count"))
            value_sum = float(item.pop("value_sum"))
            numerator_sum = float(item.pop("numerator_sum"))
            denominator_sum = float(item.pop("denominator_sum"))
            confidence_sum = float(item.pop("confidence_sum"))
            allocation_bases = item.pop("allocation_bases")
            if aggregation == "ratio":
                value = numerator_sum / denominator_sum if denominator_sum else None
            elif aggregation == "average":
                value = numerator_sum / denominator_sum if denominator_sum else None
            else:
                value = value_sum
            materialized.append(
                {
                    **item,
                    "aggregation": aggregation,
                    "measured_metric_value": round(value, 6) if value is not None else None,
                    "numerator": round(numerator_sum, 6) if aggregation in {"ratio", "average"} else None,
                    "denominator": round(denominator_sum, 6) if aggregation in {"ratio", "average"} else None,
                    "event_count": event_count,
                    "source_session_count": len(item["source_session_codes"]),
                    "average_confidence": round(confidence_sum / event_count, 6)
                    if event_count
                    else None,
                    "allocation_basis": allocation_bases[0]
                    if len(allocation_bases) == 1
                    else "mixed_event_time_clock_alignment_within_exposure",
                    "limitations": [
                        "This is a descriptive event-time intersection, not a causal effect.",
                        "Events outside observed content intervals remain unallocated.",
                        "Non-session clocks require an exact active TimeMapping clock match and coverage.",
                    ],
                }
            )
        return (
            sorted(
                materialized,
                key=lambda item: (
                    -(float(item["measured_metric_value"]) if item["measured_metric_value"] is not None else 0),
                    item["plan_code"],
                    item["scene_code"],
                ),
            ),
            summary,
        )

    def list_reports(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM functional_attribution_reports ORDER BY created_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _attribution_metric_definition_ref(
        sessions: list[dict[str, Any]], metric_key: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Return a report pin only when every selected metric uses one catalog revision."""

        pins: list[dict[str, Any]] = []
        for session in sessions:
            if metric_key not in (session.get("metrics") or {}):
                return None, "metric_missing_in_session"
            matching = [
                reference
                for reference in (session.get("metric_definition_refs") or [])
                if reference.get("metric_key") == metric_key
            ]
            if len(matching) != 1:
                return None, "metric_unpinned"
            pins.append(matching[0])
        if not pins:
            return None, "metric_unpinned"
        identity = {
            key: pins[0].get(key)
            for key in ("metric_code", "revision_number", "fingerprint_sha256")
        }
        if any(
            {
                key: pin.get(key)
                for key in ("metric_code", "revision_number", "fingerprint_sha256")
            }
            != identity
            for pin in pins[1:]
        ):
            return None, "metric_pin_mismatch"
        return pins[0], "resolved"

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
