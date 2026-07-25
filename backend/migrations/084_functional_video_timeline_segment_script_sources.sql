-- TimelineSegment rows already point to their authoritative source Shot.  Freeze
-- the Shot's adopted ScriptBlock codes as well, so the rendered-video branch can
-- expose its content provenance without rereading a mutable project projection.

ALTER TABLE functional_video_timeline_segments
    ADD COLUMN IF NOT EXISTS source_script_block_codes JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE functional_video_timeline_segments
    ADD CONSTRAINT chk_functional_video_timeline_segment_script_blocks
    CHECK (jsonb_typeof(source_script_block_codes) = 'array');
