from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.routes.maitu import (
    get_maitu_authority_verifier,
    get_maitu_slot_repository,
    require_maitu_reconciliation_operator,
    require_maitu_script_layout_worker,
    router,
)
from app.repositories import maitu as maitu_repository
from app.repositories.maitu import MaituMaterialSlotRepository

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
READBACK_ATTESTATION_KEY = "test-readback-attestation-key-32-bytes"


pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


class BackendAuthorityStub:
    @staticmethod
    def _signed_payload(attested: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        evidence = {
            **payload["evidence"],
            "backend_authority_observation": {"live_room_id": "47000002"},
        }
        unsigned_evidence = dict(evidence)
        attested = {**attested, "evidence": unsigned_evidence}
        signature = hmac.new(
            READBACK_ATTESTATION_KEY.encode("utf-8"),
            json.dumps(attested, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        evidence["readback_attestation_algorithm"] = "hmac-sha256-v1"
        evidence["readback_attestation"] = signature
        return {**payload, "evidence": evidence}

    def attest_completion(self, **kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        checkpoint = kwargs["checkpoint"]
        result = self._signed_payload(
            {
                "build_plan_code": kwargs["build_plan_code"],
                "execution_code": kwargs["execution_code"],
                "operation_index": kwargs["operation_index"],
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "attempt_id": str(payload["attempt_id"]),
                "lease_token": str(payload["lease_token"]),
                "lease_version": payload["lease_version"],
                "completion_id": str(payload["completion_id"]),
            },
            payload,
        )
        MaituMaterialSlotRepository._validate_completion_readback_attestation(
            build_plan_code=kwargs["build_plan_code"],
            execution_code=kwargs["execution_code"],
            operation_index=kwargs["operation_index"],
            checkpoint=checkpoint,
            payload=result,
        )
        return result

    def attest_reconciliation(self, **kwargs: Any) -> dict[str, Any]:
        payload = kwargs["payload"]
        checkpoint = kwargs["checkpoint"]
        return self._signed_payload(
            {
                "build_plan_code": kwargs["build_plan_code"],
                "execution_code": kwargs["execution_code"],
                "operation_index": kwargs["operation_index"],
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "reconciliation_id": str(payload["reconciliation_id"]),
                "reconciled_attempt_id": str(payload["reconciled_attempt_id"]),
                "resolution": payload["resolution"],
            },
            payload,
        )


class WorkerCheckpointHttpAdapter:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    @staticmethod
    def _json(response) -> dict[str, Any]:
        assert response.status_code == 200, response.text
        return response.json()

    def start_script_layout_execution(self, build_plan_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/start",
                json=payload,
            )
        )

    def renew_script_layout_execution(
        self, build_plan_code: str, execution_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{execution_code}/renew",
                json=payload,
            )
        )

    def begin_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{execution_code}/operations/{operation_index}/begin",
                json=payload,
            )
        )

    def dispatch_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{execution_code}/operations/{operation_index}/dispatch",
                json=payload,
            )
        )

    def invalidate_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{execution_code}/operations/{operation_index}/invalidate",
                json=payload,
            )
        )

    def complete_script_layout_execution_operation(
        self, build_plan_code: str, execution_code: str, operation_index: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{execution_code}/operations/{operation_index}/complete",
                json=payload,
            )
        )

    def finalize_script_layout_execution(
        self, build_plan_code: str, execution_code: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{execution_code}/finalize",
                json=payload,
            )
        )


class TrackingInMemorySession:
    def __init__(self) -> None:
        from browser_use_worker.script_layout_draft_executor import InMemoryScriptLayoutDraftSession

        self.delegate = InMemoryScriptLayoutDraftSession(live_room_id="47000002")
        self.rename_count = 0

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)

    def rename_clip(
        self,
        *,
        live_room_id: str,
        clip_id: int,
        name: str,
        expected_live_room_title: str | None = None,
    ) -> dict[str, Any]:
        self.rename_count += 1
        result = self.delegate.rename_clip(
            live_room_id=live_room_id,
            clip_id=clip_id,
            name=name,
            expected_live_room_title=expected_live_room_title,
        )
        return {**result, "verified": True, "verification_source": "working_room_readback"}


