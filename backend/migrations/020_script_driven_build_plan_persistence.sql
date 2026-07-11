-- Persist script-driven BuildPlan metadata without fabricating a blueprint identity.
-- Operation-specific payloads continue to use the existing operation details JSONB.

ALTER TABLE maitu_live_room_build_plans
    ALTER COLUMN blueprint_code DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE maitu_live_room_build_plan_executions
    ALTER COLUMN blueprint_code DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS details JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    ALTER TABLE maitu_live_room_build_plans
        ADD CONSTRAINT chk_maitu_live_room_build_plan_details_object
        CHECK (jsonb_typeof(details) = 'object');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
    ALTER TABLE maitu_live_room_build_plan_executions
        ADD CONSTRAINT chk_maitu_live_room_build_execution_details_object
        CHECK (jsonb_typeof(details) = 'object');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;
