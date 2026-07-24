-- Closed-loop content aggregates and immutable carrier-independent revisions.

CREATE TABLE IF NOT EXISTS domain_sequences (
    sequence_date DATE NOT NULL,
    object_type VARCHAR(64) NOT NULL,
    current_value BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sequence_date, object_type),
    CONSTRAINT chk_domain_sequences_value CHECK (current_value >= 0)
);

CREATE TABLE IF NOT EXISTS content_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    current_revision_number INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    owner_principal VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_content_project_revision CHECK (current_revision_number >= 0),
    CONSTRAINT chk_content_project_status CHECK (status IN ('draft', 'active', 'archived'))
);

CREATE TABLE IF NOT EXISTS content_project_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES content_projects(id) ON DELETE CASCADE,
    project_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'content-project.v1',
    generation_goal TEXT NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    producer_role VARCHAR(64) NOT NULL DEFAULT 'human_business',
    producer_strategy_revision VARCHAR(128) NOT NULL DEFAULT 'human_input.v1',
    fingerprint_sha256 CHAR(64) NOT NULL,
    expected_parent_revision INTEGER,
    created_by VARCHAR(128),
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, revision_number),
    UNIQUE (project_code, revision_number),
    CONSTRAINT chk_content_project_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_content_project_revision_status CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_content_project_revision_schema CHECK (schema_version ~ '^[a-z0-9-]+\.v[1-9][0-9]*$'),
    CONSTRAINT chk_content_project_revision_content CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT chk_content_project_revision_sources CHECK (jsonb_typeof(source_revision_refs) = 'array'),
    CONSTRAINT chk_content_project_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_content_project_revision_confirmation CHECK (
        (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
        OR status <> 'confirmed'
    )
);

CREATE INDEX IF NOT EXISTS idx_content_project_revisions_project
    ON content_project_revisions(project_id, revision_number DESC);
CREATE INDEX IF NOT EXISTS idx_content_project_revisions_fingerprint
    ON content_project_revisions(fingerprint_sha256);

CREATE TABLE IF NOT EXISTS story_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    story_brief_code VARCHAR(64) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id),
    project_code VARCHAR(64) NOT NULL,
    current_revision_number INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_story_brief_current_revision CHECK (current_revision_number >= 0)
);

