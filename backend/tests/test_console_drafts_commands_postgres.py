from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.domain.contracts import canonical_fingerprint
from app.domain.errors import DomainConflictError, DomainValidationError
from app.repositories.console_commands import ConsoleCommandRepository
from app.repositories.console_drafts import ConsoleDraftRepository
from app.repositories.content_core import ContentCoreRepository
from app.repositories.control_plane import ControlPlaneRepository
from app.repositories.live_observations import LiveObservationRepository
from app.repositories.releases import ReleaseRepository
from app.schemas.control_plane import WorkflowRunCreate


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _project_document(title: str, goal: str) -> dict:
    return {
        "title": title,
        "generation_goal": goal,
        "content": {"theme": "wine", "audience": "new customers"},
        "source_revision_refs": [],
    }


def test_console_draft_autosave_conflict_sensitive_data_and_confirm_are_transactional() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        project = ContentCoreRepository(connection).create_project(
            title=f"Draft project {suffix}",
            generation_goal="Initial goal",
            content={},
            actor_id="operator-a",
        )
        project_code = project["project_code"]
        drafts = ConsoleDraftRepository(connection)
        first_document = _project_document(f"Confirmed project {suffix}", "Explain the product clearly")
        first = drafts.save_draft(
            entity_type="content_project",
            entity_code=project_code,
            draft_kind="input",
            schema_version="console-draft.v1",
            expected_revision=0,
            base_entity_revision=1,
            document=first_document,
            actor_id="operator-a",
        )
        replay = drafts.save_draft(
            entity_type="content_project",
            entity_code=project_code,
            draft_kind="input",
            schema_version="console-draft.v1",
            expected_revision=0,
            base_entity_revision=1,
            document=first_document,
            actor_id="operator-a",
        )
        second_document = _project_document(f"Confirmed project {suffix}", "Explain origin and tasting notes")
        second = drafts.save_draft(
            entity_type="content_project",
            entity_code=project_code,
            draft_kind="input",
            schema_version="console-draft.v1",
            expected_revision=1,
            base_entity_revision=1,
            document=second_document,
            actor_id="operator-b",
        )
        assert first["draft_revision"] == replay["draft_revision"] == 1
        assert second["draft_revision"] == 2

        with pytest.raises(DomainConflictError) as stale:
            drafts.save_draft(
                entity_type="content_project",
                entity_code=project_code,
                draft_kind="input",
                schema_version="console-draft.v1",
                expected_revision=1,
                base_entity_revision=1,
                document={**second_document, "generation_goal": "Stale tab"},
                actor_id="operator-a",
            )
        assert stale.value.code == "CONSOLE_DRAFT_REVISION_CONFLICT"
        assert stale.value.details["actual_revision"] == 2

        with pytest.raises(DomainConflictError) as rebase:
            drafts.save_draft(
                entity_type="content_project",
                entity_code=project_code,
                draft_kind="input",
                schema_version="console-draft.v1",
                expected_revision=2,
                base_entity_revision=2,
                document={**second_document, "generation_goal": "Silent rebase"},
                actor_id="operator-a",
            )
        assert rebase.value.code == "CONSOLE_DRAFT_BASE_REVISION_CONFLICT"

        with pytest.raises(DomainValidationError) as sensitive:
            drafts.save_draft(
                entity_type="content_project",
                entity_code=f"SENSITIVE-{suffix}",
                draft_kind="input",
                schema_version="console-draft.v1",
                expected_revision=0,
                base_entity_revision=0,
                document={"password": "must-not-persist"},
                actor_id="operator-a",
            )
        assert sensitive.value.code == "CONSOLE_DRAFT_SENSITIVE_DATA_REJECTED"

        commands = ConsoleCommandRepository(connection)
        invalid_project = ContentCoreRepository(connection).create_project(
            title=f"Invalid draft project {suffix}",
            generation_goal="Initial goal",
            content={},
            actor_id="operator-a",
        )
        invalid_draft = drafts.save_draft(
            entity_type="content_project",
            entity_code=invalid_project["project_code"],
            draft_kind="input",
            schema_version="console-draft.v1",
            expected_revision=0,
            base_entity_revision=1,
            document={"title": "", "generation_goal": "", "content": {}, "source_revision_refs": []},
            actor_id="operator-a",
        )
        with pytest.raises(DomainValidationError) as invalid_schema:
            commands.confirm_content_project(
                invalid_project["project_code"],
                expected_entity_revision=1,
                expected_draft_revision=invalid_draft["draft_revision"],
                idempotency_key=f"confirm-invalid-{suffix}",
                actor_id="operator-a",
            )
        assert invalid_schema.value.code == "CONTENT_PROJECT_REQUIRED_FIELD_MISSING"
        assert connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        confirmed = commands.confirm_content_project(
            project_code,
            expected_entity_revision=1,
            expected_draft_revision=2,
            idempotency_key=f"confirm-{suffix}",
            actor_id="operator-b",
        )
        confirm_replay = commands.confirm_content_project(
            project_code,
            expected_entity_revision=1,
            expected_draft_revision=2,
            idempotency_key=f"confirm-{suffix}",
            actor_id="operator-b",
        )
        current = ContentCoreRepository(connection).get_project(project_code)
        consumed = drafts.get_draft("content_project", project_code, "input")
        assert confirmed["entity_revision"] == 1
        assert confirm_replay["receipt_code"] == confirmed["receipt_code"]
        assert confirm_replay["replayed"] is True
        assert current is not None and current["status"] == "confirmed"
        assert current["generation_goal"] == second_document["generation_goal"]
        assert consumed is not None and consumed["status"] == "consumed" and consumed["draft_revision"] == 3

        reopened_document = _project_document(f"Confirmed project {suffix}", "A genuinely new fixed goal")
        reopened = drafts.save_draft(
            entity_type="content_project",
            entity_code=project_code,
            draft_kind="input",
            schema_version="console-draft.v1",
            expected_revision=3,
            base_entity_revision=1,
            document=reopened_document,
            actor_id="operator-a",
        )
        next_confirmed = commands.confirm_content_project(
            project_code,
            expected_entity_revision=1,
            expected_draft_revision=4,
            idempotency_key=f"confirm-next-{suffix}",
            actor_id="operator-a",
        )
        previous = ContentCoreRepository(connection).get_project_revision(project_code, 1)
        assert reopened["status"] == "active"
        assert next_confirmed["entity_revision"] == 2
        assert previous is not None and previous["status"] == "superseded"

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE console_draft_events SET event_type = 'saved' WHERE draft_code = %s",
                    (first["draft_code"],),
                )
        connection.rollback()


