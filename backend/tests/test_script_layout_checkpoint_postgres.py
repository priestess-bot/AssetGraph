from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from pydantic import SecretStr

from app.repositories import maitu as maitu_repository
from app.repositories.maitu import BuildPlanCheckpointConflictError, MaituMaterialSlotRepository

DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
READBACK_ATTESTATION_KEY = "test-readback-attestation-key-32-bytes"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _start_payload(operation_plan: dict, *, suffix: str) -> dict:
    return {
        "start_request_id": str(uuid4()),
        "run_attempt_id": str(uuid4()),
        "lease_token": str(uuid4()),
        "lease_owner": f"phase-d-postgres-{suffix}",
        "source_plan_fingerprint": operation_plan["checkpoint_source_fingerprint"],
        "target_live_room_id": "47000002",
        "operations": [
            {"operation_index": index, "intent": operation}
            for index, operation in enumerate(operation_plan["operations"])
        ],
        "mode": "script_layout_draft",
        "checkpoint_contract": "script_layout_checkpoint_v1",
    }


def _fenced_payload(execution: dict, checkpoint: dict, run_attempt_id: str) -> dict:
    return {
        "operation_fingerprint": checkpoint["operation_fingerprint"],
        "attempt_id": run_attempt_id,
        "lease_token": str(execution["lease_token"]),
        "lease_version": execution["lease_version"],
        "lease_owner": execution["lease_owner"],
    }


