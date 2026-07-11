from __future__ import annotations

import threading
from types import MethodType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

import browser_use_worker.runner as runner_module
from browser_use_worker.browser_cli_session import BrowserUseCliSession, BrowserUseCliSessionConfig
from browser_use_worker.client import AssetGraphClientError
from browser_use_worker.config import WorkerConfig
from browser_use_worker.maitu_executor import MaituBrowserExecutionError, MaituBrowserUseExecutor
from browser_use_worker.runner import BrowserUseWorker, DryRunBrowserUseExecutor, OperationExecutionResult


class FakeClient:
    def __init__(self, bundle: dict[str, Any] | None) -> None:
        self.bundle = bundle
        self.timeout_seconds = 30.0
        self.plan: dict[str, Any] = {}
        self.claim_payloads: list[dict[str, Any]] = []
        self.heartbeats: list[tuple[str, dict[str, Any]]] = []
        self.checkpoint_begins: list[tuple[str, str, dict[str, Any]]] = []
        self.checkpoint_completes: list[tuple[str, str, dict[str, Any]]] = []
        self.begin_failures_remaining = 0
        self.begin_conflict = False
        self.begin_decisions: list[str] = []
        self.block_begin_until_heartbeat = False
        self.complete_failures_remaining = 0
        self.releases: list[tuple[str, dict[str, Any]]] = []
        self.results: list[tuple[str, dict[str, Any]]] = []
        self.result_attempts: list[tuple[str, dict[str, Any]]] = []
        self.result_failures_remaining = 0
        self.block_result_until_heartbeat = False
        self.result_request_started = threading.Event()
        self.block_release_until_heartbeat = False
        self.release_request_started = threading.Event()
        self.callback_heartbeat_event = threading.Event()
        self.result_request_timeouts: list[float | None] = []
        self.release_request_timeouts: list[float | None] = []
        self.heartbeat_event = threading.Event()
        self.heartbeat_attempt_event = threading.Event()
        self.heartbeat_calls = 0
        self.fail_heartbeat = False
        self.fail_next_periodic_heartbeat = False
        self.fail_heartbeats_after_periodic_failure = False
        self.periodic_heartbeat_failed = False

    def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        self.claim_payloads.append(payload)
        return self.bundle

    def heartbeat_retry_task(self, retry_task_code: str, **payload: Any) -> dict[str, Any]:
        self.heartbeat_calls += 1
        is_periodic = threading.current_thread().name.startswith("retry-heartbeat-")
        if is_periodic:
            self.heartbeat_attempt_event.set()
        if is_periodic and self.fail_next_periodic_heartbeat:
            self.fail_next_periodic_heartbeat = False
            self.periodic_heartbeat_failed = True
            raise RuntimeError("transient periodic heartbeat failure")
        if self.periodic_heartbeat_failed and self.fail_heartbeats_after_periodic_failure:
            raise RuntimeError("lease cannot be revalidated")
        if self.fail_heartbeat:
            raise RuntimeError("lease lost")
        self.heartbeats.append((retry_task_code, payload))
        if is_periodic:
            self.heartbeat_event.set()
        if self.result_request_started.is_set() or self.release_request_started.is_set():
            self.callback_heartbeat_event.set()
        return {}

    def begin_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        *,
        request_timeout_seconds: float | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self.checkpoint_begins.append((retry_task_code, operation_key, payload))
        if self.block_begin_until_heartbeat:
            assert self.heartbeat_attempt_event.wait(timeout=0.1), "periodic heartbeat was not attempted"
        if self.begin_conflict:
            raise AssetGraphClientError("HTTP 409: checkpoint fingerprint conflict")
        if self.begin_failures_remaining:
            self.begin_failures_remaining -= 1
            raise RuntimeError("uncertain begin response")
        return {"decision": self.begin_decisions.pop(0) if self.begin_decisions else "skip"}

    def complete_retry_operation_checkpoint(
        self,
        retry_task_code: str,
        operation_key: str,
        *,
        request_timeout_seconds: float | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self.checkpoint_completes.append((retry_task_code, operation_key, payload))
        if self.complete_failures_remaining:
            self.complete_failures_remaining -= 1
            raise RuntimeError("uncertain complete response")
        return {"state": "completed", "decision": "skip"}

    def release_retry_task(
        self,
        retry_task_code: str,
        *,
        request_timeout_seconds: float | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self.release_request_timeouts.append(request_timeout_seconds)
        if self.block_release_until_heartbeat:
            self.release_request_started.set()
            assert self.callback_heartbeat_event.wait(timeout=0.1), "lease heartbeat stopped before release confirmation"
        self.releases.append((retry_task_code, payload))
        return {}

    def write_retry_execution_result(
        self,
        retry_task_code: str,
        *,
        request_timeout_seconds: float | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self.result_request_timeouts.append(request_timeout_seconds)
        self.result_attempts.append((retry_task_code, payload))
        if self.block_result_until_heartbeat:
            self.result_request_started.set()
            assert self.callback_heartbeat_event.wait(timeout=0.1), "lease heartbeat stopped before result confirmation"
        if self.result_failures_remaining > 0:
            self.result_failures_remaining -= 1
            raise RuntimeError("uncertain result transport failure")
        self.results.append((retry_task_code, payload))
        return {}

    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        return {"asset_code": asset_code}

    def get_replacement_plan_operation_plan(self, plan_code: str) -> dict[str, Any]:
        return self.plan


class WorkerAssetClient:
    def get_asset(self, asset_code: str) -> dict[str, Any] | None:
        return {"asset_code": asset_code}


class WorkerMaituSession:
    def __init__(
        self,
        *,
        timeout_seconds: float = 1.0,
        wait_event: threading.Event | None = None,
        recoverable_error: bool = False,
    ) -> None:
        self.config = SimpleNamespace(timeout_seconds=timeout_seconds)
        self.wait_event = wait_event
        self.recoverable_error = recoverable_error
        self.guard: Any = None
        self.called = False

    def set_execution_guard(self, guard: Any) -> None:
        self.guard = guard

    def ensure_ready(self, *, maitu_project_code: str | None, scene_name: str | None) -> None:
        self.called = True

    def recover_login(self) -> None:
        self.called = True

    def upload_asset(self, asset: dict[str, Any]) -> None:
        self.called = True

    def replace_layer_asset(self, operation: dict[str, Any], asset: dict[str, Any]) -> None:
        self.called = True
        if self.wait_event is not None:
            assert self.wait_event.wait(timeout=1.0), "periodic lease heartbeat was not observed"
        if self.recoverable_error:
            raise MaituBrowserExecutionError("temporary browser failure", retryable=True)

    def save_project(self) -> None:
        self.called = True

    def capture_screenshot(self, *, label: str) -> str | None:
        return "AG-IMG-1"

    def execute_generic_operation(self, operation: dict[str, Any], asset: dict[str, Any] | None) -> None:
        self.called = True


def make_executor(
    *,
    asset_client: Any,
    timeout_seconds: float = 1.0,
) -> tuple[MaituBrowserUseExecutor, BrowserUseCliSession]:
    session = BrowserUseCliSession(
        config=BrowserUseCliSessionConfig(timeout_seconds=timeout_seconds),
    )
    return MaituBrowserUseExecutor(asset_client=asset_client, session=session), session


class GuardIgnoringExecutor:
    """Deliberately lies about its safety contract to model an untrusted plugin."""

    max_side_effect_seconds = 1.0

    def __init__(self) -> None:
        self.called = False

    def set_execution_guard(self, guard: Any) -> None:
        return None

    def execute_operation_plan(self, operation_plan: dict[str, Any]) -> OperationExecutionResult:
        self.called = True
        return OperationExecutionResult(status="succeeded", summary="unsafe executor ran")


def sample_bundle() -> dict[str, Any]:
    return {
        "retry_task": {
            "retry_task_code": "MT-RETRY-20260708-000001",
            "claimed_by": "worker-1",
            "claim_token": "c1a1d000-0000-4000-8000-000000000001",
            "lease_version": 3,
        },
        "operation_plan": {
            "retry_task_code": "MT-RETRY-20260708-000001",
            "operations": [
                {
                    "operation_type": "retry_replace_layer_asset",
                    "asset_code": "AG-IMG-1",
                    "operation_key": "replace-layer-01",
                    "operation_fingerprint": "a" * 64,
                    "status": "ready",
                },
                {
                    "operation_type": "save_project",
                    "operation_key": "save-project-01",
                    "operation_fingerprint": "b" * 64,
                    "status": "ready",
                },
            ],
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


def test_dry_run_queue_worker_refuses_before_claiming() -> None:
    client = FakeClient(sample_bundle())
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1", dry_run=True)
    worker = BrowserUseWorker(config=config, client=client, executor=DryRunBrowserUseExecutor())

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.releases == []
    assert client.results == []


def test_dry_run_replacement_plan_returns_operation_details() -> None:
    operation_plan = {
        "plan_code": "MT-PLAN-20260709-000001",
        "operations": [
            {
                "operation_type": "replace_layer_asset",
                "slot_code": "MT-SLOT-20260709-000001",
                "asset_code": "AG-VID-20260709-000052",
                "asset_display_code": "MT-VID-0024",
                "instruction": "将素材替换为 MT-VID-0024",
            }
        ],
    }
    result = DryRunBrowserUseExecutor().execute_operation_plan(operation_plan)

    assert result.status == "released"
    assert "MT-PLAN-20260709-000001" in result.summary
    assert result.details["operation_count"] == 1
    assert result.details["operations"][0]["asset_display_code"] == "MT-VID-0024"


def test_worker_can_dry_run_replacement_plan_by_code() -> None:
    client = FakeClient(None)
    client.plan = {
        "plan_code": "MT-PLAN-20260709-000001",
        "operations": [{"operation_type": "replace_layer_asset", "slot_code": "MT-SLOT-1"}],
    }
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1", dry_run=True)
    worker = BrowserUseWorker(config=config, client=client, executor=DryRunBrowserUseExecutor())

    result = worker.run_plan_once("MT-PLAN-20260709-000001")

    assert result.status == "released"
    assert result.details["plan_code"] == "MT-PLAN-20260709-000001"


def test_dry_run_replacement_plan_rejects_untrusted_executor_before_execution() -> None:
    client = FakeClient(None)
    client.plan = {
        "plan_code": "MT-PLAN-20260709-000001",
        "operations": [{"operation_type": "replace_layer_asset", "slot_code": "MT-SLOT-1"}],
    }
    executor = GuardIgnoringExecutor()
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1", dry_run=True),
        client=client,
        executor=executor,
    )

    try:
        worker.run_plan_once("MT-PLAN-20260709-000001")
    except RuntimeError as exc:
        assert "dry-run" in str(exc).lower()
    else:
        raise AssertionError("untrusted dry-run executor was not rejected")
    assert executor.called is False


def test_successful_executor_heartbeats_and_writes_owned_idempotent_result() -> None:
    client = FakeClient(sample_bundle())
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor(asset_client=client)[0])

    assert worker.run_once() is True
    assert client.releases == []
    assert client.heartbeats[0] == (
        "MT-RETRY-20260708-000001",
        {
            "claimed_by": "worker-1",
            "claim_token": "c1a1d000-0000-4000-8000-000000000001",
            "lease_version": 3,
            "lock_ttl_seconds": 900,
        },
    )
    retry_task_code, payload = client.results[0]
    assert retry_task_code == "MT-RETRY-20260708-000001"
    assert payload["retry_execution_status"] == "succeeded"
    assert payload["screenshot_asset_code"] is None
    assert payload["claimed_by"] == "worker-1"
    assert payload["claim_token"] == "c1a1d000-0000-4000-8000-000000000001"
    assert payload["lease_version"] == 3
    UUID(payload["retry_execution_id"])


def test_worker_retries_uncertain_result_write_with_same_execution_id() -> None:
    client = FakeClient(sample_bundle())
    client.result_failures_remaining = 1
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert len(client.result_attempts) == 2
    assert len(client.results) == 1
    assert client.result_attempts[0][1]["retry_execution_id"] == client.result_attempts[1][1]["retry_execution_id"]


def test_worker_persists_recoverable_release_idempotently_with_execution_receipt() -> None:
    client = FakeClient(sample_bundle())
    client.begin_failures_remaining = 3
    client.result_failures_remaining = 1
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert client.releases == []
    assert len(client.result_attempts) == 2
    assert len(client.results) == 1
    assert client.result_attempts[0][1]["retry_execution_status"] == "released"
    assert client.result_attempts[0][1]["retry_execution_id"] == client.result_attempts[1][1]["retry_execution_id"]


def test_worker_caps_result_retry_budget_below_lease_ttl() -> None:
    client = FakeClient(sample_bundle())
    client.result_failures_remaining = 2
    lease_ttl_seconds = 60
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=lease_ttl_seconds,
            lease_heartbeat_interval_seconds=0.01,
        ),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert len(client.result_request_timeouts) == 3
    assert all(timeout is not None for timeout in client.result_request_timeouts)
    assert sum(timeout or 0 for timeout in client.result_request_timeouts) + 0.3 < lease_ttl_seconds
    assert len(client.results) == 1


def test_worker_keeps_heartbeat_running_until_result_is_confirmed() -> None:
    client = FakeClient(sample_bundle())
    client.block_result_until_heartbeat = True
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=60,
            lease_heartbeat_interval_seconds=0.01,
        ),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert client.result_request_started.is_set()
    assert len(client.heartbeats) >= 2
    assert len(client.results) == 1


def test_worker_keeps_heartbeat_running_until_recoverable_release_receipt_is_confirmed() -> None:
    client = FakeClient(sample_bundle())
    client.begin_failures_remaining = 3
    client.block_result_until_heartbeat = True
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=60,
            lease_heartbeat_interval_seconds=0.01,
        ),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert client.result_request_started.is_set()
    assert len(client.heartbeats) >= 2
    assert len(client.results) == 1
    assert client.results[0][1]["retry_execution_status"] == "released"


