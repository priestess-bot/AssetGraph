-- Bind optional governed metric revisions to the manual operational surface.
-- The snapshots are immutable history: later catalog revisions never rewrite a
-- previously imported session or descriptive attribution report.

ALTER TABLE functional_operation_sessions
    ADD COLUMN IF NOT EXISTS metric_definition_refs JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE functional_operation_sessions
    ADD CONSTRAINT chk_functional_operation_metric_definition_refs
    CHECK (jsonb_typeof(metric_definition_refs) = 'array');

ALTER TABLE functional_attribution_reports
    ADD COLUMN IF NOT EXISTS metric_definition_ref JSONB;

ALTER TABLE functional_attribution_reports
    ADD CONSTRAINT chk_functional_attribution_metric_definition_ref
    CHECK (
        metric_definition_ref IS NULL
        OR jsonb_typeof(metric_definition_ref) = 'object'
    );