def test_template_publish_and_release_decision_are_revision_bound_and_idempotent() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        live = LiveObservationRepository(connection)
        template = live.create_room_template({"name": f"Template {suffix}", "description": None})
        revision = live.create_room_template_revision(
            template["template_code"],
            {
                "source_session_code": None,
                "contract_version": "layout-hypothesis.v1",
                "canvas": {"width": 1080, "height": 1920},
                "scenes": [{"scene_key": "main"}],
                "components": [],
                "audio_policy": {},
                "provenance": {"source_session_codes": [f"SESSION-{suffix}"]},
                "confidence": 0.8,
                "created_by": "operator-a",
                "content_fingerprint": "a" * 64,
            },
        )
        commands = ConsoleCommandRepository(connection)
        published = commands.publish_live_room_template(
            template["template_code"],
            expected_revision=revision["revision_number"],
            structured_reason={"reason_code": "REVIEW_COMPLETE", "summary": "Reference-only limits reviewed"},
            idempotency_key=f"publish-{suffix}",
            actor_id="operator-a",
        )
        publish_replay = commands.publish_live_room_template(
            template["template_code"],
            expected_revision=revision["revision_number"],
            structured_reason={"reason_code": "REVIEW_COMPLETE", "summary": "Reference-only limits reviewed"},
            idempotency_key=f"publish-{suffix}",
            actor_id="operator-a",
        )
        assert published["layout_fidelity"] == "approximate"
        assert published["buildability"] == "reference_only"
        assert publish_replay["receipt_code"] == published["receipt_code"]

        releases = ReleaseRepository(connection)
        release = releases.create_release_with_manifest(
            subject_type="production_variant",
            subject_code=f"VARIANT-{suffix}",
            subject_revision=1,
            carrier_kind="live_room_draft",
            created_by="producer-a",
            manifest={
                "subject_refs": {},
                "artifact_refs": [],
                "rights_snapshot": {"status": "valid"},
                "quality_snapshot": {"gates": []},
                "lineage_snapshot": {"complete": True},
                "carrier_facet": {},
            },
            manifest_fingerprint=canonical_fingerprint({"kind": "console-command-release", "suffix": suffix}),
            signature_algorithm="hmac-sha256",
            signature_key_id="test-key",
            signature_value="c" * 64,
        )
        releases.transition_release(
            release["release_code"],
            expected_status="candidate",
            target_status="validating",
            actor_id="validator-a",
            reason_code="VALIDATION_STARTED",
            evidence={},
        )
        releases.transition_release(
            release["release_code"],
            expected_status="validating",
            target_status="awaiting_approval",
            actor_id="validator-a",
            reason_code="VALIDATION_PASSED",
            evidence={},
        )
        approved = commands.decide_release(
            release["release_code"],
            expected_manifest_revision=1,
            decision="approve",
            structured_reason={"reason_code": "ALL_GATES_PASS", "summary": "Fixed manifest reviewed"},
            approved_scope={"target_type": "maitu_room"},
            idempotency_key=f"approve-{suffix}",
            actor_id="approver-b",
        )
        approval_replay = commands.decide_release(
            release["release_code"],
            expected_manifest_revision=1,
            decision="approve",
            structured_reason={"reason_code": "ALL_GATES_PASS", "summary": "Fixed manifest reviewed"},
            approved_scope={"target_type": "maitu_room"},
            idempotency_key=f"approve-{suffix}",
            actor_id="approver-b",
        )
        assert approved["status"] == "approved"
        assert approval_replay["receipt_code"] == approved["receipt_code"]
        assert releases.get_release(release["release_code"])["status"] == "approved"