CREATE TABLE IF NOT EXISTS story_brief_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    story_brief_id UUID NOT NULL REFERENCES story_briefs(id) ON DELETE CASCADE,
    story_brief_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'story-brief.v1',
    source_project_revision_id UUID NOT NULL REFERENCES content_project_revisions(id),
    content JSONB NOT NULL,
    fact_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    template_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    producer_role VARCHAR(64) NOT NULL,
    producer_strategy_revision VARCHAR(128) NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128),
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (story_brief_id, revision_number),
    UNIQUE (story_brief_code, revision_number),
    CONSTRAINT chk_story_brief_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_story_brief_revision_status CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_story_brief_revision_content CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT chk_story_brief_revision_facts CHECK (jsonb_typeof(fact_revision_refs) = 'array'),
    CONSTRAINT chk_story_brief_revision_templates CHECK (jsonb_typeof(template_revision_refs) = 'array'),
    CONSTRAINT chk_story_brief_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS content_script_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    script_revision_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id),
    source_story_brief_revision_id UUID NOT NULL REFERENCES story_brief_revisions(id),
    legacy_script_id UUID REFERENCES scripts(id) ON DELETE SET NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'content-script.v1',
    title VARCHAR(255) NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_strategy_ref VARCHAR(128) NOT NULL,
    prompt_revision VARCHAR(128) NOT NULL,
    producer_role VARCHAR(64) NOT NULL DEFAULT 'writer',
    producer_strategy_revision VARCHAR(128) NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128),
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, revision_number),
    CONSTRAINT chk_content_script_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_content_script_revision_status CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_content_script_revision_content CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT chk_content_script_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS content_script_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    block_code VARCHAR(80) NOT NULL UNIQUE,
    script_revision_id UUID NOT NULL REFERENCES content_script_revisions(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    module_type VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    estimated_duration_ms BIGINT,
    product_ref VARCHAR(128),
    fact_citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    template_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (script_revision_id, sort_order),
    CONSTRAINT chk_content_script_block_order CHECK (sort_order >= 0),
    CONSTRAINT chk_content_script_block_duration CHECK (estimated_duration_ms IS NULL OR estimated_duration_ms >= 0),
    CONSTRAINT chk_content_script_block_facts CHECK (jsonb_typeof(fact_citations) = 'array'),
    CONSTRAINT chk_content_script_block_templates CHECK (jsonb_typeof(template_sources) = 'array'),
    CONSTRAINT chk_content_script_block_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS content_program_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_revision_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id),
    source_script_revision_id UUID NOT NULL REFERENCES content_script_revisions(id),
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'content-program.v1',
    producer_role VARCHAR(64) NOT NULL DEFAULT 'director',
    producer_strategy_revision VARCHAR(128) NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    UNIQUE (project_id, revision_number),
    CONSTRAINT chk_content_program_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_content_program_revision_status CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_content_program_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS program_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_code VARCHAR(80) NOT NULL UNIQUE,
    program_revision_id UUID NOT NULL REFERENCES content_program_revisions(id) ON DELETE CASCADE,
    sort_order INTEGER NOT NULL,
    semantic_goal TEXT NOT NULL,
    entry_condition TEXT,
    exit_condition TEXT,
    script_block_start INTEGER NOT NULL,
    script_block_end INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (program_revision_id, sort_order),
    CONSTRAINT chk_program_segment_order CHECK (sort_order >= 0),
    CONSTRAINT chk_program_segment_range CHECK (script_block_start >= 0 AND script_block_end > script_block_start),
    CONSTRAINT chk_program_segment_metadata CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT chk_program_segment_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS shot_list_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_list_revision_code VARCHAR(80) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id),
    source_program_revision_id UUID NOT NULL REFERENCES content_program_revisions(id),
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'shot-list.v1',
    producer_role VARCHAR(64) NOT NULL DEFAULT 'director',
    producer_strategy_revision VARCHAR(128) NOT NULL,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    UNIQUE (project_id, revision_number),
    CONSTRAINT chk_shot_list_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_shot_list_revision_status CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_shot_list_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS shots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_code VARCHAR(80) NOT NULL UNIQUE,
    shot_list_revision_id UUID NOT NULL REFERENCES shot_list_revisions(id) ON DELETE CASCADE,
    program_segment_id UUID NOT NULL REFERENCES program_segments(id),
    sort_order INTEGER NOT NULL,
    composition_intent JSONB NOT NULL DEFAULT '{}'::jsonb,
    material_role_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    audio_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    continuity JSONB NOT NULL DEFAULT '{}'::jsonb,
    acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
    estimated_duration_ms BIGINT,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shot_list_revision_id, sort_order),
    CONSTRAINT chk_shot_order CHECK (sort_order >= 0),
    CONSTRAINT chk_shot_duration CHECK (estimated_duration_ms IS NULL OR estimated_duration_ms >= 0),
    CONSTRAINT chk_shot_composition CHECK (jsonb_typeof(composition_intent) = 'object'),
    CONSTRAINT chk_shot_material_roles CHECK (jsonb_typeof(material_role_requirements) = 'array'),
    CONSTRAINT chk_shot_audio_actions CHECK (jsonb_typeof(audio_actions) = 'array'),
    CONSTRAINT chk_shot_continuity CHECK (jsonb_typeof(continuity) = 'object'),
    CONSTRAINT chk_shot_acceptance CHECK (jsonb_typeof(acceptance_criteria) = 'array'),
    CONSTRAINT chk_shot_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS production_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    variant_code VARCHAR(64) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES content_projects(id),
    project_code VARCHAR(64) NOT NULL,
    carrier_kind VARCHAR(32) NOT NULL,
    current_revision_number INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, variant_code),
    CONSTRAINT chk_production_variant_carrier CHECK (carrier_kind IN ('live_room', 'rendered_video')),
    CONSTRAINT chk_production_variant_revision CHECK (current_revision_number >= 0),
    CONSTRAINT chk_production_variant_status CHECK (status IN ('draft', 'active', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_production_variants_project
    ON production_variants(project_id, carrier_kind);

CREATE TABLE IF NOT EXISTS production_variant_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    variant_id UUID NOT NULL REFERENCES production_variants(id) ON DELETE CASCADE,
    variant_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'production-variant.v1',
    carrier_kind VARCHAR(32) NOT NULL,
    source_story_brief_revision_id UUID NOT NULL REFERENCES story_brief_revisions(id),
    source_script_revision_id UUID NOT NULL REFERENCES content_script_revisions(id),
    source_shot_list_revision_id UUID NOT NULL REFERENCES shot_list_revisions(id),
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    stale BOOLEAN NOT NULL DEFAULT false,
    stale_reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by VARCHAR(128),
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (variant_id, revision_number),
    UNIQUE (variant_code, revision_number),
    CONSTRAINT chk_production_variant_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_production_variant_revision_status CHECK (status IN ('draft', 'confirmed', 'superseded')),
    CONSTRAINT chk_production_variant_revision_carrier CHECK (carrier_kind IN ('live_room', 'rendered_video')),
    CONSTRAINT chk_production_variant_revision_config CHECK (jsonb_typeof(configuration) = 'object'),
    CONSTRAINT chk_production_variant_revision_sources CHECK (jsonb_typeof(source_revision_refs) = 'array'),
    CONSTRAINT chk_production_variant_revision_stale CHECK (jsonb_typeof(stale_reason_codes) = 'array'),
    CONSTRAINT chk_production_variant_revision_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS shot_projection_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_id UUID NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(128) NOT NULL,
    target_revision INTEGER NOT NULL,
    relation_type VARCHAR(64) NOT NULL,
    applicable_start_ms BIGINT,
    applicable_end_ms BIGINT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shot_id, target_type, target_code, target_revision, relation_type),
    CONSTRAINT chk_shot_projection_target_revision CHECK (target_revision >= 1),
    CONSTRAINT chk_shot_projection_target_type CHECK (target_type IN ('maitu_scene_blueprint', 'layer_blueprint', 'timeline_segment')),
    CONSTRAINT chk_shot_projection_relation CHECK (relation_type IN ('projects_to', 'implemented_by', 'contributes_to')),
    CONSTRAINT chk_shot_projection_range CHECK (
        (applicable_start_ms IS NULL AND applicable_end_ms IS NULL)
        OR (applicable_start_ms >= 0 AND applicable_end_ms > applicable_start_ms)
    ),
    CONSTRAINT chk_shot_projection_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_shot_projection_target
    ON shot_projection_links(target_type, target_code, target_revision);

CREATE TABLE IF NOT EXISTS domain_derivation_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(64) NOT NULL,
    source_code VARCHAR(128) NOT NULL,
    source_revision INTEGER NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(128) NOT NULL,
    target_revision INTEGER NOT NULL,
    relation_type VARCHAR(64) NOT NULL DEFAULT 'derived_from',
    producer_role VARCHAR(64) NOT NULL,
    producer_strategy_revision VARCHAR(128) NOT NULL,
    input_fingerprint CHAR(64) NOT NULL,
    output_fingerprint CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_type, source_code, source_revision, target_type, target_code, target_revision, relation_type),
    CONSTRAINT chk_domain_derivation_revisions CHECK (source_revision >= 1 AND target_revision >= 1),
    CONSTRAINT chk_domain_derivation_input_sha CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_domain_derivation_output_sha CHECK (output_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_domain_derivation_source
    ON domain_derivation_edges(source_type, source_code, source_revision);
CREATE INDEX IF NOT EXISTS idx_domain_derivation_target
    ON domain_derivation_edges(target_type, target_code, target_revision);

CREATE TABLE IF NOT EXISTS stale_propagation_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(64) NOT NULL,
    source_code VARCHAR(128) NOT NULL,
    old_revision INTEGER NOT NULL,
    new_revision INTEGER NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_code VARCHAR(128) NOT NULL,
    target_revision INTEGER NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ,
    cleared_by_revision INTEGER,
    UNIQUE (source_type, source_code, new_revision, target_type, target_code, target_revision),
    CONSTRAINT chk_stale_source_revisions CHECK (old_revision >= 1 AND new_revision > old_revision),
    CONSTRAINT chk_stale_target_revision CHECK (target_revision >= 1),
    CONSTRAINT chk_stale_clear_revision CHECK (cleared_by_revision IS NULL OR cleared_by_revision >= 1)
);

