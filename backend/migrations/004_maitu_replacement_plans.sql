-- AssetGraph Maitu replacement plan extension
-- Stores Agent-generated replacement plans for Maitu projects/templates.

CREATE TABLE IF NOT EXISTS maitu_replacement_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code VARCHAR(64) NOT NULL UNIQUE,
    plan_name VARCHAR(255) NOT NULL,
    maitu_project_code VARCHAR(64),
    scene_name VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    strategy VARCHAR(64) NOT NULL DEFAULT 'best_match',
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plans_project ON maitu_replacement_plans(maitu_project_code);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plans_scene ON maitu_replacement_plans(scene_name);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plans_status ON maitu_replacement_plans(status);

CREATE TABLE IF NOT EXISTS maitu_replacement_plan_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES maitu_replacement_plans(id),
    plan_code VARCHAR(64) NOT NULL,
    slot_code VARCHAR(64) NOT NULL,
    slot_name VARCHAR(128),
    required_category VARCHAR(64),
    selected_asset_code VARCHAR(64),
    selected_asset_title VARCHAR(255),
    match_score NUMERIC(5, 4),
    match_reasons JSONB,
    replacement_policy VARCHAR(32),
    sort_order INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'selected',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, slot_code)
);

CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_items_plan_code ON maitu_replacement_plan_items(plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_items_slot_code ON maitu_replacement_plan_items(slot_code);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_items_asset_code ON maitu_replacement_plan_items(selected_asset_code);
CREATE INDEX IF NOT EXISTS idx_maitu_replacement_plan_items_status ON maitu_replacement_plan_items(status);
