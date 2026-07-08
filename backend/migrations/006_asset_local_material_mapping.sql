-- AssetGraph local material identity mapping
-- Keeps AssetGraph global asset_code stable while preserving source-side material codes
-- such as MT-VID-0001 and DH-MDL-0001-F022 for Browser-use and Maitu workflows.

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS display_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS local_file_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS entity_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_system VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_subtype VARCHAR(64),
    ADD COLUMN IF NOT EXISTS usage VARCHAR(128),
    ADD COLUMN IF NOT EXISTS subject VARCHAR(255),
    ADD COLUMN IF NOT EXISTS file_role VARCHAR(128),
    ADD COLUMN IF NOT EXISTS browser_use_hint TEXT,
    ADD COLUMN IF NOT EXISTS local_relative_path TEXT,
    ADD COLUMN IF NOT EXISTS duplicate_group VARCHAR(64),
    ADD COLUMN IF NOT EXISTS duplicate_rank INTEGER,
    ADD COLUMN IF NOT EXISTS duplicate_count INTEGER,
    ADD COLUMN IF NOT EXISTS duplicate_primary_local_file_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS duplicate_primary_asset_code VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_assets_display_code ON assets(display_code);
CREATE INDEX IF NOT EXISTS idx_assets_local_file_code ON assets(local_file_code);
CREATE INDEX IF NOT EXISTS idx_assets_entity_code ON assets(entity_code);
CREATE INDEX IF NOT EXISTS idx_assets_source_system ON assets(source_system);
CREATE INDEX IF NOT EXISTS idx_assets_maitu_type ON assets(maitu_type);
CREATE INDEX IF NOT EXISTS idx_assets_maitu_subtype ON assets(maitu_subtype);
CREATE INDEX IF NOT EXISTS idx_assets_usage ON assets(usage);
CREATE INDEX IF NOT EXISTS idx_assets_subject ON assets(subject);
CREATE INDEX IF NOT EXISTS idx_assets_file_role ON assets(file_role);
CREATE INDEX IF NOT EXISTS idx_assets_duplicate_group ON assets(duplicate_group);