CREATE OR REPLACE FUNCTION protect_closed_loop_revision()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IN ('confirmed', 'published', 'approved', 'released', 'superseded') THEN
        IF OLD.status IN ('confirmed', 'published', 'approved')
           AND NEW.status = 'superseded'
           AND (to_jsonb(OLD) - ARRAY['status', 'superseded_at', 'updated_at']::text[])
               = (to_jsonb(NEW) - ARRAY['status', 'superseded_at', 'updated_at']::text[]) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'immutable closed-loop revision cannot be mutated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_content_project_revision_immutable ON content_project_revisions;
CREATE TRIGGER trg_content_project_revision_immutable
BEFORE UPDATE ON content_project_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();

DROP TRIGGER IF EXISTS trg_story_brief_revision_immutable ON story_brief_revisions;
CREATE TRIGGER trg_story_brief_revision_immutable
BEFORE UPDATE ON story_brief_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();

DROP TRIGGER IF EXISTS trg_content_script_revision_immutable ON content_script_revisions;
CREATE TRIGGER trg_content_script_revision_immutable
BEFORE UPDATE ON content_script_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();

DROP TRIGGER IF EXISTS trg_content_program_revision_immutable ON content_program_revisions;
CREATE TRIGGER trg_content_program_revision_immutable
BEFORE UPDATE ON content_program_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();

DROP TRIGGER IF EXISTS trg_shot_list_revision_immutable ON shot_list_revisions;
CREATE TRIGGER trg_shot_list_revision_immutable
BEFORE UPDATE ON shot_list_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();

DROP TRIGGER IF EXISTS trg_production_variant_revision_immutable ON production_variant_revisions;
CREATE TRIGGER trg_production_variant_revision_immutable
BEFORE UPDATE ON production_variant_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();
