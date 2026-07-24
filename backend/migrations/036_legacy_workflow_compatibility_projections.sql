-- Read-only WorkflowRun/StepRun compatibility projections over legacy queues.

CREATE OR REPLACE VIEW legacy_workflow_run_projections_v1 AS
SELECT 'LEGACY-WORKBENCH:' || run.run_code AS projection_run_code,
       'maitu_workbench_run'::varchar AS source_type,
       run.run_code::varchar AS source_code,
       'legacy_live_room_workbench'::varchar AS workflow_type,
       'live_room_configuration'::varchar AS subject_type,
       run.run_code::varchar AS subject_code,
       NULL::integer AS subject_revision,
       CASE run.status
           WHEN 'draft' THEN 'queued'
           WHEN 'planning' THEN 'running'
           WHEN 'execution_queued' THEN 'queued'
           WHEN 'executing' THEN 'running'
           WHEN 'completed' THEN 'succeeded'
           WHEN 'failed' THEN 'failed'
           ELSE 'waiting_human'
       END::varchar AS status,
       100::integer AS priority,
       CASE WHEN run.status = 'completed' THEN 1 ELSE 0 END::integer AS progress_completed,
       1::integer AS progress_total,
       CASE WHEN run.status IN ('ready', 'blocked', 'replan_required', 'preflight_passed')
            THEN run.status ELSE NULL END::varchar AS waiting_reason,
       run.error_code::varchar AS error_code,
       run.error_message::text AS error_summary,
       run.created_at,
       run.updated_at,
       NULL::timestamptz AS started_at,
       run.completed_at,
       jsonb_build_object(
           'title', run.title,
           'topic', run.topic,
           'legacy_status', run.status,
           'target_live_room_id', run.target_live_room_id,
           'active_plan_revision', run.active_plan_revision,
           'production_variant_revision_id', run.production_variant_revision_id,
           'live_room_configuration_revision_id', run.live_room_configuration_revision_id
       ) AS source_snapshot,
       'legacy_import'::varchar AS mapping_quality,
       true AS read_only
FROM maitu_workbench_runs AS run

UNION ALL

SELECT 'LEGACY-VIDEO:' || job.job_code,
       'video_production_job', job.job_code, 'legacy_rendered_video',
       'rendered_video_variant', job.job_code, NULL::integer,
       CASE job.status
           WHEN 'queued' THEN 'queued' WHEN 'running' THEN 'running'
           WHEN 'succeeded' THEN 'succeeded' ELSE 'failed'
       END,
       100, job.progress_percent, 100, NULL::varchar,
       job.error_code, job.error_message, job.created_at, job.updated_at,
       job.started_at, job.completed_at,
       jsonb_build_object(
           'topic', job.topic,
           'preset_code', job.preset_code,
           'legacy_status', job.status,
           'current_stage', job.current_stage,
           'production_variant_revision_id', job.production_variant_revision_id
       ),
       'legacy_import', true
FROM video_production_jobs AS job

UNION ALL

SELECT 'LEGACY-CAPTURE:' || session.session_code,
       'live_capture_session', session.session_code, 'legacy_live_capture',
       'capture_session', session.session_code, NULL::integer,
       CASE session.status
           WHEN 'starting' THEN 'running' WHEN 'recording' THEN 'running'
           WHEN 'finalizing' THEN 'running' WHEN 'completed' THEN 'succeeded'
           WHEN 'abandoned' THEN 'cancelled' ELSE 'failed'
       END,
       100, CASE WHEN session.status = 'completed' THEN 1 ELSE 0 END, 1,
       NULL::varchar, session.failure_code, session.failure_message,
       session.created_at, session.updated_at, session.started_at, session.ended_at,
       jsonb_build_object(
           'target_code', session.target_code,
           'platform', session.platform,
           'legacy_status', session.status,
           'source_live_session_id', session.source_live_session_id,
           'recorder_engine', session.recorder_engine,
           'recorder_version', session.recorder_version
       ),
       'legacy_import', true
FROM live_capture_sessions AS session

UNION ALL

