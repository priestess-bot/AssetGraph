from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.domain.errors import DomainConflictError
from app.repositories.content_workflow import ContentWorkflowRepository
from app.services.content_workflow import (
    GuidedContentGenerationWorker,
    GuidedContentWorkflowService,
)


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured"
)


class FakeGenerator:
    def generate_outline(self, payload: dict, *, principal_id: str) -> dict:
        return {
            "sections": [
                {
                    "section_key": "section-1",
                    "title": "开场",
                    "objective": "建立主题",
                    "key_points": ["欢迎"],
                }
            ],
            "invocation_evidence_ref": "ART-OUTLINE-TEST",
        }

    def generate_script_section(self, payload: dict, *, principal_id: str) -> dict:
        return {
            "speech": "欢迎来到直播间。",
            "material_requirements": [
                {
                    "material_role": "background",
                    "description": "开场背景",
                    "priority": "required",
                    "keywords": ["开场"],
                }
            ],
            "invocation_evidence_ref": "ART-SCRIPT-TEST",
        }


def test_stale_generation_job_rejects_old_worker_terminal_writes() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        repository = ContentWorkflowRepository(connection)
        try:
            workflow = service.create_project(
                title=f"Guided lease {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="租约测试",
                selected_asset_codes=[],
                actor_id="test-operator",
            )
            queued = service.enqueue_outline(project_code, actor_id="test-operator")
            claimed = repository.claim_job("old-worker", lease_seconds=300)
            assert claimed is not None
            assert claimed["job_code"] == queued["job_code"]
            item = repository.job_items(claimed["id"])[0]
            assert repository.mark_item_running(
                item["id"], job_id=claimed["id"], worker_id="old-worker"
            ) is True

            project = repository.get_project(project_code)
            assert project is not None
            repository.stale_active_jobs(project["project_id"], stages=["outline"])

            assert repository.complete_item(
                item["id"],
                job_id=claimed["id"],
                worker_id="old-worker",
                output_payload={"unexpected": True},
                evidence_ref=None,
            ) is False
            assert repository.fail_item(
                item["id"],
                job_id=claimed["id"],
                worker_id="old-worker",
                error_code="OLD_WORKER",
                error_message="must not overwrite item state",
            ) is False

            assert repository.complete_job(
                claimed["id"], worker_id="old-worker", result_refs={"unexpected": True}
            ) is None
            assert repository.fail_job(
                claimed["id"],
                worker_id="old-worker",
                error_code="OLD_WORKER",
                error_message="must not requeue stale work",
            ) is None
            assert repository.get_job(claimed["job_code"])["status"] == "stale"
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM content_projects WHERE project_code = %s",
                        (project_code,),
                    )
                connection.commit()


