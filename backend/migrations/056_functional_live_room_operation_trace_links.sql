-- Explicit BuildPlan-operation links for generated live-room projections.
-- A link is append-only provenance: it does not represent execution success.

CREATE TABLE IF NOT EXISTS functional_live_room_operation_trace_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES functional_live_room_plans(id) ON DELETE CASCADE,
    build_plan_operation_id UUID NOT NULL REFERENCES maitu_live_room_build_plan_operations(id) ON DELETE CASCADE,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(160) NOT NULL,
    target_revision INTEGER NOT NULL DEFAULT 1,
    relation_type VARCHAR(32) NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (build_plan_operation_id, target_type, target_code, target_revision, relation_type),
    CONSTRAINT chk_functional_live_room_operation_trace_target
        CHECK (target_type IN ('maitu_scene_blueprint', 'layer_blueprint')),
    CONSTRAINT chk_functional_live_room_operation_trace_revision
        CHECK (target_revision >= 1),
    CONSTRAINT chk_functional_live_room_operation_trace_relation
        CHECK (relation_type IN ('preflights', 'configures', 'mutates', 'writes', 'verifies', 'saves')),
    CONSTRAINT chk_functional_live_room_operation_trace_evidence
        CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_functional_live_room_operation_trace_plan
    ON functional_live_room_operation_trace_links(plan_id, created_at);
CREATE INDEX IF NOT EXISTS idx_functional_live_room_operation_trace_target
    ON functional_live_room_operation_trace_links(target_type, target_code, target_revision);
