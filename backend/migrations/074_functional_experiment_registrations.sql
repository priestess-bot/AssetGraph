-- Registration is immutable once an experiment is created. Legacy experiments
-- retain an empty registration because their original plan was never recorded.

ALTER TABLE functional_experiments
    ADD COLUMN IF NOT EXISTS registration JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS assignment_strategy VARCHAR(64) NOT NULL DEFAULT 'stable_hash_sha256_v1',
    ADD COLUMN IF NOT EXISTS registration_fingerprint_sha256 CHAR(64);

ALTER TABLE functional_experiments
    ADD CONSTRAINT chk_functional_experiment_registration CHECK (
        jsonb_typeof(registration) = 'object'
    ) NOT VALID;

ALTER TABLE functional_experiments
    ADD CONSTRAINT chk_functional_experiment_assignment_strategy CHECK (
        assignment_strategy = 'stable_hash_sha256_v1'
    ) NOT VALID;

ALTER TABLE functional_experiments
    ADD CONSTRAINT chk_functional_experiment_registration_fingerprint CHECK (
        registration_fingerprint_sha256 IS NULL
        OR registration_fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    ) NOT VALID;
