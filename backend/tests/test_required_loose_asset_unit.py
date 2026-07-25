from __future__ import annotations

import pytest

from app.domain.errors import DomainValidationError
from app.services.functional_live_rooms import FunctionalLiveRoomService


def test_required_loose_asset_evidence_counts_emitted_layers() -> None:
    evidence, failures = FunctionalLiveRoomService._evaluate_required_loose_asset_codes(
        asset_codes=["AG-IMG-001", "AG-IMG-002"],
        decisions=[
            {"selected_asset_code": "AG-IMG-001", "role": "background"},
            {"selected_asset_code": "AG-IMG-001", "role": "background"},
        ],
    )

    assert evidence == [
        {"source_kind": "loose_asset", "asset_code": "AG-IMG-001", "mode": "required", "min_occurrences": 1, "observed_occurrences": 2, "status": "satisfied"},
        {"source_kind": "loose_asset", "asset_code": "AG-IMG-002", "mode": "required", "min_occurrences": 1, "observed_occurrences": 0, "status": "unsatisfied_minimum"},
    ]
    assert failures == ["required_loose_asset_unsatisfied_minimum:AG-IMG-002"]


def test_required_loose_asset_must_be_directly_selected() -> None:
    with pytest.raises(DomainValidationError, match="explicitly selected"):
        FunctionalLiveRoomService._validate_required_loose_asset_codes(
            ["AG-IMG-002"],
            ["AG-IMG-001"],
            [{"asset_code": "AG-IMG-001"}, {"asset_code": "AG-IMG-002"}],
        )
