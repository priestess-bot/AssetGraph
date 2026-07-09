-- AssetGraph Maitu live-room BuildPlan extension
-- Stores dry-run build plans generated from persisted LiveRoomBlueprints.

CREATE TABLE IF NOT EXISTS maitu_live_room_build_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_plan_code VARCHAR(64) NOT NULL UNIQUE,
    blueprint_code VARCHAR(64) NOT NULL,
    plan_name VARCHAR(255) NOT NULL,
    target_app VARCHAR(64) NOT NULL DEFAULT 'maitu',
    executor VARCHAR(64) NOT NULL DEFAULT 'browser_use',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    strategy VARCHAR(64) NOT NULL DEFAULT 'reference_rebuild_dry_run',
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_live_room_build_plans_blueprint_code ON maitu_live_room_build_plans(blueprint_code);
CREATE INDEX IF NOT EXISTS idx_maitu_live_room_build_plans_status ON maitu_live_room_build_plans(status);
CREATE INDEX IF NOT EXISTS idx_maitu_live_room_build_plans_strategy ON maitu_live_room_build_plans(strategy);

CREATE TABLE IF NOT EXISTS maitu_live_room_build_plan_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_plan_id UUID NOT NULL REFERENCES maitu_live_room_build_plans(id),
    build_plan_code VARCHAR(64) NOT NULL,
    operation_type VARCHAR(64) NOT NULL,
    operation_name VARCHAR(255) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    scene_name VARCHAR(128),
    layer_name VARCHAR(128),
    layer_role VARCHAR(64),
    required_category VARCHAR(64),
    accepted_asset_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    replacement_policy VARCHAR(32),
    script_block_code VARCHAR(64),
    script_block_content TEXT,
    instruction TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operations_plan_code ON maitu_live_room_build_plan_operations(build_plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operations_type ON maitu_live_room_build_plan_operations(operation_type);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operations_scene ON maitu_live_room_build_plan_operations(scene_name);
CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operations_status ON maitu_live_room_build_plan_operations(status);
