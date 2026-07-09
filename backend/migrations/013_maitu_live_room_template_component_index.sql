-- AssetGraph Maitu live-room template scene/component index
-- Materializes LiveRoomBlueprint scenes/layers into first-class searchable template scene and component rows.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS maitu_live_room_template_scenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_id UUID REFERENCES maitu_live_room_blueprints(id) ON DELETE CASCADE,
    blueprint_code VARCHAR(64) NOT NULL,
    template_library_code VARCHAR(64),
    scene_template_code VARCHAR(128) NOT NULL,
    scene_code VARCHAR(128),
    scene_name VARCHAR(128) NOT NULL,
    scene_type VARCHAR(64),
    sort_order INTEGER,
    reference_product_name TEXT,
    reference_item_id VARCHAR(128),
    reference_clip_id VARCHAR(128),
    script_block_code VARCHAR(128),
    script_sort_order INTEGER,
    script_content TEXT,
    component_count INTEGER NOT NULL DEFAULT 0,
    raw_scene JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (blueprint_code, scene_template_code)
);

CREATE INDEX IF NOT EXISTS idx_maitu_template_scenes_blueprint_code
ON maitu_live_room_template_scenes(blueprint_code);

CREATE INDEX IF NOT EXISTS idx_maitu_template_scenes_template_library_code
ON maitu_live_room_template_scenes(template_library_code);

CREATE INDEX IF NOT EXISTS idx_maitu_template_scenes_scene_name
ON maitu_live_room_template_scenes(scene_name);

CREATE INDEX IF NOT EXISTS idx_maitu_template_scenes_script_content_trgm
ON maitu_live_room_template_scenes USING gin (script_content gin_trgm_ops);

CREATE TABLE IF NOT EXISTS maitu_live_room_template_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_template_id UUID REFERENCES maitu_live_room_template_scenes(id) ON DELETE CASCADE,
    blueprint_code VARCHAR(64) NOT NULL,
    template_library_code VARCHAR(64),
    scene_template_code VARCHAR(128) NOT NULL,
    component_template_code VARCHAR(128) NOT NULL,
    scene_code VARCHAR(128),
    scene_name VARCHAR(128) NOT NULL,
    scene_type VARCHAR(64),
    reference_product_name TEXT,
    reference_item_id VARCHAR(128),
    reference_clip_id VARCHAR(128),
    component_name VARCHAR(255),
    component_type VARCHAR(64),
    component_role VARCHAR(64),
    layer_code VARCHAR(128),
    layer_name VARCHAR(255),
    layer_role VARCHAR(64),
    material_id INTEGER,
    material_tab VARCHAR(64),
    source_material_type VARCHAR(64),
    required_category VARCHAR(64),
    accepted_asset_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    replacement_policy VARCHAR(64),
    geometry JSONB NOT NULL DEFAULT '{}'::jsonb,
    z_index INTEGER,
    speaker_id INTEGER,
    digital_human_image_id INTEGER,
    source_material_url TEXT,
    source_cover_url TEXT,
    sort_order INTEGER,
    raw_layer JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (blueprint_code, scene_template_code, component_template_code)
);

CREATE INDEX IF NOT EXISTS idx_maitu_template_components_scene_template_code
ON maitu_live_room_template_components(scene_template_code);

CREATE INDEX IF NOT EXISTS idx_maitu_template_components_blueprint_code
ON maitu_live_room_template_components(blueprint_code);

CREATE INDEX IF NOT EXISTS idx_maitu_template_components_role_category
ON maitu_live_room_template_components(component_role, required_category);
