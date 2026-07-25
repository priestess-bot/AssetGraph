from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.repositories.material_library import MaterialLibraryRepository, MaterialLibraryValidationError
from app.schemas.material_library import AssetGapUpdate


def test_asset_library_cannot_create_another_global_gap_waiver() -> None:
    with pytest.raises(ValidationError):
        AssetGapUpdate(status="waived", waiver_reason="should be scoped to a plan")


def test_historical_global_waiver_can_only_become_obsolete() -> None:
    MaterialLibraryRepository._validate_gap_transition("waived", "obsolete")
    with pytest.raises(MaterialLibraryValidationError, match="ASSET_GAP_INVALID_TRANSITION"):
        MaterialLibraryRepository._validate_gap_transition("open", "waived")
