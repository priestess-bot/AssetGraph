from __future__ import annotations

import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.domain.contracts import Capability
from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.console_drafts import ConsoleDraftRepository
from app.repositories.content_core import ContentCoreRepository
from app.repositories.live_observations import LiveObservationRepository
from app.repositories.policy import PolicyRepository
from app.repositories.releases import ReleaseRepository
from app.services.live_observations import LiveObservationConflictError, build_template_projection
from app.services.policy import PolicyDecisionService, PolicyRequest


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_AUTHORIZATION_CAPABILITIES = {
    Capability.WRITE_DRAFT,
    Capability.UPLOAD_ASSET,
    Capability.DELIVER_RELEASE,
    Capability.REBUILD_PROJECTION,
}


class ConsoleCommandRepository:
    """Named Console commands with durable, non-secret idempotency receipts."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def confirm_content_project(
        self,
        project_code: str,
        *,
        expected_entity_revision: int,
        expected_draft_revision: int,
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        command_type = "confirm"
        entity_type = "content_project"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._lock_command(cursor, command_type, entity_type, project_code, idempotency_key)
            replay = self._receipt(cursor, command_type, entity_type, project_code, idempotency_key)
            if replay:
                return replay
            cursor.execute(
                """
                SELECT * FROM console_drafts
                WHERE entity_type = 'content_project' AND entity_code = %s AND draft_kind = 'input'
                FOR UPDATE
                """,
                (project_code,),
            )
            draft = cursor.fetchone()
            if draft is None:
                self.connection.rollback()
                raise DomainConflictError("CONSOLE_DRAFT_NOT_FOUND", "No input draft exists for this content project")
            if int(draft["draft_revision"]) != expected_draft_revision or draft["status"] != "active":
                self.connection.rollback()
                raise DomainConflictError(
                    "CONSOLE_DRAFT_REVISION_CONFLICT",
                    "The input draft changed or was already consumed",
                    details={
                        "expected_revision": expected_draft_revision,
                        "actual_revision": int(draft["draft_revision"]),
                        "status": draft["status"],
                    },
                )
            if int(draft["base_entity_revision"]) != expected_entity_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "CONSOLE_DRAFT_BASE_REVISION_CONFLICT",
                    "The draft is based on another content project revision",
                    details={
                        "draft_base_revision": int(draft["base_entity_revision"]),
                        "expected_entity_revision": expected_entity_revision,
                    },
                )
            try:
                document = self._content_project_document(draft["document"])
            except DomainValidationError:
                self.connection.rollback()
                raise
            confirmed = ContentCoreRepository(self.connection).materialize_and_confirm_project_revision(
                project_code,
                expected_revision=expected_entity_revision,
                title=document["title"],
                generation_goal=document["generation_goal"],
                content=document["content"],
                source_revision_refs=document["source_revision_refs"],
                actor_id=actor_id,
                commit=False,
            )
            consumed_revision = expected_draft_revision + 1
            cursor.execute(
                """
                UPDATE console_drafts
                SET draft_revision = %s, status = 'consumed', updated_by = %s, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (consumed_revision, actor_id, draft["id"]),
            )
            consumed = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO console_draft_events (
                    draft_id, draft_code, draft_revision, event_type,
                    base_entity_revision, content_fingerprint, actor_id, event_metadata
                )
                VALUES (%s, %s, %s, 'consumed', %s, %s, %s, %s)
                """,
                (
                    consumed["id"],
                    consumed["draft_code"],
                    consumed_revision,
                    consumed["base_entity_revision"],
                    consumed["content_fingerprint"],
                    actor_id,
                    Jsonb({"result_entity_revision": confirmed["revision_number"], "status": "confirmed"}),
                ),
            )
            result = {
                "command": command_type,
                "entity_type": entity_type,
                "entity_code": project_code,
                "entity_revision": int(confirmed["revision_number"]),
                "status": "confirmed",
                "draft_revision": consumed_revision,
                "impact": "The fixed content-project input revision is now available to generation workflows.",
            }
            receipt = self._record_receipt(
                cursor,
                command_type=command_type,
                entity_type=entity_type,
                entity_code=project_code,
                requested_revision=expected_entity_revision,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
                result_status="succeeded",
                result=result,
            )
            self._audit(cursor, receipt, actor_id=actor_id)
        self.connection.commit()
        return receipt

    def publish_live_room_template(
        self,
        template_code: str,
        *,
        expected_revision: int,
        structured_reason: dict[str, Any],
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        command_type = "publish"
        entity_type = "live_room_template"
        ConsoleDraftRepository._validate_document(structured_reason)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._lock_command(cursor, command_type, entity_type, template_code, idempotency_key)
            replay = self._receipt(cursor, command_type, entity_type, template_code, idempotency_key)
            if replay:
                return replay
            repository = LiveObservationRepository(self.connection)
            template = repository.get_room_template(template_code, include_revisions=True)
            if template is None:
                self.connection.rollback()
                raise KeyError(template_code)
            revision = next(
                (row for row in template.get("revisions") or [] if int(row["revision_number"]) == expected_revision),
                None,
            )
            if revision is None:
                self.connection.rollback()
                raise DomainConflictError("TEMPLATE_REVISION_NOT_FOUND", "Room template revision was not found")
            projection = build_template_projection(template, revision)
            try:
                published = repository.publish_room_template_revision(
                    template_code,
                    expected_revision,
                    {
                        "review_notes": structured_reason["summary"],
                        "reviewed_by": actor_id,
                        "published_by": actor_id,
                        "publication_reason": structured_reason.get("reason_code"),
                    },
                    projection,
                    commit=False,
                )
            except LiveObservationConflictError as exc:
                self.connection.rollback()
                raise DomainConflictError("TEMPLATE_PUBLISH_CONFLICT", str(exc)) from exc
            result = {
                "command": command_type,
                "entity_type": entity_type,
                "entity_code": template_code,
                "entity_revision": expected_revision,
                "status": "published",
                "layout_fidelity": published["layout_fidelity"],
                "buildability": published["buildability"],
                "impact": "The reviewed template projection is now selectable at this fixed revision.",
            }
            receipt = self._record_receipt(
                cursor,
                command_type=command_type,
                entity_type=entity_type,
                entity_code=template_code,
                requested_revision=expected_revision,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
                result_status="succeeded",
                result=result,
            )
            self._audit(cursor, receipt, actor_id=actor_id)
        self.connection.commit()
        return receipt

    def decide_release(
        self,
        release_code: str,
        *,
        expected_manifest_revision: int,
        decision: str,
        structured_reason: dict[str, Any],
        approved_scope: dict[str, Any],
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise DomainValidationError("RELEASE_DECISION_INVALID", "Release decision must be approve or reject")
        ConsoleDraftRepository._validate_document(structured_reason)
        ConsoleDraftRepository._validate_document(approved_scope)
        entity_type = "release"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._lock_command(cursor, decision, entity_type, release_code, idempotency_key)
            replay = self._receipt(cursor, decision, entity_type, release_code, idempotency_key)
            if replay:
                return replay
            approval = ReleaseRepository(self.connection).add_approval(
                release_code,
                decision=decision,
                structured_reason=structured_reason,
                approved_scope=approved_scope,
                decided_by=actor_id,
                expected_manifest_revision=expected_manifest_revision,
                commit=False,
            )
            target_status = "approved" if decision == "approve" else "candidate"
            result = {
                "command": decision,
                "entity_type": entity_type,
                "entity_code": release_code,
                "entity_revision": expected_manifest_revision,
                "status": target_status,
                "approval_code": approval["approval_code"],
                "impact": (
                    "The fixed release manifest is approved; delivery remains a separate explicit operation."
                    if decision == "approve"
                    else "The release returned to candidate and cannot be delivered as approved."
                ),
            }
            receipt = self._record_receipt(
                cursor,
                command_type=decision,
                entity_type=entity_type,
                entity_code=release_code,
                requested_revision=expected_manifest_revision,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
                result_status="succeeded",
                result=result,
            )
            self._audit(cursor, receipt, actor_id=actor_id)
        self.connection.commit()
        return receipt

    def issue_authorization(
        self,
        run_code: str,
        *,
        task_code: str,
        expected_task_revision: int,
        idempotency_key: str,
        actor_id: str,
        environment: str,
        trace_id: str | None,
    ) -> dict[str, Any]:
        command_type = "authorize"
        entity_type = "workflow_run"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            self._lock_command(cursor, command_type, entity_type, run_code, idempotency_key)
            replay = self._receipt(cursor, command_type, entity_type, run_code, idempotency_key)
            if replay:
                replay["authorization_token"] = None
                replay["token_available"] = False
                return replay
            cursor.execute(
                """
                SELECT task.*, run.run_code
                FROM human_tasks AS task
                JOIN workflow_runs AS run ON run.id = task.run_id
                WHERE task.task_code = %s
                FOR UPDATE OF task
                """,
                (task_code,),
            )
            task = cursor.fetchone()
            if task is None or task["run_code"] != run_code:
                self.connection.rollback()
                raise DomainConflictError("AUTHORIZATION_TASK_NOT_FOUND", "Authorization HumanTask was not found for this run")
            if int(task["revision"]) != expected_task_revision:
                self.connection.rollback()
                raise DomainConflictError(
                    "HUMAN_TASK_REVISION_CONFLICT",
                    "Authorization HumanTask changed since it was loaded",
                    details={"expected_revision": expected_task_revision, "actual_revision": int(task["revision"])},
                )
            if task["task_type"] != "authorize_execution" or task["status"] != "decided" or task["decision"] != "approve":
                self.connection.rollback()
                raise DomainConflictError(
                    "AUTHORIZATION_TASK_NOT_APPROVED",
                    "A decided authorize_execution HumanTask with an approve decision is required",
                )
            cursor.execute(
                "SELECT authorization_code FROM execution_authorizations WHERE source_human_task_id = %s",
                (task["id"],),
            )
            already_issued = cursor.fetchone()
            if already_issued is not None:
                self.connection.rollback()
                raise DomainConflictError(
                    "AUTHORIZATION_TASK_ALREADY_USED",
                    "This HumanTask has already issued an execution authorization",
                    details={"authorization_code": already_issued["authorization_code"]},
                )
            try:
                subject = dict(task["subject"])
                capability = self._authorization_capability(subject.get("capability"))
                principal_id = self._required_text(subject, "principal_id")
                target_type = self._required_text(subject, "target_type")
                target_id = self._required_text(subject, "target_id")
                plan_hash = self._required_sha(subject, "plan_or_release_hash")
                site_fingerprint = subject.get("site_fingerprint")
                if site_fingerprint is not None and not _SHA256.fullmatch(str(site_fingerprint)):
                    raise DomainValidationError(
                        "AUTHORIZATION_TASK_SUBJECT_INVALID",
                        "HumanTask site fingerprint is invalid",
                    )
                try:
                    ttl_seconds = int(subject.get("ttl_seconds") or 0)
                except (TypeError, ValueError) as exc:
                    raise DomainValidationError(
                        "AUTHORIZATION_TASK_TTL_INVALID",
                        "HumanTask authorization TTL must be an integer between 30 and 300 seconds",
                    ) from exc
                if ttl_seconds < 30 or ttl_seconds > 300:
                    raise DomainValidationError(
                        "AUTHORIZATION_TASK_TTL_INVALID",
                        "HumanTask authorization TTL must be between 30 and 300 seconds",
                    )
            except DomainValidationError:
                self.connection.rollback()
                raise
            approval_chain = (
                {
                    "principal_id": task["decided_by"],
                    "decision": "approve",
                    "task_code": task_code,
                    "task_revision": expected_task_revision,
                    "structured_reason": task["structured_reason"],
                },
            )
            authorization, raw_token = PolicyDecisionService(PolicyRepository(self.connection)).issue_execution_authorization(
                PolicyRequest(
                    principal_type="worker",
                    principal_id=principal_id,
                    roles=frozenset({"production_worker"}),
                    capability=capability,
                    target_type=target_type,
                    target_id=target_id,
                    action="issue",
                    environment=environment,
                    plan_or_release_hash=plan_hash,
                    site_fingerprint=str(site_fingerprint) if site_fingerprint else None,
                    approval_chain=approval_chain,
                    trace_id=trace_id,
                ),
                ttl=timedelta(seconds=ttl_seconds),
                source_human_task_id=str(task["id"]),
                commit=False,
            )
            result = {
                "command": command_type,
                "entity_type": entity_type,
                "entity_code": run_code,
                "entity_revision": expected_task_revision,
                "status": "issued",
                "authorization_code": authorization["authorization_code"],
                "capability": capability.value,
                "target_type": target_type,
                "target_id": target_id,
                "expires_at": authorization["expires_at"].isoformat(),
                "impact": "A short-lived, target/hash-bound, single-use authorization was issued; no external write ran.",
            }
            receipt = self._record_receipt(
                cursor,
                command_type=command_type,
                entity_type=entity_type,
                entity_code=run_code,
                requested_revision=expected_task_revision,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
                result_status="issued",
                result=result,
            )
            self._audit(cursor, receipt, actor_id=actor_id)
        self.connection.commit()
        receipt["authorization_token"] = raw_token
        receipt["token_available"] = True
        return receipt

    @staticmethod
    def _content_project_document(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) - {"title", "generation_goal", "content", "source_revision_refs"}:
            raise DomainValidationError(
                "CONTENT_PROJECT_DRAFT_SCHEMA_INVALID",
                "Content project input drafts contain only title, generation_goal, content and source_revision_refs",
            )
        title = value.get("title")
        goal = value.get("generation_goal")
        content = value.get("content", {})
        sources = value.get("source_revision_refs", [])
        if not isinstance(title, str) or not title.strip() or not isinstance(goal, str) or not goal.strip():
            raise DomainValidationError("CONTENT_PROJECT_REQUIRED_FIELD_MISSING", "Title and generation goal are required")
        if not isinstance(content, dict) or not isinstance(sources, list) or not all(isinstance(row, dict) for row in sources):
            raise DomainValidationError("CONTENT_PROJECT_DRAFT_SCHEMA_INVALID", "Content and source revision refs are invalid")
        return {
            "title": title,
            "generation_goal": goal,
            "content": content,
            "source_revision_refs": sources,
        }

    @staticmethod
    def _authorization_capability(value: Any) -> Capability:
        try:
            capability = Capability(str(value))
        except ValueError as exc:
            raise DomainValidationError("AUTHORIZATION_TASK_CAPABILITY_INVALID", "HumanTask capability is invalid") from exc
        if capability not in _AUTHORIZATION_CAPABILITIES:
            raise DomainValidationError(
                "AUTHORIZATION_TASK_CAPABILITY_INVALID",
                "HumanTask capability is not eligible for Console execution authorization",
            )
        return capability

    @staticmethod
    def _required_text(subject: dict[str, Any], key: str) -> str:
        value = subject.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise DomainValidationError("AUTHORIZATION_TASK_SUBJECT_INVALID", f"HumanTask {key} is invalid")
        return value.strip()

    @classmethod
    def _required_sha(cls, subject: dict[str, Any], key: str) -> str:
        value = cls._required_text(subject, key)
        if not _SHA256.fullmatch(value):
            raise DomainValidationError("AUTHORIZATION_TASK_SUBJECT_INVALID", f"HumanTask {key} is invalid")
        return value

    @staticmethod
    def _lock_command(
        cursor: Any,
        command_type: str,
        entity_type: str,
        entity_code: str,
        idempotency_key: str,
    ) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{command_type}:{entity_type}:{entity_code}:{idempotency_key}",),
        )

    @staticmethod
    def _receipt(
        cursor: Any,
        command_type: str,
        entity_type: str,
        entity_code: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        cursor.execute(
            """
            SELECT * FROM console_command_receipts
            WHERE command_type = %s AND entity_type = %s
              AND entity_code = %s AND idempotency_key = %s
            """,
            (command_type, entity_type, entity_code, idempotency_key),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        result = dict(row["result_payload"])
        result.update({"receipt_code": row["receipt_code"], "replayed": True})
        return result

    @staticmethod
    def _record_receipt(
        cursor: Any,
        *,
        command_type: str,
        entity_type: str,
        entity_code: str,
        requested_revision: int | None,
        idempotency_key: str,
        actor_id: str,
        result_status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        receipt_code = f"COMMAND-{uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO console_command_receipts (
                receipt_code, command_type, entity_type, entity_code,
                requested_entity_revision, idempotency_key, actor_id,
                result_status, result_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                receipt_code,
                command_type,
                entity_type,
                entity_code,
                requested_revision,
                idempotency_key,
                actor_id,
                result_status,
                Jsonb(result),
            ),
        )
        return {**result, "receipt_code": receipt_code, "replayed": False}

    @staticmethod
    def _audit(cursor: Any, receipt: dict[str, Any], *, actor_id: str) -> None:
        cursor.execute(
            """
            INSERT INTO audit_events (
                audit_event_id, principal_type, principal_id, action,
                target_type, target_code, target_revision, outcome,
                reason_code, details
            )
            VALUES (%s, 'user', %s, %s, %s, %s, %s, 'succeeded', %s, %s)
            """,
            (
                uuid4(),
                actor_id,
                receipt["command"],
                receipt["entity_type"],
                receipt["entity_code"],
                receipt.get("entity_revision"),
                f"CONSOLE_{str(receipt['command']).upper()}_SUCCEEDED",
                Jsonb({"receipt_code": receipt["receipt_code"], "status": receipt["status"]}),
            ),
        )
