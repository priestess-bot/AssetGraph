from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.services import maitu_authority
from app.services.maitu_authority import (
    MaituAuthorityConfigurationError,
    MaituAuthorityUpstreamError,
    MaituAuthorityVerifier,
)


def _verifier(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> MaituAuthorityVerifier:
    monkeypatch.setattr(
        maitu_authority.settings,
        "maitu_authority_token",
        SecretStr("strict-fake-authority-token-value"),
    )
    monkeypatch.setattr(
        maitu_authority.settings,
        "maitu_readback_attestation_key",
        SecretStr("strict-fake-attestation-key-at-least-32-bytes"),
    )
    client = httpx.Client(
        base_url="https://api.maituai.com/",
        transport=handler,
        headers={"Authorization": "strict-fake-authority-token-value"},
    )
    return MaituAuthorityVerifier(client=client)


@pytest.mark.parametrize("status_code", [401, 403])
def test_authority_authentication_failure_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    verifier = _verifier(
        monkeypatch,
        httpx.MockTransport(lambda _request: httpx.Response(status_code, json={"error": "denied"})),
    )
    with pytest.raises(MaituAuthorityConfigurationError, match="authentication failed"):
        verifier._get("live/room/40147")
    verifier.close()


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_authority_rate_limit_and_server_failure_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    verifier = _verifier(
        monkeypatch,
        httpx.MockTransport(lambda _request: httpx.Response(status_code, json={"error": "temporary"})),
    )
    with pytest.raises(MaituAuthorityUpstreamError, match="temporarily unavailable"):
        verifier._get("live/room/40147")
    verifier.close()


def test_authority_timeout_and_malformed_json_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("strict fake timeout", request=request)

    timeout_verifier = _verifier(monkeypatch, httpx.MockTransport(timeout))
    with pytest.raises(MaituAuthorityUpstreamError, match="readback failed"):
        timeout_verifier._get("live/room/40147")
    timeout_verifier.close()

    malformed_verifier = _verifier(
        monkeypatch,
        httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})
        ),
    )
    with pytest.raises(MaituAuthorityUpstreamError, match="readback failed"):
        malformed_verifier._get("live/room/40147")
    malformed_verifier.close()


def test_authority_rejects_untrusted_origin_and_missing_backend_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(maitu_authority.settings, "maitu_authority_base_url", "https://attacker.invalid")
    with pytest.raises(MaituAuthorityConfigurationError, match="origin is not trusted"):
        MaituAuthorityVerifier()

    monkeypatch.setattr(maitu_authority.settings, "maitu_authority_base_url", "https://api.maituai.com")
    monkeypatch.setattr(maitu_authority.settings, "maitu_authority_token", None)
    verifier = MaituAuthorityVerifier(
        client=httpx.Client(
            base_url="https://api.maituai.com/",
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
        )
    )
    with pytest.raises(MaituAuthorityConfigurationError, match="token is not configured"):
        verifier._get("live/room/40147")
    verifier.close()
