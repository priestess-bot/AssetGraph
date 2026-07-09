-- AssetGraph Maitu live-room blueprint ingestion
-- Stores Browser-use Observe-derived ReferenceRoomProfile and LiveRoomBlueprint artifacts.

CREATE TABLE IF NOT EXISTS maitu_reference_room_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_code VARCHAR(64) NOT NULL UNIQUE,
    source VARCHAR(64) NOT NULL DEFAULT 'browser_use_observe',
    source_url TEXT,
    page_title VARCHAR(255),
    reference_room_id VARCHAR(64),
    reference_room_name VARCHAR(255),
    platform VARCHAR(64),
    active_scene_name VARCHAR(128),
    logged_in BOOLEAN NOT NULL DEFAULT false,
    login_required BOOLEAN NOT NULL DEFAULT false,
    scenes JSONB NOT NULL DEFAULT '[]'::jsonb,
    active_scene_layers JSONB NOT NULL DEFAULT '[]'::jsonb,
    material_tabs JSONB NOT NULL DEFAULT '[]'::jsonb,
    workbench_tabs JSONB NOT NULL DEFAULT '[]'::jsonb,
    script_texts JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_reference_profiles_room_id ON maitu_reference_room_profiles(reference_room_id);
CREATE INDEX IF NOT EXISTS idx_maitu_reference_profiles_platform ON maitu_reference_room_profiles(platform);
CREATE INDEX IF NOT EXISTS idx_maitu_reference_profiles_active_scene ON maitu_reference_room_profiles(active_scene_name);

CREATE TABLE IF NOT EXISTS maitu_live_room_blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blueprint_code VARCHAR(64) NOT NULL UNIQUE,
    reference_profile_id UUID REFERENCES maitu_reference_room_profiles(id),
    reference_profile_code VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    platform VARCHAR(64),
    room_type VARCHAR(64) NOT NULL DEFAULT 'reference_rebuild',
    reference_room_id VARCHAR(64),
    reference_room_name VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    description TEXT,
    scenes JSONB NOT NULL DEFAULT '[]'::jsonb,
    script_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
    material_tabs JSONB NOT NULL DEFAULT '[]'::jsonb,
    workbench_tabs JSONB NOT NULL DEFAULT '[]'::jsonb,
    safety_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_blueprint JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_live_room_blueprints_profile_code ON maitu_live_room_blueprints(reference_profile_code);
CREATE INDEX IF NOT EXISTS idx_maitu_live_room_blueprints_room_id ON maitu_live_room_blueprints(reference_room_id);
CREATE INDEX IF NOT EXISTS idx_maitu_live_room_blueprints_status ON maitu_live_room_blueprints(status);
CREATE INDEX IF NOT EXISTS idx_maitu_live_room_blueprints_platform ON maitu_live_room_blueprints(platform);
CREATE INDEX IF NOT EXISTS idx_maitu_live_room_blueprints_created_at ON maitu_live_room_blueprints(created_at);
