-- Asset gaps are durable resolution work, not a mutable warning string.  The
-- event log preserves every state change while the current row stays cheap to
-- query from planning and the material-library workbench.

ALTER TABLE asset_gaps
    ADD COLUMN IF NOT EXISTS gap_type VARCHAR(64) NOT NULL DEFAULT 'material_missing',
    ADD COLUMN IF NOT EXISTS impact_summary TEXT,
    ADD COLUMN IF NOT EXISTS alternative_asset_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS resolution_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS resolution_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS resolved_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS waived_reason TEXT;

DO $$ BEGIN
    ALTER TABLE asset_gaps
        ADD CONSTRAINT chk_asset_gaps_gap_type
            CHECK (gap_type IN ('material_missing', 'role_coverage', 'constraint_conflict', 'rights_pending', 'quality_improvement'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE asset_gaps
        ADD CONSTRAINT chk_asset_gaps_alternatives
            CHECK (jsonb_typeof(alternative_asset_codes) = 'array');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE asset_gaps
        ADD CONSTRAINT chk_asset_gaps_resolution_snapshot
            CHECK (jsonb_typeof(resolution_snapshot) = 'object');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE asset_gaps
        ADD CONSTRAINT chk_asset_gaps_resolution_evidence
            CHECK (jsonb_typeof(resolution_evidence) = 'object');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS asset_gap_resolution_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_code VARCHAR(64) NOT NULL UNIQUE,
    gap_id UUID NOT NULL REFERENCES asset_gaps(id) ON DELETE CASCADE,
    previous_status VARCHAR(32),
    status VARCHAR(32) NOT NULL,
    actor VARCHAR(128),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_asset_gap_resolution_events_status
        CHECK (status IN ('open', 'candidate_found', 'resolved', 'waived', 'obsolete')),
    CONSTRAINT chk_asset_gap_resolution_events_payload CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_asset_gap_resolution_events_gap
    ON asset_gap_resolution_events(gap_id, created_at, event_code);