def test_worker_sends_periodic_heartbeat_during_long_execution() -> None:
    client = FakeClient(sample_bundle())
    client.block_begin_until_heartbeat = True
    config = WorkerConfig(
        api_base_url="http://assetgraph",
        worker_id="worker-1",
        lock_ttl_seconds=60,
        lease_heartbeat_interval_seconds=0.01,
    )
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor(asset_client=client)[0])

    assert worker.run_once() is True
    assert len(client.heartbeats) >= 2
    assert len(client.results) == 1


def test_worker_recovers_transient_periodic_heartbeat_before_writeback() -> None:
    client = FakeClient(sample_bundle())
    client.block_begin_until_heartbeat = True
    client.fail_next_periodic_heartbeat = True
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=60,
            lease_heartbeat_interval_seconds=0.01,
        ),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert client.heartbeat_calls >= 3
    assert len(client.results) == 1


def test_worker_refuses_writeback_when_periodic_heartbeat_cannot_be_revalidated() -> None:
    client = FakeClient(sample_bundle())
    client.block_begin_until_heartbeat = True
    client.fail_next_periodic_heartbeat = True
    client.fail_heartbeats_after_periodic_failure = True
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=60,
            lease_heartbeat_interval_seconds=0.01,
        ),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    assert worker.run_once() is True
    assert client.heartbeat_calls >= 3
    assert client.results == []
    assert client.releases == []


