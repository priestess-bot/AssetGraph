-- Operational observations are append-only evidence.  A planned live-room
-- branch is never treated as exposure until a source-backed interval exists.

ALTER TABLE functional_operation_sessions
    ADD COLUMN IF NOT EXISTS live_room_plan_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS variant_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS release_code VARCHAR(64);

CREATE TABLE IF NOT EXISTS functional_content_exposures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exposure_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES functional_operation_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    plan_code VARCHAR(64) NOT NULL,
    variant_code VARCHAR(64) NOT NULL,
    release_code VARCHAR(64),
    scene_code VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    source_kind VARCHAR(32) NOT NULL,
    evidence_note TEXT NOT NULL,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0.5,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_content_exposure_interval CHECK (ended_at > started_at),
    CONSTRAINT chk_functional_content_exposure_source CHECK (source_kind IN ('manual_observation', 'served_log', 'recording_match')),
    CONSTRAINT chk_functional_content_exposure_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT chk_functional_content_exposure_status CHECK (status IN ('active', 'superseded', 'retracted'))
);

CREATE INDEX IF NOT EXISTS idx_functional_content_exposures_session
    ON functional_content_exposures(session_code, started_at, ended_at);
CREATE INDEX IF NOT EXISTS idx_functional_content_exposures_plan
    ON functional_content_exposures(plan_code, created_at DESC);
