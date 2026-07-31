from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.repositories.console import ConsoleRepository


DATABASE_URL = os.getenv("ASSETGRAPH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="ASSETGRAPH_TEST_DATABASE_URL is not configured")


def test_console_read_models_search_and_deep_link_real_control_plane_data() -> None:
    suffix = uuid4().hex
    asset_code = f"CON-{suffix[:12]}"
    run_code = f"RUN-CONSOLE-{suffix[:16]}"
    task_code = f"TASK-CONSOLE-{suffix[:16]}"
    alert_code = f"ALERT-CONSOLE-{suffix[:16]}"
    with psycopg.connect(DATABASE_URL) as connection:
        try:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    INSERT INTO assets (asset_code, asset_type, title, original_filename, status)
                    VALUES (%s, 'IMG', %s, %s, 'ready')
                    """,
                    (asset_code, f"Console searchable {suffix}", f"{asset_code}.png"),
                )
                cursor.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_code, workflow_type, subject_type, subject_code, status,
                        priority, progress_completed, progress_total, waiting_reason,
                        requested_by
                    ) VALUES (
                        %s, 'console_validation', 'asset', %s, 'waiting_human',
                        5, 1, 2, 'approval required', 'operator-a'
                    ) RETURNING id
                    """,
                    (run_code, asset_code),
                )
                run_id = cursor.fetchone()["id"]
                cursor.execute(
                    """
                    INSERT INTO human_tasks (
                        task_code, run_id, task_type, status, priority,
                        owner_principal, subject, due_at
                    ) VALUES (
                        %s, %s, 'review_console_evidence', 'open', 5,
                        'operator-a', %s::jsonb, now() + interval '1 hour'
                    )
                    """,
                    (task_code, run_id, '{"summary":"Review Console evidence"}'),
                )
                cursor.execute(
                    """
                    INSERT INTO evidence_integrity_alerts (
                        alert_code, alert_type, severity, subject_type, subject_code,
                        reason_code, dedupe_key, evidence
                    ) VALUES (
                        %s, 'console_validation', 'warning', 'workflow_run', %s,
                        'CONSOLE_VALIDATION_WARNING', %s, '{"artifact":"ART-CONSOLE"}'::jsonb
                    )
                    """,
                    (alert_code, run_code, f"console:{suffix}"),
                )
            connection.commit()

            repository = ConsoleRepository(connection)
            search = repository.search(suffix, limit=20)
            asset = next(row for row in search if row["entity_code"] == asset_code)
            assert asset["href"] == f"/assets?asset={asset_code}"

            tasks = repository.list_tasks("operator-a")
            task = next(row for row in tasks if row["item_code"] == task_code)
            assert task["item_type"] == "human_task"
            assert task["href"] == "/projects?view=activity"
            assert all(row["item_code"] != run_code for row in tasks)

            notifications = repository.list_notifications()
            notification = next(
                row for row in notifications if row["notification_code"] == alert_code
            )
            assert notification["state"] == "warning"
            assert notification["evidence"] == {"artifact": "ART-CONSOLE"}
        finally:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM evidence_integrity_alerts WHERE alert_code = %s", (alert_code,))
                cursor.execute("DELETE FROM workflow_runs WHERE run_code = %s", (run_code,))
                cursor.execute("DELETE FROM assets WHERE asset_code = %s", (asset_code,))
            connection.commit()
