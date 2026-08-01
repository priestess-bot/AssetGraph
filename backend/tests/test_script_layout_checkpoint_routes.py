from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.routes.maitu import (
    _public_execution_result,
    get_maitu_authority_verifier,
    get_maitu_slot_repository,
    require_maitu_reconciliation_operator,
    require_maitu_script_layout_worker,
    reject_script_layout_worker_secret,
    router,
)

RUN_ATTEMPT = "44444444-4444-4444-8444-444444444444"
LEASE_TOKEN = "55555555-5555-4555-8555-555555555555"


class CheckpointAuthorityVerifier:
    calls: list[str] = []

    @staticmethod
    def _attest(payload: dict[str, Any]) -> dict[str, Any]:
        evidence = {
            **payload["evidence"],
            "backend_authority_observation": {"live_room_id": "47000002"},
            "readback_attestation_algorithm": "hmac-sha256-v1",
            "readback_attestation": "a" * 64,
        }
        return {**payload, "evidence": evidence}

    def attest_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("external")
        return self._attest(kwargs["payload"])

    def attest_functional_worker_observed_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("worker_observed_test_only")
        return self._attest(kwargs["payload"])

    def attest_reconciliation(self, **kwargs: Any) -> dict[str, Any]:
        return self._attest(kwargs["payload"])


class CheckpointRouteRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.worker_observed_test_context: dict[str, Any] | None = None

    @staticmethod
    def checkpoint(state: str, decision: str) -> dict[str, Any]:
        return {
            "id": "33333333-3333-4333-8333-333333333333",
            "operation_index": 0,
            "operation_type": "create_scene",
            "operation_name": "新建场景：促单",
            "scene_name": "促单",
            "action_type": "create_draft_scene",
            "status": "completed" if state == "completed" else state,
            "retryable": False,
            "details": {},
            "sort_order": 0,
            "operation_fingerprint": "b" * 64,
            "effect_class": "mutating",
            "intent_snapshot": {"operation_type": "create_scene", "scene_name": "促单"},
            "checkpoint_state": state,
            "decision": decision,
            "attempt_id": RUN_ATTEMPT,
            "completion_id": "66666666-6666-4666-8666-666666666666" if state == "completed" else None,
            "completion_evidence": {"verified": True, "operation_applied": True} if state == "completed" else {},
            "reconciliation_evidence": {},
        }

    @classmethod
    def execution(cls, execution_status: str = "in_progress") -> dict[str, Any]:
        return {
            "id": "11111111-1111-4111-8111-111111111111",
            "execution_code": "MT-EXEC-20260712-000001",
            "build_plan_code": "MT-BUILD-20260712-000001",
            "blueprint_code": None,
            "execution_attempt_id": "22222222-2222-4222-8222-222222222222",
            "start_request_id": "77777777-7777-4777-8777-777777777777",
            "run_attempt_id": RUN_ATTEMPT,
            "plan_fingerprint": "a" * 64,
            "manifest_fingerprint": "c" * 64,
            "expected_operation_count": 1,
            "checkpoint_contract": "script_layout_checkpoint_v1",
            "lease_owner": "checkpoint-route-worker",
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "executor": "browser_use",
            "execution_status": execution_status,
            "mode": "script_layout_draft",
            "ready_for_go_live": False,
            "manual_review_required": execution_status == "completed_with_manual_review",
            "details": {},
            "operation_results": [cls.checkpoint("not_started", "execute")],
        }

    def start_script_layout_execution(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start", (build_plan_code, payload)))
        return self.execution()

    @staticmethod
    def get_live_room_build_plan_operations(build_plan_code: str) -> dict[str, Any]:
        return {
            "build_plan_code": build_plan_code,
            "target_live_room_id": "47000002",
            "checkpoint_source_fingerprint": "d" * 64,
            "operations": [
                {
                    "operation_type": "preflight_content_build_plan",
                    "operation_name": "只读预检",
                    "sort_order": 0,
                    "status": "ready",
                    "target_live_room_id": "47000002",
                    "instruction": "只读预检目标草稿",
                }
            ],
        }

    def renew_script_layout_execution(
        self, build_plan_code: str, execution_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("renew", (build_plan_code, execution_code, payload)))
        return self.execution()

    def begin_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("begin", (build_plan_code, execution_code, operation_index, payload)))
        return self.checkpoint("prepared", "execute")

    def dispatch_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("dispatch", (build_plan_code, execution_code, operation_index, payload)))
        return self.checkpoint("dispatched", "execute")

    def complete_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("complete", (build_plan_code, execution_code, operation_index, payload)))
        return self.checkpoint("completed", "skip")

    def reconcile_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("reconcile", (build_plan_code, execution_code, operation_index, payload)))
        return self.checkpoint("retry_authorized", "execute")

    def finalize_script_layout_execution(
        self, build_plan_code: str, execution_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("finalize", (build_plan_code, execution_code, payload)))
        return self.execution(payload["execution_status"])

    def list_live_room_build_plan_execution_results(self, *_args, **_kwargs) -> list[dict[str, Any]]:
        return [self.execution()]

    def get_live_room_build_plan_execution_result_by_code(self, *_args) -> dict[str, Any]:
        return self.execution()

    def get_functional_worker_readback_completion_context(self, **_kwargs: Any) -> dict[str, Any] | None:
        return self.worker_observed_test_context


