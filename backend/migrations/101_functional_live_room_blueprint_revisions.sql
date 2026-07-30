-- Blueprint edits create a derived immutable plan. The source plan and its
-- BuildPlan remain available for historical references and comparison.

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS revised_from_plan_code VARCHAR(64)
        REFERENCES functional_live_room_plans(plan_code),
    ADD COLUMN IF NOT EXISTS revision_context JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_functional_live_room_revision_context'
          AND conrelid = 'functional_live_room_plans'::regclass
    ) THEN
        ALTER TABLE functional_live_room_plans
            ADD CONSTRAINT chk_functional_live_room_revision_context
                CHECK (jsonb_typeof(revision_context) = 'object');
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_functional_live_room_plan_revision_source
    ON functional_live_room_plans(revised_from_plan_code, created_at DESC)
    WHERE revised_from_plan_code IS NOT NULL;
