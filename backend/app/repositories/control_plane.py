from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainAuthorizationError, DomainConflictError, DomainValidationError
from app.domain.protected_resources import protected_resource_denial
from app.domain.state_machines import STEP_STATE_MACHINE, WORKFLOW_STATE_MACHINE
from app.services.state_transitions import require_audited_transition


class WorkflowLeaseConflictError(DomainConflictError):
    pass


class ControlPlaneRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT * FROM workflow_runs
                WHERE workflow_type = %s AND idempotency_key = %s
                """,
                (payload["workflow_type"], payload["idempotency_key"]),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if (
                    existing["subject_type"] != payload["subject_type"]
                    or existing["subject_code"] != payload["subject_code"]
                    or existing["subject_revision"] != payload.get("subject_revision")
                ):
                    raise DomainConflictError(
                        "WORKFLOW_IDEMPOTENCY_CONFLICT",
                        "The idempotency key already identifies a different workflow subject",
                    )
                self.connection.rollback()
                return self.get_workflow_run(str(existing["run_code"])) or {}

            parent_run_id = None
            if parent_code := payload.get("parent_run_code"):
                cursor.execute("SELECT id FROM workflow_runs WHERE run_code = %s", (parent_code,))
                parent = cursor.fetchone()
                if parent is None:
                    raise DomainConflictError("WORKFLOW_PARENT_NOT_FOUND", "Parent workflow run does not exist")
                parent_run_id = parent["id"]

            run_code = self._next_code(cursor, prefix="RUN", object_type="workflow_run")
            cursor.execute(
                """
                INSERT INTO workflow_runs (
                    run_code, workflow_type, subject_type, subject_code, subject_revision,
                    parent_run_id, priority, progress_total, budget, trace_id, root_span_id,
                    idempotency_key, requested_by, queue_reason
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run_code,
                    payload["workflow_type"],
                    payload["subject_type"],
                    payload["subject_code"],
                    payload.get("subject_revision"),
                    parent_run_id,
                    payload.get("priority", 100),
                    len(payload["steps"]),
                    Jsonb(payload.get("budget") or {}),
                    payload.get("trace_id"),
                    payload.get("root_span_id"),
                    payload["idempotency_key"],
                    payload["requested_by"],
                    "waiting_for_dependencies",
                ),
            )
            run_id = cursor.fetchone()["id"]
            step_ids: dict[str, UUID] = {}
            for sort_order, step in enumerate(payload["steps"]):
                step_code = self._next_code(cursor, prefix="STEP", object_type="workflow_step")
                status = "pending" if step.get("depends_on") else "ready"
                cursor.execute(
                    """
                    INSERT INTO workflow_steps (
                        step_code, run_id, run_code, step_type, sort_order, status,
                        priority, idempotency_key, side_effect_level, max_attempts,
                        backoff_policy, timeout_seconds, cancellable,
                        compensation_strategy, reconcile_strategy, input_fingerprint
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        step_code,
                        run_id,
                        run_code,
                        step["step_type"],
                        sort_order,
                        status,
                        step.get("priority", 100),
                        step["idempotency_key"],
                        step.get("side_effect_level", "pure_compute"),
                        step.get("max_attempts", 3),
                        Jsonb(step.get("backoff_policy") or {}),
                        step["timeout_seconds"],
                        step.get("cancellable", True),
                        step.get("compensation_strategy"),
                        step.get("reconcile_strategy"),
                        step["input_fingerprint"],
                    ),
                )
                step_ids[step["step_key"]] = cursor.fetchone()["id"]
            for step in payload["steps"]:
                for dependency_key in step.get("depends_on") or []:
                    cursor.execute(
                        """
                        INSERT INTO workflow_step_dependencies (step_id, depends_on_step_id)
                        VALUES (%s, %s)
                        """,
                        (step_ids[step["step_key"]], step_ids[dependency_key]),
                    )
            self._append_history(
                cursor,
                run_id=run_id,
                from_status=None,
                to_status="queued",
                actor_type="user",
                actor_id=payload["requested_by"],
                reason_code="WORKFLOW_CREATED",
            )
        self.connection.commit()
        return self.get_workflow_run(run_code) or {}

    def get_workflow_run(self, run_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT run.*, parent.run_code AS parent_run_code
                FROM workflow_runs AS run
                LEFT JOIN workflow_runs AS parent ON parent.id = run.parent_run_id
                WHERE run.run_code = %s
                """,
                (run_code,),
            )
            run = cursor.fetchone()
            if run is None:
                return None
            result = self._serialize(run)
            cursor.execute(
                """
                SELECT step.*,
                       COALESCE(
                           jsonb_agg(dependency.step_code ORDER BY dependency.sort_order)
                               FILTER (WHERE dependency.id IS NOT NULL),
                           '[]'::jsonb
                       ) AS depends_on
                FROM workflow_steps AS step
                LEFT JOIN workflow_step_dependencies AS link ON link.step_id = step.id
                LEFT JOIN workflow_steps AS dependency ON dependency.id = link.depends_on_step_id
                WHERE step.run_id = %s
                GROUP BY step.id
                ORDER BY step.sort_order
                """,
                (run["id"],),
            )
            result["steps"] = [self._serialize_step(row, include_claim_token=False) for row in cursor.fetchall()]
            result["human_tasks"] = self._fetch_human_tasks(cursor, run_id=run["id"])
        return result

    def cancel_workflow_run(self, run_code: str, *, requested_by: str, reason: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM workflow_runs WHERE run_code = %s FOR UPDATE", (run_code,))
            run = cursor.fetchone()
            if run is None:
                self.connection.rollback()
                return None
            if WORKFLOW_STATE_MACHINE.is_terminal(run["status"]):
                raise DomainConflictError(
                    "WORKFLOW_ALREADY_TERMINAL",
                    "A terminal workflow cannot be cancelled",
                    details={"status": run["status"]},
                )
            cursor.execute(
                """
                SELECT count(*) FROM workflow_steps
                WHERE run_id = %s AND status IN ('running', 'reconcile_required')
                """,
                (run["id"],),
            )
            active_count = int(cursor.fetchone()["count"])
            target_status = "cancelling" if active_count else "cancelled"
            require_audited_transition(
                self.connection,
                WORKFLOW_STATE_MACHINE,
                current=run["status"],
                target=target_status,
                principal_type="user",
                principal_id=requested_by,
                target_type="workflow_run",
                target_code=run_code,
                trace_id=run["trace_id"],
            )
            completed_at = datetime.now(UTC) if target_status == "cancelled" else None
            cursor.execute(
                """
                UPDATE workflow_runs
                SET status = %s, cancellation_requested_at = now(),
                    waiting_reason = %s, completed_at = %s, updated_at = now()
                WHERE id = %s
                """,
                (target_status, reason, completed_at, run["id"]),
            )
            cursor.execute(
                """
                UPDATE workflow_steps
                SET status = 'cancelled', completed_at = now(), updated_at = now()
                WHERE run_id = %s AND status IN ('pending', 'ready', 'waiting_human')
                """,
                (run["id"],),
            )
            cursor.execute(
                """
                UPDATE human_tasks SET status = 'cancelled', updated_at = now()
                WHERE run_id = %s AND status IN ('open', 'claimed', 'escalated')
                """,
                (run["id"],),
            )
            self._append_history(
                cursor,
                run_id=run["id"],
                from_status=run["status"],
                to_status=target_status,
                actor_type="user",
                actor_id=requested_by,
                reason_code="WORKFLOW_CANCEL_REQUESTED",
                evidence={"reason": reason},
            )
        self.connection.commit()
        return self.get_workflow_run(run_code)

    def claim_next_step(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        accepted_step_types: list[str] | None = None,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._recover_expired_leases(cursor)
            params: list[Any] = []
            type_filter = ""
            if accepted_step_types:
                type_filter = "AND step.step_type = ANY(%s)"
                params.append(accepted_step_types)
            cursor.execute(
                f"""
                SELECT step.*, run.trace_id, run.root_span_id
                FROM workflow_steps AS step
                JOIN workflow_runs AS run ON run.id = step.run_id
                WHERE step.status = 'ready'
                  AND run.status IN ('queued', 'running')
                  {type_filter}
                ORDER BY run.priority, step.priority, run.created_at, step.sort_order
                FOR UPDATE OF step SKIP LOCKED
                LIMIT 1
                """,
                tuple(params),
            )
            step = cursor.fetchone()
            if step is None:
                self.connection.commit()
                return None
            claim_token = uuid4()
            cursor.execute(
                """
                UPDATE workflow_steps
                SET status = 'running', claimed_by = %s, claim_token = %s,
                    lease_version = lease_version + 1,
                    lease_expires_at = now() + make_interval(secs => %s),
                    heartbeat_at = now(), attempt = attempt + 1,
                    started_at = COALESCE(started_at, now()), updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, claim_token, lease_seconds, step["id"]),
            )
            claimed = cursor.fetchone()
            cursor.execute("SELECT * FROM workflow_runs WHERE id = %s FOR UPDATE", (step["run_id"],))
            run = cursor.fetchone()
            if run["status"] == "queued":
                cursor.execute(
                    "UPDATE workflow_runs SET status = 'running', started_at = now(), queue_reason = NULL, updated_at = now() WHERE id = %s",
                    (run["id"],),
                )
                self._append_history(
                    cursor,
                    run_id=run["id"],
                    step_id=step["id"],
                    from_status="queued",
                    to_status="running",
                    actor_type="worker",
                    actor_id=worker_id,
                    reason_code="STEP_CLAIMED",
                )
        self.connection.commit()
        result = self._serialize_step(claimed, include_claim_token=True)
        if run["trace_id"] and run["root_span_id"]:
            result["traceparent"] = f"00-{run['trace_id']}-{run['root_span_id']}-01"
        else:
            result["traceparent"] = None
        return result

    def heartbeat_step(
        self,
        step_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        lease_seconds: int,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE workflow_steps
                SET heartbeat_at = now(),
                    lease_expires_at = now() + make_interval(secs => %s),
                    updated_at = now()
                WHERE step_code = %s AND status = 'running' AND claimed_by = %s
                  AND claim_token = %s AND lease_version = %s AND lease_expires_at > now()
                  AND started_at + make_interval(secs => timeout_seconds) > now()
                RETURNING *
                """,
                (lease_seconds, step_code, worker_id, claim_token, lease_version),
            )
            step = cursor.fetchone()
        self.connection.commit()
        return self._serialize_step(step, include_claim_token=False) if step else None

    def prepare_external_effect(
        self,
        step_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        target_type: str,
        target_id: str,
        operation_type: str,
        idempotency_key: str,
        plan_or_release_hash: str,
        request_fingerprint: str,
    ) -> dict[str, Any]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            step = self._lock_owned_step(
                cursor,
                step_code,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_version=lease_version,
            )
            if step is None:
                self.connection.rollback()
                raise DomainConflictError("WORKFLOW_STEP_LEASE_INVALID", "Active workflow step lease was not found")
            if step["side_effect_level"] not in {"write_external", "irreversible_external"}:
                self.connection.rollback()
                raise DomainValidationError(
                    "WORKFLOW_EXTERNAL_EFFECT_NOT_ALLOWED",
                    "Only an external-write step may prepare an external effect",
                )
            cursor.execute(
                """
                SELECT * FROM workflow_external_effects
                WHERE step_id = %s AND attempt = %s AND idempotency_key = %s
                """,
                (step["id"], step["attempt"], idempotency_key),
            )
            existing = cursor.fetchone()
            if existing is not None:
                same_request = (
                    existing["target_type"] == target_type
                    and existing["target_id"] == target_id
                    and existing["operation_type"] == operation_type
                    and existing["plan_or_release_hash"] == plan_or_release_hash
                    and existing["request_fingerprint"] == request_fingerprint
                )
                self.connection.rollback()
                if not same_request:
                    raise DomainConflictError(
                        "WORKFLOW_EXTERNAL_EFFECT_IDEMPOTENCY_CONFLICT",
                        "External effect idempotency key identifies a different request",
                    )
                return self._serialize(existing)
            effect_code = self._next_code(cursor, prefix="EFFECT", object_type="workflow_external_effect")
            cursor.execute(
                """
                INSERT INTO workflow_external_effects (
                    effect_code, step_id, step_code, attempt, target_type,
                    target_id, operation_type, idempotency_key,
                    plan_or_release_hash, request_fingerprint
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    effect_code,
                    step["id"],
                    step_code,
                    step["attempt"],
                    target_type,
                    target_id,
                    operation_type,
                    idempotency_key,
                    plan_or_release_hash,
                    request_fingerprint,
                ),
            )
            effect = cursor.fetchone()
            self._append_effect_history(
                cursor,
                effect_id=effect["id"],
                from_phase=None,
                to_phase="prepared",
                revision=1,
                actor_type="worker",
                actor_id=worker_id,
                reason_code="EXTERNAL_EFFECT_PREPARED",
                evidence={"request_fingerprint": request_fingerprint},
            )
        self.connection.commit()
        return self._serialize(effect)

    def authorize_external_effect(
        self,
        effect_code: str,
        *,
        expected_revision: int,
        authorization_code: str,
        actor_id: str,
    ) -> dict[str, Any]:
        return self._transition_external_effect(
            effect_code,
            expected_revision=expected_revision,
            expected_phase="prepared",
            target_phase="authorized",
            actor_type="worker",
            actor_id=actor_id,
            reason_code="COMMIT_TIME_AUTHORIZATION_ACCEPTED",
            assignments={"authorization_code": authorization_code, "authorized_at": datetime.now(UTC)},
            evidence={"authorization_code": authorization_code},
        )

    def assert_external_effect_target_writable(
        self,
        effect_code: str,
        *,
        capability: str,
    ) -> None:
        """Worker-side guard that independently reloads the effect target and registry."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT target_type, target_id FROM workflow_external_effects WHERE effect_code = %s",
                (effect_code,),
            )
            effect = cursor.fetchone()
            if effect is None:
                self.connection.rollback()
                raise DomainConflictError("EXTERNAL_EFFECT_NOT_FOUND", "Workflow external effect does not exist")
            cursor.execute(
                """
                SELECT * FROM protected_resources
                WHERE resource_type = %s AND resource_id = %s
                  AND revoked_at IS NULL AND effective_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (effect["target_type"], effect["target_id"]),
            )
            protected = cursor.fetchone()
        if denial_reason := protected_resource_denial(dict(protected) if protected else None, capability):
            self.connection.rollback()
            raise DomainAuthorizationError(
                "WORKER_TARGET_PROTECTED",
                "Worker refused an external write to a protected resource",
                details={
                    "effect_code": effect_code,
                    "target_type": effect["target_type"],
                    "target_id": effect["target_id"],
                    "reason_code": denial_reason,
                },
            )

    def begin_external_commit(
        self,
        effect_code: str,
        *,
        expected_revision: int,
        actor_id: str,
    ) -> dict[str, Any]:
        return self._transition_external_effect(
            effect_code,
            expected_revision=expected_revision,
            expected_phase="authorized",
            target_phase="committing",
            actor_type="worker",
            actor_id=actor_id,
            reason_code="EXTERNAL_COMMIT_STARTED",
            assignments={"commit_started_at": datetime.now(UTC)},
        )

    def record_external_commit(
        self,
        effect_code: str,
        *,
        expected_revision: int,
        actor_id: str,
        outcome: str,
        response_summary: dict[str, Any] | None,
        external_identity: dict[str, Any] | None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        if outcome not in {"applied", "not_applied", "unknown"}:
            raise DomainValidationError("EXTERNAL_COMMIT_OUTCOME_INVALID", "Unsupported external commit outcome")
        target_phase = {
            "applied": "committed",
            "not_applied": "failed",
            "unknown": "reconcile_required",
        }[outcome]
        effect = self._transition_external_effect(
            effect_code,
            expected_revision=expected_revision,
            expected_phase="committing",
            target_phase=target_phase,
            actor_type="worker",
            actor_id=actor_id,
            reason_code=f"EXTERNAL_COMMIT_{outcome.upper()}",
            assignments={
                "commit_completed_at": datetime.now(UTC),
                "response_summary": response_summary,
                "external_identity": external_identity,
                "unknown_outcome": outcome == "unknown",
                "error_code": error_code,
            },
            evidence={
                "outcome": outcome,
                "response_fingerprint": canonical_fingerprint(response_summary),
                "external_identity_fingerprint": canonical_fingerprint(external_identity),
                "error_code": error_code,
            },
        )
        if outcome == "unknown":
            with self.connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    UPDATE workflow_steps
                    SET status = 'reconcile_required', claimed_by = NULL,
                        claim_token = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL, error_code = 'EXTERNAL_OUTCOME_UNKNOWN',
                        error_summary = 'External commit outcome requires authoritative reconciliation',
                        updated_at = now()
                    WHERE id = %s
                    RETURNING run_id
                    """,
                    (effect["step_id"],),
                )
                step = cursor.fetchone()
                cursor.execute(
                    """
                    UPDATE workflow_runs SET status = 'reconcile_required', updated_at = now()
                    WHERE id = %s AND status IN ('running', 'cancelling')
                    """,
                    (step["run_id"],),
                )
            self.connection.commit()
        return effect

    def complete_external_readback(
        self,
        effect_code: str,
        *,
        expected_revision: int,
        actor_id: str,
        external_identity: dict[str, Any],
        readback_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if not external_identity or not readback_evidence:
            raise DomainValidationError(
                "EXTERNAL_READBACK_EVIDENCE_REQUIRED",
                "External identity and authoritative readback evidence are required",
            )
        return self._transition_external_effect(
            effect_code,
            expected_revision=expected_revision,
            expected_phase="committed",
            target_phase="readback_succeeded",
            actor_type="worker",
            actor_id=actor_id,
            reason_code="EXTERNAL_READBACK_VERIFIED",
            assignments={
                "external_identity": external_identity,
                "readback_evidence": readback_evidence,
                "readback_completed_at": datetime.now(UTC),
            },
            evidence={
                "readback_verified": True,
                "external_identity_fingerprint": canonical_fingerprint(external_identity),
                "readback_fingerprint": canonical_fingerprint(readback_evidence),
            },
        )

    def complete_step(
        self,
        step_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        output_fingerprint: str,
        actual_cost: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            step = self._lock_owned_step(
                cursor,
                step_code,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_version=lease_version,
            )
            if step is None:
                self.connection.rollback()
                return None
            if step["side_effect_level"] in {"write_external", "irreversible_external"}:
                cursor.execute(
                    """
                    SELECT phase FROM workflow_external_effects
                    WHERE step_id = %s AND attempt = %s
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    (step["id"], step["attempt"]),
                )
                effect = cursor.fetchone()
                if effect is None or effect["phase"] != "readback_succeeded":
                    self.connection.rollback()
                    raise DomainConflictError(
                        "EXTERNAL_EFFECT_READBACK_REQUIRED",
                        "External-write step cannot succeed before authoritative readback",
                    )
            require_audited_transition(
                self.connection,
                STEP_STATE_MACHINE,
                current=step["status"],
                target="succeeded",
                principal_type="worker",
                principal_id=worker_id,
                target_type="workflow_step",
                target_code=step_code,
            )
            cursor.execute(
                """
                UPDATE workflow_steps
                SET status = 'succeeded', output_fingerprint = %s,
                    claimed_by = NULL, claim_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = now(), updated_at = now()
                WHERE id = %s
                """,
                (output_fingerprint, step["id"]),
            )
            cursor.execute(
                """
                UPDATE workflow_runs
                SET actual_cost = actual_cost || %s::jsonb, updated_at = now()
                WHERE id = %s
                """,
                (Jsonb(actual_cost), step["run_id"]),
            )
            self._promote_ready_steps(cursor, run_id=step["run_id"])
            self._aggregate_run(cursor, run_id=step["run_id"], actor_id=worker_id)
        self.connection.commit()
        return self.get_step(step_code)

    def fail_step(
        self,
        step_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        error_code: str,
        error_summary: str,
        side_effect_known_not_applied: bool,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            step = self._lock_owned_step(
                cursor,
                step_code,
                worker_id=worker_id,
                claim_token=claim_token,
                lease_version=lease_version,
            )
            if step is None:
                self.connection.rollback()
                return None
            external_write = step["side_effect_level"] in {"write_external", "irreversible_external"}
            if external_write and not side_effect_known_not_applied:
                target = "reconcile_required"
            elif step["attempt"] < step["max_attempts"]:
                target = "ready"
            else:
                target = "failed"
            require_audited_transition(
                self.connection,
                STEP_STATE_MACHINE,
                current=step["status"],
                target=target,
                principal_type="worker",
                principal_id=worker_id,
                target_type="workflow_step",
                target_code=step_code,
            )
            completed_at = datetime.now(UTC) if target == "failed" else None
            cursor.execute(
                """
                UPDATE workflow_steps
                SET status = %s, claimed_by = NULL, claim_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL,
                    error_code = %s, error_summary = %s, completed_at = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (target, error_code, error_summary, completed_at, step["id"]),
            )
            self._aggregate_run(cursor, run_id=step["run_id"], actor_id=worker_id)
        self.connection.commit()
        return self.get_step(step_code)

    def get_step(self, step_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM workflow_steps WHERE step_code = %s", (step_code,))
            step = cursor.fetchone()
        return self._serialize_step(step, include_claim_token=False) if step else None

    def get_external_effect(self, effect_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM workflow_external_effects WHERE effect_code = %s",
                (effect_code,),
            )
            effect = cursor.fetchone()
        return self._serialize(effect) if effect else None

    def create_human_task(
        self,
        *,
        step_code: str,
        task_type: str,
        subject: dict[str, Any],
        priority: int = 100,
        owner_principal: str | None = None,
        due_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        if due_at and expires_at and due_at >= expires_at:
            raise DomainValidationError(
                "HUMAN_TASK_SLA_INVALID",
                "HumanTask due_at must be before expires_at",
            )
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM workflow_steps WHERE step_code = %s FOR UPDATE", (step_code,))
            step = cursor.fetchone()
            if step is None:
                raise DomainConflictError("WORKFLOW_STEP_NOT_FOUND", "Workflow step does not exist")
            if step["status"] != "running":
                raise DomainConflictError("HUMAN_TASK_STEP_NOT_RUNNING", "Only a running step can request human work")
            task_code = self._next_code(cursor, prefix="TASK", object_type="human_task")
            cursor.execute(
                """
                INSERT INTO human_tasks (
                    task_code, run_id, step_id, task_type, priority, owner_principal,
                    due_at, expires_at, subject
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    task_code,
                    step["run_id"],
                    step["id"],
                    task_type,
                    priority,
                    owner_principal,
                    due_at,
                    expires_at,
                    Jsonb(subject),
                ),
            )
            cursor.execute(
                """
                UPDATE workflow_steps
                SET status = 'waiting_human', claimed_by = NULL, claim_token = NULL,
                    lease_expires_at = NULL, heartbeat_at = NULL, updated_at = now()
                WHERE id = %s
                """,
                (step["id"],),
            )
            cursor.execute(
                """
                UPDATE workflow_runs
                SET status = 'waiting_human', waiting_reason = %s, updated_at = now()
                WHERE id = %s
                """,
                (task_type, step["run_id"]),
            )
        self.connection.commit()
        return self.get_human_task(task_code) or {}

    def sweep_human_tasks(self) -> dict[str, int]:
        escalated_count = 0
        expired_count = 0
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE human_tasks
                SET status = 'expired', revision = revision + 1, updated_at = now()
                WHERE status IN ('open', 'claimed', 'escalated')
                  AND expires_at IS NOT NULL AND expires_at <= now()
                RETURNING run_id, step_id, task_code
                """
            )
            expired = cursor.fetchall()
            expired_count = len(expired)
            for task in expired:
                if task["step_id"] is not None:
                    cursor.execute(
                        """
                        UPDATE workflow_steps
                        SET status = 'failed', error_code = 'HUMAN_TASK_EXPIRED',
                            error_summary = 'Required human decision expired',
                            completed_at = now(), updated_at = now()
                        WHERE id = %s AND status = 'waiting_human'
                        """,
                        (task["step_id"],),
                    )
                self._aggregate_run(cursor, run_id=task["run_id"], actor_id="human-task-sweeper")
            cursor.execute(
                """
                UPDATE human_tasks
                SET status = 'escalated', escalated_at = now(),
                    revision = revision + 1, updated_at = now()
                WHERE status IN ('open', 'claimed')
                  AND due_at IS NOT NULL AND due_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                RETURNING id
                """
            )
            escalated_count = len(cursor.fetchall())
        self.connection.commit()
        return {"escalated": escalated_count, "expired": expired_count}

    def list_human_tasks(
        self,
        *,
        status: str | None = None,
        owner_principal: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("task.status = %s")
            params.append(status)
        if owner_principal:
            clauses.append("task.owner_principal = %s")
            params.append(owner_principal)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((limit, offset))
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"""
                SELECT task.*, run.run_code, step.step_code
                FROM human_tasks AS task
                JOIN workflow_runs AS run ON run.id = task.run_id
                LEFT JOIN workflow_steps AS step ON step.id = task.step_id
                {where}
                ORDER BY task.priority, task.due_at NULLS LAST, task.created_at
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = cursor.fetchall()
        return [self._serialize(row) for row in rows]

    def get_human_task(self, task_code: str) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT task.*, run.run_code, step.step_code
                FROM human_tasks AS task
                JOIN workflow_runs AS run ON run.id = task.run_id
                LEFT JOIN workflow_steps AS step ON step.id = task.step_id
                WHERE task.task_code = %s
                """,
                (task_code,),
            )
            task = cursor.fetchone()
        return self._serialize(task) if task else None

    def claim_human_task(
        self,
        task_code: str,
        *,
        claimed_by: str,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                UPDATE human_tasks
                SET status = 'claimed', claimed_by = %s, claimed_at = now(),
                    revision = revision + 1, updated_at = now()
                WHERE task_code = %s AND status IN ('open', 'escalated')
                  AND revision = %s AND (expires_at IS NULL OR expires_at > now())
                RETURNING id
                """,
                (claimed_by, task_code, expected_revision),
            )
            updated = cursor.fetchone()
        self.connection.commit()
        return self.get_human_task(task_code) if updated else None

    def decide_human_task(
        self,
        task_code: str,
        *,
        decided_by: str,
        expected_revision: int,
        decision: str,
        structured_reason: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM human_tasks WHERE task_code = %s FOR UPDATE", (task_code,))
            task = cursor.fetchone()
            if task is None:
                self.connection.rollback()
                return None
            if task["revision"] != expected_revision or task["status"] not in {"open", "claimed", "escalated"}:
                raise DomainConflictError(
                    "HUMAN_TASK_REVISION_CONFLICT",
                    "HumanTask was changed or is no longer decidable",
                )
            if task["claimed_by"] is not None and task["claimed_by"] != decided_by:
                raise DomainConflictError("HUMAN_TASK_CLAIM_CONFLICT", "HumanTask is claimed by another principal")
            cursor.execute(
                """
                UPDATE human_tasks
                SET status = 'decided', decision = %s, structured_reason = %s,
                    decided_by = %s, decided_at = now(), revision = revision + 1,
                    updated_at = now()
                WHERE id = %s
                """,
                (decision, Jsonb(structured_reason), decided_by, task["id"]),
            )
            if task["step_id"] is not None:
                cursor.execute(
                    """
                    UPDATE workflow_steps SET status = 'ready', updated_at = now()
                    WHERE id = %s AND status = 'waiting_human'
                    """,
                    (task["step_id"],),
                )
            cursor.execute(
                """
                UPDATE workflow_runs SET status = 'running', waiting_reason = NULL, updated_at = now()
                WHERE id = %s AND status = 'waiting_human'
                """,
                (task["run_id"],),
            )
        self.connection.commit()
        return self.get_human_task(task_code)

    def _transition_external_effect(
        self,
        effect_code: str,
        *,
        expected_revision: int,
        expected_phase: str,
        target_phase: str,
        actor_type: str,
        actor_id: str | None,
        reason_code: str,
        assignments: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed_columns = {
            "authorization_code",
            "authorized_at",
            "commit_started_at",
            "commit_completed_at",
            "response_summary",
            "external_identity",
            "readback_evidence",
            "readback_completed_at",
            "reconcile_evidence",
            "reconciled_at",
            "unknown_outcome",
            "error_code",
        }
        values = assignments or {}
        unknown_columns = set(values) - allowed_columns
        if unknown_columns:
            raise ValueError(f"unsupported external effect assignments: {sorted(unknown_columns)}")
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT * FROM workflow_external_effects WHERE effect_code = %s FOR UPDATE",
                (effect_code,),
            )
            current = cursor.fetchone()
            if current is None:
                self.connection.rollback()
                raise KeyError(effect_code)
            if current["revision"] != expected_revision or current["phase"] != expected_phase:
                self.connection.rollback()
                raise DomainConflictError(
                    "WORKFLOW_EXTERNAL_EFFECT_REVISION_CONFLICT",
                    "External effect phase or revision changed since it was loaded",
                    details={
                        "expected_phase": expected_phase,
                        "actual_phase": current["phase"],
                        "expected_revision": expected_revision,
                        "actual_revision": current["revision"],
                    },
                )
            clauses = ["phase = %s", "revision = revision + 1", "updated_at = now()"]
            params: list[Any] = [target_phase]
            for column, value in values.items():
                clauses.append(f"{column} = %s")
                params.append(Jsonb(value) if isinstance(value, dict) else value)
            params.append(current["id"])
            cursor.execute(
                f"""
                UPDATE workflow_external_effects
                SET {', '.join(clauses)}
                WHERE id = %s
                RETURNING *
                """,
                tuple(params),
            )
            updated = cursor.fetchone()
            self._append_effect_history(
                cursor,
                effect_id=current["id"],
                from_phase=expected_phase,
                to_phase=target_phase,
                revision=int(updated["revision"]),
                actor_type=actor_type,
                actor_id=actor_id,
                reason_code=reason_code,
                evidence=evidence or {},
            )
        self.connection.commit()
        return self._serialize(updated)

    @staticmethod
    def _append_effect_history(
        cursor: Any,
        *,
        effect_id: UUID,
        from_phase: str | None,
        to_phase: str,
        revision: int,
        actor_type: str,
        actor_id: str | None,
        reason_code: str,
        evidence: dict[str, Any],
    ) -> None:
        event_payload = {
            "effect_id": str(effect_id),
            "from_phase": from_phase,
            "to_phase": to_phase,
            "revision": revision,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "reason_code": reason_code,
            "evidence": evidence,
        }
        event_fingerprint = canonical_fingerprint(event_payload)
        cursor.execute(
            """
            SELECT chain_hash FROM workflow_external_effect_history
            WHERE effect_id = %s ORDER BY revision DESC, id DESC LIMIT 1
            """,
            (effect_id,),
        )
        previous = cursor.fetchone()
        previous_chain_hash = previous["chain_hash"] if previous else None
        chain_hash = hashlib.sha256(
            f"{previous_chain_hash or ''}:{event_fingerprint}".encode("utf-8")
        ).hexdigest()
        cursor.execute(
            """
            INSERT INTO workflow_external_effect_history (
                effect_id, from_phase, to_phase, revision, actor_type,
                actor_id, reason_code, evidence, event_fingerprint,
                previous_chain_hash, chain_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                effect_id,
                from_phase,
                to_phase,
                revision,
                actor_type,
                actor_id,
                reason_code,
                Jsonb(evidence),
                event_fingerprint,
                previous_chain_hash,
                chain_hash,
            ),
        )

    def _recover_expired_leases(self, cursor: Any) -> None:
        cursor.execute(
            """
            UPDATE workflow_steps
            SET status = CASE
                    WHEN side_effect_level IN ('write_external', 'irreversible_external')
                        THEN 'reconcile_required'
                    WHEN attempt < max_attempts THEN 'ready'
                    ELSE 'failed'
                END,
                claimed_by = NULL, claim_token = NULL, lease_expires_at = NULL,
                heartbeat_at = NULL,
                error_code = CASE
                    WHEN started_at + make_interval(secs => timeout_seconds) <= now()
                        THEN 'WORKFLOW_STEP_TIMEOUT'
                    ELSE 'WORKFLOW_LEASE_EXPIRED'
                END,
                error_summary = 'Worker lease or absolute step timeout expired before a terminal result',
                completed_at = CASE
                    WHEN side_effect_level NOT IN ('write_external', 'irreversible_external')
                     AND attempt >= max_attempts THEN now()
                    ELSE completed_at
                END,
                updated_at = now()
            WHERE status = 'running'
              AND (
                  lease_expires_at <= now()
                  OR started_at + make_interval(secs => timeout_seconds) <= now()
              )
            """
        )
        cursor.execute(
            """
            UPDATE workflow_runs AS run
            SET status = 'reconcile_required', updated_at = now()
            WHERE run.status IN ('running', 'cancelling')
              AND EXISTS (
                  SELECT 1 FROM workflow_steps AS step
                  WHERE step.run_id = run.id AND step.status = 'reconcile_required'
              )
            """
        )
        cursor.execute(
            """
            UPDATE workflow_runs AS run
            SET status = 'failed', error_code = 'WORKFLOW_STEP_FAILED',
                error_summary = 'A workflow step exhausted its attempts or timed out',
                completed_at = now(), updated_at = now()
            WHERE run.status IN ('queued', 'running', 'waiting_human')
              AND EXISTS (
                  SELECT 1 FROM workflow_steps AS step
                  WHERE step.run_id = run.id AND step.status = 'failed'
              )
            """
        )

    def _lock_owned_step(
        self,
        cursor: Any,
        step_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT * FROM workflow_steps
            WHERE step_code = %s AND status = 'running' AND claimed_by = %s
              AND claim_token = %s AND lease_version = %s AND lease_expires_at > now()
              AND started_at + make_interval(secs => timeout_seconds) > now()
            FOR UPDATE
            """,
            (step_code, worker_id, claim_token, lease_version),
        )
        return cursor.fetchone()

    def _promote_ready_steps(self, cursor: Any, *, run_id: UUID) -> None:
        cursor.execute(
            """
            UPDATE workflow_steps AS candidate
            SET status = 'ready', updated_at = now()
            WHERE candidate.run_id = %s AND candidate.status = 'pending'
              AND NOT EXISTS (
                  SELECT 1
                  FROM workflow_step_dependencies AS link
                  JOIN workflow_steps AS dependency ON dependency.id = link.depends_on_step_id
                  WHERE link.step_id = candidate.id AND dependency.status <> 'succeeded'
              )
            """,
            (run_id,),
        )

    def _aggregate_run(self, cursor: Any, *, run_id: UUID, actor_id: str) -> None:
        cursor.execute("SELECT * FROM workflow_runs WHERE id = %s FOR UPDATE", (run_id,))
        run = cursor.fetchone()
        cursor.execute(
            """
            SELECT status, count(*) AS count FROM workflow_steps
            WHERE run_id = %s GROUP BY status
            """,
            (run_id,),
        )
        counts = {row["status"]: int(row["count"]) for row in cursor.fetchall()}
        completed = counts.get("succeeded", 0) + counts.get("cancelled", 0)
        target = run["status"]
        error_code = None
        completed_at = None
        if counts.get("reconcile_required", 0):
            target = "reconcile_required"
        elif counts.get("failed", 0):
            target = "failed"
            error_code = "WORKFLOW_STEP_FAILED"
            completed_at = datetime.now(UTC)
        elif completed == run["progress_total"]:
            target = "cancelled" if run["status"] == "cancelling" else "succeeded"
            completed_at = datetime.now(UTC)
        elif counts.get("waiting_human", 0):
            target = "waiting_human"
        elif run["status"] == "queued":
            target = "running"
        if target != run["status"]:
            require_audited_transition(
                self.connection,
                WORKFLOW_STATE_MACHINE,
                current=run["status"],
                target=target,
                principal_type="system",
                principal_id=None,
                target_type="workflow_run",
                target_code=run["run_code"],
                trace_id=run["trace_id"],
            )
            self._append_history(
                cursor,
                run_id=run_id,
                from_status=run["status"],
                to_status=target,
                actor_type="worker",
                actor_id=actor_id,
                reason_code="WORKFLOW_AGGREGATED",
            )
        cursor.execute(
            """
            UPDATE workflow_runs
            SET status = %s, progress_completed = %s, error_code = %s,
                completed_at = COALESCE(%s, completed_at), updated_at = now()
            WHERE id = %s
            """,
            (target, completed, error_code, completed_at, run_id),
        )

    def _fetch_human_tasks(self, cursor: Any, *, run_id: UUID) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT task.*, run.run_code, step.step_code
            FROM human_tasks AS task
            JOIN workflow_runs AS run ON run.id = task.run_id
            LEFT JOIN workflow_steps AS step ON step.id = task.step_id
            WHERE task.run_id = %s
            ORDER BY task.created_at
            """,
            (run_id,),
        )
        return [self._serialize(row) for row in cursor.fetchall()]

    @staticmethod
    def _append_history(
        cursor: Any,
        *,
        run_id: UUID,
        from_status: str | None,
        to_status: str,
        actor_type: str,
        actor_id: str | None,
        reason_code: str,
        step_id: UUID | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO workflow_status_history (
                run_id, step_id, from_status, to_status, reason_code,
                actor_type, actor_id, evidence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                step_id,
                from_status,
                to_status,
                reason_code,
                actor_type,
                actor_id,
                Jsonb(evidence or {}),
            ),
        )

    @staticmethod
    def _serialize(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        for key, value in list(result.items()):
            if isinstance(value, UUID):
                result[key] = str(value)
        return result

    def _serialize_step(self, row: dict[str, Any], *, include_claim_token: bool) -> dict[str, Any]:
        result = self._serialize(row)
        if not include_claim_token:
            result.pop("claim_token", None)
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
        sequence = int(cursor.fetchone()["current_value"])
        return f"{prefix}-{sequence_date:%Y%m%d}-{sequence:06d}"
