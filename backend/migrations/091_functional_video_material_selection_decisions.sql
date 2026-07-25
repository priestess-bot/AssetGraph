ALTER TABLE functional_video_plans
    ADD COLUMN IF NOT EXISTS material_selection_decision_code VARCHAR(64)
    REFERENCES functional_decision_logs(decision_code) ON DELETE RESTRICT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_functional_video_plan_material_selection_decision
    ON functional_video_plans(material_selection_decision_code)
    WHERE material_selection_decision_code IS NOT NULL;
