from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository
from app.services.redaction import redact_sensitive_fields


DELETION_OUTCOMES = frozenset(
    {"deleted", "tombstoned", "retained_legal_hold", "not_found", "failed"}
)


class DeletionGovernanceService:
    def __init__(self, repository: PrivacyGovernanceRepository):
        self.repository = repository

    def create_legal_hold(
        self,
        *,
        subject_type: str,
        subject_code: str,
        scope: dict[str, Any],
        reason: str,
        evidence_refs: list[dict[str, Any]],
        owner_principal: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        if expires_at.tzinfo is None or expires_at <= datetime.now(UTC):
            raise DomainValidationError(
                "LEGAL_HOLD_EXPIRY_REQUIRED",
                "Legal hold requires a future timezone-aware expiry",
            )
        if not scope or not reason or not owner_principal:
            raise DomainValidationError(
                "LEGAL_HOLD_FIELDS_REQUIRED",
                "Legal hold owner, scope and reason are required",
            )
        return self.repository.create_legal_hold(
            subject_type=subject_type,
            subject_code=subject_code,
            scope=scope,
            reason=reason,
            evidence_refs=evidence_refs,
            owner_principal=owner_principal,
            expires_at=expires_at,
        )

    def request_deletion(
        self,
        *,
        subject_type: str,
        subject_code: str,
        targets: list[dict[str, str]],
        required_processors: list[str],
        requested_by: str,
    ) -> dict[str, Any]:
        normalized_targets: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for target in targets:
            normalized = {
                "target_type": str(target.get("target_type") or "").strip(),
                "target_code": str(target.get("target_code") or "").strip(),
                "source_system": str(target.get("source_system") or "").strip(),
            }
            key = (normalized["target_type"], normalized["target_code"], normalized["source_system"])
            if not all(key):
                raise DomainValidationError(
                    "DELETION_TARGET_INVALID",
                    "Every deletion target requires type, code and source system",
                )
            if key not in seen:
                seen.add(key)
                normalized_targets.append(normalized)
        processors = sorted({value.strip() for value in required_processors if value.strip()})
        if not normalized_targets or not processors:
            raise DomainValidationError(
                "DELETION_SCOPE_EMPTY",
                "Deletion requires at least one target and one downstream processor",
            )
        requested_scope = {"targets": sorted(normalized_targets, key=lambda item: tuple(item.values()))}
        identity = {
            "subject_type": subject_type,
            "subject_code": subject_code,
            "requested_scope": requested_scope,
            "required_processors": processors,
            "requested_by": requested_by,
        }
        return self.repository.create_deletion_run(
            subject_type=subject_type,
            subject_code=subject_code,
            requested_scope=requested_scope,
            required_processors=processors,
            requested_by=requested_by,
            request_fingerprint=canonical_fingerprint(identity),
        )

    def record_receipt(
        self,
        deletion_run_code: str,
        *,
        processor: str,
        target_type: str,
        target_code: str,
        outcome: str,
        retention_basis: str | None,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if outcome not in DELETION_OUTCOMES:
            raise DomainValidationError("DELETION_OUTCOME_INVALID", "Unsupported deletion receipt outcome")
        redaction = redact_sensitive_fields(evidence, context="public_evidence")
        if redaction.redacted_paths:
            raise DomainValidationError(
                "DELETION_RECEIPT_EVIDENCE_SENSITIVE",
                "Deletion receipt evidence must not contain credentials or raw personal fields",
                details={"redacted_paths": list(redaction.redacted_paths)},
            )
        if outcome == "retained_legal_hold" and not retention_basis:
            raise DomainValidationError(
                "DELETION_RETENTION_BASIS_REQUIRED",
                "Retained targets require a legal retention basis",
            )
        return self.repository.record_deletion_receipt(
            deletion_run_code,
            processor=processor,
            target_type=target_type,
            target_code=target_code,
            outcome=outcome,
            retention_basis=retention_basis,
            evidence=evidence,
        )
