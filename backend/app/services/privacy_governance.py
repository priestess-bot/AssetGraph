from __future__ import annotations

from dataclasses import dataclass

from app.domain.contracts import DataClassification, canonical_fingerprint
from app.domain.errors import DomainAuthorizationError, DomainUnavailableError, DomainValidationError
from app.repositories.privacy_governance import PrivacyGovernanceRepository


DATA_ACCESS_ACTIONS = frozenset(
    {"export", "decrypt", "batch_query", "model_call", "graph_query", "delete"}
)


@dataclass(frozen=True, slots=True)
class DataAccessRequest:
    principal_id: str
    roles: frozenset[str]
    purpose: str
    action: str
    resource_type: str
    resource_code: str
    data_classification: DataClassification
    trace_id: str | None = None


class DataAccessService:
    def __init__(
        self,
        repository: PrivacyGovernanceRepository,
        *,
        policy_code: str = "baseline-purpose-bound-access",
    ) -> None:
        self.repository = repository
        self.policy_code = policy_code

    def authorize(self, request: DataAccessRequest) -> dict:
        self._validate(request)
        try:
            policy = self.repository.get_active_access_policy(self.policy_code)
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "DATA_ACCESS_POLICY_UNAVAILABLE",
                "Data access policy is unavailable; access is denied",
            ) from exc

        reasons: list[str] = []
        revision = 1
        if policy is None:
            reasons.append("NO_ACTIVE_DATA_ACCESS_POLICY")
            rules: dict = {}
        else:
            revision = int(policy["revision_number"])
            rules = dict(policy["rules"])

        grants_by_role = rules.get("role_grants") or {}
        matching_grant = False
        if isinstance(grants_by_role, dict):
            for role in request.roles:
                grants = grants_by_role.get(role) or []
                if not isinstance(grants, list):
                    continue
                for grant in grants:
                    if not isinstance(grant, dict):
                        continue
                    if (
                        request.purpose in set(grant.get("purposes") or [])
                        and request.action in set(grant.get("actions") or [])
                        and request.data_classification.value in set(grant.get("data_classes") or [])
                    ):
                        matching_grant = True
                        break
                if matching_grant:
                    break
        if not matching_grant:
            reasons.append("ROLE_PURPOSE_ACTION_CLASS_DENIED")

        decision = "deny" if reasons else "allow"
        decision_input = {
            "principal_id": request.principal_id,
            "roles": sorted(request.roles),
            "purpose": request.purpose,
            "action": request.action,
            "resource_type": request.resource_type,
            "resource_code": request.resource_code,
            "data_classification": request.data_classification,
            "policy_code": self.policy_code,
            "policy_revision": revision,
        }
        try:
            recorded = self.repository.record_access_decision(
                principal_id=request.principal_id,
                roles=sorted(request.roles),
                purpose=request.purpose,
                action=request.action,
                resource_type=request.resource_type,
                resource_code=request.resource_code,
                data_class=request.data_classification.value,
                policy_code=self.policy_code,
                policy_revision=revision,
                decision=decision,
                reason_codes=reasons,
                input_fingerprint=canonical_fingerprint(decision_input),
                trace_id=request.trace_id,
            )
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "DATA_ACCESS_AUDIT_UNAVAILABLE",
                "Data access decision could not be audited; access is denied",
            ) from exc
        if decision == "deny":
            raise DomainAuthorizationError(
                "DATA_ACCESS_DENIED",
                "Role, purpose, action and data classification are not jointly authorized",
                details={
                    "decision_code": recorded["decision_code"],
                    "reason_codes": recorded["reason_codes"],
                },
            )
        return recorded

    @staticmethod
    def _validate(request: DataAccessRequest) -> None:
        if not request.principal_id or not request.roles:
            raise DomainValidationError("DATA_ACCESS_PRINCIPAL_INVALID", "Principal and at least one role are required")
        if request.action not in DATA_ACCESS_ACTIONS:
            raise DomainValidationError("DATA_ACCESS_ACTION_INVALID", "Unsupported governed data action")
        for value in (request.purpose, request.resource_type, request.resource_code):
            if not value or len(value) > 255:
                raise DomainValidationError("DATA_ACCESS_TARGET_INVALID", "Purpose and target must be bounded non-empty values")
