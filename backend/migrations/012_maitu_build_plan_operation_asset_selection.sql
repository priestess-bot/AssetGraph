-- AssetGraph Maitu live-room BuildPlan asset-selection extension
-- Adds selected asset evidence to BuildPlan operations so script/context driven planning can be reviewed before UI mutation.

ALTER TABLE maitu_live_room_build_plan_operations
    ADD COLUMN IF NOT EXISTS selected_asset_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS selected_asset_title VARCHAR(255),
    ADD COLUMN IF NOT EXISTS selected_asset_display_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS selected_asset_local_file_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS selected_asset_original_filename VARCHAR(512),
    ADD COLUMN IF NOT EXISTS selected_asset_local_relative_path TEXT,
    ADD COLUMN IF NOT EXISTS selected_asset_browser_use_hint TEXT,
    ADD COLUMN IF NOT EXISTS match_score NUMERIC(8, 4),
    ADD COLUMN IF NOT EXISTS match_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS selection_source VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operations_selected_asset_code
ON maitu_live_room_build_plan_operations(selected_asset_code);

CREATE INDEX IF NOT EXISTS idx_maitu_build_plan_operations_selection_source
ON maitu_live_room_build_plan_operations(selection_source);
