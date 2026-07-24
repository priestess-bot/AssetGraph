from __future__ import annotations

from datetime import timedelta
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from app.domain.contracts import EvidenceLevel, canonical_fingerprint
from app.domain.errors import DomainValidationError
from app.repositories.data_governance import DataGovernanceRepository
from app.schemas.data_governance import (
    DataContractDefinition,
    EvidenceAssignment,
    MetricRevisionDefinition,
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
        contract = self.repository.get_active_contract(request.contract_code, request.contract_revision)
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
        return self.repository.ingest_standard_event(
            contract_id=contract["id"],
            envelope=envelope,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
            payload_fingerprint=fingerprint,
            quality_status=quality_status,
            quarantine_reason=quarantine_reason,
        )


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
