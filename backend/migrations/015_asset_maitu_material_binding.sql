-- Maitu material/source binding for direct script-driven draft insertion.
-- AssetGraph assets keep local file identity, while these optional fields point
-- to the corresponding uploaded/known Maitu material records or URLs.

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS maitu_material_id INTEGER,
    ADD COLUMN IF NOT EXISTS source_material_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_material_url TEXT,
    ADD COLUMN IF NOT EXISTS source_cover_url TEXT,
    ADD COLUMN IF NOT EXISTS speaker_id INTEGER,
    ADD COLUMN IF NOT EXISTS digital_human_image_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_assets_maitu_material_id ON assets(maitu_material_id);
CREATE INDEX IF NOT EXISTS idx_assets_source_material_type ON assets(source_material_type);
CREATE INDEX IF NOT EXISTS idx_assets_speaker_id ON assets(speaker_id);
CREATE INDEX IF NOT EXISTS idx_assets_digital_human_image_id ON assets(digital_human_image_id);
