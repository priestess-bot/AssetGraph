-- AssetGraph real asset ingestion hardening
-- Adds idempotency and original-file tracking for imports from curated local folders.

CREATE UNIQUE INDEX IF NOT EXISTS idx_assets_source_local_code_active
ON assets(source_system, local_file_code)
WHERE local_file_code IS NOT NULL AND deleted_at IS NULL;

ALTER TABLE asset_files
    ADD COLUMN IF NOT EXISTS source_relative_path TEXT,
    ADD COLUMN IF NOT EXISTS local_file_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS storage_status VARCHAR(32) NOT NULL DEFAULT 'stored';

CREATE INDEX IF NOT EXISTS idx_asset_files_local_file_code ON asset_files(local_file_code);
CREATE INDEX IF NOT EXISTS idx_asset_files_object_key ON asset_files(object_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_files_asset_role_unique
ON asset_files(asset_id, file_role);
