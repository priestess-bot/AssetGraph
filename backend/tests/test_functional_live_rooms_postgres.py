from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainValidationError
from app.repositories.assets import AssetRepository
from app.services.functional_content import FunctionalContentService
from app.services.functional_live_rooms import FunctionalLiveRoomService


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _asset(repository: AssetRepository, suffix: str, role: str, capability: str = "maitu_bound") -> dict:
    return repository.create(
        {
            "asset_type": "IMG",
            "title": f"{role} {suffix}",
            "original_filename": f"{role}-{suffix}.png",
            "media_kind": "image",
            "material_roles": [role],
            "execution_capability": capability,
        }
    )


def _generated_project(connection: psycopg.Connection, suffix: str) -> dict:
    content = FunctionalContentService(connection)
    project = content.create_project(
        {
            "title": f"Live plan {suffix}",
            "generation_goal": "Generate a short product introduction live room",
            "theme": "Product launch",
            "story": "Audience asks how to choose the product.",
            "must_include": [],
            "must_avoid": [],
            "fact_card_codes": [],
            "secondary_template_codes": [],
        },
        actor_id="test-operator",
    )
    content.confirm_project(project["project_code"], expected_revision=1, actor_id="test-operator")
    content.parse_design_brief(
        project["project_code"],
        expected_revision=1,
        raw_input="Create the project baseline before the live-room branch.",
        actor_id="test-operator",
    )
    content.confirm_design_brief(project["project_code"], expected_revision=1, actor_id="test-operator")
    return content.generate_chain(project["project_code"], actor_id="test-operator")


def test_functional_live_room_plan_compiles_and_only_requests_maitu_execution() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        project = _generated_project(connection, suffix)
        selected = [
            _asset(assets, suffix, "digital_human"),
            _asset(assets, suffix, "background"),
            _asset(assets, suffix, "promotion_text"),
        ]
        service = FunctionalLiveRoomService(connection)
        plan = service.create_plan(
            {
                "project_code": project["project_code"],
                "target_live_room_id": f"empty-draft-{suffix}",
                "expected_title": "Product launch draft",
                "asset_codes": [item["asset_code"] for item in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )

        assert plan["status"] == "ready"
        assert plan["blueprint"]["schema_version"] == "maitu-scene-blueprint.functional.v1"
        assert len(plan["blueprint"]["scenes"]) == 3
        assert plan["build_plan"]["go_live"] is False
        assert plan["build_plan"]["build_plan_code"].startswith("MT-BUILD-")
        assert "go_live" not in {operation["operation_type"] for operation in plan["build_plan"]["operations"]}
        assert {operation["operation_type"] for operation in plan["build_plan"]["operations"]} <= {
            "preflight_content_build_plan",
            "fill_default_scene",
            "create_scene",
            "insert_asset_layer",
            "position_asset_layer",
            "write_script",
            "verify_scene",
            "save_draft",
        }
        assert all(scene["scene_blueprint_code"].startswith("MSB-VARIANT-") for scene in plan["blueprint"]["scenes"])
        assert all(layer["layer_blueprint_code"].startswith("LYR-MSB-VARIANT-") for scene in plan["blueprint"]["scenes"] for layer in scene["layers"])

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM maitu_scene_blueprints
                WHERE production_variant_revision_id = (
                    SELECT id FROM production_variant_revisions
                    WHERE variant_code = %s AND revision_number = 1
                )
                """,
                (plan["variant_code"],),
            )
            assert cursor.fetchone()[0] == 3
            cursor.execute(
                """
                SELECT count(*)
                FROM layer_blueprints AS layer
                JOIN maitu_scene_blueprints AS scene ON scene.id = layer.scene_blueprint_id
                WHERE scene.scene_blueprint_code = ANY(%s)
                """,
                ([scene["scene_blueprint_code"] for scene in plan["blueprint"]["scenes"]],),
            )
            assert cursor.fetchone()[0] == 6
            cursor.execute(
                """
                SELECT count(*) FROM shot_projection_links
                WHERE target_code = ANY(%s) AND target_type IN ('maitu_scene_blueprint', 'layer_blueprint')
                """,
                (
                    [scene["scene_blueprint_code"] for scene in plan["blueprint"]["scenes"]]
                    + [layer["layer_blueprint_code"] for scene in plan["blueprint"]["scenes"] for layer in scene["layers"]],
                ),
            )
            assert cursor.fetchone()[0] == 9
            cursor.execute(
                """
                SELECT details->'script_layout_build_plan'->>'blueprint_fingerprint' AS blueprint_fingerprint
                FROM maitu_live_room_build_plans
                WHERE build_plan_code = %s
                """,
                (plan["build_plan"]["build_plan_code"],),
            )
            assert cursor.fetchone()[0] == plan["build_plan"]["blueprint_fingerprint"]

        requested = service.confirm_execution(plan["plan_code"], confirmed=True)
        assert requested is not None
        assert requested["execution_status"] == "requested"
        assert requested["execution_evidence"]["status"] == "awaiting_maitu_worker"


def test_functional_live_room_plan_blocks_unbound_required_material() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        project = _generated_project(connection, suffix)
        selected = [
            _asset(assets, suffix, "digital_human"),
            _asset(assets, suffix, "background", capability="local_only"),
            _asset(assets, suffix, "promotion_text"),
        ]
        service = FunctionalLiveRoomService(connection)
        plan = service.create_plan(
            {
                "project_code": project["project_code"],
                "target_live_room_id": f"empty-draft-{suffix}",
                "expected_title": "Blocked draft",
                "asset_codes": [item["asset_code"] for item in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )

        assert plan["status"] == "blocked"
        assert any(reason.startswith("asset_not_maitu_bound") for reason in plan["blocked_reasons"])
        blocked = service.confirm_execution(plan["plan_code"], confirmed=True)
        assert blocked is not None
        assert blocked["execution_status"] == "blocked"


def test_live_room_plan_rejects_template_not_pinned_by_content_project() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        project = _generated_project(connection, suffix)
        selected = [
            _asset(assets, suffix, "digital_human"),
            _asset(assets, suffix, "background"),
            _asset(assets, suffix, "promotion_text"),
        ]
        with pytest.raises(DomainValidationError) as invalid:
            FunctionalLiveRoomService(connection).create_plan(
                {
                    "project_code": project["project_code"],
                    "target_live_room_id": f"empty-draft-{suffix}",
                    "expected_title": "Template mismatch",
                    "primary_template_code": "LR-TPL-NOT-PINNED",
                    "asset_codes": [item["asset_code"] for item in selected],
                    "group_codes": [],
                },
                actor_id="test-operator",
            )
        assert invalid.value.code == "LIVE_ROOM_TEMPLATE_SELECTION_MISMATCH"