SELECT 'LEGACY-CLIP:' || job.clip_job_code,
       'live_clip_job', job.clip_job_code, 'legacy_live_clip',
       'capture_session', job.session_code, NULL::integer,
       CASE job.status
           WHEN 'queued' THEN 'queued' WHEN 'running' THEN 'running'
           WHEN 'succeeded' THEN 'succeeded' WHEN 'cancelled' THEN 'cancelled'
           ELSE 'failed'
       END,
       100, CASE WHEN job.status = 'succeeded' THEN 1 ELSE 0 END, 1,
       NULL::varchar, job.error_code, job.error_message,
       job.created_at, job.updated_at, job.started_at, job.completed_at,
       jsonb_build_object(
           'session_code', job.session_code,
           'legacy_status', job.status,
           'cut_mode', job.cut_mode,
           'requested_start_seconds', job.requested_start_seconds,
           'requested_end_seconds', job.requested_end_seconds
       ),
       'legacy_import', true
FROM live_clip_jobs AS job

UNION ALL

SELECT 'LEGACY-ANALYSIS:' || run.analysis_run_code,
       'live_analysis_run', run.analysis_run_code, 'legacy_live_analysis',
       'capture_session', run.session_code, NULL::integer,
       CASE run.status
           WHEN 'queued' THEN 'queued' WHEN 'running' THEN 'running'
           WHEN 'succeeded' THEN 'succeeded' WHEN 'cancelled' THEN 'cancelled'
           ELSE 'failed'
       END,
       100, CASE WHEN run.status = 'succeeded' THEN 1 ELSE 0 END, 1,
       NULL::varchar, run.error_code, run.error_message,
       run.created_at, run.updated_at, run.started_at, run.completed_at,
       jsonb_build_object(
           'session_code', run.session_code,
           'legacy_status', run.status,
           'analysis_type', run.analysis_type,
           'input_fingerprint', run.input_fingerprint,
           'attempt_count', run.attempt_count,
           'max_attempts', run.max_attempts
       ),
       'legacy_import', true
FROM live_analysis_runs AS run

UNION ALL

SELECT 'LEGACY-RETRY:' || task.retry_task_code,
       'maitu_retry_task', task.retry_task_code, 'legacy_maitu_retry',
       'maitu_build_plan', task.plan_code, NULL::integer,
       CASE task.status
           WHEN 'pending' THEN 'queued' WHEN 'in_progress' THEN 'running'
           WHEN 'resolved' THEN 'succeeded' WHEN 'manual_required' THEN 'waiting_human'
           WHEN 'failed' THEN 'failed' ELSE 'reconcile_required'
       END,
       50, CASE WHEN task.status = 'resolved' THEN 1 ELSE 0 END, 1,
       CASE WHEN task.status = 'manual_required' THEN 'manual_required' ELSE NULL END,
       task.failure_type, task.error_message,
       task.created_at, task.updated_at, task.claimed_at,
       CASE WHEN task.status IN ('resolved', 'failed') THEN task.updated_at ELSE NULL END,
       jsonb_build_object(
           'plan_code', task.plan_code,
           'execution_code', task.execution_code,
           'slot_code', task.slot_code,
           'asset_code', task.asset_code,
           'legacy_status', task.status,
           'retry_attempt_count', task.retry_attempt_count,
           'lease_version', task.lease_version
       ),
       'legacy_import', true
FROM maitu_execution_retry_tasks AS task
WHERE task.deleted_at IS NULL;

CREATE OR REPLACE VIEW legacy_workflow_step_projections_v1 AS
SELECT 'LEGACY-WORKBENCH-STEP:' || run.run_code AS projection_step_code,
       'LEGACY-WORKBENCH:' || run.run_code AS projection_run_code,
       'maitu_workbench_run'::varchar AS source_type,
       run.run_code::varchar AS source_code,
       'legacy_workbench_lifecycle'::varchar AS step_type,
       0::integer AS sort_order,
       CASE run.status
           WHEN 'draft' THEN 'pending' WHEN 'planning' THEN 'running'
           WHEN 'execution_queued' THEN 'pending' WHEN 'executing' THEN 'running'
           WHEN 'completed' THEN 'succeeded' WHEN 'failed' THEN 'failed'
           ELSE 'waiting_human'
       END::varchar AS status,
       1::integer AS attempt,
       run.error_code::varchar AS error_code,
       run.error_message::text AS error_summary,
       NULL::timestamptz AS started_at,
       run.completed_at,
       jsonb_build_object('legacy_status', run.status) AS source_snapshot,
       true AS read_only
