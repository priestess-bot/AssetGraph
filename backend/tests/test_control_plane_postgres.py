from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from app.repositories.control_plane import ControlPlaneRepository
from app.schemas.control_plane import WorkflowRunCreate


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def _payload(*, suffix: str, external_second_step: bool = True) -> dict:
    payload = WorkflowRunCreate.model_validate(
        {
            "workflow_type": "closed_loop_test",
            "subject_type": "content_project",
            "subject_code": f"CONTENT-{suffix}",
            "subject_revision": 1,
            "idempotency_key": f"workflow-{suffix}",
            "steps": [
                {
                    "step_key": "prepare",
                    "step_type": f"prepare_{suffix}",
                    "idempotency_key": f"prepare-{suffix}",
                    "timeout_seconds": 60,
                    "input_fingerprint": "a" * 64,
                },
                {
                    "step_key": "commit",
                    "step_type": f"external_{suffix}" if external_second_step else f"finish_{suffix}",
                    "depends_on": ["prepare"],
                    "idempotency_key": f"commit-{suffix}",
                    "side_effect_level": "write_external" if external_second_step else "pure_compute",
                    "reconcile_strategy": "authoritative_readback" if external_second_step else None,
                    "timeout_seconds": 60,
                    "input_fingerprint": "b" * 64,
                },
            ],
        }
    ).model_dump(mode="json")
    payload["requested_by"] = "operator-a"
    return payload


def test_workflow_dag_idempotency_fenced_lease_and_unknown_side_effect_reconcile() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        created = repository.create_workflow_run(_payload(suffix=suffix))
        run_code = created["run_code"]
        try:
            replay = repository.create_workflow_run(_payload(suffix=suffix))
            assert replay["run_code"] == run_code
            assert [step["status"] for step in created["steps"]] == ["ready", "pending"]

            prepare = repository.claim_next_step(
                worker_id="worker-a",
                lease_seconds=60,
                accepted_step_types=[f"prepare_{suffix}"],
            )
            assert prepare is not None
            assert prepare["step_type"] == f"prepare_{suffix}"
            assert prepare["attempt"] == 1
            assert repository.heartbeat_step(
                prepare["step_code"],
                worker_id="worker-b",
                claim_token=prepare["claim_token"],
                lease_version=prepare["lease_version"],
                lease_seconds=60,
            ) is None
            assert repository.heartbeat_step(
                prepare["step_code"],
                worker_id="worker-a",
                claim_token=prepare["claim_token"],
                lease_version=prepare["lease_version"],
                lease_seconds=60,
            ) is not None
            assert repository.complete_step(
                prepare["step_code"],
                worker_id="worker-a",
                claim_token=prepare["claim_token"],
                lease_version=prepare["lease_version"],
                output_fingerprint="c" * 64,
                actual_cost={"cpu_seconds": 1},
            )["status"] == "succeeded"

            commit = repository.claim_next_step(
                worker_id="worker-b",
                lease_seconds=60,
                accepted_step_types=[f"external_{suffix}"],
            )
            assert commit is not None
            assert commit["step_type"] == f"external_{suffix}"
            failed = repository.fail_step(
                commit["step_code"],
                worker_id="worker-b",
                claim_token=commit["claim_token"],
                lease_version=commit["lease_version"],
                error_code="UPSTREAM_TIMEOUT",
                error_summary="outcome unknown",
                side_effect_known_not_applied=False,
            )
            assert failed is not None
            assert failed["status"] == "reconcile_required"
            current = repository.get_workflow_run(run_code)
            assert current is not None
            assert current["status"] == "reconcile_required"
            assert current["progress_completed"] == 1
        finally:
            # Append-only status history intentionally blocks ungoverned cascade deletion.
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM workflow_runs WHERE run_code = %s", (run_code,))
            connection.rollback()


