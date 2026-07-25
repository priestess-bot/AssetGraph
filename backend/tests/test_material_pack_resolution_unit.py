from __future__ import annotations

import pytest

from app.repositories.material_library import MaterialLibraryRepository, MaterialLibraryValidationError
from app.services.functional_live_rooms import FunctionalLiveRoomService


def test_asset_effect_summary_withholds_automatic_recommendation_for_low_sample_or_descriptive_evidence() -> None:
    low_sample = MaterialLibraryRepository._asset_effect_summary(
        {
            "effect_code": "EFFECT-LOW", "status": "approved", "evidence_level": "associational",
            "selected_session_count": 2,
        }
    )
    descriptive = MaterialLibraryRepository._asset_effect_summary(
        {
            "effect_code": "EFFECT-DESC", "status": "approved", "evidence_level": "descriptive",
            "selected_session_count": 5,
        }
    )
    eligible = MaterialLibraryRepository._asset_effect_summary(
        {
            "effect_code": "EFFECT-READY", "status": "approved", "evidence_level": "associational",
            "selected_session_count": 3,
        }
    )

    assert low_sample["automatic_recommendation_eligible"] is False
    assert "EFFECT_SAMPLE_SIZE_BELOW_MINIMUM" in low_sample["recommendation_blockers"]
    assert descriptive["automatic_recommendation_eligible"] is False
    assert "EFFECT_EVIDENCE_NOT_ASSOCIATIONAL" in descriptive["recommendation_blockers"]
    assert eligible["automatic_recommendation_eligible"] is True
    assert eligible["recommendation_blockers"] == []


def test_material_pack_rules_preserve_all_sources_and_strongest_usage() -> None:
    repository = MaterialLibraryRepository(None)  # type: ignore[arg-type]

    rules, conflicts = repository._merge_material_rules(
        [
            {
                "pack_code": "AG-PACK-BASE",
                "pack_kind": "total",
                "revision_number": 2,
                "pack_constraints": [{"kind": "pin_layer_bottom", "hard": True}],
                "resolved_entries": [
                    {
                        "entry_key": "entry-1",
                        "material_role": "background",
                        "mode": "optional",
                        "min_occurrences": 0,
                        "max_occurrences": 4,
                        "applicable_scope": {"kind": "whole_room"},
                        "pack_constraints": [],
                        "resolved_asset_codes": ["AG-IMG-001"],
                    }
                ],
            },
            {
                "pack_code": "AG-PACK-REQUIRED",
                "pack_kind": "classification",
                "revision_number": 3,
                "pack_constraints": [],
                "resolved_entries": [
                    {
                        "entry_key": "entry-2",
                        "material_role": "background",
                        "mode": "required",
                        "min_occurrences": 2,
                        "max_occurrences": 3,
                        "applicable_scope": {"kind": "whole_room"},
                        "pack_constraints": [{"kind": "preserve_aspect_ratio", "hard": True}],
                        "resolved_asset_codes": ["AG-IMG-001"],
                    }
                ],
            },
        ]
    )

    assert conflicts == []
    assert rules == [
        {
            "asset_code": "AG-IMG-001",
            "material_role": "background",
            "mode": "required",
            "min_occurrences": 2,
            "max_occurrences": 3,
            "applicable_scopes": [{"kind": "whole_room"}],
            "hard_constraints": [
                {"kind": "pin_layer_bottom", "hard": True},
                {"kind": "preserve_aspect_ratio", "hard": True},
            ],
            "sources": [
                {
                    "pack_code": "AG-PACK-BASE", "pack_kind": "total", "revision_number": 2, "entry_key": "entry-1",
                    "mode": "optional", "min_occurrences": 0, "max_occurrences": 4,
                    "applicable_scope": {"kind": "whole_room"}, "alternative_set_key": None,
                    "source_group_code": None, "source_category_pack_code": None,
                },
                {
                    "pack_code": "AG-PACK-REQUIRED", "pack_kind": "classification", "revision_number": 3, "entry_key": "entry-2",
                    "mode": "required", "min_occurrences": 2, "max_occurrences": 3,
                    "applicable_scope": {"kind": "whole_room"}, "alternative_set_key": None,
                    "source_group_code": None, "source_category_pack_code": None,
                },
            ],
        }
    ]


def test_exclusive_role_conflict_never_silently_selects_one_pack() -> None:
    conflicts = MaterialLibraryRepository._exclusive_role_conflicts(
        [
            {
                "pack_code": "AG-PACK-A", "exclusive_roles": ["background"],
                "resolved_entries": [{"material_role": "background", "resolved_asset_codes": ["AG-IMG-A"]}],
            },
            {
                "pack_code": "AG-PACK-B", "exclusive_roles": ["background"],
                "resolved_entries": [{"material_role": "background", "resolved_asset_codes": ["AG-IMG-B"]}],
            },
        ]
    )

    assert conflicts[0]["code"] == "MATERIAL_PACK_EXCLUSIVE_ROLE_CONFLICT"
    assert conflicts[0]["pack_codes"] == ["AG-PACK-A", "AG-PACK-B"]


