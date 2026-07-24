from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import Connection
from psycopg.rows import dict_row


class ConsoleRepository:
    """Read-side aggregation for the shared operations Console."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT *
                FROM (
                    SELECT 'asset'::varchar AS entity_type,
                           asset_code::varchar AS entity_code,
                           COALESCE(title, original_filename)::varchar AS title,
                           status::varchar AS status,
                           NULL::integer AS revision,
                           '/assets/library?asset=' || asset_code AS href,
                           updated_at
                    FROM assets
                    WHERE deleted_at IS NULL
                      AND (asset_code ILIKE %s OR COALESCE(title, '') ILIKE %s
                           OR original_filename ILIKE %s)

                    UNION ALL

                    SELECT 'content_project', project_code, title, status,
                           NULLIF(current_revision_number, 0),
                           '/content/projects?project=' || project_code, updated_at
                    FROM content_projects
                    WHERE project_code ILIKE %s OR title ILIKE %s

                    UNION ALL

                    SELECT 'workflow_run', run_code,
                           workflow_type || ' / ' || subject_code, status,
                           subject_revision,
                           '/governance/runs?run=' || run_code, updated_at
                    FROM workflow_runs
                    WHERE run_code ILIKE %s OR workflow_type ILIKE %s
                       OR subject_code ILIKE %s

                    UNION ALL

                    SELECT 'release', release_code,
                           subject_type || ' / ' || subject_code, status,
                           subject_revision,
                           '/production/releases?release=' || release_code, updated_at
                    FROM releases
                    WHERE release_code ILIKE %s OR subject_code ILIKE %s

                    UNION ALL

                    SELECT 'live_room_template', template.template_code, template.name,
                           template.status,
                           published.revision_number,
                           '/research/live-sources?template=' || template.template_code,
                           template.updated_at
                    FROM live_room_templates AS template
                    LEFT JOIN live_room_template_revisions AS published
                      ON published.id = template.published_revision_id
                    WHERE template.template_code ILIKE %s OR template.name ILIKE %s

                    UNION ALL

                    SELECT 'capture_session', session.session_code,
                           COALESCE(target.display_name, session.target_code), session.status,
                           NULL::integer,
                           '/research/live-sources?view=sessions&session=' || session.session_code,
                           session.updated_at
                    FROM live_capture_sessions AS session
                    LEFT JOIN live_watch_targets AS target ON target.id = session.target_id
                    WHERE session.session_code ILIKE %s OR session.target_code ILIKE %s
                       OR COALESCE(target.display_name, '') ILIKE %s

                    UNION ALL

                    SELECT 'legacy_workbench_run', run_code, title, status,
                           NULLIF(active_plan_revision, 0),
                           '/production/live-rooms?run=' || run_code, updated_at
                    FROM maitu_workbench_runs
                    WHERE run_code ILIKE %s OR title ILIKE %s OR topic ILIKE %s
                ) AS matches
                ORDER BY updated_at DESC, entity_type, entity_code
                LIMIT %s
                """,
                (
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    limit,
                ),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_tasks(self, operator_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT task.task_code AS item_code, 'human_task'::varchar AS item_type,
                       task.task_type AS title, task.status, task.priority,
                       COALESCE(task.subject->>'summary', run.waiting_reason, run.subject_code) AS summary,
                       '/governance/runs?run=' || run.run_code || '&task=' || task.task_code AS href,
                       task.due_at, task.updated_at,
                       run.run_code, run.progress_completed, run.progress_total,
                       task.owner_principal, task.claimed_by
                FROM human_tasks AS task
                JOIN workflow_runs AS run ON run.id = task.run_id
                WHERE task.status IN ('open', 'claimed', 'escalated')
                  AND (task.owner_principal IS NULL OR task.owner_principal = %s
                       OR task.claimed_by = %s)
                ORDER BY task.priority, task.due_at NULLS LAST, task.updated_at DESC
                LIMIT %s
                """,
                (operator_id, operator_id, limit),
            )
            tasks.extend(dict(row) for row in cursor.fetchall())
            cursor.execute(
                """
                SELECT run.run_code AS item_code, 'workflow_run'::varchar AS item_type,
                       run.workflow_type AS title, run.status, run.priority,
                       COALESCE(run.waiting_reason, run.queue_reason, run.error_summary, run.subject_code) AS summary,
                       '/governance/runs?run=' || run.run_code AS href,
                       NULL::timestamptz AS due_at, run.updated_at,
                       run.run_code, run.progress_completed, run.progress_total,
                       run.requested_by AS owner_principal, NULL::varchar AS claimed_by
                FROM workflow_runs AS run
                WHERE run.status IN ('queued', 'running', 'waiting_human', 'cancelling', 'reconcile_required')
                  AND (run.requested_by IS NULL OR run.requested_by = %s)
                  AND NOT EXISTS (
                      SELECT 1 FROM human_tasks AS task
                      WHERE task.run_id = run.id AND task.status IN ('open', 'claimed', 'escalated')
                  )
                ORDER BY run.priority, run.updated_at DESC
                LIMIT %s
                """,
                (operator_id, limit),
            )
            tasks.extend(dict(row) for row in cursor.fetchall())
        tasks.sort(
            key=lambda item: (
                int(item["priority"]),
                item["due_at"] or datetime.max.replace(tzinfo=item["updated_at"].tzinfo),
                item["item_code"],
            )
        )
        return tasks[:limit]

    def list_notifications(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT alert_code AS notification_code,
                       CASE severity WHEN 'critical' THEN 'error' ELSE 'warning' END::varchar AS state,
                       reason_code AS title,
                       subject_type || ' / ' || subject_code AS summary,
                       '/governance/runs?alert=' || alert_code AS href,
                       evidence, occurrence_count, last_detected_at AS occurred_at,
                       status
                FROM evidence_integrity_alerts
                WHERE status <> 'resolved'

                UNION ALL

                SELECT 'RELEASE:' || release_code, 'reconcile_required',
                       'RELEASE_RECONCILE_REQUIRED',
                       subject_type || ' / ' || subject_code,
                       '/production/releases?release=' || release_code,
                       jsonb_build_object('release_code', release_code), 1, updated_at, status
                FROM releases
                WHERE status IN ('reconcile_required', 'delivery_failed')

                ORDER BY occurred_at DESC, notification_code
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]
