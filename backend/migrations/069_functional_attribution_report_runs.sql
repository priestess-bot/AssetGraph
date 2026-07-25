-- A descriptive attribution report is a frozen computation snapshot. Its
-- publication state is distinct from its evidence level: a published
-- descriptive result must never be interpreted as a causal result.

ALTER TABLE functional_attribution_reports
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS fingerprint_sha256 CHAR(64),
    ADD COLUMN IF NOT EXISTS supersedes_report_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS published_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

ALTER TABLE functional_attribution_reports
    DROP CONSTRAINT IF EXISTS chk_functional_attribution_report_status,
    ADD CONSTRAINT chk_functional_attribution_report_status CHECK (
        status IN ('legacy', 'review_required', 'insufficient_data', 'published_descriptive', 'superseded', 'failed')
    ),
    DROP CONSTRAINT IF EXISTS chk_functional_attribution_input_snapshot,
    ADD CONSTRAINT chk_functional_attribution_input_snapshot CHECK (jsonb_typeof(input_snapshot) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_functional_attribution_quality_snapshot,
    ADD CONSTRAINT chk_functional_attribution_quality_snapshot CHECK (jsonb_typeof(quality_snapshot) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_functional_attribution_fingerprint,
    ADD CONSTRAINT chk_functional_attribution_fingerprint CHECK (
        fingerprint_sha256 IS NULL OR fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    ),
    DROP CONSTRAINT IF EXISTS chk_functional_attribution_publication,
    ADD CONSTRAINT chk_functional_attribution_publication CHECK (
        (status = 'published_descriptive' AND published_by IS NOT NULL AND published_at IS NOT NULL)
        OR status <> 'published_descriptive'
    );

CREATE INDEX IF NOT EXISTS idx_functional_attribution_reports_status_created
    ON functional_attribution_reports (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_functional_attribution_reports_supersedes
    ON functional_attribution_reports (supersedes_report_code)
    WHERE supersedes_report_code IS NOT NULL;
