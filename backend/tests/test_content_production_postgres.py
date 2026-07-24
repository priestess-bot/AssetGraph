from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.domain.errors import DomainValidationError
from app.repositories.content_core import ContentCoreRepository
from app.repositories.content_production import ContentProductionRepository
from app.repositories.video_productions import VideoProductionRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _build_confirmed_content_chain(
    connection: psycopg.Connection, suffix: str
) -> tuple[ContentProductionRepository, dict[str, dict]]:
    core = ContentCoreRepository(connection)
    repository = ContentProductionRepository(connection)
    project = core.create_project(
        title=f"Cross-carrier project {suffix}",
        generation_goal="Explain verified product value through a structured story",
        content={"audience": "new customers", "theme": "craft"},
        actor_id="operator-a",
    )
    core.confirm_project_revision(project["project_code"], revision_number=1, actor_id="operator-a")

    story = repository.create_story_brief_revision(
        project_code=project["project_code"],
        project_revision=1,
        expected_revision=0,
        source_design_brief_revision=f"DESIGN-{suffix}@1",
        content={
            "objective": "Introduce the product",
            "theme": "craft",
            "narrative_premise": "from origin to use",
            "must_include": ["verified origin"],
            "must_avoid": ["unsupported superlatives"],
        },
        fact_revision_refs=[{"fact_card_code": f"FACT-{suffix}", "revision": 1}],
        template_revision_refs=[{"template_code": f"TPL-{suffix}", "revision": 1}],
        actor_id="operator-a",
    )
    repository.confirm_story_brief_revision(
        story["story_brief_code"], revision_number=1, actor_id="operator-a"
    )

    script = repository.create_script_revision(
        story_brief_code=story["story_brief_code"],
        story_brief_revision=1,
        expected_revision=0,
        title="Origin and use",
        content={"language": "zh-CN"},
        blocks=[
            {
                "module_type": "opening",
                "content": "This origin statement is verified.",
                "estimated_duration_ms": 8000,
                "fact_citations": [{"fact_card_code": f"FACT-{suffix}", "revision": 1}],
                "template_sources": [{"template_code": f"TPL-{suffix}", "module": "opening"}],
            },
            {
                "module_type": "demonstration",
                "content": "Show the product and invite a question.",
                "estimated_duration_ms": 12000,
                "interaction_intent": {"type": "question"},
                "cta_intent": {"type": "learn_more"},
            },
        ],
        model_strategy_ref="provider-neutral-writer.v1",
        prompt_revision="script.prompt.v1",
        producer_strategy_revision="writer.default.v1",
        generation_run_code=f"RUN-{suffix}",
        validation_result={"fact_citations_complete": True},
        actor_id="writer-a",
    )
    repository.confirm_script_revision(
        script["script_revision_code"], revision_number=1, actor_id="editor-a"
    )

    program = repository.create_program_revision(
        script_revision_code=script["script_revision_code"],
        expected_revision=0,
        segments=[
            {
                "program_phase": "opening_and_demo",
                "semantic_goal": "Establish trust and demonstrate use",
                "estimated_duration_ms": 20000,
                "interaction_actions": [{"type": "invite_question"}],
                "cta_actions": [{"type": "learn_more"}],
                "script_block_adoptions": [
                    {"block_code": script["blocks"][0]["block_code"], "content_action": "deliver"},
                    {"block_code": script["blocks"][1]["block_code"], "content_action": "interact"},
                ],
            }
        ],
        producer_strategy_revision="program.default.v1",
        actor_id="director-a",
    )
    repository.confirm_program_revision(
        program["program_revision_code"], revision_number=1, actor_id="director-a"
    )

    with pytest.raises(DomainValidationError) as forbidden_locator:
        repository.create_shot_list_revision(
            program_revision_code=program["program_revision_code"],
            expected_revision=0,
            shots=[
                {
                    "program_segment_code": program["segments"][0]["segment_code"],
                    "shot_goal": "Invalid mutable locator",
                    "composition_intent": {"file_path": "/tmp/product.png"},
                    "script_block_sources": [{"block_code": script["blocks"][0]["block_code"]}],
                }
            ],
            producer_strategy_revision="shots.default.v1",
            actor_id="director-a",
        )
    assert forbidden_locator.value.code == "SHOT_RUNTIME_LOCATOR_FORBIDDEN"

    shot_list = repository.create_shot_list_revision(
        program_revision_code=program["program_revision_code"],
        expected_revision=0,
        shots=[
            {
                "program_segment_code": program["segments"][0]["segment_code"],
                "shot_goal": "Show verified origin and product use",
                "composition_intent": {"framing": "product_on_table", "priority": "product"},
                "material_role_requirements": ["background", "product"],
                "audio_actions": [{"type": "deliver_script"}],
                "continuity": {"product_position": "stable"},
                "acceptance_criteria": ["origin claim is audible", "product is visible"],
                "estimated_duration_ms": 20000,
                "script_block_sources": [
                    {"block_code": script["blocks"][0]["block_code"], "relation_type": "quotes"},
                    {"block_code": script["blocks"][1]["block_code"], "relation_type": "supports"},
                ],
            }
        ],
        producer_strategy_revision="shots.default.v1",
        actor_id="director-a",
    )
    repository.confirm_shot_list_revision(
        shot_list["shot_list_revision_code"], revision_number=1, actor_id="director-a"
    )
    projection = repository.add_shot_projection_link(
        shot_code=shot_list["shots"][0]["shot_code"],
        target_type="maitu_scene_blueprint",
        target_code=f"SCENE-{suffix}",
        target_revision=1,
        relation_type="projects_to",
        evidence={"compiler": "live-room.v1"},
    )
    assert projection["target_type"] == "maitu_scene_blueprint"

    return repository, {
        "project": project,
        "story": story,
        "script": script,
        "program": program,
        "shot_list": shot_list,
    }


