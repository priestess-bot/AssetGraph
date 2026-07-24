-- Preserve the external identity and source context of an observed operation
-- session. Nullable fields retain compatibility with older manual imports.

ALTER TABLE functional_operation_sessions
    ADD COLUMN IF NOT EXISTS external_session_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS account_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS target_resource_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS source_timezone VARCHAR(64) NOT NULL DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS source_evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE functional_operation_sessions
    ADD CONSTRAINT chk_functional_operation_source_evidence
    CHECK (jsonb_typeof(source_evidence) = 'object');

CREATE UNIQUE INDEX IF NOT EXISTS uq_functional_operation_platform_external_session
    ON functional_operation_sessions (platform, external_session_id)
    WHERE external_session_id IS NOT NULL;
