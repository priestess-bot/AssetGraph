-- Connect Functional Live Room Plans to the leased Maitu worker protocol.
-- Existing workbench-run jobs remain valid; functional jobs use a verified
-- browser readback instead of the currently unavailable backend authority API.

CREATE TABLE IF NOT EXISTS maitu_live_room_inspection_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    inspection_code VARCHAR(80) NOT NULL UNIQUE,
    target_live_room_id VARCHAR(128) NOT NULL,
    expected_title VARCHAR(255),
    authority_mode VARCHAR(32) NOT NULL DEFAULT 'worker_readback',
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt INTEGER NOT NULL DEFAULT 1,
    input_fingerprint CHAR(64) NOT NULL,
    idempotency_key VARCHAR(128),
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    room_fingerprint CHAR(64),
    claimed_by VARCHAR(128),
    lease_token UUID,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    error_code VARCHAR(64),
    error_message TEXT,
    requested_by VARCHAR(128),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_maitu_room_inspection_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    CONSTRAINT chk_maitu_room_inspection_authority
        CHECK (authority_mode IN ('worker_readback', 'independent_backend')),
    CONSTRAINT chk_maitu_room_inspection_attempt CHECK (attempt >= 1),
    CONSTRAINT chk_maitu_room_inspection_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_room_inspection_result CHECK (jsonb_typeof(result) = 'object'),
    CONSTRAINT chk_maitu_room_inspection_lease
        CHECK (
            (claimed_by IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
            OR (claimed_by IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        ),
    CONSTRAINT chk_maitu_room_inspection_terminal
        CHECK (
            (status IN ('succeeded', 'failed') AND completed_at IS NOT NULL)
            OR status NOT IN ('succeeded', 'failed')
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_room_inspection_idempotency
    ON maitu_live_room_inspection_jobs(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_maitu_room_inspection_claim
    ON maitu_live_room_inspection_jobs(status, created_at);

ALTER TABLE maitu_workbench_draft_execution_jobs
    ADD COLUMN IF NOT EXISTS source_kind VARCHAR(32) NOT NULL DEFAULT 'workbench_run',
    ADD COLUMN IF NOT EXISTS functional_plan_id UUID REFERENCES functional_live_room_plans(id),
    ADD COLUMN IF NOT EXISTS functional_plan_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(32) NOT NULL DEFAULT 'fresh_draft',
    ADD COLUMN IF NOT EXISTS authority_mode VARCHAR(32) NOT NULL DEFAULT 'independent_backend',
    ADD COLUMN IF NOT EXISTS room_inspection_id UUID REFERENCES maitu_live_room_inspection_jobs(id),
    ADD COLUMN IF NOT EXISTS room_inspection_code VARCHAR(80),
    ADD COLUMN IF NOT EXISTS room_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS room_fingerprint CHAR(64),
    ADD COLUMN IF NOT EXISTS stage VARCHAR(64) NOT NULL DEFAULT 'queued',
    ADD COLUMN IF NOT EXISTS progress_current INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS progress_total INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS stage_events JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE maitu_workbench_draft_execution_jobs
    ALTER COLUMN run_id DROP NOT NULL,
    ALTER COLUMN run_code DROP NOT NULL,
    ALTER COLUMN plan_revision_id DROP NOT NULL,
    ALTER COLUMN plan_revision_number DROP NOT NULL,
    ALTER COLUMN preflight_id DROP NOT NULL,
    ALTER COLUMN preflight_code DROP NOT NULL;

ALTER TABLE maitu_workbench_draft_execution_jobs
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_status;

ALTER TABLE maitu_workbench_draft_execution_jobs
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_source_kind,
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_mode,
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_authority,
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_source,
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_room_snapshot,
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_stage_events,
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_progress;

ALTER TABLE maitu_workbench_draft_execution_jobs
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_status
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'reconcile_required', 'cancelled')),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_source_kind
        CHECK (source_kind IN ('workbench_run', 'functional_live_room_plan')),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_mode
        CHECK (execution_mode IN ('fresh_draft', 'replace_test_draft')),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_authority
        CHECK (authority_mode IN ('worker_readback', 'independent_backend')),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_source
        CHECK (
            (source_kind = 'workbench_run' AND run_id IS NOT NULL AND functional_plan_id IS NULL)
            OR
            (source_kind = 'functional_live_room_plan' AND run_id IS NULL AND functional_plan_id IS NOT NULL)
        ),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_room_snapshot
        CHECK (jsonb_typeof(room_snapshot) = 'object'),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_stage_events
        CHECK (jsonb_typeof(stage_events) = 'array'),
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_progress
        CHECK (progress_current >= 0 AND progress_total >= 0 AND progress_current <= progress_total);

ALTER TABLE maitu_workbench_draft_execution_jobs
    DROP CONSTRAINT IF EXISTS chk_maitu_workbench_draft_execution_terminal;

ALTER TABLE maitu_workbench_draft_execution_jobs
    ADD CONSTRAINT chk_maitu_workbench_draft_execution_terminal
        CHECK (
            (status IN ('succeeded', 'failed', 'reconcile_required', 'cancelled') AND completed_at IS NOT NULL)
            OR status NOT IN ('succeeded', 'failed', 'reconcile_required', 'cancelled')
        );

CREATE INDEX IF NOT EXISTS idx_maitu_workbench_draft_functional_plan
    ON maitu_workbench_draft_execution_jobs(functional_plan_code, created_at DESC)
    WHERE functional_plan_code IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_maitu_workbench_draft_one_active_functional_plan
    ON maitu_workbench_draft_execution_jobs(functional_plan_id)
    WHERE source_kind = 'functional_live_room_plan'
      AND functional_plan_id IS NOT NULL
      AND status IN ('queued', 'running', 'reconcile_required');

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS execution_job_code VARCHAR(80),
    ADD COLUMN IF NOT EXISTS room_inspection_code VARCHAR(80),
    ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(32),
    ADD COLUMN IF NOT EXISTS execution_authority_mode VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_functional_live_room_execution_job
    ON functional_live_room_plans(execution_job_code)
    WHERE execution_job_code IS NOT NULL;