def _insert_legacy_workbench_run(
    connection: psycopg.Connection, *, suffix: str, target_live_room_id: str
) -> str:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            INSERT INTO maitu_workbench_product_fact_cards (
                fact_card_code, title, current_approved_version
            ) VALUES (%s, 'Legacy fact', 1) RETURNING id
            """,
            (f"LEGACY-FACT-{suffix}",),
        )
        card_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO maitu_workbench_product_fact_card_versions (
                fact_card_id, fact_card_code, version_code, version_number,
                status, content, content_sha256, approved_by, approved_at
            ) VALUES (%s, %s, %s, 1, 'approved', '{}'::jsonb, %s, 'legacy-import', now())
            RETURNING id
            """,
            (card_id, f"LEGACY-FACT-{suffix}", f"LEGACY-FACT-{suffix}-V001", "a" * 64),
        )
        fact_version_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO maitu_workbench_inventory_sync_jobs (
                sync_job_code, status, request_fingerprint, completed_at
            ) VALUES (%s, 'succeeded', %s, now()) RETURNING id
            """,
            (f"LEGACY-SYNC-{suffix}", "b" * 64),
        )
        sync_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO maitu_workbench_inventory_snapshots (
                snapshot_code, sync_job_id, source_system, fingerprint_sha256,
                item_count, captured_at
            ) VALUES (%s, %s, 'maitu', %s, 0, now()) RETURNING id
            """,
            (f"LEGACY-SNAPSHOT-{suffix}", sync_id, "c" * 64),
        )
        snapshot_id = cursor.fetchone()["id"]
        cursor.execute(
            """
            UPDATE maitu_workbench_inventory_sync_jobs
            SET snapshot_id = %s, snapshot_code = %s
            WHERE id = %s
            """,
            (snapshot_id, f"LEGACY-SNAPSHOT-{suffix}", sync_id),
        )
        run_code = f"LEGACY-WB-{suffix}"
        cursor.execute(
            """
            INSERT INTO maitu_workbench_runs (
                run_code, title, topic, fact_card_version_id, fact_card_version_code,
                inventory_snapshot_id, inventory_snapshot_code, target_live_room_id
            ) VALUES (%s, 'Legacy run', 'Legacy topic', %s, %s, %s, %s, %s)
            """,
            (
                run_code,
                fact_version_id,
                f"LEGACY-FACT-{suffix}-V001",
                snapshot_id,
                f"LEGACY-SNAPSHOT-{suffix}",
                target_live_room_id,
            ),
        )
    connection.commit()
    return run_code


