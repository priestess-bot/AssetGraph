from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.domain.errors import DomainValidationError
from app.repositories.assets import AssetRepository
from app.repositories.material_library import MaterialLibraryRepository
from app.repositories.releases import ReleaseRepository
from app.services.functional_content import FunctionalContentService
from app.services.functional_live_rooms import FunctionalLiveRoomService
from app.services.releases import ReleaseService


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


def _generated_project(
    connection: psycopg.Connection,
    suffix: str,
    *,
    target_duration_seconds: int | None = None,
) -> dict:
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
            "target_duration_seconds": target_duration_seconds,
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
        assert {gate["gate"]: gate["status"] for gate in plan["gate_results"]} == {
            "identity_version": "pass",
            "authorization_facts": "pass",
            "input_boundary": "pass",
            "structural_references": "pass",
            "execution_constraints": "pass",
            "branch_quality": "pass",
            "evidence_completeness": "warning",
        }
        assert plan["quality_report"]["missing_material_roles"] == []
        assert all(scene["scene_blueprint_code"].startswith("MSB-VARIANT-") for scene in plan["blueprint"]["scenes"])
        assert all(layer["layer_blueprint_code"].startswith("LYR-MSB-VARIANT-") for scene in plan["blueprint"]["scenes"] for layer in scene["layers"])

        trace = service.get_trace(plan["plan_code"])
        assert trace["content_chain"]["content_project_revision"] == {
            "code": project["project_code"], "revision": 1,
        }
        assert [operation["operation_type"] for operation in trace["operations"]] == [
            operation["operation_type"] for operation in plan["build_plan"]["operations"]
        ]
        assert all(operation["targets"] for operation in trace["operations"])
        assert all(
            target["shot"] is not None and target["program_segment"] is not None and target["script_blocks"]
            for operation in trace["operations"]
            for target in operation["targets"]
        )

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
            cursor.execute(
                """
                SELECT count(*) FROM functional_live_room_operation_trace_links
                WHERE plan_id = (SELECT id FROM functional_live_room_plans WHERE plan_code = %s)
                """,
                (plan["plan_code"],),
            )
            assert cursor.fetchone()[0] == sum(len(operation["targets"]) for operation in trace["operations"])

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


def test_live_room_plan_selects_only_published_material_pack_and_freezes_resolved_assets() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        library = MaterialLibraryRepository(connection)
        project = _generated_project(connection, suffix)
        selected = [
            _asset(assets, suffix, "digital_human"),
            _asset(assets, suffix, "background"),
            _asset(assets, suffix, "promotion_text"),
        ]
        group = library.create_group(
            {"title": f"Pack inputs {suffix}", "asset_codes": [asset["asset_code"] for asset in selected]}
        )
        draft_pack = library.create_pack(
            {
                "title": f"Room pack {suffix}", "role": "background",
                "entries": [{"selection_kind": "group", "selection_code": group["group_code"], "mode": "required", "min_occurrences": 1}],
            }
        )
        service = FunctionalLiveRoomService(connection)
        with pytest.raises(DomainValidationError) as draft_invalid:
            service.create_plan(
                {
                    "project_code": project["project_code"], "target_live_room_id": f"draft-pack-{suffix}",
                    "expected_title": "Draft pack must fail", "material_pack_codes": [draft_pack["pack_code"]],
                },
                actor_id="test-operator",
            )
        assert draft_invalid.value.code == "LIVE_ROOM_MATERIAL_PACK_INVALID"

        published_pack = library.publish_pack(draft_pack["pack_code"])
        assert published_pack is not None
        plan = service.create_plan(
            {
                "project_code": project["project_code"], "target_live_room_id": f"published-pack-{suffix}",
                "expected_title": "Published pack plan", "material_pack_codes": [published_pack["pack_code"]],
            },
            actor_id="test-operator",
        )
        assert plan["status"] == "ready"
        assert plan["selected_material_pack_codes"] == [published_pack["pack_code"]]
        assert plan["selected_asset_codes"] == published_pack["resolved_asset_codes"]
        snapshot = plan["build_plan"]["inventory_snapshot"]
        assert snapshot["material_pack_refs"] == [{
            "pack_code": published_pack["pack_code"], "revision_number": 1,
            "fingerprint_sha256": published_pack["fingerprint_sha256"], "role": "background",
            "entries": published_pack["entries"], "resolved_asset_codes": published_pack["resolved_asset_codes"],
        }]

        library.replace_group_members(group["group_code"], [selected[0]["asset_code"]])
        assert plan["build_plan"]["inventory_snapshot"]["asset_codes"] == [asset["asset_code"] for asset in selected]


