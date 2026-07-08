-- AssetGraph initial schema
-- Applies the MVP data model for assets, live sessions, and live-asset indexing.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_code VARCHAR(32) NOT NULL UNIQUE,
    asset_type VARCHAR(16) NOT NULL,
    title VARCHAR(255),
    original_filename VARCHAR(512) NOT NULL,
    file_ext VARCHAR(32),
    mime_type VARCHAR(128),
    file_size BIGINT,
    checksum_sha256 CHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    project_id UUID,
    description TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_assets_asset_type ON assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status);
CREATE INDEX IF NOT EXISTS idx_assets_created_at ON assets(created_at);
CREATE INDEX IF NOT EXISTS idx_assets_project_id ON assets(project_id);

CREATE TABLE IF NOT EXISTS asset_sequences (
    sequence_date DATE NOT NULL,
    asset_type VARCHAR(16) NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sequence_date, asset_type)
);

CREATE TABLE IF NOT EXISTS asset_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id),
    asset_code VARCHAR(32) NOT NULL,
    file_role VARCHAR(32) NOT NULL,
    bucket_name VARCHAR(128) NOT NULL,
    object_key TEXT NOT NULL,
    mime_type VARCHAR(128),
    file_size BIGINT,
    checksum_sha256 CHAR(64),
    width INTEGER,
    height INTEGER,
    duration_seconds NUMERIC(12, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_files_asset_id ON asset_files(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_files_asset_code ON asset_files(asset_code);
CREATE INDEX IF NOT EXISTS idx_asset_files_file_role ON asset_files(file_role);

CREATE TABLE IF NOT EXISTS tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL UNIQUE,
    tag_type VARCHAR(32) NOT NULL DEFAULT 'manual',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asset_tags (
    asset_id UUID NOT NULL REFERENCES assets(id),
    tag_id UUID NOT NULL REFERENCES tags(id),
    source VARCHAR(32) NOT NULL DEFAULT 'manual',
    confidence NUMERIC(5, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_id, tag_id, source)
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id),
    asset_code VARCHAR(32) NOT NULL,
    job_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_processing_jobs_status ON processing_jobs(status);
CREATE INDEX IF NOT EXISTS idx_processing_jobs_asset_code ON processing_jobs(asset_code);

CREATE TABLE IF NOT EXISTS live_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    live_code VARCHAR(40) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    platform VARCHAR(64),
    streamer_name VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    project_id UUID,
    scheduled_start_at TIMESTAMPTZ,
    actual_start_at TIMESTAMPTZ,
    actual_end_at TIMESTAMPTZ,
    description TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_live_sessions_live_code ON live_sessions(live_code);
CREATE INDEX IF NOT EXISTS idx_live_sessions_project_id ON live_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_live_sessions_status ON live_sessions(status);

CREATE TABLE IF NOT EXISTS live_sequences (
    sequence_date DATE PRIMARY KEY,
    current_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_assets (
    live_id UUID NOT NULL REFERENCES live_sessions(id),
    asset_id UUID NOT NULL REFERENCES assets(id),
    live_code VARCHAR(40) NOT NULL,
    asset_code VARCHAR(32) NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    start_time_seconds NUMERIC(12, 3),
    end_time_seconds NUMERIC(12, 3),
    segment_label VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (live_id, asset_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_live_assets_live_code ON live_assets(live_code);
CREATE INDEX IF NOT EXISTS idx_live_assets_asset_code ON live_assets(asset_code);
CREATE INDEX IF NOT EXISTS idx_live_assets_relation_type ON live_assets(relation_type);
