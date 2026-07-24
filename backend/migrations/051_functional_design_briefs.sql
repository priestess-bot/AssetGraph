CREATE TABLE IF NOT EXISTS functional_design_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_brief_code VARCHAR(64) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    source_project_revision_id UUID NOT NULL REFERENCES content_project_revisions(id) ON DELETE RESTRICT,
    source_project_revision_number INTEGER NOT NULL CHECK (source_project_revision_number >= 1),
    revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    raw_input TEXT NOT NULL,
    parsed_brief JSONB NOT NULL DEFAULT '{}'::jsonb,
    open_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    user_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
    parser_strategy_ref VARCHAR(128) NOT NULL,
    prompt_revision VARCHAR(128) NOT NULL,
    response_fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, revision_number),
    CONSTRAINT chk_functional_design_brief_status
        CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_functional_design_brief_payloads
        CHECK (jsonb_typeof(parsed_brief) = 'object'
           AND jsonb_typeof(open_questions) = 'array'
           AND jsonb_typeof(user_overrides) = 'object'),
    CONSTRAINT chk_functional_design_brief_confirmation
        CHECK ((status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
            OR status <> 'confirmed')
);

CREATE INDEX IF NOT EXISTS idx_functional_design_briefs_project
    ON functional_design_briefs(project_id, revision_number DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_functional_design_briefs_confirmed
    ON functional_design_briefs(project_id)
    WHERE status = 'confirmed';