def test_live_room_constraint_profiles_bind_to_snapshot_and_place_product_on_table_surface() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        library = MaterialLibraryRepository(connection)
        project = _generated_project(connection, suffix)
        background = _asset(assets, suffix, "background")
        product = _asset(assets, suffix, "product_display")
        library.write_constraint_profile(
            background["asset_code"],
            [{"kind": "table_surface", "hard": True, "parameters": {"name": "table_surface", "rect": [0.2, 0.65, 0.6, 0.15]}}],
        )
        library.write_constraint_profile(
            product["asset_code"],
            [{"kind": "align_anchor", "hard": True, "parameters": {"region": "table_surface", "anchor": "bottom_center"}}],
        )
        service = FunctionalLiveRoomService(connection)
        selected = service._selected_assets([background["asset_code"], product["asset_code"]], [])
        detail = FunctionalContentService(connection).get_detail(project["project_code"])
        assert detail is not None
        for shot in detail["shot_list"]["shots"]:
            shot["material_role_requirements"] = ["background", "product_display"]

        blueprint, _, blocked = service._compile(
            detail,
            selected,
            {"target_live_room_id": f"draft-{suffix}", "expected_title": "Constrained draft"},
            variant_code=f"VARIANT-{suffix}",
        )

        assert blocked == []
        layers = {layer["role"]: layer for layer in blueprint["scenes"][0]["layers"]}
        assert layers["product_display"]["normalized_geometry"] == {
            "x": pytest.approx(0.3), "y": pytest.approx(0.65), "width": pytest.approx(0.4), "height": pytest.approx(0.15),
        }
        assert layers["product_display"]["constraint_evidence"]["constraint_profile_ref"]["revision"] == 1

        library.write_constraint_profile(
            product["asset_code"],
            [{"kind": "require_named_region", "hard": True, "parameters": {"region": "missing_surface"}}],
        )
        missing_region = service._selected_assets([product["asset_code"]], [])
        for shot in detail["shot_list"]["shots"]:
            shot["material_role_requirements"] = ["product_display"]
        _, _, missing_blocked = service._compile(
            detail,
            missing_region,
            {"target_live_room_id": f"draft-{suffix}", "expected_title": "Blocked constrained draft"},
            variant_code=f"VARIANT-{suffix}-B",
        )
        assert missing_blocked == [
            f"constraint_named_region_missing:missing_surface:shot:{shot['shot_code']}"
            for shot in detail["shot_list"]["shots"]
        ]


