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


class StoryboardFakeGenerator(FakeGenerator):
    def generate_outline(self, payload: dict, *, principal_id: str) -> dict:
        return {
            "sections": [
                {
                    "section_key": "section-1",
                    "title": "Opening",
                    "objective": "Introduce the session",
                    "key_points": [],
                },
                {
                    "section_key": "section-2",
                    "title": "Product details",
                    "objective": "Explain the product",
                    "key_points": [],
                },
            ],
            "invocation_evidence_ref": "ART-OUTLINE-STORYBOARD-TEST",
        }

    def generate_script_section(self, payload: dict, *, principal_id: str) -> dict:
        section_key = str((payload.get("section") or {}).get("section_key") or "section")
        return {
            "speech": f"Initial speech for {section_key}",
            "material_requirements": [],
            "invocation_evidence_ref": "ART-SCRIPT-STORYBOARD-TEST",
        }

    def generate_storyboard_scene(self, payload: dict, *, principal_id: str) -> dict:
        return {
            "title": "Regenerated first scene",
            "layer_asset_codes": ["ASSET-LAYER-1"],
            "invocation_evidence_ref": "ART-STORYBOARD-SCENE-TEST",
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
            workflow = service.confirm_setup(
                project_code,
                expected_revision=workflow["setup_branch"]["current_revision_number"],
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
            workflow = service.confirm_setup(
                project_code,
                expected_revision=workflow["setup_branch"]["current_revision_number"],
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
            workflow = service.confirm_setup(
                project_code,
                expected_revision=workflow["setup_branch"]["current_revision_number"],
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

            script_node_code = workflow["active_path"][-1]
            no_change = service.confirmation_preview(project_code, "outline")
            assert no_change["changed"] is False
            workflow = service.confirm_outline(
                project_code,
                expected_revision=no_change["expected_revision"],
                preview_fingerprint=no_change["preview_fingerprint"],
                actor_id="test-operator",
            )
            assert workflow["confirmation"]["outcome"] == "unchanged"
            assert workflow["gates"]["script_current"] is True
            assert workflow["active_path"][-1] == script_node_code

            sections = [
                {
                    "section_key": item["section_key"],
                    "title": f"{item['title']}（修订）",
                    "objective": item["objective"],
                    "key_points": item["key_points"],
                }
                for item in workflow["outline"]["sections"]
            ]
            workflow = service.revise_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                sections=sections,
                actor_id="test-operator",
            )
            preview = service.confirmation_preview(project_code, "outline")
            assert preview["changed"] is True
            assert preview["diff"]["changed"] == ["section-1"]
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                preview_fingerprint=preview["preview_fingerprint"],
                actor_id="test-operator",
            )
            assert workflow["gates"]["script_current"] is False
            with pytest.raises(DomainConflictError) as stale_storyboard:
                service.enqueue_storyboard(
                    project_code,
                    template_code="TPL-NOT-READ",
                    revision=1,
                    projection_fingerprint="a" * 64,
                    actor_id="test-operator",
                )
            assert stale_storyboard.value.code == "GUIDED_SCRIPT_INPUT_STALE"

            regenerated = service.enqueue_script(project_code, actor_id="test-operator")
            assert regenerated["status"] == "queued"
            assert regenerated["job_code"] != first_script_job["job_code"]
            assert len([node for node in service.workflow_tree(project_code)["nodes"] if node["stage"] == "script"]) == 2
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


def test_script_regeneration_creates_isolated_sibling_branches() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        worker = GuidedContentGenerationWorker(connection, generator=FakeGenerator())
        try:
            workflow = service.create_project(
                title=f"Guided branches {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="Branch test",
                selected_asset_codes=[],
                actor_id="test-operator",
            )
            workflow = service.confirm_setup(
                project_code,
                expected_revision=workflow["setup_branch"]["current_revision_number"],
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
            first_workflow = service.get_workflow(project_code)
            first = first_workflow["script"]
            assert first is not None
            first_content = first["blocks"][0]["content"]
            first_node_code = first_workflow["active_path"][-1]

            queued = service.enqueue_script(project_code, actor_id="test-operator")
            assert queued["status"] == "queued"
            interim = service.get_workflow(project_code)
            assert interim["script"] is None
            second_node_code = interim["active_path"][-1]
            assert second_node_code != first_node_code
            assert worker.run_once("archive-worker")["status"] == "succeeded"
            second = service.get_workflow(project_code)["script"]
            assert second is not None
            assert second["revision_number"] == 1

            tree = service.workflow_tree(project_code)
            restored = service.select_branch(
                project_code,
                node_code=first_node_code,
                expected_head_revision=tree["head_revision"],
                actor_id="test-operator",
            )
            assert restored["script"] is not None
            assert restored["script"]["blocks"][0]["content"] == first_content
            assert restored["active_path"][-1] == first_node_code
            assert len([node for node in restored["tree"]["nodes"] if node["stage"] == "script"]) == 2
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        "SELECT id FROM content_projects WHERE project_code = %s", (project_code,)
                    )
                    row = cursor.fetchone()
                    if row:
                        cursor.execute(
                            "DELETE FROM content_script_revisions WHERE project_id = %s", (row["id"],)
                        )
                        cursor.execute("DELETE FROM story_briefs WHERE project_id = %s", (row["id"],))
                    cursor.execute(
                        "DELETE FROM content_projects WHERE project_code = %s", (project_code,)
                    )
                connection.commit()


def test_targeted_storyboard_scene_regeneration_preserves_other_scenes_and_clears_stale_gate() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        worker = GuidedContentGenerationWorker(connection, generator=StoryboardFakeGenerator())
        try:
            workflow = service.create_project(
                title=f"Guided storyboard scene {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="Storyboard scene regeneration",
                selected_asset_codes=[],
                actor_id="test-operator",
            )
            workflow = service.confirm_setup(
                project_code,
                expected_revision=workflow["setup_branch"]["current_revision_number"],
                actor_id="test-operator",
            )
            service.enqueue_outline(project_code, actor_id="test-operator")
            assert worker.run_once("storyboard-scene-worker")["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            service.enqueue_script(project_code, actor_id="test-operator")
            assert worker.run_once("storyboard-scene-worker")["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            workflow = service.confirm_script(
                project_code,
                expected_revision=workflow["script"]["revision_number"],
                actor_id="test-operator",
            )

            project = service.repository.get_project(project_code)
            assert project is not None
            context = service.versions.context(project["project_id"])
            outline_node = service.versions.stage_node(context, "outline")
            script_node = service.versions.stage_node(context, "script")
            assert outline_node is not None and outline_node.get("revision") is not None
            assert script_node is not None and script_node.get("revision") is not None
            original_script_revision = script_node["revision"]
            storyboard_node = service.versions.create_node(
                project_id=project["project_id"],
                project_code=project_code,
                stage="storyboard",
                parent_node_id=script_node["id"],
                label="Two scene storyboard",
                actor_id="test-operator",
            )
            initial_storyboard = service.versions.save_revision(
                node_id=storyboard_node["id"],
                expected_revision=0,
                content={"template_code": "TEST-TEMPLATE"},
                items=[
                    {
                        "item_key": item["item_key"],
                        "item_type": "storyboard_scene",
                        "source_item_key": item["item_key"],
                        "content": {
                            "shot_code": item["item_key"],
                            "title": f"Initial {item['item_key']}",
                            "script": item["content"]["speech"],
                            "layers": [
                                {
                                    "asset_code": "ASSET-LAYER-1",
                                    "kind": "image",
                                    "z_index": 1,
                                }
                            ],
                        },
                        "source_node_revision_id": original_script_revision["id"],
                        "source_item_version_id": item["item_version_id"],
                    }
                    for item in original_script_revision["items"]
                ],
                actor_id="test-operator",
                producer_kind="human",
                producer_ref="test-storyboard-seed",
                source_parent_revision_id=original_script_revision["id"],
            )
            assert initial_storyboard["revision_number"] == 1

            changed_script = service.versions.save_revision(
                node_id=script_node["id"],
                expected_revision=original_script_revision["revision_number"],
                content=dict(original_script_revision["content"]),
                items=[
                    {
                        "item_key": "section-1",
                        "item_type": "script_block",
                        "source_item_key": "section-1",
                        "content": {
                            "speech": "Changed first script block",
                            "material_requirements": [],
                        },
                        "source_node_revision_id": outline_node["revision"]["id"],
                        "source_item_version_id": outline_node["revision"]["items"][0][
                            "item_version_id"
                        ],
                    },
                    {
                        "item_key": "section-2",
                        "item_version_id": original_script_revision["items"][1][
                            "item_version_id"
                        ],
                    },
                ],
                actor_id="test-operator",
                producer_kind="human",
                producer_ref="test-script-change",
                source_parent_revision_id=outline_node["revision"]["id"],
            )
            service.versions.confirm_revision(
                node_id=script_node["id"],
                expected_revision=changed_script["revision_number"],
                actor_id="test-operator",
            )

            stale_workflow = service.get_workflow(project_code)
            assert stale_workflow["gates"]["storyboard_current"] is False
            assert [
                scene["stale"]
                for scene in stale_workflow["storyboard"]["blueprint"]["scenes"]
            ] == [True, False]

            reaffirmed = service.reaffirm_storyboard_scene(
                project_code,
                "section-1",
                expected_revision=initial_storyboard["revision_number"],
                actor_id="test-operator",
            )
            reaffirmed_versions_one = service.versions.item_versions(
                storyboard_node["id"], "section-1"
            )
            reaffirmed_versions_two = service.versions.item_versions(
                storyboard_node["id"], "section-2"
            )
            active_script = service.versions.stage_node(
                service.versions.context(project["project_id"]), "script"
            )

            assert active_script is not None and active_script.get("revision") is not None
            assert reaffirmed["gates"]["storyboard_current"] is True
            assert len(reaffirmed_versions_one) == 2
            assert len(reaffirmed_versions_two) == 1
            assert reaffirmed_versions_one[-1]["source_item_version_id"] == active_script[
                "revision"
            ]["items"][0]["item_version_id"]
            assert reaffirmed_versions_two[0]["id"] == initial_storyboard["items"][1][
                "item_version_id"
            ]
            current_storyboard_node = service.versions.node_by_id(storyboard_node["id"])
            assert current_storyboard_node is not None

            queued = service.enqueue_storyboard_scene_regeneration(
                project_code,
                "section-1",
                expected_revision=current_storyboard_node["current_revision_number"],
                guidance="Use the current script block",
                actor_id="test-operator",
            )
            assert queued["operation"] == "regenerate_storyboard_scene"
            assert worker.run_once("storyboard-scene-worker")["status"] == "succeeded"

            regenerated = service.get_workflow(project_code)
            scenes = regenerated["storyboard"]["blueprint"]["scenes"]
            by_key = {scene["shot_code"]: scene for scene in scenes}
            versions_one = service.versions.item_versions(storyboard_node["id"], "section-1")
            versions_two = service.versions.item_versions(storyboard_node["id"], "section-2")
            active_script = service.versions.stage_node(
                service.versions.context(project["project_id"]), "script"
            )

            assert active_script is not None and active_script.get("revision") is not None
            assert regenerated["gates"]["storyboard_current"] is True
            assert by_key["section-1"]["title"] == "Regenerated first scene"
            assert by_key["section-1"]["script"] == "Changed first script block"
            assert by_key["section-1"]["source_item_version_id"] == str(
                active_script["revision"]["items"][0]["item_version_id"]
            )
            assert by_key["section-2"]["title"] == "Initial section-2"
            assert len(versions_one) == len(reaffirmed_versions_one) + 1
            assert len(versions_two) == 1
            assert versions_two == reaffirmed_versions_two
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        "SELECT id FROM content_projects WHERE project_code = %s", (project_code,)
                    )
                    row = cursor.fetchone()
                    if row:
                        cursor.execute(
                            "DELETE FROM content_script_revisions WHERE project_id = %s", (row["id"],)
                        )
                        cursor.execute("DELETE FROM story_briefs WHERE project_id = %s", (row["id"],))
                    cursor.execute(
                        "DELETE FROM content_projects WHERE project_code = %s", (project_code,)
                    )
                connection.commit()


def test_outline_structure_changes_sync_script_and_storyboard_drafts_without_regeneration() -> None:
    assert DATABASE_URL is not None
    project_code = ""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        service = GuidedContentWorkflowService(connection)
        worker = GuidedContentGenerationWorker(connection, generator=StoryboardFakeGenerator())
        try:
            workflow = service.create_project(
                title=f"Guided structural sync {uuid4().hex}",
                target_live_room_id="39826",
                actor_id="test-operator",
            )
            project_code = workflow["project"]["project_code"]
            workflow = service.update_setup(
                project_code,
                expected_project_revision=workflow["project"]["revision_number"],
                expected_material_pool_revision=workflow["material_pool"]["revision_number"],
                theme="Structural synchronization",
                selected_asset_codes=[],
                actor_id="test-operator",
            )
            workflow = service.confirm_setup(
                project_code,
                expected_revision=workflow["setup_branch"]["current_revision_number"],
                actor_id="test-operator",
            )
            service.enqueue_outline(project_code, actor_id="test-operator")
            assert worker.run_once("structure-sync-worker")["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            service.enqueue_script(project_code, actor_id="test-operator")
            assert worker.run_once("structure-sync-worker")["status"] == "succeeded"
            workflow = service.get_workflow(project_code)
            workflow = service.confirm_script(
                project_code,
                expected_revision=workflow["script"]["revision_number"],
                actor_id="test-operator",
            )

            project = service.repository.get_project(project_code)
            assert project is not None
            context = service.versions.context(project["project_id"])
            script_node = service.versions.stage_node(context, "script")
            assert script_node is not None and script_node.get("revision") is not None
            initial_script = script_node["revision"]
            initial_script_versions = {
                item["item_key"]: item["item_version_id"] for item in initial_script["items"]
            }
            storyboard_node = service.versions.create_node(
                project_id=project["project_id"],
                project_code=project_code,
                stage="storyboard",
                parent_node_id=script_node["id"],
                label="Structure sync storyboard",
                actor_id="test-operator",
            )
            initial_storyboard = service.versions.save_revision(
                node_id=storyboard_node["id"],
                expected_revision=0,
                content={"template_code": "TEST-TEMPLATE"},
                items=[
                    {
                        "item_key": item["item_key"],
                        "item_type": "storyboard_scene",
                        "source_item_key": item["item_key"],
                        "content": {
                            "shot_code": item["item_key"],
                            "title": f"Initial {item['item_key']}",
                            "layers": [
                                {
                                    "asset_code": "ASSET-LAYER-1",
                                    "kind": "image",
                                    "z_index": 1,
                                }
                            ],
                        },
                        "source_node_revision_id": initial_script["id"],
                        "source_item_version_id": item["item_version_id"],
                    }
                    for item in initial_script["items"]
                ],
                actor_id="test-operator",
                producer_kind="human",
                producer_ref="test-structure-sync-seed",
                source_parent_revision_id=initial_script["id"],
            )
            initial_storyboard_versions = {
                item["item_key"]: item["item_version_id"]
                for item in initial_storyboard["items"]
            }

            def outline_input(section: dict) -> dict:
                return {
                    key: section[key]
                    for key in ("section_key", "title", "objective", "key_points")
                }

            reordered_sections = [
                outline_input(workflow["outline"]["sections"][1]),
                outline_input(workflow["outline"]["sections"][0]),
            ]
            workflow = service.revise_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                sections=reordered_sections,
                actor_id="test-operator",
            )
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            reordered_script_node = service.versions.stage_node(
                service.versions.context(project["project_id"]), "script"
            )

            assert reordered_script_node is not None and reordered_script_node.get("revision") is not None
            assert reordered_script_node["status"] == "draft"
            assert reordered_script_node["revision"]["producer_ref"].startswith("sync-structure:")
            assert [item["item_key"] for item in reordered_script_node["revision"]["items"]] == [
                "section-2",
                "section-1",
            ]
            assert {
                item["item_key"]: item["item_version_id"]
                for item in reordered_script_node["revision"]["items"]
            } == initial_script_versions

            workflow = service.confirm_script(
                project_code,
                expected_revision=workflow["script"]["revision_number"],
                actor_id="test-operator",
            )
            reordered_storyboard_node = service.versions.stage_node(
                service.versions.context(project["project_id"]), "storyboard"
            )

            assert reordered_storyboard_node is not None and reordered_storyboard_node.get("revision") is not None
            assert reordered_storyboard_node["status"] == "draft"
            assert reordered_storyboard_node["revision"]["producer_ref"].startswith("sync-structure:")
            assert [item["item_key"] for item in reordered_storyboard_node["revision"]["items"]] == [
                "section-2",
                "section-1",
            ]
            assert {
                item["item_key"]: item["item_version_id"]
                for item in reordered_storyboard_node["revision"]["items"]
            } == initial_storyboard_versions

            retained_section = outline_input(workflow["outline"]["sections"][0])
            workflow = service.revise_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                sections=[retained_section],
                actor_id="test-operator",
            )
            workflow = service.confirm_outline(
                project_code,
                expected_revision=workflow["outline"]["revision_number"],
                actor_id="test-operator",
            )
            deleted_script_node = service.versions.stage_node(
                service.versions.context(project["project_id"]), "script"
            )

            assert deleted_script_node is not None and deleted_script_node.get("revision") is not None
            assert deleted_script_node["status"] == "draft"
            assert [item["item_key"] for item in deleted_script_node["revision"]["items"]] == [
                "section-2"
            ]
            assert deleted_script_node["revision"]["items"][0]["item_version_id"] == initial_script_versions[
                "section-2"
            ]

            workflow = service.confirm_script(
                project_code,
                expected_revision=workflow["script"]["revision_number"],
                actor_id="test-operator",
            )
            deleted_storyboard_node = service.versions.stage_node(
                service.versions.context(project["project_id"]), "storyboard"
            )
            tree = service.workflow_tree(project_code)

            assert deleted_storyboard_node is not None and deleted_storyboard_node.get("revision") is not None
            assert deleted_storyboard_node["status"] == "draft"
            assert [item["item_key"] for item in deleted_storyboard_node["revision"]["items"]] == [
                "section-2"
            ]
            assert deleted_storyboard_node["revision"]["items"][0]["item_version_id"] == (
                initial_storyboard_versions["section-2"]
            )
            assert len([node for node in tree["nodes"] if node["stage"] == "script"]) == 1
            assert len([node for node in tree["nodes"] if node["stage"] == "storyboard"]) == 1
        finally:
            connection.rollback()
            if project_code:
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        "SELECT id FROM content_projects WHERE project_code = %s", (project_code,)
                    )
                    row = cursor.fetchone()
                    if row:
                        cursor.execute(
                            "DELETE FROM content_script_revisions WHERE project_id = %s", (row["id"],)
                        )
                        cursor.execute("DELETE FROM story_briefs WHERE project_id = %s", (row["id"],))
                    cursor.execute(
                        "DELETE FROM content_projects WHERE project_code = %s", (project_code,)
                    )
                connection.commit()
