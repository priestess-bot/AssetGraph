-- A rendered-video plan's editable JSON timeline is convenient for the UI,
-- but it is not the authoritative lineage object.  Persist one immutable
-- TimelineSegment projection per video clip and timeline revision so a
-- rendered frame range can always be traced back to the confirmed source Shot.

CREATE TABLE IF NOT EXISTS functional_video_timeline_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES functional_video_plans(id) ON DELETE CASCADE,
    timeline_revision INTEGER NOT NULL,
    segment_code VARCHAR(128) NOT NULL,
    clip_code VARCHAR(80) NOT NULL,
    source_shot_id UUID NOT NULL REFERENCES shots(id) ON DELETE RESTRICT,
    source_shot_code VARCHAR(128) NOT NULL,
    timeline_start_ms BIGINT NOT NULL,
    timeline_end_ms BIGINT NOT NULL,
    source_range JSONB NOT NULL DEFAULT '{}'::jsonb,
    transform JSONB NOT NULL DEFAULT '{}'::jsonb,
    transition VARCHAR(32) NOT NULL DEFAULT 'cut',
    artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, timeline_revision, clip_code),
    UNIQUE (segment_code, timeline_revision),
    CONSTRAINT chk_functional_video_timeline_segment_revision
        CHECK (timeline_revision >= 1),
    CONSTRAINT chk_functional_video_timeline_segment_range
        CHECK (timeline_start_ms >= 0 AND timeline_end_ms > timeline_start_ms),
    CONSTRAINT chk_functional_video_timeline_segment_source_range
        CHECK (jsonb_typeof(source_range) = 'object'),
    CONSTRAINT chk_functional_video_timeline_segment_transform
        CHECK (jsonb_typeof(transform) = 'object'),
    CONSTRAINT chk_functional_video_timeline_segment_artifact_refs
        CHECK (jsonb_typeof(artifact_refs) = 'array'),
    CONSTRAINT chk_functional_video_timeline_segment_fingerprint
        CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_functional_video_timeline_segments_plan_revision
    ON functional_video_timeline_segments(plan_id, timeline_revision, timeline_start_ms);
CREATE INDEX IF NOT EXISTS idx_functional_video_timeline_segments_source_shot
    ON functional_video_timeline_segments(source_shot_id, created_at DESC);
