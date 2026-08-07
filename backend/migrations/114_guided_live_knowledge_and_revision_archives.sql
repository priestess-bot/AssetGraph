-- Guided live-project knowledge references, setup assistants, and immutable
-- revision archives.  Archive rows deliberately live outside the immutable
-- content revision tables so a previous revision is never rewritten.

ALTER TABLE content_generation_jobs
    ADD COLUMN IF NOT EXISTS operation VARCHAR(64) NOT NULL DEFAULT 'generate';

UPDATE content_generation_jobs
SET operation = CASE stage
    WHEN 'outline' THEN 'generate_outline'
    WHEN 'script' THEN 'generate_script'
    WHEN 'storyboard' THEN 'generate_storyboard'
    ELSE operation
END
WHERE operation = 'generate';

DROP INDEX IF EXISTS idx_content_generation_job_active;

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_generation_job_active
    ON content_generation_jobs(project_id, stage, operation)
    WHERE status IN ('queued', 'running');

ALTER TABLE content_generation_jobs
    DROP CONSTRAINT IF EXISTS chk_content_generation_job_stage;

ALTER TABLE content_generation_jobs
    ADD CONSTRAINT chk_content_generation_job_stage CHECK (
        stage IN ('setup', 'outline', 'script', 'storyboard')
    );

ALTER TABLE content_generation_jobs
    ADD CONSTRAINT chk_content_generation_job_operation CHECK (
        operation IN (
            'optimize_theme',
            'recommend_knowledge',
            'recommend_materials',
            'generate_outline',
            'regenerate_outline_section',
            'generate_script',
            'generate_storyboard'
        )
    );

CREATE TABLE IF NOT EXISTS content_guided_revision_archives (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    archive_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    project_code VARCHAR(64) NOT NULL,
    artifact_type VARCHAR(32) NOT NULL,
    artifact_code VARCHAR(80) NOT NULL,
    revision_number INTEGER NOT NULL,
    reason VARCHAR(128) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    archived_by VARCHAR(128) NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    restored_from_archive_code VARCHAR(80),
    UNIQUE (project_id, artifact_type, artifact_code, revision_number),
    CONSTRAINT chk_content_guided_archive_type CHECK (artifact_type IN ('outline', 'script')),
    CONSTRAINT chk_content_guided_archive_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_content_guided_archive_details CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_content_guided_revision_archives_project
    ON content_guided_revision_archives(project_id, artifact_type, archived_at DESC);
