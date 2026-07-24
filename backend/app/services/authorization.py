from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from app.domain.contracts import Capability
from app.domain.errors import DomainAuthorizationError, DomainValidationError


EXTERNAL_WRITE_CAPABILITIES = frozenset(
    {
        Capability.WRITE_DRAFT,
        Capability.UPLOAD_ASSET,
        Capability.DELIVER_RELEASE,
        Capability.REBUILD_PROJECTION,
        Capability.GO_LIVE,
    }
)


@dataclass(frozen=True, slots=True)
class AuthorizationClaim:
    authorization_code: str
    principal_id: str
    capability: Capability
    target_type: str
    target_id: str
    plan_or_release_hash: str
    site_fingerprint: str | None
    nonce_hash: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    status: str = "active"
    single_use: bool = True
    consumed_at: datetime | None = None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_authorization_claim(
    *,
    authorization_code: str,
    principal_id: str,
    capability: Capability,
    target_type: str,
    target_id: str,
    plan_or_release_hash: str,
    site_fingerprint: str | None,
    ttl: timedelta,
    now: datetime | None = None,
) -> tuple[AuthorizationClaim, str]:
    if capability not in EXTERNAL_WRITE_CAPABILITIES:
        raise DomainValidationError(
            "AUTHORIZATION_CAPABILITY_NOT_EXTERNAL",
            "ExecutionAuthorization is only issued for external side-effect capabilities",
        )
    if capability is Capability.GO_LIVE:
        raise DomainAuthorizationError(
            "GO_LIVE_CAPABILITY_DISABLED",
            "Go-live authorization cannot be issued while the global capability is disabled",
        )
    if ttl <= timedelta(0) or ttl > timedelta(minutes=15):
        raise DomainValidationError(
            "AUTHORIZATION_TTL_INVALID",
            "ExecutionAuthorization TTL must be greater than zero and no more than 15 minutes",
        )
    if len(plan_or_release_hash) != 64 or any(character not in "0123456789abcdef" for character in plan_or_release_hash):
        raise DomainValidationError("AUTHORIZATION_HASH_INVALID", "Plan or release hash must be lowercase SHA-256")
    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    raw_token = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(24)
    claim = AuthorizationClaim(
        authorization_code=authorization_code,
        principal_id=principal_id,
        capability=capability,
        target_type=target_type,
        target_id=target_id,
        plan_or_release_hash=plan_or_release_hash,
        site_fingerprint=site_fingerprint,
        nonce_hash=token_hash(nonce),
        token_hash=token_hash(raw_token),
        issued_at=issued_at,
        expires_at=issued_at + ttl,
    )
    return claim, raw_token


def consume_authorization_claim(
    claim: AuthorizationClaim,
    *,
    raw_token: str,
    principal_id: str,
    capability: Capability,
    target_type: str,
    target_id: str,
    plan_or_release_hash: str,
    site_fingerprint: str | None,
    now: datetime | None = None,
) -> AuthorizationClaim:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    failures: list[str] = []
    if claim.status != "active":
        failures.append("AUTHORIZATION_NOT_ACTIVE")
    if checked_at >= claim.expires_at:
        failures.append("AUTHORIZATION_EXPIRED")
    if not hmac.compare_digest(claim.token_hash, token_hash(raw_token)):
        failures.append("AUTHORIZATION_TOKEN_INVALID")
    if claim.principal_id != principal_id:
        failures.append("AUTHORIZATION_PRINCIPAL_MISMATCH")
    if claim.capability is not capability:
        failures.append("AUTHORIZATION_CAPABILITY_MISMATCH")
    if claim.target_type != target_type or claim.target_id != target_id:
        failures.append("AUTHORIZATION_TARGET_MISMATCH")
    if not hmac.compare_digest(claim.plan_or_release_hash, plan_or_release_hash):
        failures.append("AUTHORIZATION_HASH_MISMATCH")
    if claim.site_fingerprint != site_fingerprint:
        failures.append("AUTHORIZATION_SITE_FINGERPRINT_MISMATCH")
    if failures:
        raise DomainAuthorizationError(
            failures[0],
            "ExecutionAuthorization verification failed closed",
            details={"failures": failures, "authorization_code": claim.authorization_code},
        )
    return replace(claim, status="consumed", consumed_at=checked_at)