def test_authorize_command_derives_scope_from_one_approved_human_task_and_returns_token_once() -> None:
    suffix = uuid4().hex
    environment = f"console-command-{suffix}"
    with psycopg.connect(DATABASE_URL) as connection:
        policy_rules = {
            "schema_version": "capability-policy.v1",
            "role_capabilities": {"production_worker": ["write_draft"]},
            "required_approval_count": {"write_draft": 1},
        }
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO capability_policy_versions (
                    policy_code, revision_number, status, rules,
                    fingerprint_sha256, approved_by, approved_at
                )
                VALUES (%s, 1, 'active', %s, %s, 'security-test', now())
                """,
                (f"console-policy-{suffix}", Jsonb(policy_rules), canonical_fingerprint(policy_rules)),
            )
            cursor.execute(
                """
                INSERT INTO capability_flags (
                    capability, environment, enabled, kill_switch_active, changed_by, reason
                )
                VALUES ('write_draft', %s, true, false, 'security-test', 'isolated command test')
                """,
                (environment,),
            )
        connection.commit()

        workflow_payload = WorkflowRunCreate.model_validate(
            {
                "workflow_type": "authorization_command_test",
                "subject_type": "content_project",
                "subject_code": f"CONTENT-{suffix}",
                "subject_revision": 1,
                "idempotency_key": f"workflow-{suffix}",
                "steps": [
                    {
                        "step_key": "authorize",
                        "step_type": f"authorize_{suffix}",
                        "idempotency_key": f"authorize-step-{suffix}",
                        "timeout_seconds": 60,
                        "input_fingerprint": "d" * 64,
                    }
                ],
            }
        ).model_dump(mode="json")
        workflow_payload["requested_by"] = "operator-a"
        control = ControlPlaneRepository(connection)
        run = control.create_workflow_run(workflow_payload)
        bad_task_code = f"TASK-BAD-{suffix}"
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO human_tasks (
                    task_code, run_id, task_type, status, revision, subject,
                    decision, structured_reason, decided_by, decided_at
                )
                VALUES (%s, %s, 'authorize_execution', 'decided', 2, %s,
                        'approve', %s, 'operator-a', now())
                """,
                (
                    bad_task_code,
                    run["id"],
                    Jsonb(
                        {
                            "principal_id": "worker-a",
                            "capability": "go_live",
                            "target_type": "maitu_room",
                            "target_id": f"room-{suffix}",
                            "plan_or_release_hash": "e" * 64,
                            "ttl_seconds": 60,
                        }
                    ),
                    Jsonb({"reason_code": "INVALID_SCOPE_TEST", "summary": "Invalid capability fixture"}),
                ),
            )
        connection.commit()
        commands = ConsoleCommandRepository(connection)
        with pytest.raises(DomainValidationError) as invalid_capability:
            commands.issue_authorization(
                run["run_code"],
                task_code=bad_task_code,
                expected_task_revision=2,
                idempotency_key=f"authorize-invalid-{suffix}",
                actor_id="operator-a",
                environment=environment,
                trace_id="1" * 32,
            )
        assert invalid_capability.value.code == "AUTHORIZATION_TASK_CAPABILITY_INVALID"
        assert connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        step = control.claim_next_step(
            worker_id="worker-a",
            lease_seconds=60,
            accepted_step_types=[f"authorize_{suffix}"],
        )
        assert step is not None
        task = control.create_human_task(
            step_code=step["step_code"],
            task_type="authorize_execution",
            subject={
                "principal_id": "worker-a",
                "capability": "write_draft",
                "target_type": "maitu_room",
                "target_id": f"room-{suffix}",
                "plan_or_release_hash": "e" * 64,
                "site_fingerprint": "f" * 64,
                "ttl_seconds": 60,
            },
            owner_principal="operator-a",
        )
        decided = control.decide_human_task(
            task["task_code"],
            decided_by="operator-a",
            expected_revision=task["revision"],
            decision="approve",
            structured_reason={"reason_code": "PREFLIGHT_MATCHED", "summary": "Target and plan reviewed"},
        )
        assert decided is not None

        commands = ConsoleCommandRepository(connection)
        issued = commands.issue_authorization(
            run["run_code"],
            task_code=task["task_code"],
            expected_task_revision=decided["revision"],
            idempotency_key=f"authorize-{suffix}",
            actor_id="operator-a",
            environment=environment,
            trace_id="1" * 32,
        )
        replay = commands.issue_authorization(
            run["run_code"],
            task_code=task["task_code"],
            expected_task_revision=decided["revision"],
            idempotency_key=f"authorize-{suffix}",
            actor_id="operator-a",
            environment=environment,
            trace_id="1" * 32,
        )
        assert issued["token_available"] is True and issued["authorization_token"]
        assert replay["receipt_code"] == issued["receipt_code"]
        assert replay["token_available"] is False and replay["authorization_token"] is None
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM execution_authorizations WHERE source_human_task_id = %s",
                (task["id"],),
            )
            assert cursor.fetchone()[0] == 1

        with pytest.raises(DomainConflictError) as reused_task:
            commands.issue_authorization(
                run["run_code"],
                task_code=task["task_code"],
                expected_task_revision=decided["revision"],
                idempotency_key=f"authorize-again-{suffix}",
                actor_id="operator-a",
                environment=environment,
                trace_id="1" * 32,
            )
        assert reused_task.value.code == "AUTHORIZATION_TASK_ALREADY_USED"
