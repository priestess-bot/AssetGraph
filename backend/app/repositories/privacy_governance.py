from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.errors import DomainAuthorizationError, DomainConflictError, DomainValidationError
from app.domain.state_machines import DELETION_RUN_STATE_MACHINE


class PrivacyGovernanceRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def get_active_access_policy(self, policy_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM data_access_policy_versions
                WHERE policy_code = %s AND status = 'active'
                ORDER BY revision_number DESC LIMIT 1
                """,
                (policy_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def get_active_redaction_policy(self, policy_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM redaction_policy_versions
                WHERE policy_code = %s AND status = 'active'
                ORDER BY revision_number DESC LIMIT 1
                """,
                (policy_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def get_active_retention_policy(self, data_class: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM retention_policy_versions
                WHERE data_class = %s AND status = 'active'
                ORDER BY revision_number DESC, approved_at DESC LIMIT 1
                """,
                (data_class,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def list_active_retention_policies(self) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (data_class) *
                FROM retention_policy_versions
                WHERE status = 'active'
                ORDER BY data_class, revision_number DESC, approved_at DESC
                """
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def record_access_decision(
        self,
        *,
        principal_id: str,
        roles: list[str],
        purpose: str,
        action: str,
        resource_type: str,
        resource_code: str,
        data_class: str,
        policy_code: str,
        policy_revision: int,
        decision: str,
        reason_codes: list[str],
        input_fingerprint: str,
        trace_id: str | None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            decision_code = self._next_code(cursor, prefix="DATA-ACCESS", object_type="data_access_decision")
            cursor.execute(
                """
                INSERT INTO data_access_decisions (
                    decision_code, principal_id, roles, purpose, action,
                    resource_type, resource_code, data_class, policy_code,
                    policy_revision, decision, reason_codes, input_fingerprint, trace_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    decision_code,
                    principal_id,
                    Jsonb(sorted(set(roles))),
                    purpose,
                    action,
                    resource_type,
                    resource_code,
                    data_class,
                    policy_code,
                    policy_revision,
                    decision,
                    Jsonb(sorted(set(reason_codes))),
                    input_fingerprint,
                    trace_id,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

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
        with self.connection.cursor(row_factory=dict_row) as cursor:
            hold_code = self._next_code(cursor, prefix="HOLD", object_type="legal_hold")
            cursor.execute(
                """
                INSERT INTO legal_holds (
                    hold_code, subject_type, subject_code, scope, reason,
                    evidence_refs, owner_principal, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    hold_code,
                    subject_type,
                    subject_code,
                    Jsonb(scope),
                    reason,
                    Jsonb(evidence_refs),
                    owner_principal,
                    expires_at,
                ),
            )
            row = cursor.fetchone()
            self._append_legal_hold_history(
                cursor,
                hold=row,
                revision=1,
                event_type="created",
                actor_id=owner_principal,
                evidence={"evidence_refs": evidence_refs},
            )
        self.connection.commit()
        result = self._serialize(row)
        result["revision"] = 1
        return result

    def release_legal_hold(
        self,
        hold_code: str,
        *,
        expected_revision: int,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT hold.*,
                       COALESCE((SELECT MAX(history.revision) FROM legal_hold_history AS history
                                 WHERE history.legal_hold_id = hold.id), 0) AS revision
                FROM legal_holds AS hold WHERE hold_code = %s FOR UPDATE
                """,
                (hold_code,),
            )
            hold = cursor.fetchone()
            if hold is None or hold["released_at"] is not None:
                self.connection.rollback()
                raise DomainConflictError("LEGAL_HOLD_NOT_ACTIVE", "Legal hold is not active")
            if int(hold["revision"]) != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "LEGAL_HOLD_REVISION_CONFLICT",
                    "Legal hold changed since it was loaded",
                    details={"current_revision": int(hold["revision"])},
                )
            cursor.execute(
                """
                UPDATE legal_holds SET released_at = now(), released_by = %s
                WHERE id = %s RETURNING *
                """,
                (actor_id, hold["id"]),
            )
            released = cursor.fetchone()
            self._append_legal_hold_history(
                cursor,
                hold=released,
                revision=expected_revision + 1,
                event_type="released",
                actor_id=actor_id,
                evidence=evidence,
            )
        self.connection.commit()
        result = self._serialize(released)
        result["revision"] = expected_revision + 1
        return result

    def create_deletion_run(
        self,
        *,
        subject_type: str,
        subject_code: str,
        requested_scope: dict[str, Any],
        required_processors: list[str],
        requested_by: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM deletion_runs WHERE request_fingerprint = %s",
                (request_fingerprint,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                return self.get_deletion_run(existing["deletion_run_code"]) or {}
            run_code = self._next_code(cursor, prefix="DELETE", object_type="deletion_run")
            cursor.execute(
                """
                INSERT INTO deletion_runs (
                    deletion_run_code, subject_type, subject_code, requested_scope,
                    required_processors, requested_by, request_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    run_code,
                    subject_type,
                    subject_code,
                    Jsonb(requested_scope),
                    Jsonb(sorted(set(required_processors))),
                    requested_by,
                    request_fingerprint,
                ),
            )
            row = cursor.fetchone()
            self._append_deletion_history(
                cursor,
                run=row,
                revision=1,
                from_status=None,
                to_status="requested",
                actor_id=requested_by,
                reason_code="DELETION_REQUESTED",
                evidence={"request_fingerprint": request_fingerprint},
            )
        self.connection.commit()
        return self.get_deletion_run(run_code) or {}

    def get_deletion_run(self, deletion_run_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM deletion_runs WHERE deletion_run_code = %s", (deletion_run_code,))
            row = cursor.fetchone()
            if row is None:
                return None
            result = self._serialize(row)
            cursor.execute(
                """
                SELECT * FROM deletion_receipts WHERE deletion_run_id = %s
                ORDER BY processor, target_type, target_code, attempt
                """,
                (row["id"],),
            )
            result["receipts"] = [self._serialize(item) for item in cursor.fetchall()]
            cursor.execute(
                """
                SELECT * FROM deletion_run_status_history WHERE deletion_run_id = %s
                ORDER BY revision
                """,
                (row["id"],),
            )
            result["history"] = [self._serialize(item) for item in cursor.fetchall()]
        return result

    def validate_deletion_run(
        self,
        deletion_run_code: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            run = self._lock_deletion_run(cursor, deletion_run_code, expected_revision)
            if run["status"] not in {"requested", "blocked_by_legal_hold"}:
                self.connection.rollback()
                DELETION_RUN_STATE_MACHINE.require_transition(run["status"], "validating")
            holds = self._active_legal_holds(cursor, run["subject_type"], run["subject_code"])
            if not holds and actor_id == run["requested_by"]:
                self.connection.rollback()
                raise DomainAuthorizationError(
                    "DELETION_SELF_APPROVAL_DENIED",
                    "Deletion requester cannot approve the same deletion run",
                )
            run = self._apply_deletion_transition(
                cursor,
                run,
                target="validating",
                actor_id=actor_id,
                reason_code="DELETION_VALIDATION_STARTED",
                evidence={},
            )
            hold_snapshot = [
                {
                    "hold_code": hold["hold_code"],
                    "scope": hold["scope"],
                    "owner_principal": hold["owner_principal"],
                    "expires_at": hold["expires_at"].isoformat(),
                }
                for hold in holds
            ]
            target = "blocked_by_legal_hold" if holds else "approved"
            run = self._apply_deletion_transition(
                cursor,
                run,
                target=target,
                actor_id=actor_id,
                reason_code="ACTIVE_LEGAL_HOLD" if holds else "DELETION_APPROVED",
                evidence={"legal_hold_snapshot": hold_snapshot},
                legal_hold_snapshot=hold_snapshot,
                approved_by=actor_id if not holds else None,
            )
        self.connection.commit()
        return self.get_deletion_run(deletion_run_code) or self._serialize(run)

    def start_deletion_run(
        self,
        deletion_run_code: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            run = self._lock_deletion_run(cursor, deletion_run_code, expected_revision)
            reason = "DELETION_RETRY_STARTED" if run["status"] == "partial_failed" else "DELETION_EXECUTION_STARTED"
            run = self._apply_deletion_transition(
                cursor,
                run,
                target="executing",
                actor_id=actor_id,
                reason_code=reason,
                evidence={"attempt": int(run["retry_count"]) + 1},
            )
        self.connection.commit()
        return self.get_deletion_run(deletion_run_code) or self._serialize(run)

    def record_deletion_receipt(
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
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM deletion_runs WHERE deletion_run_code = %s FOR UPDATE", (deletion_run_code,))
            run = cursor.fetchone()
            if run is None:
                self.connection.rollback()
                raise DomainConflictError("DELETION_RUN_NOT_FOUND", "Deletion run does not exist")
            if run["status"] != "executing":
                self.connection.rollback()
                raise DomainConflictError(
                    "DELETION_RECEIPT_PHASE_INVALID",
                    "Deletion receipts are accepted only while the run is executing",
                )
            targets = run["requested_scope"].get("targets") or []
            target = next(
                (
                    item
                    for item in targets
                    if item.get("target_type") == target_type and item.get("target_code") == target_code
                ),
                None,
            )
            if processor not in set(run["required_processors"]) or target is None:
                self.connection.rollback()
                raise DomainValidationError(
                    "DELETION_RECEIPT_TARGET_UNDECLARED",
                    "Receipt processor and target must be declared by the deletion run",
                )
            attempt = int(run["retry_count"]) + 1
            cursor.execute(
                """
                SELECT * FROM deletion_receipts
                WHERE deletion_run_id = %s AND processor = %s
                  AND target_type = %s AND target_code = %s AND attempt = %s
                """,
                (run["id"], processor, target_type, target_code, attempt),
            )
            existing = cursor.fetchone()
            if existing is not None:
                same = (
                    existing["outcome"] == outcome
                    and existing["retention_basis"] == retention_basis
                    and existing["evidence"] == evidence
                )
                self.connection.rollback()
                if not same:
                    raise DomainConflictError(
                        "DELETION_RECEIPT_CONFLICT",
                        "The processor already reported a different result for this attempt",
                    )
                return self._serialize(existing)
            cursor.execute(
                """
                INSERT INTO deletion_receipts (
                    deletion_run_id, processor, target_type, target_code,
                    outcome, retention_basis, evidence, attempt
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    run["id"],
                    processor,
                    target_type,
                    target_code,
                    outcome,
                    retention_basis,
                    Jsonb(evidence),
                    attempt,
                ),
            )
            receipt = cursor.fetchone()
            if outcome in {"deleted", "tombstoned"}:
                cursor.execute(
                    """
                    INSERT INTO data_tombstones (
                        subject_type, subject_code, source_system,
                        deletion_run_id, reason_code
                    ) VALUES (%s, %s, %s, %s, 'DELETION_CONFIRMED')
                    ON CONFLICT (subject_type, subject_code, source_system) DO NOTHING
                    """,
                    (target_type, target_code, target["source_system"], run["id"]),
                )
        self.connection.commit()
        return self._serialize(receipt)

    def verify_deletion_run(
        self,
        deletion_run_code: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            run = self._lock_deletion_run(cursor, deletion_run_code, expected_revision)
            run = self._apply_deletion_transition(
                cursor,
                run,
                target="verifying",
                actor_id=actor_id,
                reason_code="DELETION_VERIFICATION_STARTED",
                evidence={},
            )
            issues = self._deletion_completion_issues(cursor, run)
            target = "partial_failed" if issues else "completed"
            run = self._apply_deletion_transition(
                cursor,
                run,
                target=target,
                actor_id=actor_id,
                reason_code="DELETION_INCOMPLETE" if issues else "DELETION_COMPLETED",
                evidence={"issues": issues},
            )
        self.connection.commit()
        return self.get_deletion_run(deletion_run_code) or self._serialize(run)

    def register_external_processor(
        self,
        *,
        processor_code: str,
        revision_number: int,
        status: str,
        purposes: list[str],
        data_classes: list[str],
        region: str,
        retention_terms: str,
        credential_owner: str,
        rotation_policy: str,
        minimum_fields: dict[str, Any],
        exit_plan: str,
        approved_by: str | None,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM external_processor_records
                WHERE processor_code = %s AND revision_number = %s
                """,
                (processor_code, revision_number),
            )
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                expected = {
                    "status": status,
                    "purposes": sorted(set(purposes)),
                    "data_classes": sorted(set(data_classes)),
                    "region": region,
                    "retention_terms": retention_terms,
                    "credential_owner": credential_owner,
                    "rotation_policy": rotation_policy,
                    "minimum_fields": minimum_fields,
                    "exit_plan": exit_plan,
                    "approved_by": approved_by,
                }
                if any(existing[key] != value for key, value in expected.items()):
                    raise DomainConflictError(
                        "EXTERNAL_PROCESSOR_REVISION_CONFLICT",
                        "Processor revision already exists with different governance terms",
                    )
                return self._serialize(existing)
            if status == "active":
                cursor.execute(
                    """
                    UPDATE external_processor_records SET status = 'superseded'
                    WHERE processor_code = %s AND status = 'active'
                    """,
                    (processor_code,),
                )
            cursor.execute(
                """
                INSERT INTO external_processor_records (
                    processor_code, revision_number, status, purposes, data_classes,
                    region, retention_terms, credential_owner, rotation_policy,
                    minimum_fields, exit_plan, approved_by, approved_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          CASE WHEN %s = 'active' THEN now() ELSE NULL END)
                RETURNING *
                """,
                (
                    processor_code,
                    revision_number,
                    status,
                    Jsonb(sorted(set(purposes))),
                    Jsonb(sorted(set(data_classes))),
                    region,
                    retention_terms,
                    credential_owner,
                    rotation_policy,
                    Jsonb(minimum_fields),
                    exit_plan,
                    approved_by,
                    status,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def get_active_external_processor(self, processor_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM external_processor_records
                WHERE processor_code = %s AND status = 'active'
                ORDER BY revision_number DESC LIMIT 1
                """,
                (processor_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def record_external_processor_call(
        self,
        *,
        processor_code: str,
        processor_revision: int,
        purpose: str,
        region: str,
        data_class: str,
        fields_sent: list[str],
        payload_fingerprint: str,
        decision: str,
        reason_codes: list[str],
        principal_id: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            call_code = self._next_code(cursor, prefix="PROCESSOR", object_type="external_processor_call")
            cursor.execute(
                """
                INSERT INTO external_processor_call_audits (
                    call_code, processor_code, processor_revision, purpose, region,
                    data_class, fields_sent, payload_fingerprint, decision,
                    reason_codes, principal_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    call_code,
                    processor_code,
                    processor_revision,
                    purpose,
                    region,
                    data_class,
                    Jsonb(fields_sent),
                    payload_fingerprint,
                    decision,
                    Jsonb(reason_codes),
                    principal_id,
                ),
            )
            row = cursor.fetchone()
        self.connection.commit()
        return self._serialize(row)

    def get_external_processor_call(self, call_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM external_processor_call_audits WHERE call_code = %s",
                (call_code,),
            )
            row = cursor.fetchone()
        return self._serialize(row) if row else None

    def register_credential(
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
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM credential_records WHERE credential_code = %s", (credential_code,))
            existing = cursor.fetchone()
            if existing is not None:
                self.connection.rollback()
                expected = {
                    "processor_code": processor_code,
                    "secret_ref": secret_ref,
                    "allowed_scopes": sorted(set(allowed_scopes)),
                    "allowed_regions": sorted(set(allowed_regions)),
                    "credential_owner": credential_owner,
                    "rotation_interval_days": rotation_interval_days,
                }
                if any(existing[key] != value for key, value in expected.items()):
                    raise DomainConflictError(
                        "CREDENTIAL_REGISTRATION_CONFLICT",
                        "Credential code already exists with different metadata",
                    )
                cursor.execute(
                    "SELECT COALESCE(MAX(revision), 0) AS revision FROM credential_rotation_events WHERE credential_id = %s",
                    (existing["id"],),
                )
                return self._credential_with_revision(existing, int(cursor.fetchone()["revision"]))
            cursor.execute(
                """
                INSERT INTO credential_records (
                    credential_code, processor_code, secret_ref, allowed_scopes,
                    allowed_regions, credential_owner, rotation_interval_days,
                    last_rotated_at, next_rotation_due_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    credential_code,
                    processor_code,
                    secret_ref,
                    Jsonb(sorted(set(allowed_scopes))),
                    Jsonb(sorted(set(allowed_regions))),
                    credential_owner,
                    rotation_interval_days,
                    rotated_at,
                    rotated_at + timedelta(days=rotation_interval_days),
                ),
            )
            row = cursor.fetchone()
            self._append_credential_event(
                cursor,
                credential=row,
                revision=1,
                event_type="registered",
                old_secret_ref=None,
                new_secret_ref=secret_ref,
                actor_id=actor_id,
                evidence={},
            )
        self.connection.commit()
        return self._credential_with_revision(row, 1)

    def refresh_due_credentials(self, *, actor_id: str, now: datetime) -> list[dict[str, Any]]:
        updated: list[dict[str, Any]] = []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT credential.*,
                       COALESCE((SELECT MAX(event.revision) FROM credential_rotation_events AS event
                                 WHERE event.credential_id = credential.id), 0) AS revision
                FROM credential_records AS credential
                WHERE status = 'active' AND next_rotation_due_at <= %s
                ORDER BY next_rotation_due_at
                FOR UPDATE SKIP LOCKED
                """,
                (now,),
            )
            for credential in cursor.fetchall():
                cursor.execute(
                    """
                    UPDATE credential_records SET status = 'rotation_due', updated_at = now()
                    WHERE id = %s RETURNING *
                    """,
                    (credential["id"],),
                )
                row = cursor.fetchone()
                revision = int(credential["revision"]) + 1
                self._append_credential_event(
                    cursor,
                    credential=row,
                    revision=revision,
                    event_type="marked_due",
                    old_secret_ref=row["secret_ref"],
                    new_secret_ref=None,
                    actor_id=actor_id,
                    evidence={"due_at": row["next_rotation_due_at"].isoformat()},
                )
                updated.append(self._credential_with_revision(row, revision))
        self.connection.commit()
        return updated

    def rotate_credential(
        self,
        credential_code: str,
        *,
        expected_revision: int,
        new_secret_ref: str,
        rotated_at: datetime,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT credential.*,
                       COALESCE((SELECT MAX(event.revision) FROM credential_rotation_events AS event
                                 WHERE event.credential_id = credential.id), 0) AS revision
                FROM credential_records AS credential
                WHERE credential_code = %s FOR UPDATE
                """,
                (credential_code,),
            )
            credential = cursor.fetchone()
            if credential is None or credential["status"] == "revoked":
                self.connection.rollback()
                raise DomainConflictError("CREDENTIAL_NOT_ACTIVE", "Credential is missing or revoked")
            if int(credential["revision"]) != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "CREDENTIAL_REVISION_CONFLICT",
                    "Credential metadata changed since it was loaded",
                    details={"current_revision": int(credential["revision"])},
                )
            if credential["secret_ref"] == new_secret_ref:
                self.connection.rollback()
                raise DomainValidationError(
                    "CREDENTIAL_SECRET_REF_UNCHANGED",
                    "Credential rotation must point to a new secret version",
                )
            cursor.execute(
                """
                UPDATE credential_records
                SET secret_ref = %s, status = 'active', last_rotated_at = %s,
                    next_rotation_due_at = %s, updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (
                    new_secret_ref,
                    rotated_at,
                    rotated_at + timedelta(days=int(credential["rotation_interval_days"])),
                    credential["id"],
                ),
            )
            row = cursor.fetchone()
            revision = expected_revision + 1
            self._append_credential_event(
                cursor,
                credential=row,
                revision=revision,
                event_type="rotated",
                old_secret_ref=credential["secret_ref"],
                new_secret_ref=new_secret_ref,
                actor_id=actor_id,
                evidence=evidence,
            )
        self.connection.commit()
        return self._credential_with_revision(row, revision)

    def revoke_credential(
        self,
        credential_code: str,
        *,
        expected_revision: int,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT credential.*,
                       COALESCE((SELECT MAX(event.revision) FROM credential_rotation_events AS event
                                 WHERE event.credential_id = credential.id), 0) AS revision
                FROM credential_records AS credential
                WHERE credential_code = %s FOR UPDATE
                """,
                (credential_code,),
            )
            credential = cursor.fetchone()
            if credential is None or credential["status"] == "revoked":
                self.connection.rollback()
                raise DomainConflictError("CREDENTIAL_NOT_ACTIVE", "Credential is missing or revoked")
            if int(credential["revision"]) != expected_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "CREDENTIAL_REVISION_CONFLICT",
                    "Credential metadata changed since it was loaded",
                    details={"current_revision": int(credential["revision"])},
                )
            cursor.execute(
                """
                UPDATE credential_records SET status = 'revoked', updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (credential["id"],),
            )
            row = cursor.fetchone()
            revision = expected_revision + 1
            self._append_credential_event(
                cursor,
                credential=row,
                revision=revision,
                event_type="revoked",
                old_secret_ref=credential["secret_ref"],
                new_secret_ref=None,
                actor_id=actor_id,
                evidence=evidence,
            )
        self.connection.commit()
        return self._credential_with_revision(row, revision)

    @staticmethod
    def _active_legal_holds(cursor: Any, subject_type: str, subject_code: str) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT * FROM legal_holds
            WHERE subject_type = %s AND subject_code = %s
              AND released_at IS NULL AND effective_at <= now()
              AND (expires_at IS NULL OR expires_at > now())
            ORDER BY effective_at, hold_code
            """,
            (subject_type, subject_code),
        )
        return list(cursor.fetchall())

    def _lock_deletion_run(
        self,
        cursor: Any,
        deletion_run_code: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        cursor.execute(
            "SELECT * FROM deletion_runs WHERE deletion_run_code = %s FOR UPDATE",
            (deletion_run_code,),
        )
        run = cursor.fetchone()
        if run is None:
            self.connection.rollback()
            raise DomainConflictError("DELETION_RUN_NOT_FOUND", "Deletion run does not exist")
        if int(run["revision"]) != expected_revision:
            self.connection.rollback()
            raise DomainConflictError(
                "DELETION_RUN_REVISION_CONFLICT",
                "Deletion run changed since it was loaded",
                details={"current_revision": int(run["revision"])},
            )
        return dict(run)

    def _apply_deletion_transition(
        self,
        cursor: Any,
        run: dict[str, Any],
        *,
        target: str,
        actor_id: str,
        reason_code: str,
        evidence: dict[str, Any],
        legal_hold_snapshot: list[dict[str, Any]] | None = None,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        current = str(run["status"])
        DELETION_RUN_STATE_MACHINE.require_transition(current, target)
        next_revision = int(run["revision"]) + 1
        retry_increment = 1 if target == "partial_failed" else 0
        retry_count = int(run["retry_count"]) + retry_increment
        next_retry_at = None
        escalated_at = run["escalated_at"]
        if target == "partial_failed":
            next_retry_at = datetime.now(UTC) + timedelta(minutes=min(2**retry_count, 60))
            escalated_at = escalated_at or datetime.now(UTC)
        elif target != "executing":
            next_retry_at = run["next_retry_at"]
        completed_at = datetime.now(UTC) if target == "completed" else run["completed_at"]
        cursor.execute(
            """
            UPDATE deletion_runs
            SET status = %s, revision = %s,
                legal_hold_snapshot = COALESCE(%s, legal_hold_snapshot),
                approved_by = COALESCE(%s, approved_by),
                retry_count = %s, next_retry_at = %s, escalated_at = %s,
                completed_at = %s,
                error_summary = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING *
            """,
            (
                target,
                next_revision,
                Jsonb(legal_hold_snapshot) if legal_hold_snapshot is not None else None,
                approved_by,
                retry_count,
                next_retry_at,
                escalated_at,
                completed_at,
                "; ".join(str(value) for value in evidence.get("issues") or []) or None,
                run["id"],
            ),
        )
        updated = dict(cursor.fetchone())
        self._append_deletion_history(
            cursor,
            run=updated,
            revision=next_revision,
            from_status=current,
            to_status=target,
            actor_id=actor_id,
            reason_code=reason_code,
            evidence=evidence,
        )
        return updated

    @staticmethod
    def _deletion_completion_issues(cursor: Any, run: dict[str, Any]) -> list[str]:
        targets = run["requested_scope"].get("targets") or []
        expected = {
            (processor, target["target_type"], target["target_code"])
            for processor in run["required_processors"]
            for target in targets
        }
        cursor.execute(
            """
            SELECT DISTINCT ON (processor, target_type, target_code)
                   processor, target_type, target_code, outcome, retention_basis, attempt
            FROM deletion_receipts
            WHERE deletion_run_id = %s
            ORDER BY processor, target_type, target_code, attempt DESC
            """,
            (run["id"],),
        )
        latest = {
            (row["processor"], row["target_type"], row["target_code"]): row
            for row in cursor.fetchall()
        }
        issues: list[str] = []
        successful = {"deleted", "tombstoned", "retained_legal_hold", "not_found"}
        for key in sorted(expected):
            receipt = latest.get(key)
            label = ":".join(key)
            if receipt is None:
                issues.append(f"missing_receipt:{label}")
            elif receipt["outcome"] not in successful:
                issues.append(f"failed_receipt:{label}")
            elif receipt["outcome"] == "retained_legal_hold" and not run["legal_hold_snapshot"]:
                issues.append(f"unjustified_retention:{label}")
        return issues

    @staticmethod
    def _append_deletion_history(
        cursor: Any,
        *,
        run: dict[str, Any],
        revision: int,
        from_status: str | None,
        to_status: str,
        actor_id: str,
        reason_code: str,
        evidence: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO deletion_run_status_history (
                deletion_run_id, deletion_run_code, revision, from_status,
                to_status, actor_id, reason_code, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run["id"],
                run["deletion_run_code"],
                revision,
                from_status,
                to_status,
                actor_id,
                reason_code,
                Jsonb(evidence),
            ),
        )

    @staticmethod
    def _append_legal_hold_history(
        cursor: Any,
        *,
        hold: dict[str, Any],
        revision: int,
        event_type: str,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> None:
        cursor.execute(
            """
            INSERT INTO legal_hold_history (
                legal_hold_id, hold_code, revision, event_type, actor_id, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (hold["id"], hold["hold_code"], revision, event_type, actor_id, Jsonb(evidence)),
        )

    @staticmethod
    def _append_credential_event(
        cursor: Any,
        *,
        credential: dict[str, Any],
        revision: int,
        event_type: str,
        old_secret_ref: str | None,
        new_secret_ref: str | None,
        actor_id: str,
        evidence: dict[str, Any],
    ) -> None:
        def fingerprint(value: str | None) -> str | None:
            return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None
        cursor.execute(
            """
            INSERT INTO credential_rotation_events (
                credential_id, credential_code, revision, event_type,
                old_secret_ref_fingerprint, new_secret_ref_fingerprint,
                actor_id, evidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                credential["id"],
                credential["credential_code"],
                revision,
                event_type,
                fingerprint(old_secret_ref),
                fingerprint(new_secret_ref),
                actor_id,
                Jsonb(evidence),
            ),
        )

    @classmethod
    def _credential_with_revision(cls, credential: dict[str, Any], revision: int) -> dict[str, Any]:
        result = cls._serialize(credential)
        result["revision"] = revision
        return result

    def rollback(self) -> None:
        self.connection.rollback()

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
        return f"{prefix}-{sequence_date:%Y%m%d}-{int(cursor.fetchone()['current_value']):06d}"
