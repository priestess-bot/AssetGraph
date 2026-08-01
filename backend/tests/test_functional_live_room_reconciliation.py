from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from app.api.routes import functional_live_rooms
from app.main import app
from app.services.functional_live_rooms import FunctionalLiveRoomService


class _ReconciliationWorkbench:
    def __init__(self) -> None:
        self.job = {
            "execution_job_code": "MT-WB-EXEC-RECOVERY-001",
            "source_kind": "functional_live_room_plan",
            "status": "reconcile_required",
            "stage": "reconcile_required",
            "progress_current": 2,
            "progress_total": 5,
            "stage_events": [{"stage": "reconcile_required", "message": "需要核对"}],
            "result": {},
            "error_code": "ROOM_WRITE_UNCERTAIN",
            "error_message": "写入结果无法安全确认",
        }

    def get_functional_draft_execution_job(self, plan_code: str) -> dict:
        assert plan_code == "LIVEPLAN-RECOVERY-001"
        return deepcopy(self.job)

    def acknowledge_draft_reconciliation(
        self,
        execution_job_code: str,
        *,
        acknowledged_by: str,
        note: str,
    ) -> dict:
        assert execution_job_code == self.job["execution_job_code"]
        assert acknowledged_by == "operator-001"
        assert note == "已核对现场，关闭旧任务。"
        self.job.update(
            {
                "status": "cancelled",
                "stage": "reconciled",
                "result": {
                    "reconciliation": {
                        "status": "acknowledged_and_closed",
                        "replay_allowed": False,
                    }
                },
            }
        )
        self.job["stage_events"] = [
            *self.job["stage_events"],
            {"stage": "reconciled", "message": note, "acknowledged_by": acknowledged_by},
        ]
        return deepcopy(self.job)


def test_service_acknowledgement_projects_closed_job_without_claiming_success() -> None:
    service = object.__new__(FunctionalLiveRoomService)
    service.workbench = _ReconciliationWorkbench()
    service.get_plan = lambda plan_code: {"plan_code": plan_code}  # type: ignore[method-assign]

    execution = service.acknowledge_execution_reconciliation(
        "LIVEPLAN-RECOVERY-001",
        acknowledged_by="operator-001",
        note="已核对现场，关闭旧任务。",
    )

    assert execution is not None
    assert execution["status"] == "cancelled"
    assert execution["stage"] == "reconciled"
    assert execution["ready_for_go_live"] is False
    assert execution["retryable"] is False
    assert execution["result"]["reconciliation"]["replay_allowed"] is False
    assert execution["stage_events"][-1]["stage"] == "reconciled"


def test_reconcile_api_returns_cancelled_reconciled_execution() -> None:
    class _RouteService:
        def acknowledge_execution_reconciliation(
            self,
            plan_code: str,
            *,
            acknowledged_by: str,
            note: str,
        ) -> dict:
            assert plan_code == "LIVEPLAN-RECOVERY-001"
            assert acknowledged_by == "operator-001"
            assert note == "已核对现场，关闭旧任务。"
            return {
                "plan_code": plan_code,
                "execution_job_code": "MT-WB-EXEC-RECOVERY-001",
                "status": "cancelled",
                "stage": "reconciled",
                "progress_current": 2,
                "progress_total": 5,
                "stage_events": [
                    {
                        "stage": "reconciled",
                        "message": note,
                        "acknowledged_by": acknowledged_by,
                    }
                ],
                "retryable": False,
                "result": {
                    "reconciliation": {
                        "status": "acknowledged_and_closed",
                        "replay_allowed": False,
                    }
                },
                "error": None,
                "ready_for_go_live": False,
            }

    app.dependency_overrides[functional_live_rooms.get_service] = _RouteService
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/functional-live-room-plans/LIVEPLAN-RECOVERY-001/execution/reconcile",
                json={
                    "acknowledged_by": "operator-001",
                    "note": "已核对现场，关闭旧任务。",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["stage"] == "reconciled"
    assert response.json()["result"]["reconciliation"]["replay_allowed"] is False