def test_live_room_duration_deviation_warns_without_blocking_plan() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        project = _generated_project(connection, suffix, target_duration_seconds=30)
        selected = [
            _asset(assets, suffix, "digital_human"),
            _asset(assets, suffix, "background"),
            _asset(assets, suffix, "promotion_text"),
        ]
        plan = FunctionalLiveRoomService(connection).create_plan(
            {
                "project_code": project["project_code"],
                "target_live_room_id": f"empty-draft-{suffix}",
                "expected_title": "Duration warning draft",
                "asset_codes": [item["asset_code"] for item in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )
        quality_gate = next(gate for gate in plan["gate_results"] if gate["gate"] == "branch_quality")
        assert plan["status"] == "ready"
        assert quality_gate["status"] == "warning"
        assert plan["quality_report"]["warnings"] == ["duration_deviation_over_50_percent"]


def test_live_room_release_candidate_freezes_plan_and_stays_pending_external_evidence() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        project = _generated_project(connection, suffix)
        selected = [
            _asset(assets, suffix, "digital_human"),
            _asset(assets, suffix, "background"),
            _asset(assets, suffix, "promotion_text"),
        ]
        service = FunctionalLiveRoomService(
            connection,
            release_signing_key=b"functional-live-room-release-test-key",
            release_signing_key_id="functional-live-room-release-test-key-id",
        )
        plan = service.create_plan(
            {
                "project_code": project["project_code"],
                "target_live_room_id": f"empty-draft-{suffix}",
                "expected_title": "Release candidate draft",
                "asset_codes": [item["asset_code"] for item in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )

        candidate = service.create_release_candidate(plan["plan_code"], actor_id="test-operator")
        replay = service.create_release_candidate(plan["plan_code"], actor_id="test-operator")
        assert candidate["release"] is not None
        assert candidate["release"]["release_code"] == replay["release"]["release_code"]
        assert candidate["release"]["status"] == "candidate"
        assert candidate["release_snapshot_artifact_code"] == candidate["release"]["snapshot_artifact_code"]

        repository = ReleaseRepository(connection)
        release = repository.get_release(candidate["release"]["release_code"])
        assert release is not None
        assert release["status"] == "candidate"
        manifest = release["manifest"]
        assert manifest["carrier_kind"] == "live_room_draft"
        assert manifest["subject_refs"]["content_project_revision"] == {
            "code": project["project_code"],
            "revision": 1,
        }
        assert manifest["subject_refs"]["production_variant_revision"]["code"] == plan["variant_code"]
        assert manifest["carrier_facet"]["build_plan_ref"]["code"] == plan["build_plan"]["build_plan_code"]
        assert manifest["artifact_refs"] == [
            {
                "artifact_code": candidate["release_snapshot_artifact_code"],
                "checksum_sha256": manifest["artifact_refs"][0]["checksum_sha256"],
                "role": "live_room_build_plan_snapshot",
            }
        ]
        assert manifest["rights_snapshot"]["status"] == "pending_evidence"
        assert any(
            gate["code"] == "GATE_RELEASE_AUTHORIZATION_PENDING" and gate["blocking"]
            for gate in manifest["quality_snapshot"]["gates"]
        )
        assert ReleaseService(
            repository,
            signing_key=b"functional-live-room-release-test-key",
            signing_key_id="functional-live-room-release-test-key-id",
        ).verify_manifest_signature(release["release_code"])

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT snapshot, snapshot_fingerprint_sha256
                FROM functional_live_room_plan_release_snapshots
                WHERE artifact_code = %s
                """,
                (candidate["release_snapshot_artifact_code"],),
            )
            snapshot = cursor.fetchone()
        assert snapshot is not None
        assert snapshot[0]["build_plan"]["build_plan_code"] == plan["build_plan"]["build_plan_code"]
        assert snapshot[0]["subject_refs"] == manifest["subject_refs"]

        with pytest.raises(DomainValidationError) as invalid:
            ReleaseService(
                repository,
                signing_key=b"functional-live-room-release-test-key",
                signing_key_id="functional-live-room-release-test-key-id",
            ).validate_candidate(release["release_code"], actor_id="validator")
        assert invalid.value.code == "RELEASE_GATE_FAILED"
        assert repository.get_release(release["release_code"])["status"] == "candidate"


def test_live_room_plan_clone_recompiles_business_inputs_for_a_new_target() -> None:
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
        source = service.create_plan(
            {
                "project_code": project["project_code"],
                "target_live_room_id": f"source-draft-{suffix}",
                "expected_title": "Source draft",
                "asset_codes": [item["asset_code"] for item in selected],
                "group_codes": [],
            },
            actor_id="test-operator",
        )
        service.create_release_candidate(source["plan_code"], actor_id="test-operator")
        source = service.confirm_execution(source["plan_code"], confirmed=True)
        assert source is not None and source["execution_status"] == "requested"

        cloned = service.clone_plan(
            source["plan_code"],
            {
                "target_live_room_id": f"clone-draft-{suffix}",
                "expected_title": "Cloned draft",
            },
            actor_id="test-operator",
        )

        assert cloned["plan_code"] != source["plan_code"]
        assert cloned["variant_code"] != source["variant_code"]
        assert cloned["target_live_room_id"] == f"clone-draft-{suffix}"
        assert cloned["selected_asset_codes"] == source["selected_asset_codes"]
        assert cloned["execution_status"] == "not_requested"
        assert cloned["execution_evidence"] == {}
        assert cloned["release"] is None
        assert cloned["release_code"] is None
        assert cloned["cloned_from_plan_code"] == source["plan_code"]
        assert cloned["clone_context"]["cleared_target_state"] == [
            "target_live_room_fingerprint", "authorization", "execution_status",
            "execution_evidence", "release", "delivery", "readback",
        ]

        with pytest.raises(DomainValidationError) as same_target:
            service.clone_plan(
                source["plan_code"],
                {
                    "target_live_room_id": source["target_live_room_id"],
                    "expected_title": "Invalid clone",
                },
                actor_id="test-operator",
            )
        assert same_target.value.code == "LIVE_ROOM_CLONE_TARGET_MUST_DIFFER"


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
