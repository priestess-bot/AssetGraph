-- Phase 6B: retry worker lease ownership, heartbeats, and idempotent result receipts.

ALTER TABLE maitu_execution_retry_tasks
    ADD COLUMN IF NOT EXISTS claim_token UUID,
    ADD COLUMN IF NOT EXISTS lease_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_retry_execution_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_maitu_retry_tasks_lease_version_nonnegative'
          AND conrelid = 'maitu_execution_retry_tasks'::regclass
    ) THEN
        ALTER TABLE maitu_execution_retry_tasks
            ADD CONSTRAINT chk_maitu_retry_tasks_lease_version_nonnegative CHECK (lease_version >= 0);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_claim_token
    ON maitu_execution_retry_tasks(claim_token)
    WHERE claim_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_maitu_retry_tasks_last_execution_id
    ON maitu_execution_retry_tasks(last_retry_execution_id)
    WHERE last_retry_execution_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS maitu_retry_execution_receipts (
    retry_execution_id UUID PRIMARY KEY,
    retry_task_code VARCHAR(64) NOT NULL REFERENCES maitu_execution_retry_tasks(retry_task_code),
    claimed_by VARCHAR(128) NOT NULL,
    lease_version BIGINT NOT NULL CHECK (lease_version >= 1),
    retry_execution_status VARCHAR(32) NOT NULL,
    result_fingerprint VARCHAR(64) NOT NULL,
    result_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maitu_retry_execution_receipts_task_code
    ON maitu_retry_execution_receipts(retry_task_code);
