from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx


class LiveResearchAPIError(RuntimeError):
    pass


class LiveResearchAPIClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000/api/live-research",
        *,
        worker_token: str | None = None,
        worker_id: str | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AssetGraph API base URL must be HTTP(S)")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("plain HTTP AssetGraph API must remain loopback-local")
        self.base_url = base_url.rstrip("/")
        self.worker_token = str(worker_token or "")
        self.worker_id = str(worker_id or "").strip()
        if self.worker_id and len(self.worker_id) > 128:
            raise ValueError("worker_id exceeds 128 characters")
        self.client = client or httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def claim_watch_target(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            "/worker/watch-target-claims",
            {"worker_id": worker_id, "lease_seconds": lease_seconds},
        )

    def heartbeat_watch_target(
        self,
        target_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        lease_seconds: int,
    ) -> dict[str, Any]:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            f"/worker/watch-targets/{target_code}/heartbeat",
            {
                "worker_id": worker_id,
                "claim_token": claim_token,
                "lease_version": lease_version,
                "lease_seconds": lease_seconds,
            },
        )

    def release_watch_target(
        self,
        target_code: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_version: int,
        outcome: str,
        next_check_seconds: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            f"/worker/watch-targets/{target_code}/release",
            {
                "worker_id": worker_id,
                "claim_token": claim_token,
                "lease_version": lease_version,
                "outcome": outcome,
                "next_check_seconds": next_check_seconds,
                "error_code": error_code,
                "error_message": error_message,
            },
        )

    def create_capture_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request("POST", "/worker/capture-sessions", payload)

    def finish_capture_session(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/worker/capture-sessions/{session_code}/finish", payload
        )

    def add_channel(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", f"/worker/capture-sessions/{session_code}/channels", payload
        )

    def finalize_chunk(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", f"/worker/capture-sessions/{session_code}/chunks", payload
        )

    def register_event_batch(
        self, session_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/worker/capture-sessions/{session_code}/raw-event-batches",
            payload,
        )

    def append_timeline(self, session_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", f"/worker/capture-sessions/{session_code}/timeline-spans", payload
        )

    def get_capture_session(self, session_code: str) -> dict[str, Any]:
        return self._request("GET", f"/capture-sessions/{session_code}")

    def claim_retention(
        self,
        worker_id: str,
        lease_seconds: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_worker_identity(worker_id)
        result = self._request(
            "POST",
            "/worker/retention/claims",
            {
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
                "limit": limit,
            },
        )
        return list(result or [])

    def complete_retention(self, payload: dict[str, Any]) -> None:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        self._request("POST", "/worker/retention/complete", payload, expect_no_content=True)

    def claim_clip_job(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            "/worker/clip-job-claims",
            {"worker_id": worker_id, "lease_seconds": lease_seconds},
        )

    def complete_clip_job(self, job_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request("POST", f"/worker/clip-jobs/{job_code}/complete", payload)

    def heartbeat_clip_job(self, job_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request("POST", f"/worker/clip-jobs/{job_code}/heartbeat", payload)

    def fail_clip_job(self, job_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request("POST", f"/worker/clip-jobs/{job_code}/fail", payload)

    def claim_analysis_run(self, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            "/worker/analysis-run-claims",
            {"worker_id": worker_id, "lease_seconds": lease_seconds},
        )

    def authorize_provider_strategy(
        self,
        *,
        worker_id: str,
        strategy_revision: str,
        analysis_type: str,
        input_fingerprint: str,
    ) -> dict[str, Any]:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            "/worker/provider-strategy-authorizations",
            {
                "worker_id": worker_id,
                "strategy_revision": strategy_revision,
                "analysis_type": analysis_type,
                "input_fingerprint": input_fingerprint,
            },
        )

    def persist_provider_invocation_evidence(
        self, evidence: dict[str, Any]
    ) -> str:
        result = self._request(
            "POST",
            "/worker/provider-invocation-evidence",
            evidence,
        )
        artifact_code = str((result or {}).get("artifact_code") or "")
        if not artifact_code:
            raise LiveResearchAPIError(
                "AssetGraph did not return a provider evidence artifact reference"
            )
        return artifact_code

    def complete_analysis_run(self, run_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request("POST", f"/worker/analysis-runs/{run_code}/complete", payload)

    def heartbeat_analysis_run(
        self, run_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request(
            "POST", f"/worker/analysis-runs/{run_code}/heartbeat", payload
        )

    def fail_analysis_run(self, run_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_worker_identity(str(payload.get("worker_id") or ""))
        return self._request("POST", f"/worker/analysis-runs/{run_code}/fail", payload)

    def retry_analysis_run(
        self, run_code: str, *, worker_id: str, reason: str
    ) -> dict[str, Any]:
        self._require_worker_identity(worker_id)
        return self._request(
            "POST",
            f"/worker/analysis-runs/{run_code}/retry",
            {"worker_id": worker_id, "reason": reason},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expect_no_content: bool = False,
    ) -> Any:
        try:
            headers: dict[str, str] = {}
            if path.startswith("/worker/"):
                if not self.worker_token or not self.worker_id:
                    raise LiveResearchAPIError("worker credentials are required for internal API calls")
                headers = {
                    "Authorization": f"Bearer {self.worker_token}",
                    "X-AssetGraph-Worker-ID": self.worker_id,
                }
            response = self.client.request(
                method, self.base_url + path, json=payload, headers=headers
            )
        except httpx.RequestError as exc:
            raise LiveResearchAPIError(f"AssetGraph request failed: {path}") from exc
        if response.status_code >= 400:
            detail = response.text[:2000]
            raise LiveResearchAPIError(
                f"AssetGraph rejected {method} {path} with {response.status_code}: {detail}"
            )
        if expect_no_content:
            if response.status_code != 204:
                raise LiveResearchAPIError(f"AssetGraph returned unexpected status for {path}")
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise LiveResearchAPIError(f"AssetGraph returned invalid JSON for {path}") from exc

    def _require_worker_identity(self, supplied: str) -> None:
        if not self.worker_id or supplied != self.worker_id:
            raise LiveResearchAPIError("payload worker_id does not match configured worker identity")
