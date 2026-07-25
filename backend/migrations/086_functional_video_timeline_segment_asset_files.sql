-- An AssetFile can be replaced in the mutable material library after a video
-- plan has been created. Keep the exact selected source-file metadata beside
-- every immutable TimelineSegment that uses it.

CREATE TABLE IF NOT EXISTS functional_video_timeline_segment_asset_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timeline_segment_id UUID NOT NULL REFERENCES functional_video_timeline_segments(id) ON DELETE CASCADE,
    asset_file_id UUID NOT NULL REFERENCES asset_files(id) ON DELETE RESTRICT,
    relation_role VARCHAR(32) NOT NULL DEFAULT 'source_video',
    asset_code VARCHAR(32) NOT NULL,
    file_role VARCHAR(32) NOT NULL,
    bucket_name VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    source_relative_path TEXT,
    mime_type VARCHAR(128),
    file_size BIGINT,
    checksum_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (timeline_segment_id, relation_role),
    CONSTRAINT chk_functional_video_timeline_segment_asset_file_role
        CHECK (relation_role = 'source_video'),
    CONSTRAINT chk_functional_video_timeline_segment_asset_file_path
        CHECK (object_key <> '' AND object_key !~ '(^|/)\.\.(/|$)' AND object_key !~ '^/'),
    CONSTRAINT chk_functional_video_timeline_segment_asset_file_size
        CHECK (file_size IS NULL OR file_size >= 0),
    CONSTRAINT chk_functional_video_timeline_segment_asset_file_checksum
        CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_functional_video_timeline_segment_asset_file
    ON functional_video_timeline_segment_asset_files(asset_file_id, created_at);
