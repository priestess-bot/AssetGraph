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
                           '/assets?asset=' || asset_code AS href,
                           updated_at
                    FROM assets
                    WHERE deleted_at IS NULL
                      AND (asset_code ILIKE %s OR COALESCE(title, '') ILIKE %s
                           OR original_filename ILIKE %s)

                    UNION ALL

                    SELECT 'content_project', project_code, title, status,
                           NULLIF(current_revision_number, 0),
                           '/projects?project=' || project_code, updated_at
                    FROM content_projects
                    WHERE project_code ILIKE %s OR title ILIKE %s

                    UNION ALL

                    SELECT 'live_room_template', template.template_code, template.name,
                           template.status,
                           published.revision_number,
                           '/templates?template=' || template.template_code,
                           template.updated_at
                    FROM live_room_templates AS template
                    LEFT JOIN live_room_template_revisions AS published
                      ON published.id = template.published_revision_id
                    WHERE template.template_code ILIKE %s OR template.name ILIKE %s

                    UNION ALL

                    SELECT 'fact_card', fact.fact_code,
                           fact.title, fact.status,
                           NULL::integer,
                           '/knowledge?fact=' || fact.fact_code,
                           fact.created_at
                    FROM functional_knowledge_facts AS fact
                    WHERE fact.fact_code ILIKE %s OR fact.title ILIKE %s OR fact.claim ILIKE %s
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
                       CASE run.subject_type
                           WHEN 'live_room_template' THEN '审核直播模板'
                           WHEN 'content_project' THEN '确认内容项目'
                           WHEN 'release' THEN '确认交付内容'
                           WHEN 'functional_live_room_plan' THEN '核对直播间方案'
                           WHEN 'functional_video_plan' THEN '核对成片结果'
                           ELSE '完成内容处理'
                       END AS title,
                       task.status, task.priority,
                       CASE task.status
                           WHEN 'claimed' THEN '该事项正在处理中，请完成检查并提交结果'
                           WHEN 'escalated' THEN '该事项需要协助处理，请查看影响和建议动作'
                           ELSE '该事项需要人工确认后才能继续'
                       END AS summary,
                       '/projects?view=activity' AS href,
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
                       CASE run.subject_type
                           WHEN 'live_room_template' THEN '正在处理直播模板'
                           WHEN 'content_project' THEN '正在生成项目内容'
                           WHEN 'release' THEN '正在交付内容'
                           WHEN 'functional_live_room_plan' THEN '正在生成直播间方案'
                           WHEN 'functional_video_plan' THEN '正在制作成片'
                           ELSE '正在处理内容'
                       END AS title,
                       run.status, run.priority,
                       CASE run.status
                           WHEN 'queued' THEN '任务已进入队列，等待开始'
                           WHEN 'running' THEN '任务正在后台处理，可离开当前页面'
                           WHEN 'waiting_human' THEN '需要人工补充信息或确认结果'
                           WHEN 'reconcile_required' THEN '外部结果需要人工核对'
                           ELSE '任务状态已更新'
                       END AS summary,
                       '/projects?view=activity' AS href,
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
                       CASE
                           WHEN reason_code LIKE '%%STALE%%' THEN '项目使用的内容已有更新'
                           WHEN reason_code LIKE '%%MISSING%%' THEN '有一项必需信息尚未准备好'
                           ELSE '有一项内容需要核对'
                       END AS title,
                       '请打开相关项目查看影响和建议处理方式' AS summary,
                       '/projects?view=activity' AS href,
                       evidence, occurrence_count, last_detected_at AS occurred_at,
                       status
                FROM evidence_integrity_alerts
                WHERE status <> 'resolved'

                UNION ALL

                SELECT 'RELEASE:' || release_code, 'reconcile_required',
                       '交付结果需要核对',
                       '目标平台的接收结果尚未完全确认',
                       '/projects?view=delivery',
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

    def business_overview(self, *, from_at: datetime, to_at: datetime) -> dict[str, Any]:
        previous_from = from_at - (to_at - from_at)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM content_projects WHERE created_at >= %s AND created_at < %s) AS projects,
                    (SELECT count(*) FROM functional_live_room_plans WHERE created_at >= %s AND created_at < %s) AS live_rooms,
                    (SELECT count(*) FROM functional_video_plans WHERE created_at >= %s AND created_at < %s) AS videos,
                    (SELECT count(*) FROM functional_operation_sessions WHERE started_at >= %s AND started_at < %s) AS sessions,
                    (SELECT count(*) FROM content_projects WHERE created_at >= %s AND created_at < %s) AS previous_projects,
                    (SELECT count(*) FROM functional_live_room_plans WHERE created_at >= %s AND created_at < %s) AS previous_live_rooms,
                    (SELECT count(*) FROM functional_video_plans WHERE created_at >= %s AND created_at < %s) AS previous_videos,
                    (SELECT count(*) FROM functional_operation_sessions WHERE started_at >= %s AND started_at < %s) AS previous_sessions
                """,
                (
                    from_at, to_at, from_at, to_at, from_at, to_at, from_at, to_at,
                    previous_from, from_at, previous_from, from_at, previous_from, from_at,
                    previous_from, from_at,
                ),
            )
            totals = dict(cursor.fetchone())
            cursor.execute(
                """
                WITH days AS (
                    SELECT generate_series(date_trunc('day', %s::timestamptz), date_trunc('day', %s::timestamptz), interval '1 day') AS day
                )
                SELECT day,
                       (SELECT count(*) FROM content_projects WHERE created_at >= day AND created_at < day + interval '1 day') AS projects,
                       (SELECT count(*) FROM functional_live_room_plans WHERE created_at >= day AND created_at < day + interval '1 day') AS live_rooms,
                       (SELECT count(*) FROM functional_video_plans WHERE created_at >= day AND created_at < day + interval '1 day') AS videos,
                       (SELECT count(*) FROM functional_operation_sessions WHERE started_at >= day AND started_at < day + interval '1 day') AS sessions
                FROM days ORDER BY day
                """,
                (from_at, to_at),
            )
            trend = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT project.project_code, project.title, count(session.id)::integer AS session_count,
                       max(session.started_at) AS last_session_at
                FROM content_projects AS project
                JOIN functional_operation_sessions AS session ON session.content_project_code = project.project_code
                WHERE session.started_at >= %s AND session.started_at < %s
                GROUP BY project.project_code, project.title
                ORDER BY session_count DESC, last_session_at DESC
                LIMIT 8
                """,
                (from_at, to_at),
            )
            rankings = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM assets WHERE deleted_at IS NULL AND status IN ('ready', 'stored')) AS ready_assets,
                    (SELECT count(*) FROM live_room_templates WHERE status = 'published') AS published_templates,
                    (SELECT count(*) FROM functional_knowledge_facts WHERE status = 'approved') AS approved_facts,
                    (SELECT count(*) FROM functional_operation_sessions WHERE content_project_code IS NOT NULL) AS bound_sessions,
                    (SELECT count(*) FROM functional_operation_sessions) AS total_sessions
                """
            )
            coverage = dict(cursor.fetchone())
            cursor.execute(
                """
                SELECT project.project_code, project.title, project.status,
                       EXISTS (SELECT 1 FROM functional_live_room_plans AS room WHERE room.project_code = project.project_code) AS has_live_room,
                       EXISTS (SELECT 1 FROM functional_video_plans AS video WHERE video.project_code = project.project_code) AS has_video,
                       (SELECT count(*) FROM functional_operation_sessions AS session WHERE session.content_project_code = project.project_code)::integer AS session_count,
                       project.updated_at
                FROM content_projects AS project
                WHERE project.archived_at IS NULL
                ORDER BY project.updated_at DESC
                LIMIT 8
                """
            )
            recent_projects = [dict(row) for row in cursor.fetchall()]
        return {
            "from_date": from_at,
            "to_date": to_at,
            "metrics": [
                {"key": "projects", "label": "新建内容项目", "value": totals["projects"], "previous_value": totals["previous_projects"], "unit": "个"},
                {"key": "live_rooms", "label": "直播间方案", "value": totals["live_rooms"], "previous_value": totals["previous_live_rooms"], "unit": "份"},
                {"key": "videos", "label": "成片制作", "value": totals["videos"], "previous_value": totals["previous_videos"], "unit": "条"},
                {"key": "sessions", "label": "已关联场次", "value": totals["sessions"], "previous_value": totals["previous_sessions"], "unit": "场"},
            ],
            "trend": [{"date": row["day"], **{key: row[key] for key in ("projects", "live_rooms", "videos", "sessions")}} for row in trend],
            "rankings": rankings,
            "coverage": coverage,
            "recent_projects": recent_projects,
        }
