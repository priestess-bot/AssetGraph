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

        gap = library.create_gap({"title": f"Need foreground {suffix}", "role": "decoration_foreground"})
        resolved = library.update_gap(
            gap["gap_code"],
            {"status": "resolved", "resolution_asset_code": product["asset_code"]},
        )
        assert resolved is not None
        assert resolved["status"] == "resolved"
        assert resolved["resolution_asset_code"] == product["asset_code"]


def test_material_library_rejects_unknown_group_members_and_pack_targets() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        library = MaterialLibraryRepository(connection)
        with pytest.raises(Exception, match="Unknown active asset codes"):
            library.create_group({"title": f"Invalid {uuid4().hex}", "asset_codes": ["AG-IMG-UNKNOWN"]})
        connection.rollback()