def test_worker_rejects_executor_call_timeout_that_can_outlive_lease() -> None:
    client = FakeClient(sample_bundle())
    executor, session = make_executor(asset_client=client, timeout_seconds=60.0)
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=60,
        ),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


def test_worker_synchronously_renews_lease_at_executor_guard_boundaries() -> None:
    client = FakeClient(sample_bundle())
    executor, _session = make_executor(asset_client=client)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is True
    assert client.heartbeat_calls >= 4
    assert len(client.results) == 1


def test_worker_does_not_execute_when_initial_heartbeat_loses_lease() -> None:
    client = FakeClient(sample_bundle())
    client.fail_heartbeat = True
    executor, session = make_executor(asset_client=client)
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=executor)

    assert worker.run_once() is True
    assert client.checkpoint_begins == []
    assert client.results == []
    assert client.releases == []


def test_lease_bound_checkpoint_controller_retries_with_stable_attempt_and_completion_ids() -> None:
    client = FakeClient(None)
    client.begin_decisions = ["execute"]
    client.begin_failures_remaining = 2
    client.complete_failures_remaining = 2
    lease = runner_module.RetryLease(
        retry_task_code="MT-RETRY-20260708-000001",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=3,
    )
    controller = runner_module.LeaseBoundOperationCheckpointController(
        client=client,
        lease=lease,
        renew_lease=lambda: client.heartbeat_retry_task(
            lease.retry_task_code,
            **lease.ownership_payload(),
            lock_ttl_seconds=60,
        ),
        request_timeout_seconds=1.0,
    )
    checkpoint_operation = {
        "operation_key": "replace-layer-01",
        "operation_fingerprint": "a" * 64,
    }

    assert controller.begin(checkpoint_operation) == "execute"
    controller.complete(
        checkpoint_operation,
        result_summary="verified replacement",
        evidence={"verified": True},
    )

    assert len(client.checkpoint_begins) == 3
    assert len({call[2]["attempt_id"] for call in client.checkpoint_begins}) == 1
    assert len(client.checkpoint_completes) == 3
    assert len({call[2]["attempt_id"] for call in client.checkpoint_completes}) == 1
    assert len({call[2]["completion_id"] for call in client.checkpoint_completes}) == 1
    assert client.checkpoint_begins[0][2]["attempt_id"] == client.checkpoint_completes[0][2]["attempt_id"]
    assert client.heartbeat_calls == 6


