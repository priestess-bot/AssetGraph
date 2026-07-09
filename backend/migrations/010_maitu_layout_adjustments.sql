-- AssetGraph Maitu natural-language layout adjustment plans
-- Stores parsed geometry targets and set_layer_transform operations before Browser-use mutates UI.

CREATE TABLE IF NOT EXISTS maitu_layout_adjustments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    adjustment_code VARCHAR(64) NOT NULL UNIQUE,
    build_plan_code VARCHAR(64),
    scene_name VARCHAR(128),
    layer_name VARCHAR(128),
    user_instruction TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    before_geometry JSONB NOT NULL,
    target_geometry JSONB NOT NULL,
    operation JSONB NOT NULL DEFAULT '{}'::jsonb,
    checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_layout_adjustments_build_plan_code ON maitu_layout_adjustments(build_plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_layout_adjustments_scene_layer ON maitu_layout_adjustments(scene_name, layer_name);
CREATE INDEX IF NOT EXISTS idx_maitu_layout_adjustments_status ON maitu_layout_adjustments(status);
CREATE INDEX IF NOT EXISTS idx_maitu_layout_adjustments_created_at ON maitu_layout_adjustments(created_at);
