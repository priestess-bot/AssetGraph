-- AssetGraph Maitu metadata extension
-- Adds material taxonomy and layout metadata used by Maitu scene/layer replacement workflows.

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_category VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_project_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS maitu_scene_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS maitu_scene_index INTEGER,
    ADD COLUMN IF NOT EXISTS maitu_layer_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS maitu_layer_index INTEGER,
    ADD COLUMN IF NOT EXISTS maitu_slot_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS maitu_slot_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS layer_left NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS layer_top NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS layer_width NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS layer_height NUMERIC(12, 3),
    ADD COLUMN IF NOT EXISTS layer_z_index INTEGER,
    ADD COLUMN IF NOT EXISTS replacement_policy VARCHAR(32) NOT NULL DEFAULT 'keep_layout';

CREATE INDEX IF NOT EXISTS idx_assets_source_type ON assets(source_type);
CREATE INDEX IF NOT EXISTS idx_assets_maitu_category ON assets(maitu_category);
CREATE INDEX IF NOT EXISTS idx_assets_maitu_project_code ON assets(maitu_project_code);
CREATE INDEX IF NOT EXISTS idx_assets_maitu_scene_name ON assets(maitu_scene_name);
CREATE INDEX IF NOT EXISTS idx_assets_maitu_slot_name ON assets(maitu_slot_name);

ALTER TABLE live_assets
    ADD COLUMN IF NOT EXISTS maitu_scene_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS maitu_layer_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS maitu_slot_name VARCHAR(128),
    ADD COLUMN IF NOT EXISTS replacement_policy VARCHAR(32);

CREATE INDEX IF NOT EXISTS idx_live_assets_maitu_scene_name ON live_assets(maitu_scene_name);
CREATE INDEX IF NOT EXISTS idx_live_assets_maitu_slot_name ON live_assets(maitu_slot_name);

CREATE TABLE IF NOT EXISTS maitu_material_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slot_code VARCHAR(64) NOT NULL UNIQUE,
    slot_name VARCHAR(128) NOT NULL,
    maitu_project_code VARCHAR(64),
    scene_name VARCHAR(128),
    scene_index INTEGER,
    layer_name VARCHAR(128),
    layer_index INTEGER,
    required_category VARCHAR(64) NOT NULL,
    accepted_asset_types VARCHAR(128),
    aspect_ratio VARCHAR(32),
    left_position NUMERIC(12, 3),
    top_position NUMERIC(12, 3),
    width NUMERIC(12, 3),
    height NUMERIC(12, 3),
    z_index INTEGER,
    replacement_policy VARCHAR(32) NOT NULL DEFAULT 'keep_layout',
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_material_slots_project ON maitu_material_slots(maitu_project_code);
CREATE INDEX IF NOT EXISTS idx_maitu_material_slots_scene ON maitu_material_slots(scene_name);
CREATE INDEX IF NOT EXISTS idx_maitu_material_slots_required_category ON maitu_material_slots(required_category);
