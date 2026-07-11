-- Phase 6C-B: audited, idempotent resolution of uncertain retry operations.

ALTER TABLE maitu_retry_operation_checkpoints
    ADD COLUMN IF NOT EXISTS completion_source VARCHAR(32),
    ADD COLUMN IF NOT EXISTS completion_reconciliation_id UUID;

UPDATE maitu_retry_operation_checkpoints
SET completion_source = 'worker'
WHERE state = 'completed' AND completion_source IS NULL;

ALTER TABLE maitu_retry_operation_checkpoints
    DROP CONSTRAINT IF EXISTS chk_maitu_retry_checkpoint_state;
ALTER TABLE maitu_retry_operation_checkpoints
    ADD CONSTRAINT chk_maitu_retry_checkpoint_state
    CHECK (state IN ('begun', 'reconcile_required', 'retry_authorized', 'completed'));

ALTER TABLE maitu_retry_operation_checkpoints
    DROP CONSTRAINT IF EXISTS chk_maitu_retry_checkpoint_completion_fields;
ALTER TABLE maitu_retry_operation_checkpoints
    ADD CONSTRAINT chk_maitu_retry_checkpoint_completion_fields
    CHECK (
        (
            state = 'completed'
            AND completion_id IS NOT NULL
            AND completion_fingerprint IS NOT NULL
            AND completed_by IS NOT NULL
            AND completed_at IS NOT NULL
            AND (
                (
                    completion_source = 'worker'
                    AND completed_lease_version IS NOT NULL
                    AND completion_reconciliation_id IS NULL
                )
                OR
                (
                    completion_source = 'reconciliation'
                    AND completed_lease_version IS NULL
                    AND completion_reconciliation_id IS NOT NULL
                    AND completion_evidence @> '{"verified": true, "operation_applied": true}'::jsonb
                )
            )
        )
        OR
        (
            state <> 'completed'
            AND completion_id IS NULL
            AND completion_fingerprint IS NULL
            AND completed_by IS NULL
            AND completed_lease_version IS NULL
            AND completed_at IS NULL
            AND completion_source IS NULL
            AND completion_reconciliation_id IS NULL
        )
    );

CREATE TABLE IF NOT EXISTS maitu_retry_operation_reconciliations (
    reconciliation_id UUID PRIMARY KEY,
    retry_task_code VARCHAR(64) NOT NULL,
    operation_key VARCHAR(128) NOT NULL,
    reconciled_attempt_id UUID NOT NULL,
    operation_fingerprint VARCHAR(64) NOT NULL,
    resolution VARCHAR(32) NOT NULL,
    resulting_state VARCHAR(32) NOT NULL,
    resolved_by VARCHAR(128) NOT NULL,
    resolution_summary TEXT NOT NULL,
    evidence JSONB NOT NULL,
    result_fingerprint VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_maitu_retry_operation_reconciliation_checkpoint
        FOREIGN KEY (retry_task_code, operation_key)
        REFERENCES maitu_retry_operation_checkpoints(retry_task_code, operation_key),
    CONSTRAINT uq_maitu_retry_operation_reconciliation_attempt
        UNIQUE (retry_task_code, operation_key, reconciled_attempt_id),
    CONSTRAINT chk_maitu_retry_operation_reconciliation_resolution
        CHECK (resolution IN ('confirmed_completed', 'confirmed_not_applied')),
    CONSTRAINT chk_maitu_retry_operation_reconciliation_resulting_state
        CHECK (
            (resolution = 'confirmed_completed' AND resulting_state = 'completed')
            OR (resolution = 'confirmed_not_applied' AND resulting_state = 'retry_authorized')
        ),
    CONSTRAINT chk_maitu_retry_operation_reconciliation_fingerprint
        CHECK (operation_fingerprint ~ '^[0-9a-f]{64}$' AND result_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_maitu_retry_operation_reconciliation_evidence
        CHECK (
            evidence @> '{"verified": true}'::jsonb
            AND (
                (resolution = 'confirmed_completed' AND evidence @> '{"operation_applied": true}'::jsonb)
                OR
                (resolution = 'confirmed_not_applied' AND evidence @> '{"operation_applied": false}'::jsonb)
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_maitu_retry_operation_reconciliations_task
    ON maitu_retry_operation_reconciliations(retry_task_code, operation_key, created_at);
