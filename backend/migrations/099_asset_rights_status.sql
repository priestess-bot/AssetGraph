ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS rights_status VARCHAR(24) NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS rights_note TEXT,
    ADD COLUMN IF NOT EXISTS rights_updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rights_updated_by VARCHAR(128);

ALTER TABLE assets
    DROP CONSTRAINT IF EXISTS chk_assets_rights_status;
ALTER TABLE assets
    ADD CONSTRAINT chk_assets_rights_status
        CHECK (rights_status IN ('pending', 'approved', 'restricted', 'revoked'));

CREATE INDEX IF NOT EXISTS idx_assets_rights_status_active
    ON assets (rights_status, updated_at DESC)
    WHERE deleted_at IS NULL;
