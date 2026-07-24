-- Canonical production-side Maitu scene/layer projections.
-- These are deliberately separate from maitu_live_room_blueprints, which
-- stores observed/reference-room layouts rather than a generated target state.

CREATE TABLE IF NOT EXISTS maitu_scene_blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_blueprint_code VARCHAR(128) NOT NULL UNIQUE,
    revision_number INTEGER NOT NULL DEFAULT 1,
    production_variant_revision_id UUID NOT NULL REFERENCES production_variant_revisions(id) ON DELETE RESTRICT,
    live_room_configuration_revision_id UUID NOT NULL REFERENCES live_room_configuration_revisions(id) ON DELETE RESTRICT,
    shot_id UUID NOT NULL REFERENCES shots(id) ON DELETE RESTRICT,
    program_segment_id UUID NOT NULL REFERENCES program_segments(id) ON DELETE RESTRICT,
    sort_order INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    transition_strategy JSONB NOT NULL DEFAULT '{}'::jsonb,
    estimated_active_start_ms BIGINT NOT NULL,
    estimated_active_end_ms BIGINT NOT NULL,
    constraint_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (live_room_configuration_revision_id, sort_order),
    CONSTRAINT chk_maitu_scene_blueprint_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_maitu_scene_blueprint_order CHECK (sort_order >= 0),
    CONSTRAINT chk_maitu_scene_blueprint_interval CHECK (
        estimated_active_start_ms >= 0 AND estimated_active_end_ms > estimated_active_start_ms
    ),
    CONSTRAINT chk_maitu_scene_blueprint_transition CHECK (jsonb_typeof(transition_strategy) = 'object'),
    CONSTRAINT chk_maitu_scene_blueprint_evidence CHECK (jsonb_typeof(constraint_evidence) = 'object'),
    CONSTRAINT chk_maitu_scene_blueprint_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_maitu_scene_blueprints_variant
    ON maitu_scene_blueprints(production_variant_revision_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_maitu_scene_blueprints_shot
    ON maitu_scene_blueprints(shot_id);

CREATE TABLE IF NOT EXISTS layer_blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_blueprint_code VARCHAR(160) NOT NULL UNIQUE,
    revision_number INTEGER NOT NULL DEFAULT 1,
    scene_blueprint_id UUID NOT NULL REFERENCES maitu_scene_blueprints(id) ON DELETE CASCADE,
    source_shot_id UUID NOT NULL REFERENCES shots(id) ON DELETE RESTRICT,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
    asset_code VARCHAR(64) NOT NULL,
    material_role VARCHAR(64) NOT NULL,
    asset_binding_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_geometry JSONB NOT NULL,
    z_order INTEGER NOT NULL,
    visual_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    audio_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    constraint_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_script_block_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scene_blueprint_id, layer_blueprint_code),
    CONSTRAINT chk_layer_blueprint_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_layer_blueprint_geometry CHECK (jsonb_typeof(normalized_geometry) = 'object'),
    CONSTRAINT chk_layer_blueprint_binding CHECK (jsonb_typeof(asset_binding_ref) = 'object'),
    CONSTRAINT chk_layer_blueprint_visual CHECK (jsonb_typeof(visual_properties) = 'object'),
    CONSTRAINT chk_layer_blueprint_audio CHECK (jsonb_typeof(audio_properties) = 'object'),
    CONSTRAINT chk_layer_blueprint_evidence CHECK (jsonb_typeof(constraint_evidence) = 'object'),
    CONSTRAINT chk_layer_blueprint_script_sources CHECK (jsonb_typeof(source_script_block_codes) = 'array'),
    CONSTRAINT chk_layer_blueprint_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_layer_blueprints_scene
    ON layer_blueprints(scene_blueprint_id, z_order);
CREATE INDEX IF NOT EXISTS idx_layer_blueprints_asset
    ON layer_blueprints(asset_code);