def test_worker_checkpoint_conflict_is_manual_without_retry_or_mutation() -> None:
    client = FakeClient(sample_bundle())
    client.begin_conflict = True
    executor, session = make_executor(asset_client=client)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is True
    assert len(client.checkpoint_begins) == 1
    assert client.results[0][1]["retry_execution_status"] == "manual_required"
    assert "checkpoint conflict" in (client.results[0][1]["error_message"] or "")


def test_worker_checkpoint_begin_exhaustion_causes_zero_mutation_and_released_result() -> None:
    client = FakeClient(sample_bundle())
    client.begin_failures_remaining = 3
    executor, session = make_executor(asset_client=client)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is True
    assert len(client.checkpoint_begins) == 3
    assert client.checkpoint_completes == []
    assert client.results[0][1]["retry_execution_status"] == "released"
    assert executor.checkpoint_controller is None


def test_checkpoint_complete_exhaustion_is_recoverable_and_bounded() -> None:
    client = FakeClient(None)
    client.begin_decisions = ["execute"]
    client.complete_failures_remaining = 3
    lease = runner_module.RetryLease(
        retry_task_code="MT-RETRY-20260708-000001",
        claimed_by="worker-1",
        claim_token="c1a1d000-0000-4000-8000-000000000001",
        lease_version=3,
    )
    controller = runner_module.LeaseBoundOperationCheckpointController(
        client=client,
        lease=lease,
        renew_lease=lambda: client.heartbeat_retry_task(
            lease.retry_task_code,
            **lease.ownership_payload(),
            lock_ttl_seconds=60,
        ),
        request_timeout_seconds=1.0,
    )
    operation = {"operation_key": "replace-layer-01", "operation_fingerprint": "a" * 64}

    assert controller.begin(operation) == "execute"
    with pytest.raises(MaituBrowserExecutionError, match="complete remained uncertain") as error:
        controller.complete(
            operation,
            result_summary="verified replacement",
            evidence={"verified": True},
        )

    assert error.value.retryable is True
    assert len(client.checkpoint_completes) == 3