def _sign_readback(payload: dict) -> str:
    return hmac.new(
        READBACK_ATTESTATION_KEY.encode("utf-8"),
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _attest_completion(
    build_plan_code: str,
    execution_code: str,
    operation_index: int,
    checkpoint: dict,
    payload: dict,
) -> dict:
    evidence = dict(payload["evidence"])
    attested = {
        "build_plan_code": build_plan_code,
        "execution_code": execution_code,
        "operation_index": operation_index,
        "operation_fingerprint": checkpoint["operation_fingerprint"],
        "attempt_id": str(payload["attempt_id"]),
        "lease_token": str(payload["lease_token"]),
        "lease_version": payload["lease_version"],
        "completion_id": str(payload["completion_id"]),
        "evidence": evidence,
    }
    return {
        **payload,
        "evidence": {
            **evidence,
            "readback_attestation_algorithm": "hmac-sha256-v1",
            "readback_attestation": _sign_readback(attested),
        },
    }


def _attest_reconciliation(
    build_plan_code: str,
    execution_code: str,
    operation_index: int,
    checkpoint: dict,
    payload: dict,
) -> dict:
    evidence = dict(payload["evidence"])
    attested = {
        "build_plan_code": build_plan_code,
        "execution_code": execution_code,
        "operation_index": operation_index,
        "operation_fingerprint": checkpoint["operation_fingerprint"],
        "reconciliation_id": str(payload["reconciliation_id"]),
        "reconciled_attempt_id": str(payload["reconciled_attempt_id"]),
        "resolution": payload["resolution"],
        "evidence": evidence,
    }
    return {
        **payload,
        "evidence": {
            **evidence,
            "readback_attestation_algorithm": "hmac-sha256-v1",
            "readback_attestation": _sign_readback(attested),
        },
    }


def test_postgres_fenced_manifest_dispatch_reconcile_and_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        maitu_repository.settings,
        "maitu_readback_attestation_key",
        SecretStr(READBACK_ATTESTATION_KEY),
    )
    migration_root = Path(__file__).resolve().parents[1] / "migrations"
    reconciliation_id: str | None = None
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute((migration_root / "020_script_driven_build_plan_persistence.sql").read_text(encoding="utf-8"))
            cursor.execute((migration_root / "021_script_layout_execution_checkpoints.sql").read_text(encoding="utf-8"))
            cursor.execute((migration_root / "021_script_layout_execution_checkpoints.sql").read_text(encoding="utf-8"))
        connection.commit()
        repository = MaituMaterialSlotRepository(connection)
        build_plan = {
            "source": "script_content_layout_build_plan_rule_v1",
            "status": "ready",
            "target_live_room_id": "47000002",
            "build_mode": "strict",
            "can_execute": True,
            "manual_review_required": False,
            "blocked_reasons": [],
            "operation_count": 2,
            "operations": [
                {
                    "operation_type": "preflight_content_build_plan",
                    "operation_name": "草稿预检",
                    "sort_order": 1,
                    "status": "ready",
                    "target_live_room_id": "47000002",
                },
                {
                    "operation_type": "create_scene",
                    "operation_name": "新建场景：促单",
                    "sort_order": 2,
                    "status": "ready",
                    "scene_index": 1,
                    "scene_name": "促单",
                }
            ],
        }
        persisted = repository.create_script_layout_build_plan(build_plan, plan_name="Phase D fenced checkpoint test")
        code = persisted["build_plan_code"]
        try:
            operation_plan = repository.get_live_room_build_plan_operations(code)
            assert operation_plan is not None
            first_start = _start_payload(operation_plan, suffix="first")
            execution = repository.start_script_layout_execution(code, first_start)
            assert execution is not None
            assert execution["expected_operation_count"] == 2
            assert execution["lease_version"] == 1
            assert len(execution["operation_results"]) == 2
            preflight_checkpoint = execution["operation_results"][0]
            checkpoint = execution["operation_results"][1]
            assert preflight_checkpoint["effect_class"] == "read_only"
            assert checkpoint["checkpoint_state"] == "not_started"
            assert checkpoint["effect_class"] == "mutating"
            assert checkpoint["intent_snapshot"]["scene_name"] == "促单"

            preflight_fence = _fenced_payload(execution, preflight_checkpoint, first_start["run_attempt_id"])
            repository.begin_script_layout_execution_operation(code, execution["execution_code"], 0, preflight_fence)
            preflight_payload = _attest_completion(
                code,
                execution["execution_code"],
                0,
                preflight_checkpoint,
                {
                    **preflight_fence,
                    "completion_id": str(uuid4()),
                    "result_summary": "working room is not live",
                    "evidence": {
                        "verified": True,
                        "operation_applied": False,
                        "no_side_effect": True,
                        "operation_index": 0,
                        "operation_type": "preflight_content_build_plan",
                        "operation_fingerprint": preflight_checkpoint["operation_fingerprint"],
                        "target_live_room_id": "47000002",
                        "clip_id": 410000,
                        "default_clip_id": 410000,
                        "environment": "working",
                        "not_live": True,
                        "verification_source": "working_room_readback",
                    },
                    "operation_result": {
                        "operation_index": 0,
                        "operation_type": "preflight_content_build_plan",
                        "status": "completed",
                    },
                },
            )
            observed = repository.complete_script_layout_execution_operation(
                code,
                execution["execution_code"],
                0,
                preflight_payload,
            )
            assert observed["checkpoint_state"] == "observed"

            idempotent_start = repository.start_script_layout_execution(code, first_start)
            assert idempotent_start["execution_code"] == execution["execution_code"]
            with pytest.raises(BuildPlanCheckpointConflictError, match="active lease"):
                repository.start_script_layout_execution(code, _start_payload(operation_plan, suffix="concurrent"))

            fenced = _fenced_payload(execution, checkpoint, first_start["run_attempt_id"])
            prepared = repository.begin_script_layout_execution_operation(code, execution["execution_code"], 1, fenced)
            assert prepared["checkpoint_state"] == "prepared"
            completion_id = str(uuid4())
            complete_payload = {
                **fenced,
                "completion_id": completion_id,
                "result_summary": "scene created and read back",
                "evidence": {
                    "verified": True,
                    "operation_applied": True,
                    "operation_index": 1,
                    "operation_type": "create_scene",
                    "operation_fingerprint": checkpoint["operation_fingerprint"],
                    "target_live_room_id": "47000002",
                    "clip_id": 416426,
                    "scene_index": 1,
                    "scene_name": "促单",
                    "verification_source": "working_room_readback",
                },
                "operation_result": {
                    "operation_index": 1,
                    "operation_type": "create_scene",
                    "operation_name": "新建场景：促单",
                    "scene_index": 1,
                    "scene_name": "促单",
                    "clip_id": 416426,
                    "action_type": "create_draft_scene",
                    "status": "completed",
                },
            }
            with pytest.raises(BuildPlanCheckpointConflictError, match="not completable"):
                repository.complete_script_layout_execution_operation(
                    code, execution["execution_code"], 1, complete_payload
                )
            dispatched = repository.dispatch_script_layout_execution_operation(code, execution["execution_code"], 1, fenced)
            assert dispatched["checkpoint_state"] == "dispatched"
            with pytest.raises(BuildPlanCheckpointConflictError, match="already consumed"):
                repository.dispatch_script_layout_execution_operation(
                    code, execution["execution_code"], 1, fenced
                )
            with pytest.raises(BuildPlanCheckpointConflictError, match="readback attestation"):
                repository.complete_script_layout_execution_operation(
                    code, execution["execution_code"], 1, complete_payload
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
                    (execution["execution_code"],),
                )
            connection.commit()

            second_start = _start_payload(operation_plan, suffix="second")
            resumed = repository.start_script_layout_execution(code, second_start)
            assert resumed["execution_code"] == execution["execution_code"]
            assert resumed["lease_version"] == 2
            resumed_checkpoint = resumed["operation_results"][1]
            resumed_fence = _fenced_payload(resumed, resumed_checkpoint, second_start["run_attempt_id"])
            reconcile_required = repository.begin_script_layout_execution_operation(
                code, execution["execution_code"], 1, resumed_fence
            )
            assert reconcile_required["decision"] == "reconcile"

            reconciliation_id = str(uuid4())
            reconcile_payload = {
                "operation_fingerprint": checkpoint["operation_fingerprint"],
                "reconciliation_id": reconciliation_id,
                "reconciled_attempt_id": first_start["run_attempt_id"],
                "resolution": "confirmed_not_applied",
                "resolution_summary": "authoritative room readback found no matching scene",
                "evidence": {
                    "verified": True,
                    "operation_applied": False,
                    "operation_index": 1,
                    "operation_type": "create_scene",
                    "operation_fingerprint": checkpoint["operation_fingerprint"],
                    "target_live_room_id": "47000002",
                },
                "reconciled_by": "phase-d-postgres-operator",
            }
            reconcile_payload = _attest_reconciliation(
                code,
                execution["execution_code"],
                1,
                checkpoint,
                reconcile_payload,
            )
            with pytest.raises(BuildPlanCheckpointConflictError, match="active"):
                repository.reconcile_script_layout_execution_operation(
                    code, execution["execution_code"], 1, reconcile_payload
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
                    (execution["execution_code"],),
                )
            connection.commit()
            retry_authorized = repository.reconcile_script_layout_execution_operation(
                code, execution["execution_code"], 1, reconcile_payload
            )
            assert retry_authorized["checkpoint_state"] == "retry_authorized"

            third_start = _start_payload(operation_plan, suffix="third")
            recovered = repository.start_script_layout_execution(code, third_start)
            recovered_checkpoint = recovered["operation_results"][1]
            recovered_fence = _fenced_payload(recovered, recovered_checkpoint, third_start["run_attempt_id"])
            repository.begin_script_layout_execution_operation(code, execution["execution_code"], 1, recovered_fence)
            repository.dispatch_script_layout_execution_operation(code, execution["execution_code"], 1, recovered_fence)
            recovered_complete_payload = _attest_completion(
                code,
                execution["execution_code"],
                1,
                recovered_checkpoint,
                {**complete_payload, **recovered_fence},
            )
            completed = repository.complete_script_layout_execution_operation(
                code,
                execution["execution_code"],
                1,
                recovered_complete_payload,
            )
            assert completed["checkpoint_state"] == "completed"

            finalization_id = str(uuid4())
            finalize_payload = {
                "finalization_id": finalization_id,
                "run_attempt_id": third_start["run_attempt_id"],
                "lease_token": str(recovered["lease_token"]),
                "lease_version": recovered["lease_version"],
                "lease_owner": recovered["lease_owner"],
                "executor": "browser_use",
                "execution_status": "completed",
                "mode": "script_layout_draft",
                "result_summary": "fenced draft complete",
                "ready_for_go_live": False,
                "manual_review_required": False,
                "details": {},
            }
            finalized = repository.finalize_script_layout_execution(code, execution["execution_code"], finalize_payload)
            assert str(finalized["finalization_id"]) == finalization_id
            repeated = repository.finalize_script_layout_execution(code, execution["execution_code"], finalize_payload)
            assert repeated["execution_code"] == execution["execution_code"]
            with pytest.raises(BuildPlanCheckpointConflictError, match="another immutable identity"):
                repository.finalize_script_layout_execution(
                    code,
                    execution["execution_code"],
                    {**finalize_payload, "finalization_id": str(uuid4())},
                )

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT count(*) FROM maitu_live_room_build_plan_executions
                    WHERE build_plan_code = %s AND checkpoint_contract = 'script_layout_checkpoint_v1'
                    """,
                    (code,),
                )
                assert cursor.fetchone()[0] == 1
                cursor.execute(
                    "SELECT count(*) FROM maitu_live_room_build_plan_reconciliations WHERE execution_code = %s",
                    (execution["execution_code"],),
                )
                assert cursor.fetchone()[0] == 1
            with pytest.raises(psycopg.errors.RaiseException, match="receipts are immutable"):
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "DELETE FROM maitu_live_room_build_plan_reconciliations WHERE reconciliation_id = %s",
                            (reconciliation_id,),
                        )
        finally:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM maitu_live_room_build_plan_operation_results WHERE build_plan_code = %s", (code,))
                cursor.execute("DELETE FROM maitu_live_room_build_plan_executions WHERE build_plan_code = %s", (code,))
                cursor.execute("DELETE FROM maitu_live_room_build_plan_operations WHERE build_plan_code = %s", (code,))
                cursor.execute("DELETE FROM maitu_live_room_build_plans WHERE build_plan_code = %s", (code,))
            connection.commit()
            if reconciliation_id is not None:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM maitu_live_room_build_plan_reconciliations WHERE reconciliation_id = %s",
                        (reconciliation_id,),
                    )
                    assert cursor.fetchone()[0] == 1
