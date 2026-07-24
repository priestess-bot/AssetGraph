-- Structured static gate and quality projections for functional live-room plans.

ALTER TABLE functional_live_room_plans
    ADD COLUMN IF NOT EXISTS gate_results JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_report JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE functional_live_room_plans
    ADD CONSTRAINT chk_functional_live_room_plan_gates
        CHECK (jsonb_typeof(gate_results) = 'array'),
    ADD CONSTRAINT chk_functional_live_room_plan_quality
        CHECK (jsonb_typeof(quality_report) = 'object');
