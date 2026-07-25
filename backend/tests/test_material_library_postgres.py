from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

from app.repositories.assets import AssetRepository
from app.repositories.material_library import MaterialLibraryRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _create_asset(repository: AssetRepository, suffix: str, *, title: str) -> dict:
    return repository.create(
        {
            "asset_type": "IMG",
            "title": title,
            "original_filename": f"{suffix}.png",
            "media_kind": "image",
            "material_roles": ["background"],
            "execution_capability": "local_only",
        }
    )


def test_material_library_groups_constraints_packs_and_gaps() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        library = MaterialLibraryRepository(connection)
        background = _create_asset(assets, f"background-{suffix}", title="Background")
        product = _create_asset(assets, f"product-{suffix}", title="Product")

        first_group = library.create_group(
            {"title": f"Primary {suffix}", "description": "shared assets", "asset_codes": [background["asset_code"]]}
        )
        second_group = library.create_group(
            {"title": f"Secondary {suffix}", "asset_codes": [background["asset_code"], product["asset_code"]]}
        )
        assert first_group["asset_codes"] == [background["asset_code"]]
        assert background["asset_code"] in second_group["asset_codes"]

        replacement = library.replace_group_members(first_group["group_code"], [product["asset_code"]])
        assert replacement is not None
        assert replacement["asset_codes"] == [product["asset_code"]]
        assert background["asset_code"] in library.get_group(second_group["group_code"])["asset_codes"]

        first_profile = library.write_constraint_profile(
            background["asset_code"],
            [{"kind": "preserve_aspect_ratio", "hard": True, "parameters": {}}],
        )
        second_profile = library.write_constraint_profile(
            background["asset_code"],
            [{"kind": "allowed_region", "hard": True, "parameters": {"rect": [0.1, 0.1, 0.8, 0.8]}}],
        )
        assert first_profile is not None and second_profile is not None
        assert first_profile["revision_number"] == 1
        assert second_profile["revision_number"] == 2
        assert first_profile["fingerprint_sha256"] != second_profile["fingerprint_sha256"]
        profile_revisions = library.list_constraint_profile_revisions(background["asset_code"])
        assert [revision["revision_number"] for revision in profile_revisions] == [2, 1]
        assert profile_revisions[0]["constraints"] == second_profile["constraints"]

        pack = library.create_pack(
            {
                "title": f"Pack {suffix}",
                "role": "background",
                "entries": [
                    {
                        "selection_kind": "group",
                        "selection_code": second_group["group_code"],
                        "mode": "required",
                        "min_occurrences": 1,
                    }
                ],
            }
        )
        assert set(pack["resolved_asset_codes"]) == {background["asset_code"], product["asset_code"]}
        assert pack["status"] == "draft"
        published = library.publish_pack(pack["pack_code"])
        assert published is not None
        assert published["status"] == "published"
        refs, resolved_asset_codes = library.resolve_published_packs([pack["pack_code"]])
        assert resolved_asset_codes == published["resolved_asset_codes"]
        assert refs == [{
            "pack_code": pack["pack_code"], "revision_number": 1,
            "fingerprint_sha256": published["fingerprint_sha256"], "role": "background",
            "entries": published["entries"], "resolved_asset_codes": published["resolved_asset_codes"],
        }]

        revised = library.create_pack_revision(
            pack["pack_code"],
            expected_revision=1,
            entries=[
                {
                    "selection_kind": "asset",
                    "selection_code": product["asset_code"],
                    "mode": "required",
                    "min_occurrences": 1,
                }
            ],
        )
        assert revised is not None
        assert revised["revision_number"] == 2
        assert revised["status"] == "draft"
        revisions = library.list_pack_revisions(pack["pack_code"])
        assert [revision["revision_number"] for revision in revisions] == [2, 1]
        assert revisions[-1]["entries"] == published["entries"]
        with pytest.raises(Exception, match="MATERIAL_PACK_REVISION_CONFLICT"):
            library.create_pack_revision(
                pack["pack_code"],
                expected_revision=1,
                entries=[
                    {
                        "selection_kind": "asset",
                        "selection_code": background["asset_code"],
                        "mode": "optional",
                        "min_occurrences": 0,
                    }
                ],
            )
        connection.rollback()

        gap = library.create_gap(
            {
                "title": f"Need foreground {suffix}",
                "role": "decoration_foreground",
                "gap_type": "role_coverage",
                "impact_summary": "The foreground layer is required for the selected branch.",
                "alternative_asset_codes": [product["asset_code"]],
            }
        )
        assert gap["status"] == "open"
        assert gap["events"][-1]["status"] == "open"
        with pytest.raises(Exception, match="ASSET_GAP_INVALID_TRANSITION"):
            library.update_gap(gap["gap_code"], {"status": "resolved", "resolution_asset_code": product["asset_code"]})
        connection.rollback()
        role_mismatch = library.update_asset_classification(
            product["asset_code"], media_kind="image", material_roles=["decoration_foreground"], execution_capability="local_only"
        )
        assert role_mismatch is not None
        candidate = library.update_gap(
            gap["gap_code"],
            {"status": "candidate_found", "resolution_asset_code": product["asset_code"], "actor": "material_editor"},
        )
        assert candidate is not None
        assert candidate["status"] == "candidate_found"
        assert candidate["resolution_snapshot"]["asset_code"] == product["asset_code"]
        resolved = library.update_gap(
            gap["gap_code"],
            {"status": "resolved", "resolution_asset_code": product["asset_code"], "actor": "material_editor"},
        )
        assert resolved is not None
        assert resolved["status"] == "resolved"
        assert resolved["resolution_asset_code"] == product["asset_code"]
        assert [event["status"] for event in resolved["events"]] == ["open", "candidate_found", "resolved"]
        gap_refs = library.resolve_gap_refs([gap["gap_code"]])
        assert gap_refs[0]["gap_code"] == gap["gap_code"]
        assert gap_refs[0]["status"] == "resolved"
        assert len(gap_refs[0]["fingerprint_sha256"]) == 64

        preview = library.preview_selection(role="decoration_foreground", carrier_kind="rendered_video")
        product_candidate = next(item for item in preview["candidates"] if item["asset_code"] == product["asset_code"])
        assert product_candidate["score_parts"]["role_match"] == 60
        assert any(item["asset_code"] == background["asset_code"] and "ROLE_MISMATCH" in item["exclusion_codes"] for item in preview["excluded"])
        assert preview["unverified_gates"] == ["RIGHTS_GRANT_NOT_IMPLEMENTED", "CONSTRAINT_SOLVER_NOT_RUN"]