FROM maitu_workbench_runs AS run

UNION ALL

SELECT 'LEGACY-VIDEO-STEP:' || stage.job_code || ':' || stage.stage_name,
       'LEGACY-VIDEO:' || stage.job_code,
       'video_production_stage', stage.job_code || ':' || stage.stage_name,
       stage.stage_name, stage.stage_order,
       CASE stage.status
           WHEN 'pending' THEN 'pending' WHEN 'running' THEN 'running'
           WHEN 'succeeded' THEN 'succeeded' ELSE 'failed'
       END,
       stage.attempt, stage.error_code, stage.error_message,
       stage.started_at, stage.completed_at,
       jsonb_build_object('legacy_status', stage.status), true
FROM video_production_stages AS stage

UNION ALL

SELECT 'LEGACY-CAPTURE-STEP:' || session.session_code,
       'LEGACY-CAPTURE:' || session.session_code,
       'live_capture_session', session.session_code, 'capture', 0,
       CASE session.status
           WHEN 'starting' THEN 'running' WHEN 'recording' THEN 'running'
           WHEN 'finalizing' THEN 'running' WHEN 'completed' THEN 'succeeded'
           WHEN 'abandoned' THEN 'cancelled' ELSE 'failed'
       END,
       1, session.failure_code, session.failure_message,
       session.started_at, session.ended_at,
       jsonb_build_object('legacy_status', session.status), true
FROM live_capture_sessions AS session

UNION ALL

SELECT 'LEGACY-CLIP-STEP:' || job.clip_job_code,
       'LEGACY-CLIP:' || job.clip_job_code,
       'live_clip_job', job.clip_job_code, 'clip', 0,
       CASE job.status
           WHEN 'queued' THEN 'pending' WHEN 'running' THEN 'running'
           WHEN 'succeeded' THEN 'succeeded' WHEN 'cancelled' THEN 'cancelled'
           ELSE 'failed'
       END,
       1, job.error_code, job.error_message, job.started_at, job.completed_at,
       jsonb_build_object('legacy_status', job.status), true
FROM live_clip_jobs AS job

UNION ALL

SELECT 'LEGACY-ANALYSIS-STEP:' || run.analysis_run_code,
       'LEGACY-ANALYSIS:' || run.analysis_run_code,
       'live_analysis_run', run.analysis_run_code, run.analysis_type, 0,
       CASE run.status
           WHEN 'queued' THEN 'pending' WHEN 'running' THEN 'running'
           WHEN 'succeeded' THEN 'succeeded' WHEN 'cancelled' THEN 'cancelled'
           ELSE 'failed'
       END,
       GREATEST(run.attempt_count, 1), run.error_code, run.error_message,
       run.started_at, run.completed_at,
       jsonb_build_object('legacy_status', run.status, 'input_fingerprint', run.input_fingerprint), true
FROM live_analysis_runs AS run

UNION ALL

SELECT 'LEGACY-RETRY-STEP:' || task.retry_task_code,
       'LEGACY-RETRY:' || task.retry_task_code,
       'maitu_retry_task', task.retry_task_code, 'retry_external_operation', 0,
       CASE task.status
           WHEN 'pending' THEN 'pending' WHEN 'in_progress' THEN 'running'
           WHEN 'resolved' THEN 'succeeded' WHEN 'manual_required' THEN 'waiting_human'
           WHEN 'failed' THEN 'failed' ELSE 'reconcile_required'
       END,
       GREATEST(task.retry_attempt_count, 1), task.failure_type, task.error_message,
       task.claimed_at,
       CASE WHEN task.status IN ('resolved', 'failed') THEN task.updated_at ELSE NULL END,
       jsonb_build_object(
           'legacy_status', task.status,
           'claim_expires_at', task.claim_expires_at,
           'lease_version', task.lease_version
       ), true
FROM maitu_execution_retry_tasks AS task
WHERE task.deleted_at IS NULL;

COMMENT ON VIEW legacy_workflow_run_projections_v1 IS
    'Read-only compatibility projection. Source tables remain authoritative; no WorkflowRun is fabricated.';
COMMENT ON VIEW legacy_workflow_step_projections_v1 IS
    'Read-only compatibility projection. Mutations must use the owning legacy API until migration is complete.';