def test_final_expired_worker_lease_becomes_failed_and_retryable() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        repository = ContentWorkflowRepository(connection)
        try:
            workflow = service.create_project(
                title=f"Guided expired lease {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="最终租约测试",
                selected_asset_codes=[],
                actor_id="test-operator",
            )
            queued = service.enqueue_outline(project_code, actor_id="test-operator")
            claimed = repository.claim_job("crashed-worker", lease_seconds=300)
            assert claimed is not None and claimed["job_code"] == queued["job_code"]
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE content_generation_jobs
                    SET attempts = max_attempts, lease_expires_at = %s
                    WHERE id = %s
                    """,
                    (datetime.now(UTC) - timedelta(seconds=1), claimed["id"]),
                )
            connection.commit()

            repository.claim_job("lease-sweeper", lease_seconds=300)
            failed = repository.get_job(queued["job_code"])
            assert failed is not None
            assert failed["status"] == "failed"
            assert failed["error_code"] == "GENERATION_WORKER_LEASE_EXHAUSTED"

            retried = repository.retry_job(queued["job_code"])
            assert retried["status"] == "queued"
            assert retried["attempts"] == 0
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM content_projects WHERE project_code = %s",
                        (project_code,),
                    )
                connection.commit()

def test_guided_outline_script_jobs_confirmation_and_waiver_are_durable() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        worker = GuidedContentGenerationWorker(connection, generator=FakeGenerator())
        try:
            workflow = service.create_project(
                title=f"Guided workflow {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="夏季新品",
                selected_asset_codes=[],
                actor_id="test-operator",
            )

            service.enqueue_outline(project_code, actor_id="test-operator")
            assert worker.run_once("test-worker")["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            with pytest.raises(DomainConflictError) as outline_regeneration:
                service.enqueue_outline(project_code, actor_id="test-operator")
            assert outline_regeneration.value.code == "GUIDED_OUTLINE_REOPEN_REQUIRED"

            service.enqueue_script(project_code, actor_id="test-operator")
            first_script_job = worker.run_once("test-worker")
            assert first_script_job["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            assert workflow["gates"]["required_material_missing_count"] == 1
            with pytest.raises(DomainConflictError) as blocked:
                service.confirm_script(
                    project_code,
                    expected_revision=workflow["script"]["revision_number"],
                    actor_id="test-operator",
                )
            assert blocked.value.code == "GUIDED_REQUIRED_MATERIALS_MISSING"

            requirement = workflow["script"]["requirements"][0]
            workflow = service.waive_material_requirement(
                project_code,
                requirement["requirement_code"],
                expected_script_revision=workflow["script"]["revision_number"],
                actor_id="test-operator",
            )
            workflow = service.confirm_script(
                project_code,
                expected_revision=workflow["script"]["revision_number"],
                actor_id="test-operator",
            )

            assert workflow["script"]["status"] == "confirmed"
            assert workflow["script"]["requirements"][0]["status"] == "waived"
            assert workflow["gates"]["storyboard_manual_only"] is True

            with pytest.raises(DomainConflictError) as script_regeneration:
                service.enqueue_script(project_code, actor_id="test-operator")
            assert script_regeneration.value.code == "GUIDED_SCRIPT_REOPEN_REQUIRED"

            workflow = service.reopen_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            assert workflow["gates"]["script_current"] is False
            assert workflow["gates"]["storyboard_confirmed"] is False
            with pytest.raises(DomainConflictError) as stale_storyboard:
                service.enqueue_storyboard(
                    project_code,
                    template_code="TPL-NOT-READ",
                    revision=1,
                    projection_fingerprint="a" * 64,
                    actor_id="test-operator",
                )
            assert stale_storyboard.value.code == "GUIDED_SCRIPT_INPUT_STALE"

            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            regenerated = service.enqueue_script(project_code, actor_id="test-operator")
            assert regenerated["status"] == "queued"
            assert regenerated["job_code"] != first_script_job["job_code"]
            history = workflow["history"]
            assert any(item["kind"] == "material_waiver" for item in history)
            assert sum(item["kind"] == "script_revision" for item in history) >= 1
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        "SELECT id FROM content_projects WHERE project_code = %s",
                        (project_code,),
                    )
                    row = cursor.fetchone()
                    if row:
                        cursor.execute(
                            "DELETE FROM content_script_revisions WHERE project_id = %s",
                            (row["id"],),
                        )
                        cursor.execute(
                            "DELETE FROM story_briefs WHERE project_id = %s",
                            (row["id"],),
                        )
                        cursor.execute(
                            "DELETE FROM content_projects WHERE id = %s",
                            (row["id"],),
                        )
                connection.commit()


def test_script_regeneration_archives_and_restore_clones_a_new_revision() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        worker = GuidedContentGenerationWorker(connection, generator=FakeGenerator())
        try:
            workflow = service.create_project(
                title=f"Guided archive {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="Archive test",
                selected_asset_codes=[],
                actor_id="test-operator",
            )
            service.enqueue_outline(project_code, actor_id="test-operator")
            assert worker.run_once("archive-worker")["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            service.enqueue_script(project_code, actor_id="test-operator")
            assert worker.run_once("archive-worker")["status"] == "succeeded"
            first = service.get_workflow(project_code)["script"]
            assert first is not None
            first_code = first["script_revision_code"]
            first_content = first["blocks"][0]["content"]

            queued = service.enqueue_script(project_code, actor_id="test-operator")
            assert queued["status"] == "queued"
            interim = service.get_workflow(project_code)
            assert interim["script"] is None
            assert interim["script_archives"][0]["script_revision_code"] == first_code
            assert worker.run_once("archive-worker")["status"] == "succeeded"
            second = service.get_workflow(project_code)["script"]
            assert second is not None
            assert second["revision_number"] == first["revision_number"] + 1

            restored = service.restore_script(
                project_code,
                first["revision_number"],
                expected_current_revision=second["revision_number"],
                actor_id="test-operator",
            )
            assert restored["script"] is not None
            assert restored["script"]["revision_number"] == second["revision_number"] + 1
            assert restored["script"]["blocks"][0]["content"] == first_content
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT revision.status, block.content
                    FROM content_script_revisions AS revision
                    JOIN content_script_blocks AS block ON block.script_revision_id = revision.id
                    WHERE revision.script_revision_code = %s
                    ORDER BY block.sort_order
                    """,
                    (first_code,),
                )
                immutable = cursor.fetchone()
            assert immutable is not None
            assert immutable["status"] == "superseded"
            assert immutable["content"] == first_content
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute("SELECT id FROM content_projects WHERE project_code = %s", (project_code,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute("DELETE FROM content_script_revisions WHERE project_id = %s", (row["id"],))
                        cursor.execute("DELETE FROM story_briefs WHERE project_id = %s", (row["id"],))
                        cursor.execute("DELETE FROM content_projects WHERE id = %s", (row["id"],))
                connection.commit()
