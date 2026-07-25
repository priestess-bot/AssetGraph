-- A confirmed experiment assignment is evidence, not an implicit recomputation.

CREATE TABLE IF NOT EXISTS functional_experiment_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_code VARCHAR(80) NOT NULL UNIQUE,
    experiment_code VARCHAR(64) NOT NULL REFERENCES functional_experiments(experiment_code) ON DELETE CASCADE,
    subject_key VARCHAR(255) NOT NULL,
    variant_key VARCHAR(80) NOT NULL,
    assignment_strategy VARCHAR(64) NOT NULL,
    registration_fingerprint_sha256 CHAR(64),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (experiment_code, subject_key),
    CONSTRAINT chk_functional_experiment_assignment_strategy CHECK (
        assignment_strategy IN ('stable_hash_sha256_v1', 'legacy_outcome_backfill_v1')
    ),
    CONSTRAINT chk_functional_experiment_assignment_fingerprint CHECK (
        registration_fingerprint_sha256 IS NULL
        OR registration_fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    )
);

-- Outcomes recorded before Assignment existed remain attributable to their
-- original stored variant, but are visibly marked as legacy backfills.
INSERT INTO functional_experiment_assignments (
    assignment_code, experiment_code, subject_key, variant_key, assignment_strategy,
    registration_fingerprint_sha256
)
SELECT
    'ASSIGN-LEGACY-' || md5(outcome.experiment_code || ':' || outcome.subject_key),
    outcome.experiment_code,
    outcome.subject_key,
    outcome.variant_key,
    'legacy_outcome_backfill_v1',
    experiment.registration_fingerprint_sha256
FROM functional_experiment_outcomes AS outcome
JOIN functional_experiments AS experiment
  ON experiment.experiment_code = outcome.experiment_code
ON CONFLICT (experiment_code, subject_key) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_functional_experiment_assignments_experiment
    ON functional_experiment_assignments (experiment_code, assigned_at DESC);
