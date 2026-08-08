-- Branch-aware authoring for guided live projects. Full generations create tree
-- nodes; edits and targeted generations create immutable versions inside a node.

CREATE TABLE IF NOT EXISTS content_guided_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    project_code VARCHAR(64) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    parent_node_id UUID REFERENCES content_guided_nodes(id) ON DELETE CASCADE,
    branch_order INTEGER NOT NULL,
    label VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    current_revision_number INTEGER NOT NULL DEFAULT 0,
    confirmed_revision_number INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_content_guided_node_stage CHECK (
        stage IN ('setup', 'outline', 'script', 'storyboard')
    ),
    CONSTRAINT chk_content_guided_node_status CHECK (
        status IN ('draft', 'generating', 'confirmed', 'needs_update', 'failed', 'archived')
    ),
    CONSTRAINT chk_content_guided_node_revisions CHECK (
        current_revision_number >= 0
        AND confirmed_revision_number >= 0
        AND confirmed_revision_number <= current_revision_number
    ),
    CONSTRAINT chk_content_guided_node_branch_order CHECK (branch_order >= 1),
    UNIQUE (project_id, stage, parent_node_id, branch_order)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_guided_setup_branch_order
    ON content_guided_nodes(project_id, stage, branch_order)
    WHERE parent_node_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_content_guided_nodes_tree
    ON content_guided_nodes(project_id, parent_node_id, stage, branch_order);

CREATE TABLE IF NOT EXISTS content_guided_node_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES content_guided_nodes(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    base_revision_id UUID REFERENCES content_guided_node_revisions(id),
    source_parent_revision_id UUID REFERENCES content_guided_node_revisions(id),
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    canonical_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    semantic_fingerprint CHAR(64) NOT NULL,
    lineage_fingerprint CHAR(64) NOT NULL,
    producer_kind VARCHAR(32) NOT NULL DEFAULT 'human',
    producer_ref VARCHAR(128),
    created_by VARCHAR(128) NOT NULL,
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    discarded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_id, revision_number),
    CONSTRAINT chk_content_guided_node_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_content_guided_node_revision_status CHECK (
        status IN ('draft', 'confirmed', 'superseded', 'discarded')
    ),
    CONSTRAINT chk_content_guided_node_revision_payloads CHECK (
        jsonb_typeof(content) = 'object'
        AND jsonb_typeof(change_summary) = 'object'
        AND jsonb_typeof(canonical_refs) = 'object'
    ),
    CONSTRAINT chk_content_guided_node_revision_fingerprints CHECK (
        semantic_fingerprint ~ '^[0-9a-f]{64}$'
        AND lineage_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_content_guided_node_revision_confirmation CHECK (
        (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
        OR status <> 'confirmed'
    )
);

CREATE INDEX IF NOT EXISTS idx_content_guided_node_revisions_node
    ON content_guided_node_revisions(node_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS content_guided_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES content_guided_nodes(id) ON DELETE CASCADE,
    item_key VARCHAR(128) NOT NULL,
    item_type VARCHAR(32) NOT NULL,
    source_item_key VARCHAR(128),
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_id, item_key),
    CONSTRAINT chk_content_guided_item_type CHECK (
        item_type IN ('outline_section', 'script_block', 'storyboard_scene')
    )
);

