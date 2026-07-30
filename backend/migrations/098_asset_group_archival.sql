ALTER TABLE asset_groups
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archive_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_asset_groups_active_updated
    ON asset_groups (updated_at DESC, group_code)
    WHERE archived_at IS NULL;
