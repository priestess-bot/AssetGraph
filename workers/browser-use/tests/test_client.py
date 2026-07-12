from __future__ import annotations

from typing import Any

import pytest

from browser_use_worker.client import AssetGraphClient, AssetGraphClientError


class RecordingClient(AssetGraphClient):
    def __init__(self) -> None:
        super().__init__("http://assetgraph")
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.request_timeouts: list[float | None] = []

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        self.request_timeouts.append(timeout_seconds)
        return {"asset_code": "AG-VID-20260709-000001"}


def test_get_asset_uses_asset_endpoint() -> None:
    client = RecordingClient()

    result = client.get_asset("AG-VID-20260709-000001")

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [("GET", "/api/assets/AG-VID-20260709-000001", None)]


def test_update_asset_maitu_material_binding_uses_binding_endpoint() -> None:
    client = RecordingClient()
    payload = {
        "maitu_material_id": 41043,
        "source_material_type": "decorative_video",
        "source_material_url": "https://static.example/video.mp4",
    }

    result = client.update_asset_maitu_material_binding("AG-VID-20260709-000056", payload)

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "PATCH",
            "/api/assets/AG-VID-20260709-000056/maitu-material-binding",
            payload,
        )
    ]


@pytest.mark.parametrize("asset_code", ["../admin", "AG-IMG/OTHER", "AG-IMG?x=1", "AG-IMG#fragment", ""])
def test_asset_paths_reject_non_segment_asset_codes(asset_code: str) -> None:
    client = RecordingClient()

    with pytest.raises(AssetGraphClientError):
        client.update_asset_maitu_material_binding(asset_code, {"maitu_material_id": 1})

    assert client.calls == []


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


