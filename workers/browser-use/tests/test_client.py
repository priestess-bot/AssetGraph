from __future__ import annotations

from typing import Any

from browser_use_worker.client import AssetGraphClient


class RecordingClient(AssetGraphClient):
    def __init__(self) -> None:
        super().__init__("http://assetgraph")
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        return {"asset_code": "AG-VID-20260709-000001"}


def test_get_asset_uses_asset_endpoint() -> None:
    client = RecordingClient()

    result = client.get_asset("AG-VID-20260709-000001")

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [("GET", "/api/assets/AG-VID-20260709-000001", None)]
