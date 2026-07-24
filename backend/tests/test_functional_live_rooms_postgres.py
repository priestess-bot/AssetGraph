from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

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
                "primary_template_code": "TPL-PRIMARY",
                "secondary_template_codes": ["TPL-SECONDARY"],
                "asset_codes": [item["asset_code"] for item in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )

        assert plan["status"] == "ready"
        assert plan["blueprint"]["schema_version"] == "maitu-scene-blueprint.functional.v1"
        assert len(plan["blueprint"]["scenes"]) == 3
        assert plan["build_plan"]["go_live"] is False
        assert "go_live" not in {operation["kind"] for operation in plan["build_plan"]["operations"]}

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