CREATE TABLE IF NOT EXISTS content_guided_item_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID NOT NULL REFERENCES content_guided_items(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    semantic_fingerprint CHAR(64) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    lineage_fingerprint CHAR(64) NOT NULL,
    producer_kind VARCHAR(32) NOT NULL DEFAULT 'human',
    producer_ref VARCHAR(128),
    guidance TEXT,
    invocation_evidence_ref VARCHAR(80),
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (item_id, version_number),
    CONSTRAINT chk_content_guided_item_version_number CHECK (version_number >= 1),
    CONSTRAINT chk_content_guided_item_version_content CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT chk_content_guided_item_version_fingerprints CHECK (
        semantic_fingerprint ~ '^[0-9a-f]{64}$'
        AND input_fingerprint ~ '^[0-9a-f]{64}$'
        AND lineage_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_content_guided_item_versions_item
    ON content_guided_item_versions(item_id, version_number DESC);

CREATE TABLE IF NOT EXISTS content_guided_node_revision_items (
    node_revision_id UUID NOT NULL REFERENCES content_guided_node_revisions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES content_guided_items(id) ON DELETE CASCADE,
    item_version_id UUID NOT NULL REFERENCES content_guided_item_versions(id),
    sort_order INTEGER NOT NULL,
    PRIMARY KEY (node_revision_id, item_id),
    UNIQUE (node_revision_id, sort_order),
    CONSTRAINT chk_content_guided_revision_item_order CHECK (sort_order >= 0)
);

CREATE INDEX IF NOT EXISTS idx_content_guided_revision_items_version
    ON content_guided_node_revision_items(item_version_id, node_revision_id);

CREATE TABLE IF NOT EXISTS content_guided_item_version_sources (
    item_version_id UUID NOT NULL REFERENCES content_guided_item_versions(id) ON DELETE CASCADE,
    source_node_revision_id UUID REFERENCES content_guided_node_revisions(id),
    source_item_version_id UUID REFERENCES content_guided_item_versions(id),
    relation_type VARCHAR(32) NOT NULL DEFAULT 'derived_from',
    accepted_by VARCHAR(128),
    accepted_at TIMESTAMPTZ,
    PRIMARY KEY (item_version_id, relation_type),
    CONSTRAINT chk_content_guided_item_source_relation CHECK (
        relation_type IN ('derived_from', 'reaffirmed_from', 'copied_from')
    ),
    CONSTRAINT chk_content_guided_item_source_target CHECK (
        source_node_revision_id IS NOT NULL OR source_item_version_id IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS content_guided_project_heads (
    project_id UUID PRIMARY KEY REFERENCES content_projects(id) ON DELETE CASCADE,
    project_code VARCHAR(64) NOT NULL UNIQUE,
    selected_root_node_id UUID REFERENCES content_guided_nodes(id) ON DELETE SET NULL,
    selected_leaf_node_id UUID REFERENCES content_guided_nodes(id) ON DELETE SET NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_content_guided_project_head_revision CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS content_guided_child_selections (
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    parent_node_id UUID NOT NULL REFERENCES content_guided_nodes(id) ON DELETE CASCADE,
    selected_child_node_id UUID NOT NULL REFERENCES content_guided_nodes(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, parent_node_id),
    CONSTRAINT chk_content_guided_child_selection_revision CHECK (revision >= 1),
    CONSTRAINT chk_content_guided_child_selection_distinct CHECK (
        parent_node_id <> selected_child_node_id
    )
);

CREATE TABLE IF NOT EXISTS content_guided_revision_projections (
    node_revision_id UUID NOT NULL REFERENCES content_guided_node_revisions(id) ON DELETE CASCADE,
    artifact_type VARCHAR(32) NOT NULL,
    artifact_code VARCHAR(128) NOT NULL,
    revision_number INTEGER,
    fingerprint_sha256 CHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_revision_id, artifact_type, artifact_code),
    CONSTRAINT chk_content_guided_projection_type CHECK (
        artifact_type IN (
            'content_project', 'material_pool', 'story_brief', 'content_script',
            'content_program', 'shot_list', 'live_room_plan'
        )
    ),
    CONSTRAINT chk_content_guided_projection_revision CHECK (
        revision_number IS NULL OR revision_number >= 1
    ),
    CONSTRAINT chk_content_guided_projection_sha CHECK (
        fingerprint_sha256 IS NULL OR fingerprint_sha256 ~ '^[0-9a-f]{64}$'
    )
);

ALTER TABLE content_generation_jobs
    ADD COLUMN IF NOT EXISTS target_node_id UUID REFERENCES content_guided_nodes(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS target_node_revision INTEGER,
    ADD COLUMN IF NOT EXISTS target_item_id UUID REFERENCES content_guided_items(id) ON DELETE CASCADE;

ALTER TABLE content_generation_jobs
    DROP CONSTRAINT IF EXISTS chk_content_generation_job_operation;

ALTER TABLE content_generation_jobs
    ADD CONSTRAINT chk_content_generation_job_operation CHECK (
        operation IN (
            'optimize_theme',
            'recommend_knowledge',
            'recommend_materials',
            'generate_outline',
            'regenerate_outline_section',
            'generate_script',
            'regenerate_script_block',
            'generate_storyboard',
            'regenerate_storyboard_scene'
        )
    );

ALTER TABLE content_generation_jobs
    ADD CONSTRAINT chk_content_generation_job_target_revision CHECK (
        target_node_revision IS NULL OR target_node_revision >= 0
    );

DROP INDEX IF EXISTS idx_content_generation_job_active;

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_generation_job_active_stage
    ON content_generation_jobs(project_id, stage, operation)
    WHERE status IN ('queued', 'running') AND target_item_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_content_generation_job_active_item
    ON content_generation_jobs(target_item_id, operation)
    WHERE status IN ('queued', 'running') AND target_item_id IS NOT NULL;