def test_human_task_wait_releases_lease_and_resumes_without_duplicate_step() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        created = repository.create_workflow_run(_payload(suffix=suffix, external_second_step=False))
        run_code = created["run_code"]
        try:
            prepare = repository.claim_next_step(
                worker_id="worker-a",
                lease_seconds=60,
                accepted_step_types=[f"prepare_{suffix}"],
            )
            assert prepare is not None
            task = repository.create_human_task(
                step_code=prepare["step_code"],
                task_type="approve_content",
                subject={"revision": 1},
                owner_principal="operator-a",
            )
            assert task["status"] == "open"
            waiting = repository.get_workflow_run(run_code)
            assert waiting is not None
            assert waiting["status"] == "waiting_human"
            waiting_step = waiting["steps"][0]
            assert waiting_step["status"] == "waiting_human"
            assert waiting_step["claimed_by"] is None
            assert waiting_step["lease_expires_at"] is None

            claimed = repository.claim_human_task(
                task["task_code"],
                claimed_by="operator-a",
                expected_revision=1,
            )
            assert claimed is not None
            decided = repository.decide_human_task(
                task["task_code"],
                decided_by="operator-a",
                expected_revision=2,
                decision="approve",
                structured_reason={"reason_code": "CONTENT_VERIFIED"},
            )
            assert decided is not None
            assert decided["status"] == "decided"

            resumed = repository.claim_next_step(
                worker_id="worker-b",
                lease_seconds=60,
                accepted_step_types=[f"prepare_{suffix}"],
            )
            assert resumed is not None
            assert resumed["step_code"] == prepare["step_code"]
            assert resumed["attempt"] == 2
            repository.complete_step(
                resumed["step_code"],
                worker_id="worker-b",
                claim_token=resumed["claim_token"],
                lease_version=resumed["lease_version"],
                output_fingerprint="c" * 64,
                actual_cost={},
            )
            finish = repository.claim_next_step(
                worker_id="worker-b",
                lease_seconds=60,
                accepted_step_types=[f"finish_{suffix}"],
            )
            assert finish is not None
            repository.complete_step(
                finish["step_code"],
                worker_id="worker-b",
                claim_token=finish["claim_token"],
                lease_version=finish["lease_version"],
                output_fingerprint="d" * 64,
                actual_cost={},
            )
            completed = repository.get_workflow_run(run_code)
            assert completed is not None
            assert completed["status"] == "succeeded"
            assert completed["progress_completed"] == 2
        finally:
            pass


def test_expired_external_lease_requires_reconcile_while_pure_compute_is_reclaimed() -> None:
    external_suffix = uuid4().hex
    pure_suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        external = repository.create_workflow_run(_payload(suffix=external_suffix))
        repository.create_workflow_run(_payload(suffix=pure_suffix, external_second_step=False))
        try:
            # Claim each first step deterministically by limiting accepted types.
            external_prepare = repository.claim_next_step(
                worker_id="worker-a",
                lease_seconds=60,
                accepted_step_types=[f"prepare_{external_suffix}"],
            )
            assert external_prepare is not None
            repository.complete_step(
                external_prepare["step_code"],
                worker_id="worker-a",
                claim_token=external_prepare["claim_token"],
                lease_version=external_prepare["lease_version"],
                output_fingerprint="c" * 64,
                actual_cost={},
            )
            # Complete the other prepare step.
            pure_prepare = repository.claim_next_step(
                worker_id="worker-a",
                lease_seconds=60,
                accepted_step_types=[f"prepare_{pure_suffix}"],
            )
            assert pure_prepare is not None
            repository.complete_step(
                pure_prepare["step_code"],
                worker_id="worker-a",
                claim_token=pure_prepare["claim_token"],
                lease_version=pure_prepare["lease_version"],
                output_fingerprint="c" * 64,
                actual_cost={},
            )

            external_commit = repository.claim_next_step(
                worker_id="worker-a",
                lease_seconds=60,
                accepted_step_types=[f"external_{external_suffix}"],
            )
            pure_finish = repository.claim_next_step(
                worker_id="worker-a",
                lease_seconds=60,
                accepted_step_types=[f"finish_{pure_suffix}"],
            )
            assert external_commit is not None and pure_finish is not None
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE workflow_steps SET lease_expires_at = %s WHERE step_code IN (%s, %s)",
                    (
                        datetime(2020, 1, 1, tzinfo=UTC),
                        external_commit["step_code"],
                        pure_finish["step_code"],
                    ),
                )
            connection.commit()

            reclaimed = repository.claim_next_step(
                worker_id="worker-b",
                lease_seconds=60,
                accepted_step_types=[f"finish_{pure_suffix}"],
            )
            assert reclaimed is not None
            assert reclaimed["step_code"] == pure_finish["step_code"]
            assert reclaimed["attempt"] == 2
            external_current = repository.get_workflow_run(external["run_code"])
            assert external_current is not None
            assert external_current["status"] == "reconcile_required"
            assert external_current["steps"][1]["status"] == "reconcile_required"
        finally:
            pass


def test_claimed_step_propagates_workflow_traceparent() -> None:
    suffix = uuid4().hex
    with psycopg.connect(DATABASE_URL) as connection:
        repository = ControlPlaneRepository(connection)
        payload = _payload(suffix=suffix, external_second_step=False)
        payload["trace_id"] = "4bf92f3577b34da6a3ce929d0e0e4736"
        payload["root_span_id"] = "00f067aa0ba902b7"
        repository.create_workflow_run(payload)

        claimed = repository.claim_next_step(
            worker_id="worker-trace",
            lease_seconds=60,
            accepted_step_types=[f"prepare_{suffix}"],
        )

        assert claimed is not None
        assert claimed["traceparent"] == (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
