-- Forward fix: append-only deletion receipts must support later retry attempts.

ALTER TABLE deletion_runs
    ADD COLUMN IF NOT EXISTS request_fingerprint CHAR(64);

UPDATE deletion_runs
SET request_fingerprint = encode(
    digest(
        convert_to(
            jsonb_build_object(
                'subject_type', subject_type,
                'subject_code', subject_code,
                'requested_scope', requested_scope,
                'required_processors', required_processors,
                'requested_by', requested_by,
                'requested_at', requested_at
            )::text,
            'UTF8'
        ),
        'sha256'
    ),
    'hex'
)
WHERE request_fingerprint IS NULL;

ALTER TABLE deletion_runs
    ALTER COLUMN request_fingerprint SET NOT NULL,
    ADD CONSTRAINT chk_deletion_run_request_sha CHECK (request_fingerprint ~ '^[0-9a-f]{64}$');

CREATE UNIQUE INDEX IF NOT EXISTS uq_deletion_runs_request_fingerprint
    ON deletion_runs(request_fingerprint);

ALTER TABLE deletion_receipts
    ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1,
    DROP CONSTRAINT IF EXISTS deletion_receipts_deletion_run_id_processor_target_type_tar_key,
    ADD CONSTRAINT uq_deletion_receipt_attempt
        UNIQUE (deletion_run_id, processor, target_type, target_code, attempt),
    ADD CONSTRAINT chk_deletion_receipt_attempt CHECK (attempt >= 1);

INSERT INTO deletion_run_status_history (
    deletion_run_id, deletion_run_code, revision, from_status, to_status,
    actor_id, reason_code, evidence, occurred_at
)
SELECT run.id, run.deletion_run_code, run.revision, NULL, run.status,
       'migration-039', 'LEGACY_DELETION_RUN_SNAPSHOT',
       jsonb_build_object('source', 'pre-039-current-state'), run.requested_at
FROM deletion_runs AS run
ON CONFLICT (deletion_run_id, revision) DO NOTHING;
