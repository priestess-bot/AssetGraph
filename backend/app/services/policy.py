from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.domain.contracts import Capability, canonical_fingerprint
from app.domain.errors import DomainAuthorizationError, DomainUnavailableError, DomainValidationError
from app.domain.protected_resources import protected_resource_denial
from app.repositories.policy import PolicyRepository
from app.services.authorization import (
    AuthorizationClaim,
    consume_authorization_claim,
    issue_authorization_claim,
)


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    principal_type: str
    principal_id: str
    roles: frozenset[str]
    capability: Capability
    target_type: str
    target_id: str
    action: str
    environment: str
    plan_or_release_hash: str | None = None
    site_fingerprint: str | None = None
    approval_chain: tuple[dict[str, Any], ...] = ()
    trace_id: str | None = None


class PolicyDecisionService:
    """Fail-closed policy decision and commit-time authorization service."""

    def __init__(self, repository: PolicyRepository):
        self.repository = repository

    def decide(
        self,
        request: PolicyRequest,
        *,
        policy_code: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        self._validate_request(request)
        reasons: list[str] = []
        try:
            policy = self.repository.get_active_policy(policy_code)
            flag = self.repository.get_capability_flag(request.capability, request.environment)
            protected = self.repository.get_protected_resource(request.target_type, request.target_id)
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "POLICY_SERVICE_UNAVAILABLE",
                "Policy dependencies are unavailable; access is denied",
            ) from exc

        if policy is None:
            reasons.append("NO_ACTIVE_POLICY")
            effective_policy_code = policy_code or "missing-policy"
            effective_policy_revision = 1
            rules: dict[str, Any] = {}
        else:
            effective_policy_code = str(policy["policy_code"])
            effective_policy_revision = int(policy["revision_number"])
            rules = dict(policy["rules"])

        if request.capability is Capability.GO_LIVE:
            reasons.append("GO_LIVE_GLOBALLY_DISABLED")
        if flag is not None and (not flag["enabled"] or flag["kill_switch_active"]):
            reasons.append("CAPABILITY_KILL_SWITCH_ACTIVE")
        if flag is None and request.capability in {
            Capability.WRITE_DRAFT,
            Capability.UPLOAD_ASSET,
            Capability.DELIVER_RELEASE,
            Capability.REBUILD_PROJECTION,
            Capability.GO_LIVE,
        }:
            reasons.append("CAPABILITY_FLAG_MISSING")

        allowed_capabilities: set[str] = set()
        role_capabilities = rules.get("role_capabilities") or {}
        if isinstance(role_capabilities, dict):
            for role in request.roles:
                values = role_capabilities.get(role) or []
                if isinstance(values, list):
                    allowed_capabilities.update(str(value) for value in values)
        if request.capability.value not in allowed_capabilities:
            reasons.append("ROLE_CAPABILITY_DENIED")

        required_approval_count = int((rules.get("required_approval_count") or {}).get(request.capability.value, 0))
        distinct_approvers = {
            str(item.get("principal_id"))
            for item in request.approval_chain
            if isinstance(item, dict) and item.get("decision") == "approve" and item.get("principal_id")
        }
        if len(distinct_approvers) < required_approval_count:
            reasons.append("APPROVAL_CHAIN_INSUFFICIENT")

        if protection_reason := protected_resource_denial(protected, request.capability):
            reasons.append(protection_reason)

        decision = "deny" if reasons else "allow"
        decision_input = {
            "principal_type": request.principal_type,
            "principal_id": request.principal_id,
            "roles": sorted(request.roles),
            "capability": request.capability,
            "target_type": request.target_type,
            "target_id": request.target_id,
            "action": request.action,
            "environment": request.environment,
            "plan_or_release_hash": request.plan_or_release_hash,
            "site_fingerprint": request.site_fingerprint,
            "approval_chain": request.approval_chain,
            "policy_code": effective_policy_code,
            "policy_revision": effective_policy_revision,
            "protected_resource": protected,
            "capability_flag": flag,
        }
        return self.repository.record_decision(
            principal_type=request.principal_type,
            principal_id=request.principal_id,
            capability=request.capability,
            target_type=request.target_type,
            target_id=request.target_id,
            action=request.action,
            plan_or_release_hash=request.plan_or_release_hash,
            site_fingerprint=request.site_fingerprint,
            policy_code=effective_policy_code,
            policy_revision=effective_policy_revision,
            decision=decision,
            reason_codes=sorted(set(reasons)),
            approval_chain=list(request.approval_chain),
            input_fingerprint=canonical_fingerprint(decision_input),
            trace_id=request.trace_id,
            commit=commit,
        )

    def issue_execution_authorization(
        self,
        request: PolicyRequest,
        *,
        ttl: timedelta,
        policy_code: str | None = None,
        now: datetime | None = None,
        source_human_task_id: str | None = None,
        commit: bool = True,
    ) -> tuple[dict[str, Any], str]:
        if request.plan_or_release_hash is None:
            raise DomainValidationError(
                "AUTHORIZATION_HASH_REQUIRED",
                "External execution authorization requires a plan or release hash",
            )
        decision = self.decide(request, policy_code=policy_code, commit=False)
        if decision["decision"] != "allow":
            # Denials are authoritative audit evidence even when an allowed
            # issuance would otherwise join a caller-owned transaction.
            self.repository.commit()
            raise DomainAuthorizationError(
                "POLICY_DECISION_DENIED",
                "Policy denied the requested execution capability",
                details={"decision_code": decision["decision_code"], "reason_codes": decision["reason_codes"]},
            )
        authorization_code = self._authorization_code(decision["decision_code"])
        claim, raw_token = issue_authorization_claim(
            authorization_code=authorization_code,
            principal_id=request.principal_id,
            capability=request.capability,
            target_type=request.target_type,
            target_id=request.target_id,
            plan_or_release_hash=request.plan_or_release_hash,
            site_fingerprint=request.site_fingerprint,
            ttl=ttl,
            now=now,
        )
        stored = self.repository.persist_authorization(
            decision=decision,
            claim=claim,
            principal_type=request.principal_type,
            source_human_task_id=source_human_task_id,
            commit=commit,
        )
        return stored, raw_token

    def authorize_commit(
        self,
        *,
        authorization_code: str,
        raw_token: str,
        request: PolicyRequest,
        now: datetime | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        self._validate_request(request)
        try:
            stored = self.repository.lock_authorization(authorization_code)
            if stored is None:
                self.repository.rollback()
                raise DomainAuthorizationError("AUTHORIZATION_NOT_FOUND", "Execution authorization was not found")
            current_flag = self.repository.get_capability_flag(request.capability, request.environment)
            protected = self.repository.get_protected_resource(request.target_type, request.target_id)
            current_policy = self.repository.get_active_policy(stored["policy_code"])
        except DomainAuthorizationError:
            raise
        except Exception as exc:
            self.repository.rollback()
            raise DomainUnavailableError(
                "AUTHORIZATION_COMMIT_CHECK_UNAVAILABLE",
                "Commit-time authorization could not be revalidated",
            ) from exc
        if current_flag is None or not current_flag["enabled"] or current_flag["kill_switch_active"]:
            self.repository.rollback()
            raise DomainAuthorizationError(
                "CAPABILITY_DISABLED_AT_COMMIT",
                "Capability is disabled at commit time",
            )
        if current_policy is None or int(current_policy["revision_number"]) != int(stored["policy_revision"]):
            self.repository.rollback()
            raise DomainAuthorizationError(
                "AUTHORIZATION_POLICY_CHANGED",
                "Authorization policy changed before commit",
            )
        if protected_resource_denial(protected, request.capability):
            self.repository.rollback()
            raise DomainAuthorizationError(
                "RESOURCE_PROTECTED_AT_COMMIT",
                "Target resource became protected before commit",
            )
        claim = self._claim_from_row(stored)
        try:
            consume_authorization_claim(
                claim,
                raw_token=raw_token,
                principal_id=request.principal_id,
                capability=request.capability,
                target_type=request.target_type,
                target_id=request.target_id,
                plan_or_release_hash=request.plan_or_release_hash or "",
                site_fingerprint=request.site_fingerprint,
                now=now,
            )
        except DomainAuthorizationError:
            self.repository.rollback()
            raise
        return self.repository.consume_locked_authorization(
            authorization_code,
            consumed_by=request.principal_id,
            commit=commit,
        )

    @staticmethod
    def _authorization_code(decision_code: str) -> str:
        return decision_code.replace("DECISION-", "AUTH-")

    @staticmethod
    def _claim_from_row(row: dict[str, Any]) -> AuthorizationClaim:
        return AuthorizationClaim(
            authorization_code=row["authorization_code"],
            principal_id=row["principal_id"],
            capability=Capability(row["capability"]),
            target_type=row["target_type"],
            target_id=row["target_id"],
            plan_or_release_hash=row["plan_or_release_hash"],
            site_fingerprint=row["site_fingerprint"],
            nonce_hash=row["nonce_hash"],
            token_hash=row["token_hash"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            status=row["status"],
            single_use=bool(row["single_use"]),
            consumed_at=row["consumed_at"],
        )

    @staticmethod
    def _validate_request(request: PolicyRequest) -> None:
        if request.principal_type not in {"user", "worker", "system"}:
            raise DomainValidationError("POLICY_PRINCIPAL_TYPE_INVALID", "Unsupported policy principal type")
        for value, code in (
            (request.plan_or_release_hash, "POLICY_HASH_INVALID"),
            (request.site_fingerprint, "POLICY_SITE_FINGERPRINT_INVALID"),
        ):
            if value is not None and (
                len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            ):
                raise DomainValidationError(code, "Policy hashes must be lowercase SHA-256")