def checkpoint_client() -> tuple[TestClient, CheckpointRouteRepository]:
    repository = CheckpointRouteRepository()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_maitu_slot_repository] = lambda: repository
    app.dependency_overrides[require_maitu_reconciliation_operator] = lambda: "checkpoint-route-operator"
    app.dependency_overrides[require_maitu_script_layout_worker] = lambda: "checkpoint-route-worker"
    app.dependency_overrides[get_maitu_authority_verifier] = CheckpointAuthorityVerifier
    return TestClient(app), repository


def test_completion_authority_is_selected_before_verification_without_failure_fallback() -> None:
    client, repository = checkpoint_client()
    CheckpointAuthorityVerifier.calls.clear()
    repository.worker_observed_test_context = {
        "execution_job_code": "MT-WB-EXEC-20260731-000006",
        "worker_id": "checkpoint-route-worker",
        "target_live_room_id": "41172",
        "expected_title": "asser测试",
        "source_plan_fingerprint": "d" * 64,
    }
    base = (
        "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/"
        "script-layout-executions/MT-EXEC-20260712-000001/operations/0/complete"
    )
    response = client.post(
        base,
        json={
            "operation_fingerprint": "b" * 64,
            "attempt_id": RUN_ATTEMPT,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "completion_id": "66666666-6666-4666-8666-666666666666",
            "result_summary": "scene created and read back",
            "evidence": {
                "verified": True,
                "operation_applied": True,
                "operation_index": 0,
                "operation_type": "create_scene",
                "operation_fingerprint": "b" * 64,
                "target_live_room_id": "47000002",
                "clip_id": 416426,
            },
            "operation_result": {
                "operation_index": 0,
                "operation_type": "create_scene",
                "status": "completed",
                "clip_id": 416426,
            },
        },
    )

    assert response.status_code == 200, response.text
    assert CheckpointAuthorityVerifier.calls == ["worker_observed_test_only"]


def test_regular_completion_never_uses_worker_observed_test_authority() -> None:
    client, _repository = checkpoint_client()
    CheckpointAuthorityVerifier.calls.clear()
    base = (
        "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/"
        "script-layout-executions/MT-EXEC-20260712-000001/operations/0/complete"
    )
    response = client.post(
        base,
        json={
            "operation_fingerprint": "b" * 64,
            "attempt_id": RUN_ATTEMPT,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "completion_id": "66666666-6666-4666-8666-666666666666",
            "result_summary": "scene created and read back",
            "evidence": {
                "verified": True,
                "operation_applied": True,
                "operation_index": 0,
                "operation_type": "create_scene",
                "operation_fingerprint": "b" * 64,
                "target_live_room_id": "47000002",
                "clip_id": 416426,
            },
            "operation_result": {
                "operation_index": 0,
                "operation_type": "create_scene",
                "status": "completed",
                "clip_id": 416426,
            },
        },
    )

    assert response.status_code == 200, response.text
    assert CheckpointAuthorityVerifier.calls == ["external"]


def test_script_layout_route_secret_filter_accepts_public_script_hashes_only() -> None:
    reject_script_layout_worker_secret(
        {
            "evidence": {
                "script_sha256": "a" * 64,
                "expected_script_sha256": "a" * 64,
                "constraint_profile_ref": {"fingerprint": "b" * 64},
            }
        }
    )

    with pytest.raises(HTTPException, match="credentials"):
        reject_script_layout_worker_secret({"evidence": {"access_token": "not-durable"}})


