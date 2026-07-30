-- Customer-facing operation data imports are staged before any session is
-- created.  The original file, normalized rows, validation findings, and
-- binding revisions remain available after confirmation.

ALTER TABLE functional_operation_sessions
    ADD COLUMN IF NOT EXISTS video_plan_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS bound_content_kind VARCHAR(64),
    ADD COLUMN IF NOT EXISTS bound_content_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS bound_content_revision INTEGER,
    ADD COLUMN IF NOT EXISTS binding_status VARCHAR(32) NOT NULL DEFAULT 'pending';

ALTER TABLE functional_operation_sessions
    ADD CONSTRAINT chk_functional_operation_binding_status
    CHECK (binding_status IN ('resolved', 'pending', 'not_required'));

ALTER TABLE functional_content_exposures
    ADD COLUMN IF NOT EXISTS content_kind VARCHAR(64) NOT NULL DEFAULT 'live_room_plan',
    ADD COLUMN IF NOT EXISTS content_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS content_revision INTEGER,
    ADD COLUMN IF NOT EXISTS scope_type VARCHAR(64) NOT NULL DEFAULT 'maitu_scene',
    ADD COLUMN IF NOT EXISTS scope_code VARCHAR(128);

UPDATE functional_content_exposures
SET content_code = plan_code,
    scope_code = scene_code
WHERE content_code IS NULL OR scope_code IS NULL;

CREATE TABLE IF NOT EXISTS functional_operation_import_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_code VARCHAR(64) NOT NULL UNIQUE,
    original_filename VARCHAR(255) NOT NULL,
    file_kind VARCHAR(16) NOT NULL,
    source_checksum_sha256 CHAR(64) NOT NULL,
    source_file BYTEA NOT NULL,
    field_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    preview_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'preview',
    created_by VARCHAR(128) NOT NULL,
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_operation_import_file_kind CHECK (file_kind IN ('csv', 'xlsx')),
    CONSTRAINT chk_functional_operation_import_checksum CHECK (source_checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_operation_import_mapping CHECK (jsonb_typeof(field_mapping) = 'object'),
    CONSTRAINT chk_functional_operation_import_summary CHECK (jsonb_typeof(preview_summary) = 'object'),
    CONSTRAINT chk_functional_operation_import_status CHECK (status IN ('preview', 'confirmed', 'failed')),
    CONSTRAINT chk_functional_operation_import_confirmation CHECK (
        (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
        OR status <> 'confirmed'
    )
);

CREATE TABLE IF NOT EXISTS functional_operation_import_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES functional_operation_import_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    row_fingerprint_sha256 CHAR(64) NOT NULL,
    raw_values JSONB NOT NULL,
    normalized_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    validation_warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    duplicate_kind VARCHAR(32),
    duplicate_of_session_code VARCHAR(64),
    binding_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    binding_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    import_status VARCHAR(32) NOT NULL,
    imported_session_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (batch_id, row_number),
    CONSTRAINT chk_functional_operation_import_row_fingerprint CHECK (row_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_operation_import_row_raw CHECK (jsonb_typeof(raw_values) = 'object'),
    CONSTRAINT chk_functional_operation_import_row_normalized CHECK (jsonb_typeof(normalized_payload) = 'object'),
    CONSTRAINT chk_functional_operation_import_row_errors CHECK (jsonb_typeof(validation_errors) = 'array'),
    CONSTRAINT chk_functional_operation_import_row_warnings CHECK (jsonb_typeof(validation_warnings) = 'array'),
    CONSTRAINT chk_functional_operation_import_row_candidates CHECK (jsonb_typeof(binding_candidates) = 'array'),
    CONSTRAINT chk_functional_operation_import_row_duplicate CHECK (
        duplicate_kind IS NULL OR duplicate_kind IN ('exact_file_row', 'existing_session')
    ),
    CONSTRAINT chk_functional_operation_import_row_binding CHECK (
        binding_status IN ('resolved', 'pending', 'not_required')
    ),
    CONSTRAINT chk_functional_operation_import_row_status CHECK (
        import_status IN ('ready', 'pending_binding', 'invalid', 'duplicate', 'imported', 'skipped')
    )
);

CREATE INDEX IF NOT EXISTS idx_functional_operation_import_rows_batch_status
    ON functional_operation_import_rows(batch_id, import_status, row_number);

CREATE TABLE IF NOT EXISTS functional_operation_session_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    binding_code VARCHAR(64) NOT NULL UNIQUE,
    session_id UUID NOT NULL REFERENCES functional_operation_sessions(id) ON DELETE CASCADE,
    session_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    resolution_status VARCHAR(32) NOT NULL,
    content_kind VARCHAR(64),
    content_code VARCHAR(128),
    content_revision INTEGER,
    candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_import_batch_code VARCHAR(64),
    evidence_note TEXT NOT NULL,
    actor VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, revision_number),
    CONSTRAINT chk_functional_operation_session_binding_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_functional_operation_session_binding_status CHECK (status IN ('active', 'superseded')),
    CONSTRAINT chk_functional_operation_session_binding_resolution CHECK (
        resolution_status IN ('resolved', 'pending', 'not_required')
    ),
    CONSTRAINT chk_functional_operation_session_binding_candidates CHECK (jsonb_typeof(candidates) = 'array')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_functional_operation_session_binding_active
    ON functional_operation_session_bindings(session_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_functional_operation_session_bindings_pending
    ON functional_operation_session_bindings(resolution_status, created_at DESC);

-- Existing session links remain usable and gain an explicit first binding
-- revision. Sessions with no content evidence stay in the pending queue.
UPDATE functional_operation_sessions
SET bound_content_kind = CASE
        WHEN live_room_plan_code IS NOT NULL THEN 'live_room_plan'
        WHEN video_plan_code IS NOT NULL THEN 'rendered_video_plan'
        WHEN content_project_code IS NOT NULL THEN 'content_project_revision'
        ELSE NULL
    END,
    bound_content_code = COALESCE(live_room_plan_code, video_plan_code, content_project_code),
    binding_status = CASE
        WHEN live_room_plan_code IS NOT NULL OR video_plan_code IS NOT NULL OR content_project_code IS NOT NULL
            THEN 'resolved'
        ELSE 'pending'
    END
WHERE bound_content_kind IS NULL;

INSERT INTO functional_operation_session_bindings
    (binding_code, session_id, session_code, revision_number, resolution_status,
     content_kind, content_code, content_revision, candidates, evidence_note, actor)
SELECT 'OPS-BIND-MIG-' || substr(md5(session.id::text), 1, 20),
       session.id,
       session.session_code,
       1,
       session.binding_status,
       session.bound_content_kind,
       session.bound_content_code,
       session.bound_content_revision,
       '[]'::jsonb,
       'Migration 102 backfilled the existing session binding.',
       'migration_102'
FROM functional_operation_sessions AS session
ON CONFLICT (session_id, revision_number) DO NOTHING;
