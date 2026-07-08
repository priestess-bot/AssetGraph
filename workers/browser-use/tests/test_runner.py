from __future__ import annotations

from typing import Any

from browser_use_worker.config import WorkerConfig
from browser_use_worker.runner import BrowserUseWorker, DryRunBrowserUseExecutor, OperationExecutionResult


class FakeClient:
    def __init__(self, bundle: dict[str, Any] | None) -> None:
        self.bundle = bundle
        self.claim_payloads: list[dict[str, Any]] = []
        self.releases: list[tuple[str, str, str]] = []
        self.results: list[tuple[str, dict[str, Any]]] = []

    def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.claim_payloads.append(payload)
        return self.bundle

    def release_retry_task(self, retry_task_code: str, *, status: str, result_summary: str) -> dict[str, Any]:
        self.releases.append((retry_task_code, status, result_summary))
        return {}

    def write_retry_execution_result(self, retry_task_code: str, **payload: Any) -> dict[str, Any]:
        self.results.append((retry_task_code, payload))
        return {}


class SucceedingExecutor:
    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        return OperationExecutionResult(status="succeeded", summary="done", screenshot_asset_code="AG-IMG-1")


class ManualExecutor:
    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        return OperationExecutionResult(
            status="manual_required",
            summary="needs human",
            error_message="captcha",
            retry_instruction="login manually",
        )


def sample_bundle() -> dict[str, Any]:
    return {
        "retry_task": {"retry_task_code": "MT-RETRY-20260708-000001"},
        "operation_plan": {
            "retry_task_code": "MT-RETRY-20260708-000001",
            "operations": [{"operation_type": "retry_replace_layer_asset"}],
        },
    }


def test_worker_claim_payload_includes_filters() -> None:
    config = WorkerConfig(
        api_base_url="http://assetgraph",
        worker_id="worker-1",
        lock_ttl_seconds=120,
        max_attempts=2,
        failure_type="missing_layer",
        maitu_project_code="MT-PROJ-1",
        scene_name="京东空白直播间",
    )
    worker = BrowserUseWorker(config=config, client=FakeClient(None), executor=DryRunBrowserUseExecutor())

    assert worker.claim_payload() == {
        "claimed_by": "worker-1",
        "lock_ttl_seconds": 120,
        "max_attempts": 2,
        "failure_type": "missing_layer",
        "maitu_project_code": "MT-PROJ-1",
        "scene_name": "京东空白直播间",
    }


def test_dry_run_releases_claimed_task() -> None:
    client = FakeClient(sample_bundle())
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1", dry_run=True)
    worker = BrowserUseWorker(config=config, client=client, executor=DryRunBrowserUseExecutor())

    assert worker.run_once() is True
    assert client.releases[0][0] == "MT-RETRY-20260708-000001"
    assert client.releases[0][1] == "pending"
    assert "Dry run validated" in client.releases[0][2]
    assert client.results == []


def test_successful_executor_writes_success_result() -> None:
    client = FakeClient(sample_bundle())
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=SucceedingExecutor())

    assert worker.run_once() is True
    assert client.releases == []
    retry_task_code, payload = client.results[0]
    assert retry_task_code == "MT-RETRY-20260708-000001"
    assert payload["retry_execution_status"] == "succeeded"
    assert payload["screenshot_asset_code"] == "AG-IMG-1"


def test_manual_executor_writes_manual_required_result() -> None:
    client = FakeClient(sample_bundle())
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=ManualExecutor())

    assert worker.run_once() is True
    retry_task_code, payload = client.results[0]
    assert retry_task_code == "MT-RETRY-20260708-000001"
    assert payload["retry_execution_status"] == "manual_required"
    assert payload["error_message"] == "captcha"
    assert payload["retry_instruction"] == "login manually"


def test_worker_returns_false_when_no_task() -> None:
    client = FakeClient(None)
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=DryRunBrowserUseExecutor())

    assert worker.run_once() is False
    assert client.releases == []
    assert client.results == []
