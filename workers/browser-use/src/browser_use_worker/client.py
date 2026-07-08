from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


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

    def release_retry_task(self, retry_task_code: str, *, status: str, result_summary: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"/api/maitu/retry-tasks/{retry_task_code}/release",
            {"status": status, "result_summary": result_summary},
        )

    def write_retry_execution_result(
        self,
        retry_task_code: str,
        *,
        retry_execution_status: str,
        result_summary: str | None = None,
        error_message: str | None = None,
        last_retry_execution_code: str | None = None,
        screenshot_asset_code: str | None = None,
        retry_instruction: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "retry_execution_status": retry_execution_status,
            "result_summary": result_summary,
            "error_message": error_message,
            "last_retry_execution_code": last_retry_execution_code,
            "screenshot_asset_code": screenshot_asset_code,
            "retry_instruction": retry_instruction,
        }
        return self._request_json(
            "POST",
            f"/api/maitu/retry-tasks/{retry_task_code}/execution-results",
            {key: value for key, value in payload.items() if value is not None},
        )

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AssetGraphClientError(f"HTTP {exc.code} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise AssetGraphClientError(f"Request failed {path}: {exc}") from exc
        if not content:
            return {}
        return json.loads(content.decode("utf-8"))
