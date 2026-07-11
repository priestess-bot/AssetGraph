-- Phase 6C-A: operation-level checkpoints for reclaim-safe retry side effects.

CREATE TABLE IF NOT EXISTS maitu_retry_operation_checkpoints (
    retry_task_code VARCHAR(64) NOT NULL REFERENCES maitu_execution_retry_tasks(retry_task_code),
    operation_key VARCHAR(128) NOT NULL,
    operation_fingerprint VARCHAR(64) NOT NULL,
    state VARCHAR(32) NOT NULL,
    attempt_id UUID NOT NULL,
    begun_by VARCHAR(128) NOT NULL,
    begun_lease_version BIGINT NOT NULL,
    completion_id UUID,
    completion_fingerprint VARCHAR(64),
    completion_summary TEXT,
    completed_by VARCHAR(128),
    completed_lease_version BIGINT,
    completion_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    begun_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (retry_task_code, operation_key),
    CONSTRAINT chk_maitu_retry_checkpoint_state
        CHECK (state IN ('begun', 'reconcile_required', 'completed')),
    CONSTRAINT chk_maitu_retry_checkpoint_fingerprint
        CHECK (operation_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_retry_checkpoint_begun_version
        CHECK (begun_lease_version >= 1),
    CONSTRAINT chk_maitu_retry_checkpoint_completion_version
        CHECK (completed_lease_version IS NULL OR completed_lease_version >= 1),
    CONSTRAINT chk_maitu_retry_checkpoint_completion_fields
        CHECK (
            (state = 'completed' AND completion_id IS NOT NULL
                AND completion_fingerprint IS NOT NULL AND completed_by IS NOT NULL
                AND completed_lease_version IS NOT NULL AND completed_at IS NOT NULL)
            OR
            (state <> 'completed' AND completion_id IS NULL
                AND completion_fingerprint IS NULL AND completed_by IS NULL
                AND completed_lease_version IS NULL AND completed_at IS NULL)
        ),
    CONSTRAINT chk_maitu_retry_checkpoint_verified_evidence
        CHECK (state <> 'completed' OR completion_evidence @> '{"verified": true}'::jsonb)
);

ALTER TABLE maitu_retry_operation_checkpoints
    ADD COLUMN IF NOT EXISTS completion_summary TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_maitu_retry_checkpoint_verified_evidence'
            AND conrelid = 'maitu_retry_operation_checkpoints'::regclass
    ) THEN
        ALTER TABLE maitu_retry_operation_checkpoints
            ADD CONSTRAINT chk_maitu_retry_checkpoint_verified_evidence
            CHECK (state <> 'completed' OR completion_evidence @> '{"verified": true}'::jsonb);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_maitu_retry_operation_checkpoints_state
    ON maitu_retry_operation_checkpoints(state);

CREATE INDEX IF NOT EXISTS idx_maitu_retry_operation_checkpoints_attempt
    ON maitu_retry_operation_checkpoints(attempt_id);

CREATE INDEX IF NOT EXISTS idx_maitu_retry_operation_checkpoints_completion
    ON maitu_retry_operation_checkpoints(completion_id)
    WHERE completion_id IS NOT NULL;
