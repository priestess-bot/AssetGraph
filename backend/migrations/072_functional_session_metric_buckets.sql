-- Event-time metric contributions derived from one immutable session metric snapshot.

CREATE TABLE IF NOT EXISTS functional_session_metric_buckets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket_code VARCHAR(80) NOT NULL UNIQUE,
    snapshot_id UUID NOT NULL REFERENCES functional_session_metric_snapshots(id) ON DELETE CASCADE,
    snapshot_code VARCHAR(80) NOT NULL,
    session_code VARCHAR(64) NOT NULL,
    source_event_id UUID NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    aggregation VARCHAR(16) NOT NULL,
    allocation_status VARCHAR(32) NOT NULL,
    value NUMERIC,
    numerator NUMERIC,
    denominator NUMERIC,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id, source_event_id),
    CONSTRAINT chk_functional_metric_bucket_aggregation CHECK (
        aggregation IN ('sum', 'count', 'min', 'max', 'average', 'ratio', 'last')
    ),
    CONSTRAINT chk_functional_metric_bucket_allocation CHECK (
        allocation_status IN ('allocatable', 'session_only')
    ),
    CONSTRAINT chk_functional_metric_bucket_sha CHECK (
        fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_functional_session_metric_buckets_snapshot_time
    ON functional_session_metric_buckets (snapshot_code, event_time, bucket_code);

CREATE INDEX IF NOT EXISTS idx_functional_session_metric_buckets_session_time
    ON functional_session_metric_buckets (session_code, event_time, bucket_code);