def test_worker_rejects_preinstalled_checkpoint_controller_before_claim() -> None:
    client = FakeClient(sample_bundle())
    executor, session = make_executor(asset_client=client)
    executor.set_checkpoint_controller(SimpleNamespace(retry_task_code="attacker"))
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []


def test_manual_executor_writes_manual_required_owned_result() -> None:
    bundle = sample_bundle()
    bundle["operation_plan"]["operations"] = [
        {
            "operation_type": "manual_retry_required",
            "instruction": "login manually",
            "operation_key": "manual-login-01",
            "operation_fingerprint": "c" * 64,
            "status": "ready",
        }
    ]
    client = FakeClient(bundle)
    client.begin_decisions = ["execute"]
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor(asset_client=client)[0])

    assert worker.run_once() is True
    retry_task_code, payload = client.results[0]
    assert retry_task_code == "MT-RETRY-20260708-000001"
    assert payload["retry_execution_status"] == "manual_required"
    assert payload["error_message"] == "login manually"
    assert payload["retry_instruction"] == "login manually"
    assert payload["claimed_by"] == "worker-1"
    assert payload["lease_version"] == 3
    UUID(payload["retry_execution_id"])


def test_worker_rejects_claim_bundle_without_lease_identity() -> None:
    bundle = sample_bundle()
    bundle["retry_task"].pop("claim_token")
    client = FakeClient(bundle)
    executor, session = make_executor(asset_client=client)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is True
    assert client.heartbeats == []
    assert client.results == []


def test_worker_rejects_trusted_executor_with_untrusted_session_before_claim() -> None:
    client = FakeClient(sample_bundle())
    session = WorkerMaituSession()
    executor = MaituBrowserUseExecutor(asset_client=WorkerAssetClient(), session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


def test_worker_rejects_exact_session_with_injected_runner_before_claim() -> None:
    client = FakeClient(sample_bundle())
    session = BrowserUseCliSession(
        config=BrowserUseCliSessionConfig(timeout_seconds=1.0),
        runner=lambda *_args, **_kwargs: "",
    )
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []


def test_worker_rejects_spoofed_bound_method_runner_before_claim() -> None:
    client = FakeClient(sample_bundle())
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))

    class SpoofedRunner:
        __self__ = session
        __func__ = BrowserUseCliSession._run_command

        def __call__(self, *_args: Any, **_kwargs: Any) -> str:
            return ""

    session._runner = SpoofedRunner()
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []


def test_worker_rejects_class_replaced_executor_method_before_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(sample_bundle())

    def injected_execute(
        _executor: MaituBrowserUseExecutor,
        _operation_plan: dict[str, Any],
    ) -> OperationExecutionResult:
        return OperationExecutionResult(status="succeeded", summary="injected")

    monkeypatch.setattr(MaituBrowserUseExecutor, "execute_operation_plan", injected_execute)
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []


def test_worker_rejects_class_replaced_execution_guard_before_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(sample_bundle())

    def injected_guard(_executor: MaituBrowserUseExecutor) -> None:
        return None

    monkeypatch.setattr(MaituBrowserUseExecutor, "_require_execution_guard", injected_guard)
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []


def test_worker_rejects_class_replaced_session_runner_before_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(sample_bundle())

    def injected_runner(_session: BrowserUseCliSession, _command: Any) -> str:
        return ""

    monkeypatch.setattr(BrowserUseCliSession, "_run_command", injected_runner)
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []


def test_session_constructor_does_not_execute_replaced_runner_descriptor_before_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(sample_bundle())
    descriptor_executions: list[str] = []

    class SideEffectDescriptor:
        def __get__(self, _instance: Any, _owner: type[Any]) -> Any:
            descriptor_executions.append("executed")
            return lambda *_args, **_kwargs: ""

    monkeypatch.setattr(BrowserUseCliSession, "_run_command", SideEffectDescriptor())
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert descriptor_executions == []
    assert worker.run_once() is False
    assert descriptor_executions == []
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []


@pytest.mark.parametrize(
    "method_name",
    [
        "ensure_ready",
        "recover_login",
        "upload_asset",
        "replace_layer_asset",
        "save_project",
        "capture_screenshot",
        "execute_generic_operation",
        "_call_browser_use",
    ],
)
def test_exact_session_methods_cannot_be_injected(method_name: str) -> None:
    client = FakeClient(sample_bundle())
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    assert not hasattr(session, "__dict__")

    def injected(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"verified": True}

    with pytest.raises(AttributeError):
        setattr(session, method_name, MethodType(injected, session))
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


def test_worker_rejects_executor_with_different_asset_client_before_claim() -> None:
    client = FakeClient(sample_bundle())
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    executor = MaituBrowserUseExecutor(asset_client=WorkerAssetClient(), session=session)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


@pytest.mark.parametrize(
    "method_name",
    ["execute_operation_plan", "set_execution_guard", "set_checkpoint_controller", "_execute_operation"],
)
def test_exact_executor_methods_cannot_be_injected(method_name: str) -> None:
    client = FakeClient(sample_bundle())
    session = BrowserUseCliSession(config=BrowserUseCliSessionConfig(timeout_seconds=1.0))
    executor = MaituBrowserUseExecutor(asset_client=client, session=session)

    def injected(*_args: Any, **_kwargs: Any) -> OperationExecutionResult:
        return OperationExecutionResult(status="succeeded", summary="injected")

    with pytest.raises(AttributeError):
        setattr(executor, method_name, MethodType(injected, executor))


def test_worker_rejects_guard_ignoring_executor_before_claim() -> None:
    client = FakeClient(sample_bundle())
    executor = GuardIgnoringExecutor()
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert executor.called is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


def test_dry_run_queue_worker_refuses_untrusted_executor_before_claim() -> None:
    client = FakeClient(sample_bundle())
    executor = GuardIgnoringExecutor()
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1", dry_run=True),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is False
    assert executor.called is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


def test_run_forever_isolates_transient_task_failure_and_keeps_polling(monkeypatch) -> None:
    class FailingClaimClient(FakeClient):
        def claim_next_retry_task(self, payload: dict[str, Any]) -> dict[str, Any] | None:
            self.claim_payloads.append(payload)
            raise RuntimeError("temporary queue transport failure")

    client = FailingClaimClient(None)
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=make_executor(asset_client=client)[0],
    )

    def stop_after_retry(_seconds: float) -> None:
        raise StopIteration

    monkeypatch.setattr("browser_use_worker.runner.time.sleep", stop_after_retry)
    with pytest.raises(StopIteration):
        worker.run_forever()
    assert len(client.claim_payloads) == 1


def test_worker_returns_false_when_no_task() -> None:
    client = FakeClient(None)
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor(asset_client=client)[0])

    assert worker.run_once() is False
    assert client.releases == []
    assert client.results == []