def test_public_execution_result_preserves_legacy_details_contract() -> None:
    legacy = CheckpointRouteRepository.execution()
    legacy["checkpoint_contract"] = None
    legacy["details"] = {"legacy": True}
    legacy["operation_results"][0]["id"] = "legacy-operation-id"
    legacy["operation_results"][0]["details"] = {"saved": True}

    public = _public_execution_result(legacy)

    assert public["details"] == {"legacy": True}
    assert public["operation_results"][0]["id"] == "legacy-operation-id"
    assert public["operation_results"][0]["details"] == {"saved": True}


def test_browser_use_operation_plan_does_not_inject_absent_manifest_defaults() -> None:
    client, _repository = checkpoint_client()

    response = client.get(
        "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/browser-use-operations"
    )

    assert response.status_code == 200
    operation = response.json()["operations"][0]
    assert "accepted_asset_types" not in operation
    assert "match_reasons" not in operation
    assert "details" not in operation


def test_script_layout_checkpoint_routes_preserve_fence_dispatch_and_operator_audit() -> None:
    client, repository = checkpoint_client()
    base = "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/script-layout-executions"
    start = client.post(
        f"{base}/start",
        json={
            "start_request_id": "77777777-7777-4777-8777-777777777777",
            "run_attempt_id": RUN_ATTEMPT,
            "source_plan_fingerprint": "d" * 64,
            "target_live_room_id": "47000002",
            "operations": [
                {
                    "operation_index": 0,
                    "intent": {
                        "operation_type": "preflight_content_build_plan",
                        "status": "ready",
                        "target_live_room_id": "47000002",
                    },
                }
            ],
        },
    )
    assert start.status_code == 200
    assert start.json()["lease_version"] == 1
    assert start.json()["lease_token"] == LEASE_TOKEN

    operation_base = f"{base}/MT-EXEC-20260712-000001/operations/0"
    fence = {
        "operation_fingerprint": "b" * 64,
        "attempt_id": RUN_ATTEMPT,
        "lease_token": LEASE_TOKEN,
        "lease_version": 1,
    }
    begin = client.post(f"{operation_base}/begin", json=fence)
    assert begin.status_code == 200
    assert begin.json()["checkpoint_state"] == "prepared"
    dispatch = client.post(f"{operation_base}/dispatch", json=fence)
    assert dispatch.status_code == 200
    assert dispatch.json()["checkpoint_state"] == "dispatched"

    complete = client.post(
        f"{operation_base}/complete",
        json={
            **fence,
            "completion_id": "66666666-6666-4666-8666-666666666666",
            "result_summary": "scene created and read back",
            "evidence": {
                "verified": True,
                "operation_applied": True,
                "operation_index": 0,
                "operation_type": "create_scene",
                "operation_fingerprint": "b" * 64,
                "target_live_room_id": "47000002",
                "clip_id": 416426,
            },
            "operation_result": {
                "operation_index": 0,
                "operation_type": "create_scene",
                "status": "completed",
                "clip_id": 416426,
            },
        },
    )
    assert complete.status_code == 200, complete.text

    reconcile = client.post(
        f"{operation_base}/reconcile",
        json={
            "operation_fingerprint": "b" * 64,
            "reconciliation_id": "88888888-8888-4888-8888-888888888888",
            "reconciled_attempt_id": RUN_ATTEMPT,
            "resolution": "confirmed_not_applied",
            "resolution_summary": "room readback found no matching scene",
            "evidence": {"verified": True, "operation_applied": False},
        },
    )
    assert reconcile.status_code == 200
    reconcile_payload = next(call[1][3] for call in repository.calls if call[0] == "reconcile")
    assert reconcile_payload["reconciled_by"] == "checkpoint-route-operator"

    finalize = client.post(
        f"{base}/MT-EXEC-20260712-000001/finalize",
        json={
            "finalization_id": "99999999-9999-4999-8999-999999999999",
            "run_attempt_id": RUN_ATTEMPT,
            "lease_token": LEASE_TOKEN,
            "lease_version": 1,
            "execution_status": "completed_with_manual_review",
            "result_summary": "draft complete",
            "manual_review_required": True,
        },
    )
    assert finalize.status_code == 200
    assert finalize.json()["execution_status"] == "completed_with_manual_review"

    public_list = client.get(
        "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/execution-results"
    )
    assert public_list.status_code == 200
    assert "lease_token" not in public_list.json()[0]
    assert "run_attempt_id" not in public_list.json()[0]
    assert "start_request_id" not in public_list.json()[0]

    public_get = client.get(
        "/api/maitu/live-room-build-plans/MT-BUILD-20260712-000001/"
        "execution-results/MT-EXEC-20260712-000001"
    )
    assert public_get.status_code == 200
    assert "lease_token" not in public_get.json()
