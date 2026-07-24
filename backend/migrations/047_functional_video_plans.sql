-- Content-project derived video plans. Media execution remains owned by video_production_jobs.

CREATE TABLE IF NOT EXISTS functional_video_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_code VARCHAR(64) NOT NULL UNIQUE,
    project_code VARCHAR(64) NOT NULL,
    variant_code VARCHAR(64) NOT NULL UNIQUE,
    video_job_code VARCHAR(64) NOT NULL UNIQUE REFERENCES video_production_jobs(job_code) ON DELETE RESTRICT,
    title VARCHAR(255) NOT NULL,
    production_timeline JSONB NOT NULL,
    render_profile JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_video_plan_timeline CHECK (jsonb_typeof(production_timeline) = 'object'),
    CONSTRAINT chk_functional_video_plan_profile CHECK (jsonb_typeof(render_profile) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_functional_video_plans_project
    ON functional_video_plans(project_code, created_at DESC);
