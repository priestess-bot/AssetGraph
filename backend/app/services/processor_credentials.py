from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.contracts import DataClassification, canonical_fingerprint
from app.domain.errors import (
    DomainAuthorizationError,
    DomainUnavailableError,
    DomainValidationError,
)
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.redaction import redact_sensitive_fields


_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_SECRET_REF = re.compile(r"^(?:vault|secret-manager|kms)://[A-Za-z0-9._/-]+$")


@dataclass(frozen=True, slots=True)
class ProcessorPayload:
    payload: dict[str, Any]
    processor_code: str
    processor_revision: int
    audit_code: str
    fields_sent: tuple[str, ...]


class ExternalProcessorService:
    def __init__(self, repository: PrivacyGovernanceRepository):
        self.repository = repository

    def register(
        self,
        *,
        processor_code: str,
        revision_number: int,
        activate: bool,
        purposes: list[str],
        data_classes: list[DataClassification],
        region: str,
        retention_terms: str,
        credential_owner: str,
        rotation_policy: str,
        minimum_fields: dict[str, dict[str, list[str]]],
        exit_plan: str,
        approved_by: str | None,
    ) -> dict[str, Any]:
        if revision_number < 1 or not processor_code:
            raise DomainValidationError("PROCESSOR_REVISION_INVALID", "Processor code and positive revision are required")
        if activate and not approved_by:
            raise DomainValidationError(
                "PROCESSOR_APPROVAL_REQUIRED",
                "Active external processor records require an approver",
            )
        if not purposes or not region or not retention_terms or not credential_owner or not rotation_policy or not exit_plan:
            raise DomainValidationError(
                "PROCESSOR_GOVERNANCE_INCOMPLETE",
                "Processor purpose, region, retention, credential owner, rotation and exit terms are required",
            )
        if DataClassification.CREDENTIAL in data_classes:
            raise DomainValidationError(
                "PROCESSOR_CREDENTIAL_DATA_FORBIDDEN",
                "Credential values cannot be sent to external processors",
            )
        normalized_fields: dict[str, dict[str, list[str]]] = {}
        for purpose in sorted(set(purposes)):
            field_policy = minimum_fields.get(purpose)
            if not isinstance(field_policy, dict):
                raise DomainValidationError(
                    "PROCESSOR_FIELD_POLICY_MISSING",
                    "Every processor purpose requires a minimum-field policy",
                )
            required = sorted(set(field_policy.get("required") or []))
            allowed = sorted(set(field_policy.get("allowed") or []))
            if not required or not set(required) <= set(allowed) or any(
                not _FIELD_PATH.fullmatch(path) for path in allowed
            ):
                raise DomainValidationError(
                    "PROCESSOR_FIELD_POLICY_INVALID",
                    "Required fields must be a non-empty subset of valid allowed field paths",
                )
            normalized_fields[purpose] = {"required": required, "allowed": allowed}
        return self.repository.register_external_processor(
            processor_code=processor_code,
            revision_number=revision_number,
            status="active" if activate else "draft",
            purposes=purposes,
            data_classes=[value.value for value in data_classes],
            region=region,
            retention_terms=retention_terms,
            credential_owner=credential_owner,
            rotation_policy=rotation_policy,
            minimum_fields=normalized_fields,
            exit_plan=exit_plan,
            approved_by=approved_by,
        )

    def prepare_payload(
        self,
        *,
        processor_code: str,
        purpose: str,
        region: str,
        data_classification: DataClassification,
        payload: dict[str, Any],
        principal_id: str,
    ) -> ProcessorPayload:
        try:
            processor = self.repository.get_active_external_processor(processor_code)
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "EXTERNAL_PROCESSOR_REGISTRY_UNAVAILABLE",
                "Processor registry is unavailable; external transmission is denied",
            ) from exc
        reasons: list[str] = []
        revision = int(processor["revision_number"]) if processor else 1
        if processor is None:
            reasons.append("PROCESSOR_NOT_ACTIVE")
            field_policy: dict[str, list[str]] = {}
        else:
            if purpose not in set(processor["purposes"]):
                reasons.append("PROCESSOR_PURPOSE_DENIED")
            if data_classification.value not in set(processor["data_classes"]):
                reasons.append("PROCESSOR_DATA_CLASS_DENIED")
            if region != processor["region"]:
                reasons.append("PROCESSOR_REGION_DENIED")
            field_policy = processor["minimum_fields"].get(purpose) or {}
        required = list(field_policy.get("required") or [])
        allowed = list(field_policy.get("allowed") or [])
        missing = [path for path in required if self._get_path(payload, path)[0] is False]
        if missing:
            reasons.append("PROCESSOR_REQUIRED_FIELD_MISSING")
        projected: dict[str, Any] = {}
        fields_sent: list[str] = []
        if not reasons:
            for path in allowed:
                found, value = self._get_path(payload, path)
                if found:
                    self._set_path(projected, path, value)
                    fields_sent.append(path)
        fingerprint = canonical_fingerprint(projected if not reasons else payload)
        try:
            audit = self.repository.record_external_processor_call(
                processor_code=processor_code,
                processor_revision=revision,
                purpose=purpose,
                region=region,
                data_class=data_classification.value,
                fields_sent=fields_sent,
                payload_fingerprint=fingerprint,
                decision="deny" if reasons else "allow",
                reason_codes=reasons,
                principal_id=principal_id,
            )
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "EXTERNAL_PROCESSOR_AUDIT_UNAVAILABLE",
                "Processor call could not be audited; external transmission is denied",
            ) from exc
        if reasons:
            raise DomainAuthorizationError(
                "EXTERNAL_PROCESSOR_CALL_DENIED",
                "External processor terms do not permit this call",
                details={"audit_code": audit["call_code"], "reason_codes": reasons},
            )
        return ProcessorPayload(
            payload=projected,
            processor_code=processor_code,
            processor_revision=revision,
            audit_code=audit["call_code"],
            fields_sent=tuple(fields_sent),
        )

    @staticmethod
    def _get_path(payload: dict[str, Any], path: str) -> tuple[bool, Any]:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
        return True, current

    @staticmethod
    def _set_path(payload: dict[str, Any], path: str, value: Any) -> None:
        current = payload
        parts = path.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value


