from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.api import auth
from app.api.routes import maitu


@dataclass
class DurablePayload:
    value: dict[str, Any]

    def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
        return self.value


def test_operator_and_worker_identity_cannot_embed_configured_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_secret = "operator-secret-value-not-an-id"
    worker_secret = "worker-secret-value-not-an-id"
    monkeypatch.setattr(
        auth.settings,
        "maitu_reconciliation_operator_token",
        SecretStr(operator_secret),
    )
    monkeypatch.setattr(
        auth.settings,
        "maitu_reconciliation_operator_id",
        f"ops-{operator_secret}",
    )
    with pytest.raises(HTTPException) as operator_error:
        auth.require_maitu_reconciliation_operator(
            authorization=f"Bearer {operator_secret}"
        )
    assert operator_error.value.status_code == 503

    monkeypatch.setattr(
        auth.settings,
        "maitu_script_layout_worker_token",
        SecretStr(worker_secret),
    )
    with pytest.raises(HTTPException) as worker_error:
        auth.require_maitu_script_layout_worker(
            authorization=f"Bearer {worker_secret}",
            worker_id=f"runner-{worker_secret}",
        )
    assert worker_error.value.status_code == 422


def test_checkpoint_durable_uuid_identity_cannot_equal_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_secret = "44444444-4444-4444-8444-444444444444"
    operator_secret = "55555555-5555-4555-8555-555555555555"
    monkeypatch.setattr(
        maitu.settings,
        "maitu_script_layout_worker_token",
        SecretStr(worker_secret),
    )
    monkeypatch.setattr(
        maitu.settings,
        "maitu_reconciliation_operator_token",
        SecretStr(operator_secret),
    )

    with pytest.raises(HTTPException) as worker_error:
        maitu.reject_script_layout_worker_secret(
            DurablePayload({"completion_id": worker_secret})
        )
    assert worker_error.value.status_code == 422

    with pytest.raises(HTTPException) as operator_error:
        maitu.reject_reconciliation_operator_secret(
            DurablePayload({"reconciliation_id": operator_secret})
        )
    assert operator_error.value.status_code == 422

    maitu.reject_script_layout_worker_secret(
        DurablePayload({"completion_id": "66666666-6666-4666-8666-666666666666"})
    )
