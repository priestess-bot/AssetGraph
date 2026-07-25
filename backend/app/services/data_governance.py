from __future__ import annotations

from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from psycopg.rows import dict_row

from app.domain.contracts import EvidenceLevel, canonical_fingerprint
from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.data_governance import DataGovernanceRepository
from app.schemas.data_governance import (
    DataContractDefinition,
    EvidenceAssignment,
    MetricRevisionDefinition,
    StandardEventBatchIngest,
    StandardEventIngest,
)


class DataGovernanceService:
    def __init__(self, repository: DataGovernanceRepository):
        self.repository = repository

    def put_contract(
        self,
        *,
        contract_code: str,
        revision_number: int,
        owner_principal: str,
        definition: DataContractDefinition,
        activate: bool,
    ) -> dict[str, Any]:
        try:
            Draft202012Validator.check_schema(definition.json_schema)
        except SchemaError as exc:
            raise DomainValidationError(
                "DATA_CONTRACT_JSON_SCHEMA_INVALID",
                "Data contract JSON Schema is invalid",
                details={"message": exc.message},
            ) from exc
        normalized = definition.model_dump(mode="json")
        return self.repository.put_data_contract(
            contract_code=contract_code,
            revision_number=revision_number,
            status="active" if activate else "draft",
            owner_principal=owner_principal,
            definition=normalized,
            fingerprint_sha256=canonical_fingerprint(normalized),
        )

    def put_metric_revision(
        self,
        *,
        metric_code: str,
        expected_revision: int,
        owner_principal: str,
        definition: MetricRevisionDefinition,
        activate: bool,
    ) -> dict[str, Any]:
        normalized = definition.model_dump(mode="json")
        return self.repository.put_metric_revision(
            metric_code=metric_code,
            expected_revision=expected_revision,
            owner_principal=owner_principal,
            definition=normalized,
            fingerprint_sha256=canonical_fingerprint(normalized),
            activate=activate,
        )

    def list_metrics(self) -> list[dict[str, Any]]:
        return self.repository.list_metrics()

    def list_metric_revisions(self, metric_code: str) -> list[dict[str, Any]]:
        return self.repository.list_metric_revisions(metric_code)

    def list_contracts(self) -> list[dict[str, Any]]:
        return self.repository.list_contracts()

    def list_contract_revisions(self, contract_code: str) -> list[dict[str, Any]]:
        return self.repository.list_contract_revisions(contract_code)

    def list_contract_consumers(self, contract_code: str) -> list[dict[str, Any]]:
        return self.repository.list_contract_consumers(contract_code)

    def ingest_event(self, request: StandardEventIngest) -> dict[str, Any]:
        prepared = self._prepare_ingest(request)
        return self.repository.ingest_standard_event(**prepared)

    def _prepare_ingest(
        self,
        request: StandardEventIngest,
        *,
        contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contract = contract or self.repository.get_active_contract(
            request.contract_code, request.contract_revision
        )
        if contract is None:
            raise DomainValidationError(
                "DATA_CONTRACT_NOT_ACTIVE",
                "The requested data contract revision is not active",
            )
        envelope = request.envelope.model_dump(mode="python")
        if envelope["source_system"] != contract["source_system"]:
            raise DomainValidationError(
                "DATA_CONTRACT_SOURCE_MISMATCH",
                "Event source system does not match its data contract",
            )
        if envelope["schema_version"] != contract["schema_version"]:
            raise DomainValidationError(
                "DATA_CONTRACT_SCHEMA_VERSION_UNKNOWN",
                "Event schema version is not accepted by this contract revision",
            )
        allowed_operations = set(contract["upsert_delete_semantics"].get("allowed_operations") or [])
        if envelope["operation"] not in allowed_operations:
            raise DomainValidationError(
                "DATA_CONTRACT_OPERATION_DENIED",
                "Event operation is not allowed by the data contract",
            )
        errors = sorted(
            Draft202012Validator(contract["json_schema"]).iter_errors(envelope["payload"]),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise DomainValidationError(
                "DATA_CONTRACT_PAYLOAD_INVALID",
                "Event payload failed JSON Schema validation",
                details={
                    "violations": [
                        {"path": "/".join(str(part) for part in error.absolute_path), "message": error.message}
                        for error in errors[:20]
                    ]
                },
            )

        quality_status = "accepted"
        quarantine_reason = None
        lateness = envelope["processing_time"] - envelope["event_time"]
        max_lateness = timedelta(seconds=int(contract["lateness_policy"].get("max_lateness_seconds", 0)))
        max_future_skew = timedelta(
            seconds=int(contract["lateness_policy"].get("max_future_clock_skew_seconds", 0))
        )
        if lateness > max_lateness:
            quality_status = "quarantined"
            quarantine_reason = "EVENT_TOO_LATE"
        elif lateness < -max_future_skew:
            quality_status = "quarantined"
            quarantine_reason = "EVENT_TIME_IN_FUTURE"

        fingerprint = canonical_fingerprint(
            {
                "schema_version": envelope["schema_version"],
                "operation": envelope["operation"],
                "entity_type": request.entity_type,
                "entity_id": request.entity_id,
                "event_time": envelope["event_time"],
                "payload": envelope["payload"],
                "tombstone": envelope["tombstone"],
            }
        )
        return {
            "contract_id": contract["id"],
            "envelope": envelope,
            "entity_type": request.entity_type,
            "entity_id": request.entity_id,
            "payload_fingerprint": fingerprint,
            "quality_status": quality_status,
            "quarantine_reason": quarantine_reason,
        }

    def ingest_event_batch(self, request: StandardEventBatchIngest) -> dict[str, Any]:
        contract = self.repository.get_active_contract(
            request.contract_code, request.contract_revision
        )
        if contract is None:
            raise DomainValidationError(
                "DATA_CONTRACT_NOT_ACTIVE",
                "The requested data contract revision is not active",
            )
        source_checksum = canonical_fingerprint(
            {
                "schema_version": "standard-event-batch.v1",
                "contract_code": request.contract_code,
                "contract_revision": request.contract_revision,
                "source_batch_id": request.source_batch_id,
                "source_watermark": request.source_watermark,
                "rows": sorted(
                    [row.model_dump(mode="python") for row in request.rows],
                    key=lambda row: (
                        str(row["envelope"]["source_system"]),
                        str(row["envelope"]["source_event_id"]),
                    ),
                ),
            }
        )
        source_watermark = request.source_watermark or max(
            row.envelope.event_time for row in request.rows
        )
        try:
            with self.repository.connection.cursor(row_factory=dict_row) as cursor:
                batch, replayed = self.repository.begin_quality_batch(
                    cursor,
                    contract_id=contract["id"],
                    source_batch_id=request.source_batch_id,
                    source_checksum=source_checksum,
                    source_watermark=source_watermark,
                )
                if replayed:
                    self.repository.connection.commit()
                    result = self.repository._serialize(batch)
                    result["contract_code"] = request.contract_code
                    result["contract_revision"] = request.contract_revision
                    result["replayed"] = True
                    return result

                accepted_count = 0
                quarantined_count = 0
                rejected_count = 0
                replayed_event_count = 0
                violation_codes: dict[str, int] = {}
                for row in request.rows:
                    event_id = row.envelope.event_id
                    try:
                        prepared = self._prepare_ingest(
                            StandardEventIngest(
                                contract_code=request.contract_code,
                                contract_revision=request.contract_revision,
                                entity_type=row.entity_type,
                                entity_id=row.entity_id,
                                envelope=row.envelope,
                            ),
                            contract=contract,
                        )
                        stored, event_replayed = self.repository.ingest_standard_event_in_cursor(
                            cursor,
                            **prepared,
                            quality_batch_id=batch["id"],
                        )
                        if event_replayed:
                            replayed_event_count += 1
                        if stored["quality_status"] == "quarantined":
                            quarantined_count += 1
                            rule_code = str(stored["quarantine_reason"] or "EVENT_QUARANTINED")
                            violation_codes[rule_code] = violation_codes.get(rule_code, 0) + 1
                            self.repository.add_quality_violation(
                                cursor,
                                batch_id=batch["id"],
                                event_id=event_id,
                                rule_code=rule_code,
                                severity="warning",
                                details={"source_event_id": row.envelope.source_event_id},
                            )
                        else:
                            accepted_count += 1
                    except (DomainValidationError, DomainConflictError) as exc:
                        rejected_count += 1
                        violation_codes[exc.code] = violation_codes.get(exc.code, 0) + 1
                        self.repository.add_quality_violation(
                            cursor,
                            batch_id=batch["id"],
                            event_id=event_id,
                            rule_code=exc.code,
                            severity="error",
                            details={
                                "message": exc.message,
                                "source_event_id": row.envelope.source_event_id,
                                "details": exc.details,
                            },
                        )
                finished = self.repository.finish_quality_batch(
                    cursor,
                    batch_id=batch["id"],
                    row_count=len(request.rows),
                    accepted_count=accepted_count,
                    quarantined_count=quarantined_count,
                    rejected_count=rejected_count,
                    quality_summary={
                        "schema_version": "data-quality-batch.v1",
                        "source_checksum": source_checksum,
                        "replayed_event_count": replayed_event_count,
                        "violation_codes": violation_codes,
                    },
                )
            self.repository.connection.commit()
        except Exception:
            self.repository.connection.rollback()
            raise
        result = self.repository._serialize(finished)
        result["contract_code"] = request.contract_code
        result["contract_revision"] = request.contract_revision
        result["replayed"] = False
        return result

    def list_quality_batches(self) -> list[dict[str, Any]]:
        return self.repository.list_quality_batches()


def validate_evidence_assignment(assignment: EvidenceAssignment) -> EvidenceLevel:
    method_levels = {
        "descriptive_summary": EvidenceLevel.DESCRIPTIVE,
        "cohort_comparison": EvidenceLevel.ASSOCIATIONAL,
        "regression": EvidenceLevel.ASSOCIATIONAL,
        "matched_comparison": EvidenceLevel.ASSOCIATIONAL,
        "difference_in_differences": EvidenceLevel.QUASI_EXPERIMENTAL,
        "regression_discontinuity": EvidenceLevel.QUASI_EXPERIMENTAL,
        "randomized_experiment": EvidenceLevel.RANDOMIZED,
    }
    supported = method_levels.get(assignment.method)
    if supported is None:
        raise DomainValidationError("EVIDENCE_METHOD_UNKNOWN", "Evidence method is not registered")
    order = list(EvidenceLevel)
    if order.index(assignment.declared_level) > order.index(supported):
        raise DomainValidationError(
            "EVIDENCE_LEVEL_UNSUPPORTED",
            "Declared evidence level exceeds the registered method",
        )
    if assignment.declared_level is EvidenceLevel.RANDOMIZED:
        if not assignment.allocation_evidence.get("randomized") or not assignment.allocation_evidence.get(
            "srm_check_passed"
        ):
            raise DomainValidationError(
                "RANDOMIZATION_EVIDENCE_INCOMPLETE",
                "Randomized evidence requires allocation proof and a passing SRM check",
            )
    if assignment.human_override and assignment.declared_level != supported:
        raise DomainValidationError(
            "HUMAN_EVIDENCE_PROMOTION_FORBIDDEN",
            "Human override cannot promote or relabel evidence",
        )
    return assignment.declared_level
