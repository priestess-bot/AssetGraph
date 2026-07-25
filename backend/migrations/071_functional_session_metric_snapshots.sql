-- Immutable session-grain metric computations over quality-accepted standard events.

CREATE TABLE IF NOT EXISTS functional_session_metric_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_code VARCHAR(80) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES functional_operation_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    metric_key VARCHAR(80) NOT NULL,
    metric_code VARCHAR(80) NOT NULL,
    metric_revision INTEGER NOT NULL,
    aggregation VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL,
    value NUMERIC,
    source_event_count BIGINT NOT NULL DEFAULT 0,
    value_json_pointer VARCHAR(512),
    numerator_json_pointer VARCHAR(512),
    denominator_json_pointer VARCHAR(512),
    source_batches JSONB NOT NULL DEFAULT '[]'::jsonb,
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_session_metric_snapshot_status CHECK (
        status IN ('ready', 'insufficient_data')
    ),
    CONSTRAINT chk_functional_session_metric_snapshot_aggregation CHECK (
        aggregation IN ('sum', 'count', 'min', 'max', 'average', 'ratio', 'last')
    ),
    CONSTRAINT chk_functional_session_metric_snapshot_value CHECK (
        (status = 'ready' AND value IS NOT NULL) OR status = 'insufficient_data'
    ),
    CONSTRAINT chk_functional_session_metric_snapshot_batches CHECK (
        jsonb_typeof(source_batches) = 'array'
    ),
    CONSTRAINT chk_functional_session_metric_snapshot_quality CHECK (
        jsonb_typeof(quality_summary) = 'object'
    ),
    CONSTRAINT chk_functional_session_metric_snapshot_input CHECK (
        jsonb_typeof(input_snapshot) = 'object'
    ),
    CONSTRAINT chk_functional_session_metric_snapshot_sha CHECK (
        fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_functional_session_metric_snapshots_session_metric_created
    ON functional_session_metric_snapshots (session_code, metric_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_functional_session_metric_snapshots_metric_created
    ON functional_session_metric_snapshots (metric_code, metric_revision, created_at DESC);
