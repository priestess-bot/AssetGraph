-- A clone carries only business inputs into a newly compiled plan. Execution,
-- release and observed-room state remain on the source plan and are never copied.

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS cloned_from_plan_code VARCHAR(64)
        REFERENCES functional_live_room_plans(plan_code),
    ADD COLUMN IF NOT EXISTS clone_context JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE functional_live_room_plans
    ADD CONSTRAINT chk_functional_live_room_clone_context
        CHECK (jsonb_typeof(clone_context) = 'object');

CREATE INDEX IF NOT EXISTS idx_functional_live_room_plan_clone_source
    ON functional_live_room_plans(cloned_from_plan_code, created_at DESC)
    WHERE cloned_from_plan_code IS NOT NULL;