def test_script_layout_checkpoint_client_sends_worker_capability_headers(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        @staticmethod
        def read() -> bytes:
            return b"{}"

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    worker_token = "-".join(["unit", "test", "worker"])
    client = AssetGraphClient(
        "http://assetgraph",
        script_layout_worker_token=worker_token,
        worker_id="worker-A",
    )

    client.start_script_layout_execution("MT-BUILD-20260712-000001", {"x": 1})

    request = captured["request"]
    assert request.get_header("Authorization") == f"Bearer {worker_token}"
    assert request.get_header("X-assetgraph-worker-id") == "worker-A"


def test_script_layout_checkpoint_client_uses_nested_execution_endpoints() -> None:
    client = RecordingClient()
    build_plan_code = "MT-BUILD-20260712-000001"
    execution_code = "MT-EXEC-20260712-000001"
    start_payload = {"plan_fingerprint": "a" * 64, "target_live_room_id": "47000002"}
    begin_payload = {"operation_fingerprint": "b" * 64, "attempt_id": "attempt"}
    complete_payload = {**begin_payload, "completion_id": "completion", "evidence": {"verified": True}}
    finalize_payload = {"execution_status": "completed_with_manual_review"}

    client.start_script_layout_execution(build_plan_code, start_payload)
    client.begin_script_layout_execution_operation(build_plan_code, execution_code, 2, begin_payload)
    client.dispatch_script_layout_execution_operation(build_plan_code, execution_code, 2, begin_payload)
    client.invalidate_script_layout_execution_operation(build_plan_code, execution_code, 2, begin_payload)
    client.complete_script_layout_execution_operation(build_plan_code, execution_code, 2, complete_payload)
    client.finalize_script_layout_execution(build_plan_code, execution_code, finalize_payload)

    base = (
        "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/"
        "script-layout-executions"
    )
    assert client.calls == [
        ("POST", f"{base}/start", start_payload),
        ("POST", f"{base}/{execution_code}/operations/2/begin", begin_payload),
        ("POST", f"{base}/{execution_code}/operations/2/dispatch", begin_payload),
        ("POST", f"{base}/{execution_code}/operations/2/invalidate", begin_payload),
        ("POST", f"{base}/{execution_code}/operations/2/complete", complete_payload),
        ("POST", f"{base}/{execution_code}/finalize", finalize_payload),
    ]


@pytest.mark.parametrize("code", ["../escape", "MT-BUILD/OTHER", "MT-BUILD?x=1", ""])
def test_script_layout_checkpoint_client_rejects_invalid_path_segments(code: str) -> None:
    client = RecordingClient()

    with pytest.raises(AssetGraphClientError):
        client.start_script_layout_execution(code, {"plan_fingerprint": "a" * 64})

    assert client.calls == []


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


def test_heartbeat_retry_task_sends_lease_identity() -> None:
    client = RecordingClient()

    result = client.heartbeat_retry_task(
        "MT-RETRY-20260710-000001",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
        lock_ttl_seconds=120,
    )

    assert result == {"asset_code": "AG-VID-20260709-000001"}
    assert client.calls == [
        (
            "POST",
            "/api/maitu/retry-tasks/MT-RETRY-20260710-000001/heartbeat",
            {
                "claimed_by": "worker-1",
                "claim_token": "c1a1d000-0000-4000-8000-000000000001",
                "lease_version": 2,
                "lock_ttl_seconds": 120,
            },
        )
    ]


def test_release_retry_task_sends_lease_identity() -> None:
    client = RecordingClient()

    client.release_retry_task(
        "MT-RETRY-20260710-000001",
        status="pending",
        result_summary="retry later",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
    )

    assert client.calls == [
        (
            "POST",
            "/api/maitu/retry-tasks/MT-RETRY-20260710-000001/release",
            {
                "status": "pending",
                "result_summary": "retry later",
                "claimed_by": "worker-1",
                "claim_token": "c1a1d000-0000-4000-8000-000000000001",
                "lease_version": 2,
            },
        )
    ]


def test_write_retry_execution_result_sends_execution_and_lease_identity() -> None:
    client = RecordingClient()

    client.write_retry_execution_result(
        "MT-RETRY-20260710-000001",
        retry_execution_id="7be4e98f-dd31-4c50-97d6-604d46ec7869",
        retry_execution_status="succeeded",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
        result_summary="done",
    )

    assert client.calls == [
        (
            "POST",
            "/api/maitu/retry-tasks/MT-RETRY-20260710-000001/execution-results",
            {
                "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
                "retry_execution_status": "succeeded",
                "claimed_by": "worker-1",
                "claim_token": "c1a1d000-0000-4000-8000-000000000001",
                "lease_version": 2,
                "result_summary": "done",
            },
        )
    ]


def test_write_retry_execution_result_uses_callback_timeout_without_serializing_it() -> None:
    client = RecordingClient()

    client.write_retry_execution_result(
        "MT-RETRY-20260710-000001",
        retry_execution_id="7be4e98f-dd31-4c50-97d6-604d46ec7869",
        retry_execution_status="succeeded",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
        request_timeout_seconds=12.5,
    )

    assert client.request_timeouts[-1] == 12.5
    assert "request_timeout_seconds" not in (client.calls[-1][2] or {})


def test_release_retry_task_uses_callback_timeout_without_serializing_it() -> None:
    client = RecordingClient()

    client.release_retry_task(
        "MT-RETRY-20260710-000001",
        status="pending",
        result_summary="retry later",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
        request_timeout_seconds=12.5,
    )

    assert client.request_timeouts[-1] == 12.5
    assert "request_timeout_seconds" not in (client.calls[-1][2] or {})


def test_begin_retry_operation_checkpoint_uses_canonical_path_payload_and_transport_timeout() -> None:
    client = RecordingClient()

    client.begin_retry_operation_checkpoint(
        "MT-RETRY-20260710-000001",
        "replace-layer-01",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
        operation_fingerprint="a" * 64,
        attempt_id="7be4e98f-dd31-4c50-97d6-604d46ec7869",
        request_timeout_seconds=12.5,
    )

    assert client.calls[-1] == (
        "POST",
        "/api/maitu/retry-tasks/MT-RETRY-20260710-000001/operations/replace-layer-01/begin",
        {
            "claimed_by": "worker-1",
            "claim_token": "c1a1d000-0000-4000-8000-000000000001",
            "lease_version": 2,
            "operation_fingerprint": "a" * 64,
            "attempt_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
        },
    )
    assert client.request_timeouts[-1] == 12.5
    assert "request_timeout_seconds" not in (client.calls[-1][2] or {})


def test_complete_retry_operation_checkpoint_uses_canonical_path_payload_and_transport_timeout() -> None:
    client = RecordingClient()
    evidence = {"verified": True, "material_id": 42}

    client.complete_retry_operation_checkpoint(
        "MT-RETRY-20260710-000001",
        "save-project-01",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=2,
        operation_fingerprint="b" * 64,
        attempt_id="7be4e98f-dd31-4c50-97d6-604d46ec7869",
        completion_id="d5ec7c2d-8af3-4ef3-a6c2-1bbd6e832d18",
        result_summary="project save verified",
        evidence=evidence,
        request_timeout_seconds=9.5,
    )

    assert client.calls[-1] == (
        "POST",
        "/api/maitu/retry-tasks/MT-RETRY-20260710-000001/operations/save-project-01/complete",
        {
            "claimed_by": "worker-1",
            "claim_token": "c1a1d000-0000-4000-8000-000000000001",
            "lease_version": 2,
            "operation_fingerprint": "b" * 64,
            "attempt_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
            "completion_id": "d5ec7c2d-8af3-4ef3-a6c2-1bbd6e832d18",
            "result_summary": "project save verified",
            "evidence": evidence,
        },
    )
    assert client.request_timeouts[-1] == 9.5
    assert "request_timeout_seconds" not in (client.calls[-1][2] or {})


@pytest.mark.parametrize("operation_key", ["../save", "save/project", "save?x=1", "", " save-project-01 "])
def test_checkpoint_paths_reject_noncanonical_operation_keys(operation_key: str) -> None:
    client = RecordingClient()

    with pytest.raises(AssetGraphClientError):
        client.begin_retry_operation_checkpoint(
            "MT-RETRY-20260710-000001",
            operation_key,
            claimed_by="worker-1",
            claim_token="c1a1d000-0000-4000-8000-000000000001",
            lease_version=2,
            operation_fingerprint="a" * 64,
            attempt_id="7be4e98f-dd31-4c50-97d6-604d46ec7869",
        )

    assert client.calls == []


@pytest.mark.parametrize("retry_task_code", ["../admin", "MT-RETRY/OTHER", "MT-RETRY?x=1", "", " MT-RETRY-1 "])
def test_retry_task_mutation_paths_reject_noncanonical_codes(retry_task_code: str) -> None:
    client = RecordingClient()

    with pytest.raises(AssetGraphClientError):
        client.heartbeat_retry_task(
            retry_task_code,
            claimed_by="worker-1",
            claim_token="c1a1d000-0000-4000-8000-000000000001",
            lease_version=2,
            lock_ttl_seconds=120,
        )

    assert client.calls == []
