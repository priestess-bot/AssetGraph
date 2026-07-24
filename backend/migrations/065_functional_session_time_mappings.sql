-- An observed live session may be aligned to a recording or platform clock.
-- Every adjustment creates a new immutable mapping revision; exposures remain
-- source evidence and are never rewritten during calibration.

CREATE TABLE IF NOT EXISTS functional_session_time_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES functional_operation_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    source_clock VARCHAR(128) NOT NULL,
    source_kind VARCHAR(32) NOT NULL,
    source_offset_ms BIGINT NOT NULL,
    drift_ppm NUMERIC(12, 4) NOT NULL DEFAULT 0,
    coverage_start_ms BIGINT NOT NULL,
    coverage_end_ms BIGINT NOT NULL,
    evidence_note TEXT NOT NULL,
    actor VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, revision_number),
    CONSTRAINT chk_functional_session_time_mapping_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_functional_session_time_mapping_status CHECK (status IN ('active', 'superseded')),
    CONSTRAINT chk_functional_session_time_mapping_source_kind
        CHECK (source_kind IN ('manual_calibration', 'recording_anchor', 'platform_anchor')),
    CONSTRAINT chk_functional_session_time_mapping_coverage
        CHECK (coverage_start_ms >= 0 AND coverage_end_ms > coverage_start_ms),
    CONSTRAINT chk_functional_session_time_mapping_drift
        CHECK (drift_ppm BETWEEN -100000 AND 100000)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_functional_session_time_mapping_active
    ON functional_session_time_mappings(session_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_functional_session_time_mappings_session
    ON functional_session_time_mappings(session_code, revision_number DESC);
