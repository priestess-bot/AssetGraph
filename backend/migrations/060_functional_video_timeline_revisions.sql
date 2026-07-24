-- Functional video plans retain an editable, revisioned timeline only until
-- their renderer has claimed the job.  Rendered outputs always retain the
-- exact revision that fed the worker.

ALTER TABLE functional_video_plans
    ADD COLUMN IF NOT EXISTS timeline_revision INTEGER NOT NULL DEFAULT 1;

ALTER TABLE functional_video_plans
    ADD CONSTRAINT chk_functional_video_plan_timeline_revision CHECK (timeline_revision >= 1);

CREATE TABLE IF NOT EXISTS functional_video_timeline_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES functional_video_plans(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    production_timeline JSONB NOT NULL,
    actor_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, revision_number),
    CONSTRAINT chk_functional_video_timeline_revision_document CHECK (jsonb_typeof(production_timeline) = 'object'),
    CONSTRAINT chk_functional_video_timeline_revision_number CHECK (revision_number >= 1)
);

INSERT INTO functional_video_timeline_revisions (plan_id, revision_number, production_timeline, actor_id)
SELECT id, timeline_revision, production_timeline, 'migration_060_backfill'
FROM functional_video_plans
ON CONFLICT (plan_id, revision_number) DO NOTHING;