def test_classification_pack_cannot_recursively_include_another_category_pack() -> None:
    repository = MaterialLibraryRepository(None)  # type: ignore[arg-type]

    with pytest.raises(MaterialLibraryValidationError, match="cannot include category packs"):
        repository._validate_pack_shape(
            pack_kind="classification",
            role="background",
            entries=[
                {
                    "selection_kind": "category_pack",
                    "selection_code": "AG-PACK-BACKGROUNDS",
                    "material_role": "background",
                    "mode": "optional",
                }
            ],
        )


def test_role_mode_filters_total_and_classification_entries_by_role() -> None:
    refs = [
        {
            "pack_code": "AG-PACK-TOTAL", "pack_kind": "total", "exclusive_roles": ["background"],
            "resolved_entries": [{"material_role": "background", "resolved_asset_codes": ["AG-IMG-TOTAL"]}],
        },
        {
            "pack_code": "AG-PACK-CLASS", "pack_kind": "classification", "exclusive_roles": ["background"],
            "resolved_entries": [{"material_role": "background", "resolved_asset_codes": ["AG-IMG-CLASS"]}],
        },
    ]

    inherited = MaterialLibraryRepository._apply_role_modes_to_pack_refs(refs, {"background": "inherit"})
    replaced = MaterialLibraryRepository._apply_role_modes_to_pack_refs(refs, {"background": "replace"})

    assert inherited[0]["resolved_asset_codes"] == ["AG-IMG-TOTAL"]
    assert inherited[1]["resolved_asset_codes"] == []
    assert inherited[1]["exclusive_roles"] == []
    assert replaced[0]["resolved_asset_codes"] == []
    assert replaced[0]["exclusive_roles"] == []
    assert replaced[1]["resolved_asset_codes"] == ["AG-IMG-CLASS"]


def test_replace_mode_only_compiles_classification_pack_candidates() -> None:
    detail = {
        "script": {"blocks": [{"block_code": "BLOCK-1", "content": "测试"}]},
        "shot_list": {"shots": [{"shot_code": "SHOT-1", "shot_goal": "开场", "material_role_requirements": ["background"], "estimated_duration_ms": 1_000}]},
    }
    assets = [
        {
            "asset_code": "AG-IMG-TOTAL", "material_roles": ["background"],
            "execution_capability": "maitu_bound", "constraint_profile_ref": None,
            "material_pack_rules": [{"material_role": "background", "sources": [{"pack_kind": "total"}]}],
        },
        {
            "asset_code": "AG-IMG-CLASS", "material_roles": ["background"],
            "execution_capability": "maitu_bound", "constraint_profile_ref": None,
            "material_pack_rules": [{"material_role": "background", "sources": [{"pack_kind": "classification"}]}],
        },
    ]

    blueprint, _, blocked = FunctionalLiveRoomService._compile(
        detail,
        assets,
        {"target_live_room_id": "room-1", "expected_title": "替换背景", "material_role_modes": {"background": "replace"}},
        variant_code="VARIANT-001",
    )

    assert blocked == []
    assert blueprint["scenes"][0]["layers"][0]["asset_code"] == "AG-IMG-CLASS"


def test_live_room_pack_requirements_count_required_and_alternative_occurrences() -> None:
    requirements = [
        {
            "pack_code": "AG-PACK-001", "revision_number": 1, "entry_key": "entry-1",
            "mode": "required", "material_role": "background", "resolved_asset_codes": ["AG-IMG-BG"],
            "min_occurrences": 2, "max_occurrences": 2, "applicable_scope": {"kind": "whole_room"},
        },
        {
            "pack_code": "AG-PACK-001", "revision_number": 1, "entry_key": "entry-2",
            "mode": "alternative", "alternative_set_key": "product-choice", "material_role": "product_display",
            "resolved_asset_codes": ["AG-IMG-PRODUCT-A"], "min_occurrences": 1,
            "max_occurrences": 2, "applicable_scope": {"kind": "whole_room"},
        },
        {
            "pack_code": "AG-PACK-001", "revision_number": 1, "entry_key": "entry-3",
            "mode": "alternative", "alternative_set_key": "product-choice", "material_role": "product_display",
            "resolved_asset_codes": ["AG-IMG-PRODUCT-B"], "min_occurrences": 1,
            "max_occurrences": 2, "applicable_scope": {"kind": "whole_room"},
        },
    ]
    decisions = [
        {"role": "background", "selected_asset_code": "AG-IMG-BG", "shot_code": "SHOT-1", "scene_code": "MSB-1"},
        {"role": "background", "selected_asset_code": "AG-IMG-BG", "shot_code": "SHOT-2", "scene_code": "MSB-2"},
        {"role": "product_display", "selected_asset_code": "AG-IMG-PRODUCT-B", "shot_code": "SHOT-2", "scene_code": "MSB-2"},
    ]

    evidence, failures = FunctionalLiveRoomService._evaluate_material_pack_requirements(
        requirements=requirements,
        decisions=decisions,
    )

    assert failures == []
    assert [item["status"] for item in evidence] == ["satisfied", "satisfied"]

    _, failures = FunctionalLiveRoomService._evaluate_material_pack_requirements(
        requirements=requirements,
        decisions=decisions[:1],
    )
    assert failures == [
        "material_pack_unsatisfied_minimum:AG-PACK-001:entry-1",
        "material_pack_unsatisfied_minimum:AG-PACK-001:alternative:product-choice",
    ]
