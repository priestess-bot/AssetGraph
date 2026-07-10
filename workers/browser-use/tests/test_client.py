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


def test_get_replacement_plan_operation_plan_uses_browser_use_endpoint() -> None:
    client = RecordingClient()

    result = client.get_replacement_plan_operation_plan("MT-PLAN-20260709-000001")

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "GET",
            "/api/maitu/replacement-plans/MT-PLAN-20260709-000001/browser-use-operations",
            None,
        )
    ]


def test_get_live_room_build_plan_operation_plan_uses_browser_use_endpoint() -> None:
    client = RecordingClient()

    result = client.get_live_room_build_plan_operation_plan("MT-BUILD-20260709-000001")

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "GET",
            "/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/browser-use-operations",
            None,
        )
    ]


def test_write_live_room_build_plan_execution_result_uses_execution_results_endpoint() -> None:
    client = RecordingClient()
    payload = {"execution_status": "blocked", "mode": "non_destructive", "operation_results": []}

    result = client.write_live_room_build_plan_execution_result("MT-BUILD-20260709-000001", payload)

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "POST",
            "/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/execution-results",
            payload,
        )
    ]


def test_get_jd_live_metric_session_uses_metric_session_endpoint() -> None:
    client = RecordingClient()

    result = client.get_jd_live_metric_session("JD-METRIC-20260710-000001")

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "GET",
            "/api/maitu/jd-live-metric-sessions/JD-METRIC-20260710-000001",
            None,
        )
    ]


def test_update_jd_live_metric_session_uses_metric_session_endpoint() -> None:
    client = RecordingClient()
    payload = {"status": "running", "result_summary": "同步抓取中"}

    result = client.update_jd_live_metric_session("JD-METRIC-20260710-000001", payload)

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "PATCH",
            "/api/maitu/jd-live-metric-sessions/JD-METRIC-20260710-000001",
            payload,
        )
    ]


def test_write_jd_live_metric_sample_uses_metric_sample_endpoint() -> None:
    client = RecordingClient()
    payload = {"scene_name": "商品01-场景01", "online_viewers": 128}

    result = client.write_jd_live_metric_sample("JD-METRIC-20260710-000001", payload)

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "POST",
            "/api/maitu/jd-live-metric-sessions/JD-METRIC-20260710-000001/samples",
            payload,
        )
    ]
