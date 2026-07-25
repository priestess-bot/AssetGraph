from __future__ import annotations

from app.services.functional_live_rooms import FunctionalLiveRoomService


def _candidate(asset_code: str) -> dict[str, object]:
    return {
        "asset_code": asset_code,
        "execution_capability": "maitu_bound",
        "constraint_profile_ref": None,
        "material_pack_rules": [],
    }


def test_selection_score_exposes_parts_and_prefers_an_unused_tied_candidate() -> None:
    candidates = [_candidate("AG-IMG-A"), _candidate("AG-IMG-B")]

    first, first_decision = FunctionalLiveRoomService._choose_material_for_role(
        role="background",
        candidates=candidates,
        overrides={},
        prior_selection_counts={},
        shot_code="SHOT-001",
        scene_code="SCENE-001",
        scene_type=None,
    )
    second, second_decision = FunctionalLiveRoomService._choose_material_for_role(
        role="background",
        candidates=candidates,
        overrides={},
        prior_selection_counts={str(first["asset_code"]): 1},
        shot_code="SHOT-002",
        scene_code="SCENE-002",
        scene_type=None,
    )

    assert first["asset_code"] == "AG-IMG-A"
    assert first_decision["selected_score_parts"] == {
        "role_match": 60,
        "execution_capability": 30,
        "constraint_profile": 0,
        "material_pack_requirement": 0,
        "repeat_penalty": 0,
    }
    assert second["asset_code"] == "AG-IMG-B"
    assert second_decision["candidate_scores"][1] == {
        "asset_code": "AG-IMG-A",
        "score": 70,
        "score_parts": {
            "role_match": 60,
            "execution_capability": 30,
            "constraint_profile": 0,
            "material_pack_requirement": 0,
            "repeat_penalty": -20,
        },
        "selection_reasons": ["ROLE_MATCH", "CAPABILITY_MAITU_BOUND", "REPEAT_PENALTY_1"],
    }
