from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.domain.errors import DomainUnavailableError, DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository


@dataclass(frozen=True, slots=True)
class RetentionResolution:
    policy_code: str
    policy_revision: int
    data_class: str
    retention_days: int | None
    expires_at: datetime | None
    legal_basis: str
    deletion_behavior: dict[str, Any]


class RetentionPolicyService:
    def __init__(self, repository: PrivacyGovernanceRepository):
        self.repository = repository

    def resolve(
        self,
        *,
        data_class: str,
        created_at: datetime,
        requested_days: int | None = None,
    ) -> RetentionResolution:
        if created_at.tzinfo is None:
            raise DomainValidationError(
                "RETENTION_TIMEZONE_REQUIRED",
                "Retention start time must be timezone-aware",
            )
        try:
            policy = self.repository.get_active_retention_policy(data_class)
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "RETENTION_POLICY_UNAVAILABLE",
                "Retention policy is unavailable; no retention decision is made",
            ) from exc
        if policy is None:
            raise DomainUnavailableError(
                "RETENTION_POLICY_UNAVAILABLE",
                "No active retention policy exists for this data class",
            )
        behavior = dict(policy["deletion_behavior"])
        baseline_days = policy["retention_days"]
        range_value = behavior.get("contract_range_days") or behavior.get("purpose_range_days")
        if requested_days is not None:
            if not isinstance(range_value, list) or len(range_value) != 2:
                if baseline_days != requested_days:
                    raise DomainValidationError(
                        "RETENTION_OVERRIDE_DENIED",
                        "This retention policy does not allow a different duration",
                    )
            else:
                lower, upper = (int(range_value[0]), int(range_value[1]))
                if requested_days < lower or requested_days > upper:
                    raise DomainValidationError(
                        "RETENTION_DURATION_OUT_OF_RANGE",
                        "Requested retention is outside the approved policy range",
                        details={"minimum_days": lower, "maximum_days": upper},
                    )
            retention_days = requested_days
        else:
            retention_days = int(baseline_days) if baseline_days is not None else None
        expires_at = created_at + timedelta(days=retention_days) if retention_days is not None else None
        return RetentionResolution(
            policy_code=str(policy["policy_code"]),
            policy_revision=int(policy["revision_number"]),
            data_class=str(policy["data_class"]),
            retention_days=retention_days,
            expires_at=expires_at,
            legal_basis=str(policy["legal_basis"]),
            deletion_behavior=behavior,
        )
