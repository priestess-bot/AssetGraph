from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


class AssetGraphClientError(RuntimeError):
    pass


@dataclass(slots=True)
class AssetGraphClient:
    base_url: str
    timeout_seconds: float = 30.0

    def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self._request_json("POST", "/api/maitu/retry-worker/next", payload)
        except AssetGraphClientError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        asset_segment = self._asset_code_segment(asset_code)
        try:
            return self._request_json("GET", f"/api/assets/{asset_segment}")
        except AssetGraphClientError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def update_asset_maitu_material_binding(self, asset_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        asset_segment = self._asset_code_segment(asset_code)
        return self._request_json("PATCH", f"/api/assets/{asset_segment}/maitu-material-binding", payload)

    def get_replacement_plan_operation_plan(self, plan_code: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/maitu/replacement-plans/{plan_code}/browser-use-operations")

    def get_live_room_build_plan_operation_plan(self, build_plan_code: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations")

    def write_live_room_build_plan_execution_result(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", f"/api/maitu/live-room-build-plans/{build_plan_code}/execution-results", payload)

    def get_jd_live_metric_session(self, capture_session_code: str) -> dict[str, Any]:
        return self._request_json("GET", f"/api/maitu/jd-live-metric-sessions/{capture_session_code}")

    def update_jd_live_metric_session(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("PATCH", f"/api/maitu/jd-live-metric-sessions/{capture_session_code}", payload)

    def write_jd_live_metric_sample(self, capture_session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", f"/api/maitu/jd-live-metric-sessions/{capture_session_code}/samples", payload)

    def heartbeat_retry_task(
        self,
        retry_task_code: str,
        *,
        claimed_by: str,
        claim_token: str,
        lease_version: int,
        lock_ttl_seconds: int,
    ) -> dict[str, Any]:
        retry_task_segment = self._retry_task_code_segment(retry_task_code)
        return self._request_json(
            "POST",
            f"/api/maitu/retry-tasks/{retry_task_segment}/heartbeat",
            {
                "claimed_by": claimed_by,
                "claim_token": claim_token,
                "lease_version": lease_version,
                "lock_ttl_seconds": lock_ttl_seconds,
            },
        )

    def release_retry_task(
        self,
        retry_task_code: str,
        *,
        status: str,
        result_summary: str,
        claimed_by: str,
        claim_token: str,
        lease_version: int,
        request_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        retry_task_segment = self._retry_task_code_segment(retry_task_code)
        return self._request_json(
            "POST",
            f"/api/maitu/retry-tasks/{retry_task_segment}/release",
            {
                "status": status,
                "result_summary": result_summary,
                "claimed_by": claimed_by,
                "claim_token": claim_token,
                "lease_version": lease_version,
            },
            timeout_seconds=request_timeout_seconds,
        )

    def write_retry_execution_result(
        self,
        retry_task_code: str,
        *,
        retry_execution_id: str,
        retry_execution_status: str,
        claimed_by: str,
        claim_token: str,
        lease_version: int,
        result_summary: str | None = None,
        error_message: str | None = None,
        last_retry_execution_code: str | None = None,
        screenshot_asset_code: str | None = None,
        retry_instruction: str | None = None,
        request_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        retry_task_segment = self._retry_task_code_segment(retry_task_code)
        payload = {
            "retry_execution_id": retry_execution_id,
            "retry_execution_status": retry_execution_status,
            "claimed_by": claimed_by,
            "claim_token": claim_token,
            "lease_version": lease_version,
            "result_summary": result_summary,
            "error_message": error_message,
            "last_retry_execution_code": last_retry_execution_code,
            "screenshot_asset_code": screenshot_asset_code,
            "retry_instruction": retry_instruction,
        }
        return self._request_json(
            "POST",
            f"/api/maitu/retry-tasks/{retry_task_segment}/execution-results",
            {key: value for key, value in payload.items() if value is not None},
            timeout_seconds=request_timeout_seconds,
        )

    @staticmethod
    def _retry_task_code_segment(retry_task_code: str) -> str:
        raw_value = str(retry_task_code or "")
        value = raw_value.strip()
        if raw_value != value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise AssetGraphClientError(f"Invalid retry_task_code path segment: {value!r}")
        return quote(value, safe="")

    @staticmethod
    def _asset_code_segment(asset_code: str) -> str:
        value = str(asset_code or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise AssetGraphClientError(f"Invalid AssetGraph asset_code path segment: {value!r}")
        return quote(value, safe="")

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        request_timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AssetGraphClientError(f"HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AssetGraphClientError(f"Request failed {path}: {exc}") from exc
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))
