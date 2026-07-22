from __future__ import annotations

import threading

import pytest

from browser_use_worker.workbench_draft_lease import (
    WorkbenchDraftLeaseError,
    WorkbenchDraftLeaseHeartbeat,
)


LEASE_TOKEN = "11111111-1111-4111-8111-111111111111"


class FakeClient:
    timeout_seconds = 0.1

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.periodic = threading.Event()
        self.fail_periodic = False

    def heartbeat_workbench_draft_execution(
        self,
        execution_job_code: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append((execution_job_code, payload))
        if threading.current_thread().name.startswith("workbench-draft-heartbeat-"):
            self.periodic.set()
            if self.fail_periodic:
                raise RuntimeError("lease lost")
        return {"status": "running"}


def test_draft_heartbeat_covers_long_work_and_validates_before_writeback() -> None:
    client = FakeClient()
    heartbeat = WorkbenchDraftLeaseHeartbeat(
        client=client,
        execution_job_code="MT-WB-EXEC-001",
        lease_token=LEASE_TOKEN,
        lease_seconds=30,
        configured_interval_seconds=0.001,
    )

    heartbeat.start()
    assert client.periodic.wait(timeout=0.2)
    assert heartbeat.ensure_active() is True
    heartbeat.stop_for_writeback()

    assert len(client.calls) >= 3  # initial, periodic, final validation
    assert all(call[1] == {"lease_token": LEASE_TOKEN, "lease_seconds": 30} for call in client.calls)
    assert heartbeat.interval_seconds <= 10


def test_any_periodic_heartbeat_failure_permanently_fences_completion() -> None:
    client = FakeClient()
    client.fail_periodic = True
    heartbeat = WorkbenchDraftLeaseHeartbeat(
        client=client,
        execution_job_code="MT-WB-EXEC-002",
        lease_token=LEASE_TOKEN,
        lease_seconds=30,
        configured_interval_seconds=0.001,
    )

    heartbeat.start()
    assert client.periodic.wait(timeout=0.2)
    with pytest.raises(WorkbenchDraftLeaseError, match="lease lost"):
        heartbeat.ensure_active()
    with pytest.raises(WorkbenchDraftLeaseError, match="lease lost"):
        heartbeat.stop_for_writeback()


def test_heartbeat_interval_is_clamped_to_one_third_of_the_lease() -> None:
    heartbeat = WorkbenchDraftLeaseHeartbeat(
        client=FakeClient(),
        execution_job_code="MT-WB-EXEC-003",
        lease_token=LEASE_TOKEN,
        lease_seconds=90,
        configured_interval_seconds=1000,
    )

    assert heartbeat.interval_seconds == 30