def test_api_db_worker_checkpoint_crash_reconcile_resume_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        maitu_repository.settings,
        "maitu_readback_attestation_key",
        SecretStr(READBACK_ATTESTATION_KEY),
    )
    from browser_use_worker.script_layout_checkpoint import AssetGraphScriptLayoutCheckpointStore
    from browser_use_worker.script_layout_draft_executor import (
        ScriptLayoutDraftActionResult,
        ScriptLayoutDraftRunner,
    )

    migration_root = Path(__file__).resolve().parents[1] / "migrations"
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute((migration_root / "020_script_driven_build_plan_persistence.sql").read_text(encoding="utf-8"))
            cursor.execute((migration_root / "021_script_layout_execution_checkpoints.sql").read_text(encoding="utf-8"))
        connection.commit()
        repository = MaituMaterialSlotRepository(connection)
        persisted = repository.create_script_layout_build_plan(
            {
                "source": "script_content_layout_build_plan_rule_v1",
                "status": "ready",
                "target_live_room_id": "47000002",
                "build_mode": "strict",
                "can_execute": True,
                "manual_review_required": False,
                "blocked_reasons": [],
                "operation_count": 3,
                "operations": [
                    {
                        "operation_type": "preflight_content_build_plan",
                        "operation_name": "草稿预检",
                        "sort_order": 1,
                        "status": "ready",
                        "target_live_room_id": "47000002",
                    },
                    {
                        "operation_type": "fill_default_scene",
                        "operation_name": "填充默认场景",
                        "sort_order": 2,
                        "status": "ready",
                        "scene_index": 0,
                        "scene_name": "开场",
                    },
                    {
                        "operation_type": "save_draft",
                        "operation_name": "人工保存门",
                        "sort_order": 3,
                        "status": "manual_review",
                    },
                ],
            },
            plan_name="Phase D API DB Worker E2E",
        )
        build_plan_code = persisted["build_plan_code"]
        try:
            operation_plan = repository.get_live_room_build_plan_operations(build_plan_code)
            assert operation_plan is not None
            app = FastAPI()
            app.include_router(router, prefix="/api")
            app.dependency_overrides[get_maitu_slot_repository] = lambda: repository
            app.dependency_overrides[require_maitu_reconciliation_operator] = lambda: "phase-d-e2e-operator"
            app.dependency_overrides[require_maitu_script_layout_worker] = lambda: "phase-d-e2e-worker"
            app.dependency_overrides[get_maitu_authority_verifier] = BackendAuthorityStub
            http = TestClient(app)
            adapter = WorkerCheckpointHttpAdapter(http)

            crashed = AssetGraphScriptLayoutCheckpointStore.start(
                client=adapter,
                operation_plan=operation_plan,
                target_live_room_id="47000002",
            )
            crashed.begin_operation(0, operation_plan["operations"][0])
            crashed.complete_operation(
                0,
                operation_plan["operations"][0],
                ScriptLayoutDraftActionResult(
                    operation_index=0,
                    operation_type="preflight_content_build_plan",
                    operation_name="草稿预检",
                    action_type="preflight_content_build_plan",
                    status="completed",
                    summary="working room preflight passed",
                    clip_id=1,
                    details={
                        "preflight_result": {
                            "verified": True,
                            "verification_source": "working_room_readback",
                            "live_room_id": "47000002",
                            "environment": "working",
                            "not_live": True,
                            "default_clip_id": 1,
                        }
                    },
                ),
            )
            uncertain = crashed.begin_operation(1, operation_plan["operations"][1])
            assert uncertain["decision"] == "execute"
            dispatched = crashed.dispatch_operation(1, operation_plan["operations"][1])
            assert dispatched["checkpoint_state"] == "dispatched"

            with pytest.raises(AssertionError, match="409"):
                AssetGraphScriptLayoutCheckpointStore.start(
                    client=adapter,
                    operation_plan=operation_plan,
                    target_live_room_id="47000002",
                )
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_executions
                    SET lease_acquired_at = now() - interval '20 minutes',
                        lease_expires_at = now() - interval '10 minutes',
                        lease_reconcile_not_before = now() - interval '1 second'
                    WHERE execution_code = %s
                    """,
                    (crashed.execution_code,),
                )
            connection.commit()

            resumed = AssetGraphScriptLayoutCheckpointStore.start(
                client=adapter,
                operation_plan=operation_plan,
                target_live_room_id="47000002",
            )
            session = TrackingInMemorySession()
            blocked_result = ScriptLayoutDraftRunner(session=session, checkpoint_store=resumed).run(operation_plan)
            assert blocked_result.status == "failed"
            assert blocked_result.actions[-1].action_type == "checkpoint_reconcile_required"
            assert session.rename_count == 0
            resumed.finalize(blocked_result)

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE maitu_live_room_build_plan_executions
                    SET lease_acquired_at = now() - interval '20 minutes',
                        lease_expires_at = now() - interval '10 minutes',
                        lease_reconcile_not_before = now() - interval '1 second'
                    WHERE execution_code = %s
                    """,
                    (resumed.execution_code,),
                )
            connection.commit()
            operation_checkpoint = resumed.operation_checkpoints[1]
            reconciliation_id = str(uuid4())
            reconciliation_evidence = {
                "verified": True,
                "operation_applied": False,
                "operation_index": 1,
                "operation_type": "fill_default_scene",
                "operation_fingerprint": operation_checkpoint["operation_fingerprint"],
                "target_live_room_id": "47000002",
                "go_live_clicked": False,
            }
            reconcile = http.post(
                f"/api/maitu/live-room-build-plans/{build_plan_code}/script-layout-executions/"
                f"{resumed.execution_code}/operations/1/reconcile",
                json={
                    "operation_fingerprint": operation_checkpoint["operation_fingerprint"],
                    "reconciliation_id": reconciliation_id,
                    "reconciled_attempt_id": str(crashed.run_attempt_id),
                    "resolution": "confirmed_not_applied",
                    "resolution_summary": "authoritative room readback confirmed default clip was not renamed",
                    "evidence": reconciliation_evidence,
                },
            )
            assert reconcile.status_code == 200, reconcile.text
            assert reconcile.json()["checkpoint_state"] == "retry_authorized"

            recovered = AssetGraphScriptLayoutCheckpointStore.start(
                client=adapter,
                operation_plan=operation_plan,
                target_live_room_id="47000002",
            )
            recovered_result = ScriptLayoutDraftRunner(session=session, checkpoint_store=recovered).run(operation_plan)
            assert recovered_result.status == "completed_with_manual_review", [
                {"action_type": action.action_type, "status": action.status, "summary": action.summary, "details": action.details}
                for action in recovered_result.actions
            ]
            assert session.rename_count == 1
            finalized = recovered.finalize(recovered_result)
            assert finalized["execution_code"] == resumed.execution_code
            assert [row["checkpoint_state"] for row in finalized["operation_results"]] == [
                "observed",
                "completed",
                "manual_required",
            ]

            with pytest.raises(AssertionError, match="409"):
                AssetGraphScriptLayoutCheckpointStore.start(
                    client=adapter,
                    operation_plan=operation_plan,
                    target_live_room_id="47000002",
                )
            assert session.rename_count == 1
        finally:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plan_operation_results WHERE build_plan_code = %s",
                    (build_plan_code,),
                )
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plan_executions WHERE build_plan_code = %s",
                    (build_plan_code,),
                )
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plan_operations WHERE build_plan_code = %s",
                    (build_plan_code,),
                )
                cursor.execute(
                    "DELETE FROM maitu_live_room_build_plans WHERE build_plan_code = %s",
                    (build_plan_code,),
                )
            connection.commit()
