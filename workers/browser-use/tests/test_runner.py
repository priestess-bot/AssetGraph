from __future__ import annotations

import threading
from types import MethodType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from browser_use_worker.browser_cli_session import BrowserUseCliSession, BrowserUseCliSessionConfig
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
    timeout_seconds: float = 1.0,
    wait_event: threading.Event | None = None,
    recoverable_error: bool = False,
) -> tuple[MaituBrowserUseExecutor, BrowserUseCliSession]:
    session = BrowserUseCliSession(
        config=BrowserUseCliSessionConfig(timeout_seconds=timeout_seconds),
    )
    session.called = False

    def mark_called(_session: BrowserUseCliSession, *_args: Any, **_kwargs: Any) -> None:
        _session.called = True

    def replace_layer_asset(
        _session: BrowserUseCliSession,
        _operation: dict[str, Any],
        _asset: dict[str, Any],
    ) -> None:
        _session.called = True
        if wait_event is not None:
            assert wait_event.wait(timeout=1.0), "periodic lease heartbeat was not observed"
        if recoverable_error:
            raise MaituBrowserExecutionError("temporary browser failure", retryable=True)

    def capture_screenshot(_session: BrowserUseCliSession, *, label: str) -> str | None:
        return "AG-IMG-1"

    session.ensure_ready = MethodType(mark_called, session)
    session.recover_login = MethodType(mark_called, session)
    session.upload_asset = MethodType(mark_called, session)
    session.replace_layer_asset = MethodType(replace_layer_asset, session)
    session.save_project = MethodType(mark_called, session)
    session.capture_screenshot = MethodType(capture_screenshot, session)
    session.execute_generic_operation = MethodType(mark_called, session)
    return MaituBrowserUseExecutor(asset_client=WorkerAssetClient(), session=session), session


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
                {"operation_type": "retry_replace_layer_asset", "asset_code": "AG-IMG-1"}
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
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor()[0])

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
    assert payload["screenshot_asset_code"] == "AG-IMG-1"
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
        executor=make_executor()[0],
    )

    assert worker.run_once() is True
    assert len(client.result_attempts) == 2
    assert len(client.results) == 1
    assert client.result_attempts[0][1]["retry_execution_id"] == client.result_attempts[1][1]["retry_execution_id"]


def test_worker_persists_recoverable_release_idempotently_with_execution_receipt() -> None:
    client = FakeClient(sample_bundle())
    client.result_failures_remaining = 1
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=make_executor(recoverable_error=True)[0],
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
        executor=make_executor()[0],
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
        executor=make_executor()[0],
    )

    assert worker.run_once() is True
    assert client.result_request_started.is_set()
    assert len(client.heartbeats) >= 2
    assert len(client.results) == 1


def test_worker_keeps_heartbeat_running_until_recoverable_release_receipt_is_confirmed() -> None:
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
        executor=make_executor(recoverable_error=True)[0],
    )

    assert worker.run_once() is True
    assert client.result_request_started.is_set()
    assert len(client.heartbeats) >= 2
    assert len(client.results) == 1
    assert client.results[0][1]["retry_execution_status"] == "released"


def test_worker_sends_periodic_heartbeat_during_long_execution() -> None:
    client = FakeClient(sample_bundle())
    config = WorkerConfig(
        api_base_url="http://assetgraph",
        worker_id="worker-1",
        lock_ttl_seconds=60,
        lease_heartbeat_interval_seconds=0.01,
    )
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor(wait_event=client.heartbeat_event)[0])

    assert worker.run_once() is True
    assert len(client.heartbeats) >= 2
    assert len(client.results) == 1


def test_worker_recovers_transient_periodic_heartbeat_before_writeback() -> None:
    client = FakeClient(sample_bundle())
    client.fail_next_periodic_heartbeat = True
    worker = BrowserUseWorker(
        config=WorkerConfig(
            api_base_url="http://assetgraph",
            worker_id="worker-1",
            lock_ttl_seconds=60,
            lease_heartbeat_interval_seconds=0.01,
        ),
        client=client,
        executor=make_executor(wait_event=client.heartbeat_attempt_event)[0],
    )

    assert worker.run_once() is True
    assert client.heartbeat_calls >= 3
    assert len(client.results) == 1


def test_worker_refuses_writeback_when_periodic_heartbeat_cannot_be_revalidated() -> None:
    client = FakeClient(sample_bundle())
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
        executor=make_executor(wait_event=client.heartbeat_attempt_event)[0],
    )

    assert worker.run_once() is True
    assert client.heartbeat_calls >= 3
    assert client.results == []
    assert client.releases == []


def test_worker_rejects_executor_call_timeout_that_can_outlive_lease() -> None:
    client = FakeClient(sample_bundle())
    executor, session = make_executor(timeout_seconds=60.0)
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
    assert session.called is False
    assert client.claim_payloads == []
    assert client.heartbeats == []
    assert client.results == []
    assert client.releases == []


def test_worker_synchronously_renews_lease_at_executor_guard_boundaries() -> None:
    client = FakeClient(sample_bundle())
    executor, _session = make_executor()
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
    executor, session = make_executor()
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=executor)

    assert worker.run_once() is True
    assert session.called is False
    assert client.results == []
    assert client.releases == []


def test_manual_executor_writes_manual_required_owned_result() -> None:
    bundle = sample_bundle()
    bundle["operation_plan"]["operations"] = [
        {"operation_type": "manual_retry_required", "instruction": "login manually"}
    ]
    client = FakeClient(bundle)
    config = WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1")
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor()[0])

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
    executor, session = make_executor()
    worker = BrowserUseWorker(
        config=WorkerConfig(api_base_url="http://assetgraph", worker_id="worker-1"),
        client=client,
        executor=executor,
    )

    assert worker.run_once() is True
    assert session.called is False
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
    assert session.called is False
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
        executor=make_executor()[0],
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
    worker = BrowserUseWorker(config=config, client=client, executor=make_executor()[0])

    assert worker.run_once() is False
    assert client.releases == []
    assert client.results == []
