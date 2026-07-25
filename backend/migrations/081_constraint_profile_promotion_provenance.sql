-- A room-local override may only become a new global Profile revision through
-- an attributable, replay-safe promotion command.

ALTER TABLE asset_constraint_profile_revisions
    ADD COLUMN IF NOT EXISTS created_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS change_reason TEXT,
    ADD COLUMN IF NOT EXISTS source_plan_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_profile_revision INTEGER,
    ADD COLUMN IF NOT EXISTS source_room_override JSONB;

ALTER TABLE asset_constraint_profile_revisions
    ADD CONSTRAINT chk_asset_constraint_profile_promotion_payload CHECK (
        source_room_override IS NULL OR jsonb_typeof(source_room_override) = 'object'
    ) NOT VALID;

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_constraint_profile_promotion_source
    ON asset_constraint_profile_revisions(profile_id, source_plan_code)
    WHERE source_plan_code IS NOT NULL;
