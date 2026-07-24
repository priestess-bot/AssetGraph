from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import Capability, canonical_fingerprint
from app.domain.errors import DomainAuthorizationError, DomainConflictError, DomainValidationError
from app.services.authorization import AuthorizationClaim


class PolicyRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def get_active_policy(self, policy_code: str | None = None) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            if policy_code is None:
                cursor.execute(
                    """
                    SELECT * FROM capability_policy_versions
                    WHERE status = 'active'
                    ORDER BY approved_at DESC, revision_number DESC
                    LIMIT 1
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM capability_policy_versions
                    WHERE status = 'active' AND policy_code = %s
                    ORDER BY revision_number DESC
                    LIMIT 1
                    """,
                    (policy_code,),
                )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def get_capability_flag(self, capability: Capability, environment: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM capability_flags
                WHERE capability = %s AND environment IN (%s, '*')
                ORDER BY CASE WHEN environment = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (capability.value, environment, environment),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def get_protected_resource(self, target_type: str, target_id: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM protected_resources
                WHERE resource_type = %s AND resource_id = %s
                  AND revoked_at IS NULL AND effective_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (target_type, target_id),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def list_protected_resources(
        self,
        *,
        resource_type: str | None = None,
        include_revoked: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        predicates: list[str] = []
        parameters: list[Any] = []
        if resource_type is not None:
            predicates.append("resource.resource_type = %s")
            parameters.append(resource_type)
        if not include_revoked:
            predicates.extend(
                (
                    "resource.revoked_at IS NULL",
                    "resource.effective_at <= now()",
                    "(resource.expires_at IS NULL OR resource.expires_at > now())",
                )
            )
        where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        parameters.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT resource.*, COALESCE(MAX(event.revision), 0) AS revision
                FROM protected_resources AS resource
                LEFT JOIN protected_resource_events AS event
                  ON event.protected_resource_id = resource.id
                {where}
                GROUP BY resource.id
                ORDER BY resource.created_at DESC, resource.resource_type, resource.resource_id
                LIMIT %s OFFSET %s
                """,
                parameters,
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def register_protected_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        protection_mode: str,
        allowed_capabilities: list[str],
        reason_code: str,
        evidence: dict[str, Any],
        effective_at: datetime | None,
        expires_at: datetime | None,
        actor_id: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if protection_mode not in {"read_only", "deny_write", "allowlisted_write"}:
            raise DomainValidationError("PROTECTION_MODE_INVALID", "Unsupported protected-resource mode")
        if protection_mode != "allowlisted_write" and allowed_capabilities:
            raise DomainValidationError(
                "PROTECTION_ALLOWLIST_INVALID",
                "Only allowlisted_write resources may declare allowed capabilities",
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT resource.*,
                       COALESCE((SELECT MAX(event.revision)
                                 FROM protected_resource_events AS event
                                 WHERE event.protected_resource_id = resource.id), 0) AS revision
                FROM protected_resources AS resource
                WHERE resource_type = %s AND resource_id = %s
                FOR UPDATE
                """,
                (resource_type, resource_id),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if bool((existing["evidence"] or {}).get("system_locked")):
                    self.connection.rollback()
                    raise DomainAuthorizationError(
                        "PROTECTED_RESOURCE_SYSTEM_LOCKED",
                        "System-locked protected resources cannot be changed",
                    )
                current_revision = int(existing["revision"])
                if expected_revision is None or expected_revision != current_revision:
                    self.connection.rollback()
                    raise DomainConflictError(
                        "PROTECTED_RESOURCE_REVISION_CONFLICT",
                        "Protected-resource revision changed or was not supplied",
                        details={"current_revision": current_revision},
                    )
                event_type = "registered" if existing["revoked_at"] is not None else "updated"
                revision = current_revision + 1
                cursor.execute(
                    """
                    UPDATE protected_resources
                    SET protection_mode = %s, allowed_capabilities = %s,
                        reason_code = %s, evidence = %s,
                        effective_at = COALESCE(%s, now()), expires_at = %s,
                        revoked_at = NULL, created_by = %s, created_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        protection_mode,
                        Jsonb(sorted(set(allowed_capabilities))),
                        reason_code,
                        Jsonb(evidence),
                        effective_at,
                        expires_at,
                        actor_id,
                        existing["id"],
                    ),
                )
                row = cursor.fetchone()
            else:
                if expected_revision is not None:
                    self.connection.rollback()
                    raise DomainConflictError(
                        "PROTECTED_RESOURCE_NOT_FOUND",
                        "Expected protected-resource revision does not exist",
                    )
                revision = 1
                event_type = "registered"
                cursor.execute(
                    """
                    INSERT INTO protected_resources (
                        resource_type, resource_id, protection_mode, allowed_capabilities,
                        reason_code, evidence, effective_at, expires_at, created_by
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s, %s)
                    RETURNING *
                    """,
                    (
                        resource_type,
                        resource_id,
                        protection_mode,
                        Jsonb(sorted(set(allowed_capabilities))),
                        reason_code,
                        Jsonb(evidence),
                        effective_at,
                        expires_at,
                        actor_id,
                    ),
                )
                row = cursor.fetchone()
            self._append_protected_resource_event(
                cursor,
                resource=row,
                revision=revision,
                event_type=event_type,
                actor_id=actor_id,
            )
        self.connection.commit()
        result = self._serialize(row)
        result["revision"] = revision
        return result

    def revoke_protected_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
        expected_revision: int,
        reason_code: str,
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT resource.*,
                       COALESCE((SELECT MAX(event.revision)
                                 FROM protected_resource_events AS event
                                 WHERE event.protected_resource_id = resource.id), 0) AS revision
                FROM protected_resources AS resource
                WHERE resource_type = %s AND resource_id = %s
                FOR UPDATE
                """,
                (resource_type, resource_id),
            )
            row = cursor.fetchone()
            if row is None or row["revoked_at"] is not None:
                self.connection.rollback()
                raise DomainConflictError("PROTECTED_RESOURCE_NOT_ACTIVE", "Protected resource is not active")
            if bool((row["evidence"] or {}).get("system_locked")):
                self.connection.rollback()
                raise DomainAuthorizationError(
                    "PROTECTED_RESOURCE_SYSTEM_LOCKED",
                    "System-locked protected resources cannot be revoked",
                )
            current_revision = int(row["revision"])
            if current_revision != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "PROTECTED_RESOURCE_REVISION_CONFLICT",
                    "Protected-resource revision changed",
                    details={"current_revision": current_revision},
                )
            cursor.execute(
                "UPDATE protected_resources SET revoked_at = now() WHERE id = %s RETURNING *",
                (row["id"],),
            )
            revoked = cursor.fetchone()
            event_resource = dict(revoked)
            event_resource["reason_code"] = reason_code
            self._append_protected_resource_event(
                cursor,
                resource=event_resource,
                revision=current_revision + 1,
                event_type="revoked",
                actor_id=actor_id,
            )
        self.connection.commit()
        result = self._serialize(revoked)
        result["revision"] = current_revision + 1
        return result

    def record_decision(
        self,
        *,
        principal_type: str,
        principal_id: str,
        capability: Capability,
        target_type: str,
        target_id: str,
        action: str,
        plan_or_release_hash: str | None,
        site_fingerprint: str | None,
        policy_code: str,
        policy_revision: int,
        decision: str,
        reason_codes: list[str],
        approval_chain: list[dict[str, Any]],
        input_fingerprint: str,
        trace_id: str | None,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            decision_code = self._next_code(cursor, prefix="DECISION", object_type="policy_decision")
            cursor.execute(
                """
                INSERT INTO policy_decisions (
                    decision_code, principal_type, principal_id, capability,
                    target_type, target_id, action, plan_or_release_hash,
                    site_fingerprint, policy_code, policy_revision, decision,
                    reason_codes, approval_chain, input_fingerprint, trace_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    decision_code,
                    principal_type,
                    principal_id,
                    capability.value,
                    target_type,
                    target_id,
                    action,
                    plan_or_release_hash,
                    site_fingerprint,
                    policy_code,
                    policy_revision,
                    decision,
                    Jsonb(reason_codes),
                    Jsonb(approval_chain),
                    input_fingerprint,
                    trace_id,
                ),
            )
            row = cursor.fetchone()
        if commit:
            self.connection.commit()
        return self._serialize(row)

    def persist_authorization(
        self,
        *,
        decision: dict[str, Any],
        claim: AuthorizationClaim,
        principal_type: str,
        source_human_task_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                INSERT INTO execution_authorizations (
                    authorization_code, decision_id, decision_code, principal_type,
                    principal_id, capability, target_type, target_id,
                    plan_or_release_hash, site_fingerprint, nonce_hash, token_hash,
                    status, single_use, issued_at, expires_at, source_human_task_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'active', %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    claim.authorization_code,
                    decision["id"],
                    decision["decision_code"],
                    principal_type,
                    claim.principal_id,
                    claim.capability.value,
                    claim.target_type,
                    claim.target_id,
                    claim.plan_or_release_hash,
                    claim.site_fingerprint,
                    claim.nonce_hash,
                    claim.token_hash,
                    claim.single_use,
                    claim.issued_at,
                    claim.expires_at,
                    source_human_task_id,
                ),
            )
            row = cursor.fetchone()
            self._append_authorization_history(
                cursor,
                authorization=row,
                event_type="issued",
                actor_type=principal_type,
                actor_id=claim.principal_id,
                event_payload={"decision_code": decision["decision_code"]},
            )
        if commit:
            self.connection.commit()
        return self._serialize(row)

    def lock_authorization(self, authorization_code: str) -> dict[str, Any] | None:
        cursor = self.connection.cursor(row_factory=dict_row)
        cursor.execute(
            """
            SELECT auth.*, decision.policy_code, decision.policy_revision
            FROM execution_authorizations AS auth
            JOIN policy_decisions AS decision ON decision.id = auth.decision_id
            WHERE auth.authorization_code = %s
            FOR UPDATE OF auth
            """,
            (authorization_code,),
        )
        row = cursor.fetchone()
        cursor.close()
        return self._serialize(row) if row else None

    def consume_locked_authorization(
        self,
        authorization_code: str,
        *,
        consumed_by: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE execution_authorizations
                SET status = 'consumed', consumed_at = now(), consumed_by = %s
                WHERE authorization_code = %s AND status = 'active'
                RETURNING *
                """,
                (consumed_by, authorization_code),
            )
            row = cursor.fetchone()
            if row is None:
                self.connection.rollback()
                raise DomainConflictError("AUTHORIZATION_CONSUME_RACE", "Authorization is no longer active")
            self._append_authorization_history(
                cursor,
                authorization=row,
                event_type="consumed",
                actor_type=row["principal_type"],
                actor_id=consumed_by,
                event_payload={"consumed_at": row["consumed_at"].isoformat()},
            )
        if commit:
            self.connection.commit()
        return self._serialize(row)

    def revoke_authorization(self, authorization_code: str, *, actor_id: str, reason: str) -> bool:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE execution_authorizations
                SET status = 'revoked', revoked_at = now(), revoked_by = %s,
                    revocation_reason = %s
                WHERE authorization_code = %s AND status = 'active'
                RETURNING *
                """,
                (actor_id, reason, authorization_code),
            )
            row = cursor.fetchone()
            updated = row is not None
            if row is not None:
                self._append_authorization_history(
                    cursor,
                    authorization=row,
                    event_type="revoked",
                    actor_type="user",
                    actor_id=actor_id,
                    event_payload={"reason": reason},
                )
        self.connection.commit()
        return updated

    def rollback(self) -> None:
        self.connection.rollback()

    def commit(self) -> None:
        self.connection.commit()

    @staticmethod
    def _append_protected_resource_event(
        cursor: Any,
        *,
        resource: dict[str, Any],
        revision: int,
        event_type: str,
        actor_id: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO protected_resource_events (
                protected_resource_id, resource_type, resource_id, revision,
                event_type, protection_mode, allowed_capabilities, reason_code,
                evidence, actor_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                resource["id"],
                resource["resource_type"],
                resource["resource_id"],
                revision,
                event_type,
                resource["protection_mode"],
                Jsonb(resource.get("allowed_capabilities") or []),
                resource["reason_code"],
                Jsonb(resource.get("evidence") or {}),
                actor_id,
            ),
        )

    @staticmethod
    def _append_authorization_history(
        cursor: Any,
        *,
        authorization: dict[str, Any],
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        event_payload: dict[str, Any],
    ) -> None:
        claim_payload = {
            "authorization_code": authorization["authorization_code"],
            "principal_type": authorization["principal_type"],
            "principal_id": authorization["principal_id"],
            "capability": authorization["capability"],
            "target_type": authorization["target_type"],
            "target_id": authorization["target_id"],
            "plan_or_release_hash": authorization["plan_or_release_hash"],
            "site_fingerprint": authorization["site_fingerprint"],
            "nonce_hash": authorization["nonce_hash"],
            "token_hash": authorization["token_hash"],
            "issued_at": authorization["issued_at"],
            "expires_at": authorization["expires_at"],
        }
        claim_fingerprint = canonical_fingerprint(claim_payload)
        cursor.execute(
            """
            SELECT revision, chain_hash FROM execution_authorization_history
            WHERE authorization_id = %s ORDER BY revision DESC LIMIT 1
            """,
            (authorization["id"],),
        )
        previous = cursor.fetchone()
        revision = int(previous["revision"]) + 1 if previous else 1
        previous_chain_hash = previous["chain_hash"] if previous else None
        event_fingerprint = canonical_fingerprint(
            {
                "authorization_code": authorization["authorization_code"],
                "revision": revision,
                "event_type": event_type,
                "authorization_status": authorization["status"],
                "actor_type": actor_type,
                "actor_id": actor_id,
                "event_payload": event_payload,
                "claim_fingerprint": claim_fingerprint,
            }
        )
        chain_hash = hashlib.sha256(
            f"{previous_chain_hash or ''}:{event_fingerprint}".encode("utf-8")
        ).hexdigest()
        cursor.execute(
            """
            INSERT INTO execution_authorization_history (
                authorization_id, authorization_code, revision, event_type,
                authorization_status, actor_type, actor_id, event_payload,
                claim_fingerprint, event_fingerprint, previous_chain_hash, chain_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                authorization["id"],
                authorization["authorization_code"],
                revision,
                event_type,
                authorization["status"],
                actor_type,
                actor_id,
                Jsonb(event_payload),
                claim_fingerprint,
                event_fingerprint,
                previous_chain_hash,
                chain_hash,
            ),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result

    @staticmethod
    def _next_code(cursor: Any, *, prefix: str, object_type: str) -> str:
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