def test_material_library_rejects_unknown_group_members_and_pack_targets() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        library = MaterialLibraryRepository(connection)
        with pytest.raises(Exception, match="Unknown active asset codes"):
            library.create_group({"title": f"Invalid {uuid4().hex}", "asset_codes": ["AG-IMG-UNKNOWN"]})
        connection.rollback()


def test_batch_asset_classification_is_atomic_for_all_targets() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        assets = AssetRepository(connection)
        library = MaterialLibraryRepository(connection)
        first = _create_asset(assets, f"first-{suffix}", title="First")
        second = _create_asset(assets, f"second-{suffix}", title="Second")

        updated = library.update_asset_classifications(
            [first["asset_code"], second["asset_code"]],
            media_kind="image",
            material_roles=["product_display"],
            execution_capability="local_only",
        )
        assert [row["asset_code"] for row in updated] == [first["asset_code"], second["asset_code"]]
        assert all(row["material_roles"] == ["product_display"] for row in updated)

        with pytest.raises(Exception, match="Unknown active asset codes"):
            library.update_asset_classifications(
                [first["asset_code"], "AG-IMG-UNKNOWN"],
                media_kind="video",
                material_roles=["supporting_video"],
                execution_capability="reference_only",
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT media_kind, material_roles, execution_capability FROM assets WHERE asset_code = %s",
                (first["asset_code"],),
            )
            row = cursor.fetchone()
        assert row == ("image", ["product_display"], "local_only")