def test_content_chain_branches_legacy_projection_immutability_and_stale_propagation() -> None:
    suffix = uuid4().hex
    target_room = f"room-{suffix[:16]}"
    with psycopg.connect(DATABASE_URL) as connection:
        repository, chain = _build_confirmed_content_chain(connection, suffix)

        with pytest.raises(psycopg.errors.RaiseException, match="immutable closed-loop revision child"):
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE shots SET shot_goal = 'tampered' WHERE shot_code = %s",
                    (chain["shot_list"]["shots"][0]["shot_code"],),
                )
        connection.rollback()

        common = {
            "project_code": chain["project"]["project_code"],
            "project_revision": 1,
            "story_brief_code": chain["story"]["story_brief_code"],
            "story_brief_revision": 1,
            "script_revision_code": chain["script"]["script_revision_code"],
            "shot_list_revision_code": chain["shot_list"]["shot_list_revision_code"],
            "material_snapshot_ref": {"snapshot_code": f"MATERIALS-{suffix}", "revision": 1},
            "constraint_snapshot_ref": {"snapshot_code": f"CONSTRAINTS-{suffix}", "revision": 1},
            "actor_id": "producer-a",
        }
        live_variant = repository.create_production_variant(
            **common,
            carrier_kind="live_room",
            branch_target={"target_live_room_id": target_room},
            configuration={"mode": "auto_write_draft"},
        )
        video_variant = repository.create_production_variant(
            **common,
            carrier_kind="rendered_video",
            branch_target={"canvas": [1080, 1920], "fps": 30},
            configuration={"render_profile": "vertical-commerce.v1"},
        )
        repository.confirm_production_variant_revision(
            live_variant["variant_code"], revision_number=1, actor_id="producer-a"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM production_variant_revisions WHERE variant_code = %s",
                (video_variant["variant_code"],),
            )
            assert cursor.fetchone()[0] == "draft"
        repository.confirm_production_variant_revision(
            video_variant["variant_code"], revision_number=1, actor_id="producer-a"
        )

        configuration = repository.create_live_room_configuration_revision(
            variant_code=live_variant["variant_code"],
            variant_revision=1,
            expected_revision=0,
            target_live_room_id=target_room,
            expected_title="Verified product live room",
            build_mode="auto_write_draft",
            inventory_snapshot_ref={"snapshot_code": f"INVENTORY-{suffix}", "revision": 1},
            site_protection_policy={"requires_blank_room": True, "readback_required": True},
            configuration={"canvas": [1080, 1920]},
            actor_id="producer-a",
        )
        repository.confirm_live_room_configuration_revision(
            configuration["configuration_code"], revision_number=1, actor_id="producer-a"
        )

        run_code = _insert_legacy_workbench_run(
            connection, suffix=suffix, target_live_room_id=target_room
        )
        workbench_link = repository.bind_workbench_run(
            run_code=run_code,
            configuration_code=configuration["configuration_code"],
            configuration_revision=1,
            actor_id="migration-a",
        )
        assert workbench_link["source_type"] == "maitu_workbench_run"

        video_job = VideoProductionRepository(connection).create(
            {"topic": f"Video {suffix}", "target_duration_seconds": 55}
        )
        video_link = repository.bind_video_production_job(
            job_code=video_job["job_code"],
            variant_code=video_variant["variant_code"],
            variant_revision=1,
            actor_id="migration-a",
        )
        assert video_link["source_type"] == "video_production_job"

        second_story = repository.create_story_brief_revision(
            project_code=chain["project"]["project_code"],
            project_revision=1,
            expected_revision=1,
            source_design_brief_revision=f"DESIGN-{suffix}@2",
            content={"objective": "Revised objective", "must_include": ["verified origin"]},
            fact_revision_refs=[{"fact_card_code": f"FACT-{suffix}", "revision": 1}],
            template_revision_refs=[],
            actor_id="operator-b",
        )
        repository.confirm_story_brief_revision(
            second_story["story_brief_code"], revision_number=2, actor_id="operator-b"
        )
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT variant_code, stale, stale_reason_codes
                FROM production_variant_revisions
                WHERE variant_code IN (%s, %s)
                ORDER BY variant_code
                """,
                (live_variant["variant_code"], video_variant["variant_code"]),
            )
            stale_variants = cursor.fetchall()
        assert len(stale_variants) == 2
        assert all(row["stale"] for row in stale_variants)
        assert all("UPSTREAM_REVISION_SUPERSEDED" in row["stale_reason_codes"] for row in stale_variants)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE video_production_jobs
                SET status = 'failed', error_code = 'COMPATIBILITY_TEST_COMPLETE',
                    error_message = 'Content aggregate compatibility fixture retired',
                    claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL,
                    heartbeat_at = NULL, completed_at = now(), updated_at = now()
                WHERE job_code = %s
                """,
                (video_job["job_code"],),
            )
        connection.commit()


def test_program_and_shot_sources_cannot_cross_revision_boundaries() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository, chain = _build_confirmed_content_chain(connection, suffix)
        with pytest.raises(DomainValidationError) as invalid_source:
            repository.create_program_revision(
                script_revision_code=chain["script"]["script_revision_code"],
                expected_revision=1,
                segments=[
                    {
                        "semantic_goal": "Invalid source",
                        "script_block_adoptions": [{"block_code": "BLOCK-OUTSIDE-REVISION"}],
                    }
                ],
                producer_strategy_revision="program.default.v1",
                actor_id="director-a",
            )
        assert invalid_source.value.code == "PROGRAM_SEGMENT_BLOCK_INVALID"
        connection.rollback()
