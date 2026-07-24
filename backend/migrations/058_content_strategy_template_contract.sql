-- `layout-hypothesis.v1` remains a read-only external-video layout reference.
-- New cleaned content templates share the stable template identity but carry a
-- separate contract, source-session bridge and explicit capability dimensions.

ALTER TABLE live_room_templates
    ADD COLUMN IF NOT EXISTS template_kind VARCHAR(32) NOT NULL DEFAULT 'layout_hypothesis';

DO $$ BEGIN
    ALTER TABLE live_room_templates
        ADD CONSTRAINT chk_live_room_template_kind
            CHECK (template_kind IN ('layout_hypothesis', 'content_strategy'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE live_room_template_revisions
    ADD COLUMN IF NOT EXISTS content_readiness VARCHAR(32) NOT NULL DEFAULT 'review_required',
    ADD COLUMN IF NOT EXISTS layout_fidelity VARCHAR(32) NOT NULL DEFAULT 'approximate',
    ADD COLUMN IF NOT EXISTS buildability VARCHAR(32) NOT NULL DEFAULT 'reference_only',
    ADD COLUMN IF NOT EXISTS content_strategy JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS layout_reference JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$ BEGIN
    ALTER TABLE live_room_template_revisions
        ADD CONSTRAINT chk_live_room_template_content_readiness
            CHECK (content_readiness IN ('blocked', 'review_required', 'ready'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE live_room_template_revisions
        ADD CONSTRAINT chk_live_room_template_layout_fidelity
            CHECK (layout_fidelity IN ('none', 'approximate', 'verified_layout'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE live_room_template_revisions
        ADD CONSTRAINT chk_live_room_template_buildability
            CHECK (buildability IN ('reference_only', 'executable'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE live_room_template_revisions
        ADD CONSTRAINT chk_live_room_template_content_strategy
            CHECK (jsonb_typeof(content_strategy) = 'object');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    ALTER TABLE live_room_template_revisions
        ADD CONSTRAINT chk_live_room_template_layout_reference
            CHECK (jsonb_typeof(layout_reference) = 'object');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS live_room_template_revision_source_sessions (
    revision_id UUID NOT NULL REFERENCES live_room_template_revisions(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES live_capture_sessions(id) ON DELETE RESTRICT,
    session_code VARCHAR(64) NOT NULL,
    target_id UUID NOT NULL REFERENCES live_watch_targets(id) ON DELETE RESTRICT,
    target_code VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (revision_id, session_id),
    UNIQUE (revision_id, session_code)
);

CREATE INDEX IF NOT EXISTS idx_live_room_template_source_session_target
    ON live_room_template_revision_source_sessions(target_code, session_code);

-- Backfill the pre-existing optional single-session reference without treating
-- incomplete historical rows as proof of a content-strategy source boundary.
INSERT INTO live_room_template_revision_source_sessions (
    revision_id, session_id, session_code, target_id, target_code
)
SELECT revision.id, session.id, session.session_code, session.target_id, session.target_code
FROM live_room_template_revisions AS revision
JOIN live_capture_sessions AS session ON session.id = revision.source_session_id
ON CONFLICT DO NOTHING;