class CredentialGovernanceService:
    def __init__(self, repository: PrivacyGovernanceRepository):
        self.repository = repository

    def register(
        self,
        *,
        credential_code: str,
        processor_code: str,
        secret_ref: str,
        allowed_scopes: list[str],
        allowed_regions: list[str],
        credential_owner: str,
        rotation_interval_days: int,
        rotated_at: datetime,
        actor_id: str,
    ) -> dict[str, Any]:
        self._validate_secret_ref(secret_ref)
        if rotated_at.tzinfo is None:
            raise DomainValidationError("CREDENTIAL_TIMEZONE_REQUIRED", "Credential rotation time must be timezone-aware")
        if not allowed_scopes or not allowed_regions or not credential_owner:
            raise DomainValidationError(
                "CREDENTIAL_SCOPE_INVALID",
                "Credential owner, scopes and regions are required",
            )
        processor = self.repository.get_active_external_processor(processor_code)
        if processor is None or processor["region"] not in set(allowed_regions):
            raise DomainValidationError(
                "CREDENTIAL_PROCESSOR_SCOPE_MISMATCH",
                "Credential must bind an active processor in an allowed region",
            )
        return self.repository.register_credential(
            credential_code=credential_code,
            processor_code=processor_code,
            secret_ref=secret_ref,
            allowed_scopes=allowed_scopes,
            allowed_regions=allowed_regions,
            credential_owner=credential_owner,
            rotation_interval_days=rotation_interval_days,
            rotated_at=rotated_at,
            actor_id=actor_id,
        )

    def rotate(
        self,
        credential_code: str,
        *,
        expected_revision: int,
        new_secret_ref: str,
        rotated_at: datetime,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_secret_ref(new_secret_ref)
        if rotated_at.tzinfo is None:
            raise DomainValidationError("CREDENTIAL_TIMEZONE_REQUIRED", "Credential rotation time must be timezone-aware")
        redacted = redact_sensitive_fields(evidence, context="public_evidence")
        if redacted.redacted_paths:
            raise DomainValidationError(
                "CREDENTIAL_EVIDENCE_SENSITIVE",
                "Credential rotation evidence cannot contain secret or personal values",
            )
        return self.repository.rotate_credential(
            credential_code,
            expected_revision=expected_revision,
            new_secret_ref=new_secret_ref,
            rotated_at=rotated_at,
            actor_id=actor_id,
            evidence=evidence,
        )

    def revoke(
        self,
        credential_code: str,
        *,
        expected_revision: int,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        redacted = redact_sensitive_fields(evidence, context="public_evidence")
        if redacted.redacted_paths:
            raise DomainValidationError(
                "CREDENTIAL_EVIDENCE_SENSITIVE",
                "Credential revocation evidence cannot contain secret or personal values",
            )
        return self.repository.revoke_credential(
            credential_code,
            expected_revision=expected_revision,
            actor_id=actor_id,
            evidence=evidence,
        )

    @staticmethod
    def _validate_secret_ref(secret_ref: str) -> None:
        if not _SECRET_REF.fullmatch(secret_ref):
            raise DomainValidationError(
                "CREDENTIAL_SECRET_REF_INVALID",
                "Only an opaque Vault, Secret Manager or KMS reference may be stored",
            )
