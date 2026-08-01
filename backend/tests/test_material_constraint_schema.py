from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.material_library import AssetConstraintProfileWrite


def test_constraint_profile_rejects_simultaneous_hard_top_and_bottom_pins() -> None:
    with pytest.raises(ValidationError):
        AssetConstraintProfileWrite.model_validate(
            {
                "constraints": [
                    {"kind": "pin_layer_top", "hard": True},
                    {"kind": "pin_layer_bottom", "hard": True},
                ]
            }
        )


def test_relative_layer_constraint_requires_known_material_role() -> None:
    with pytest.raises(ValidationError):
        AssetConstraintProfileWrite.model_validate(
            {
                "constraints": [
                    {
                        "kind": "above_role",
                        "hard": True,
                        "parameters": {"role": "not-a-material-role"},
                    }
                ]
            }
        )


def test_absolute_layer_pin_cannot_be_saved_as_a_soft_preference() -> None:
    with pytest.raises(ValidationError, match="absolute layer band and must be hard"):
        AssetConstraintProfileWrite.model_validate(
            {"constraints": [{"kind": "pin_layer_top", "hard": False, "parameters": {}}]}
        )
