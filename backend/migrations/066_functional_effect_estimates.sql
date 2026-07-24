-- Functional effect evidence is derived from an immutable descriptive report.
-- New revisions are appended; approval never changes the underlying report.

CREATE TABLE IF NOT EXISTS functional_effect_estimates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    effect_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    attribution_report_code VARCHAR(64) NOT NULL REFERENCES functional_attribution_reports(report_code),
    subject_type VARCHAR(64) NOT NULL,
    subject_code VARCHAR(128) NOT NULL,
    metric_key VARCHAR(80) NOT NULL,
    evidence_level VARCHAR(32) NOT NULL DEFAULT 'descriptive',
    status VARCHAR(32) NOT NULL DEFAULT 'candidate',
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    effect_payload JSONB NOT NULL,
    eligibility_snapshot JSONB NOT NULL,
    note TEXT NOT NULL,
    approved_by VARCHAR(128),
    approved_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (effect_code, revision_number),
    CONSTRAINT chk_functional_effect_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_functional_effect_level CHECK (evidence_level IN ('descriptive', 'associational')),
    CONSTRAINT chk_functional_effect_status CHECK (status IN ('candidate', 'approved', 'revoked', 'superseded')),
    CONSTRAINT chk_functional_effect_context CHECK (jsonb_typeof(context) = 'object'),
    CONSTRAINT chk_functional_effect_payload CHECK (jsonb_typeof(effect_payload) = 'object'),
    CONSTRAINT chk_functional_effect_eligibility CHECK (jsonb_typeof(eligibility_snapshot) = 'object'),
    CONSTRAINT chk_functional_effect_fingerprint CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_effect_approval CHECK (
        (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
        OR status <> 'approved'
    )
);

CREATE INDEX IF NOT EXISTS idx_functional_effect_estimates_subject
    ON functional_effect_estimates(subject_type, subject_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_functional_effect_estimates_report
    ON functional_effect_estimates(attribution_report_code, created_at DESC);
