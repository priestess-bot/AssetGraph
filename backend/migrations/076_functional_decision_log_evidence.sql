-- Decision logs retain their own evidence snapshot so downstream drafts can be
-- reconstructed without inferring a decision from mutable current state.

ALTER TABLE functional_decision_logs
    ADD COLUMN IF NOT EXISTS decision_type VARCHAR(64) NOT NULL DEFAULT 'manual_recommendation',
    ADD COLUMN IF NOT EXISTS decision_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS fingerprint_sha256 CHAR(64);

ALTER TABLE functional_decision_logs
    ADD CONSTRAINT chk_functional_decision_payload CHECK (
        jsonb_typeof(decision_payload) = 'object'
    ) NOT VALID;

ALTER TABLE functional_decision_logs
    ADD CONSTRAINT chk_functional_decision_source_refs CHECK (
        jsonb_typeof(source_revision_refs) = 'array'
    ) NOT VALID;

ALTER TABLE functional_decision_logs
    ADD CONSTRAINT chk_functional_decision_fingerprint CHECK (
        fingerprint_sha256 IS NULL OR fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    ) NOT VALID;
