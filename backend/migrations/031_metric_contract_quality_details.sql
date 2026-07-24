-- Complete the metric catalog and source-contract semantics required for
-- reproducible attribution. Existing nullable columns preserve legacy rows.

ALTER TABLE metric_definition_revisions
    ADD COLUMN IF NOT EXISTS grain VARCHAR(128),
    ADD COLUMN IF NOT EXISTS currency CHAR(3),
    ADD COLUMN IF NOT EXISTS event_time_field VARCHAR(255),
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(64),
    ADD COLUMN IF NOT EXISTS business_day_boundary VARCHAR(32),
    ADD COLUMN IF NOT EXISTS deduplication_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS refund_window_days INTEGER,
    ADD COLUMN IF NOT EXISTS null_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS outlier_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS schema_compatibility JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_slo JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE metric_definition_revisions
    DROP CONSTRAINT IF EXISTS chk_metric_revision_deduplication,
    ADD CONSTRAINT chk_metric_revision_deduplication CHECK (jsonb_typeof(deduplication_keys) = 'array'),
    DROP CONSTRAINT IF EXISTS chk_metric_revision_refund_window,
    ADD CONSTRAINT chk_metric_revision_refund_window CHECK (refund_window_days IS NULL OR refund_window_days >= 0),
    DROP CONSTRAINT IF EXISTS chk_metric_revision_null_rule,
    ADD CONSTRAINT chk_metric_revision_null_rule CHECK (jsonb_typeof(null_rule) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_metric_revision_outlier_rule,
    ADD CONSTRAINT chk_metric_revision_outlier_rule CHECK (jsonb_typeof(outlier_rule) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_metric_revision_schema_compatibility,
    ADD CONSTRAINT chk_metric_revision_schema_compatibility CHECK (jsonb_typeof(schema_compatibility) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_metric_revision_quality_slo,
    ADD CONSTRAINT chk_metric_revision_quality_slo CHECK (jsonb_typeof(quality_slo) = 'object');

ALTER TABLE data_contracts
    ADD COLUMN IF NOT EXISTS primary_key_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS enum_mappings JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS field_classifications JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS expected_volume JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_slo JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE data_contracts
    DROP CONSTRAINT IF EXISTS chk_data_contract_primary_keys,
    ADD CONSTRAINT chk_data_contract_primary_keys CHECK (jsonb_typeof(primary_key_paths) = 'array'),
    DROP CONSTRAINT IF EXISTS chk_data_contract_enum_mappings,
    ADD CONSTRAINT chk_data_contract_enum_mappings CHECK (jsonb_typeof(enum_mappings) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_data_contract_classifications,
    ADD CONSTRAINT chk_data_contract_classifications CHECK (jsonb_typeof(field_classifications) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_data_contract_expected_volume,
    ADD CONSTRAINT chk_data_contract_expected_volume CHECK (jsonb_typeof(expected_volume) = 'object'),
    DROP CONSTRAINT IF EXISTS chk_data_contract_quality_slo,
    ADD CONSTRAINT chk_data_contract_quality_slo CHECK (jsonb_typeof(quality_slo) = 'object');

CREATE TABLE IF NOT EXISTS data_quality_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_code VARCHAR(80) NOT NULL UNIQUE,
    contract_id UUID NOT NULL REFERENCES data_contracts(id),
    source_batch_id VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'validating',
    row_count BIGINT NOT NULL DEFAULT 0,
    accepted_count BIGINT NOT NULL DEFAULT 0,
    quarantined_count BIGINT NOT NULL DEFAULT 0,
    rejected_count BIGINT NOT NULL DEFAULT 0,
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_watermark TIMESTAMPTZ,
    validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contract_id, source_batch_id),
    CONSTRAINT chk_data_quality_batch_status CHECK (
        status IN ('validating', 'accepted', 'quarantined', 'rejected', 'partial_failed')
    ),
    CONSTRAINT chk_data_quality_batch_counts CHECK (
        row_count >= 0 AND accepted_count >= 0 AND quarantined_count >= 0 AND rejected_count >= 0
        AND accepted_count + quarantined_count + rejected_count <= row_count
    ),
    CONSTRAINT chk_data_quality_batch_summary CHECK (jsonb_typeof(quality_summary) = 'object')
);

CREATE TABLE IF NOT EXISTS data_quality_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID REFERENCES data_quality_batches(id) ON DELETE CASCADE,
    event_id UUID,
    rule_code VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    field_path VARCHAR(255),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_data_quality_violation_severity CHECK (severity IN ('warning', 'error', 'fatal')),
    CONSTRAINT chk_data_quality_violation_details CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_data_quality_violations_batch
    ON data_quality_violations(batch_id, severity, rule_code);
