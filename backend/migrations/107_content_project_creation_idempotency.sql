-- Resumable product entry: a lost create response must not duplicate a project.

ALTER TABLE content_projects
    ADD COLUMN IF NOT EXISTS creation_idempotency_key VARCHAR(128),
    ADD COLUMN IF NOT EXISTS creation_input_fingerprint CHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_projects_creation_idempotency_key
ON content_projects(creation_idempotency_key)
WHERE creation_idempotency_key IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_content_projects_creation_idempotency_pair'
          AND conrelid = 'content_projects'::regclass
    ) THEN
        ALTER TABLE content_projects
            ADD CONSTRAINT chk_content_projects_creation_idempotency_pair CHECK (
                (creation_idempotency_key IS NULL AND creation_input_fingerprint IS NULL)
                OR (
                    creation_idempotency_key IS NOT NULL
                    AND btrim(creation_idempotency_key) <> ''
                    AND creation_input_fingerprint ~ '^[0-9a-f]{64}$'
                )
            );
    END IF;
END $$;
