-- Complete the carrier-independent content chain and legacy branch projections.

ALTER TABLE story_brief_revisions
    ADD COLUMN source_design_brief_revision VARCHAR(128) NOT NULL DEFAULT 'legacy_import',
    ADD COLUMN input_fingerprint CHAR(64);

UPDATE story_brief_revisions
SET input_fingerprint = fingerprint_sha256
WHERE input_fingerprint IS NULL;

ALTER TABLE story_brief_revisions
    ALTER COLUMN input_fingerprint SET NOT NULL,
    ADD CONSTRAINT chk_story_brief_input_sha
        CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT chk_story_brief_confirmation
        CHECK (
            (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
            OR status <> 'confirmed'
        );

ALTER TABLE content_script_revisions
    ADD COLUMN generation_run_code VARCHAR(80),
    ADD COLUMN validation_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN source_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT chk_content_script_validation CHECK (jsonb_typeof(validation_result) = 'object'),
    ADD CONSTRAINT chk_content_script_sources CHECK (jsonb_typeof(source_revision_refs) = 'array'),
    ADD CONSTRAINT chk_content_script_confirmation
        CHECK (
            (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
            OR status <> 'confirmed'
        );

ALTER TABLE content_script_blocks
    ADD COLUMN interaction_intent JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN cta_intent JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT chk_content_script_block_interaction CHECK (jsonb_typeof(interaction_intent) = 'object'),
    ADD CONSTRAINT chk_content_script_block_cta CHECK (jsonb_typeof(cta_intent) = 'object');

ALTER TABLE content_program_revisions
    ADD COLUMN source_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN created_by VARCHAR(128),
    ADD COLUMN confirmed_by VARCHAR(128),
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD CONSTRAINT chk_content_program_sources CHECK (jsonb_typeof(source_revision_refs) = 'array'),
    ADD CONSTRAINT chk_content_program_confirmation
        CHECK (
            (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
            OR status <> 'confirmed'
        );

ALTER TABLE program_segments
    ADD COLUMN program_phase VARCHAR(64) NOT NULL DEFAULT 'body',
    ADD COLUMN estimated_duration_ms BIGINT,
    ADD COLUMN product_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN interaction_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN cta_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN branch_applicability JSONB NOT NULL DEFAULT '["live_room", "rendered_video"]'::jsonb,
    ADD CONSTRAINT chk_program_segment_duration CHECK (estimated_duration_ms IS NULL OR estimated_duration_ms >= 0),
    ADD CONSTRAINT chk_program_segment_products CHECK (jsonb_typeof(product_refs) = 'array'),
    ADD CONSTRAINT chk_program_segment_interactions CHECK (jsonb_typeof(interaction_actions) = 'array'),
    ADD CONSTRAINT chk_program_segment_ctas CHECK (jsonb_typeof(cta_actions) = 'array'),
    ADD CONSTRAINT chk_program_segment_branches CHECK (jsonb_typeof(branch_applicability) = 'array');

CREATE TABLE IF NOT EXISTS program_segment_script_block_adoptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_id UUID NOT NULL REFERENCES program_segments(id) ON DELETE CASCADE,
    script_block_id UUID NOT NULL REFERENCES content_script_blocks(id),
    adoption_order INTEGER NOT NULL,
    content_start_offset INTEGER,
    content_end_offset INTEGER,
    content_action VARCHAR(64) NOT NULL DEFAULT 'deliver',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (segment_id, script_block_id, adoption_order),
    CONSTRAINT chk_segment_adoption_order CHECK (adoption_order >= 0),
    CONSTRAINT chk_segment_adoption_offsets CHECK (
        (content_start_offset IS NULL AND content_end_offset IS NULL)
        OR (content_start_offset >= 0 AND content_end_offset > content_start_offset)
    ),
    CONSTRAINT chk_segment_adoption_action CHECK (
        content_action IN ('deliver', 'summarize', 'repeat', 'interact', 'convert')
    ),
    CONSTRAINT chk_segment_adoption_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_segment_block_adoptions_block
    ON program_segment_script_block_adoptions(script_block_id, segment_id);

ALTER TABLE shot_list_revisions
    ADD COLUMN source_revision_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN created_by VARCHAR(128),
    ADD COLUMN confirmed_by VARCHAR(128),
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD CONSTRAINT chk_shot_list_sources CHECK (jsonb_typeof(source_revision_refs) = 'array'),
    ADD CONSTRAINT chk_shot_list_confirmation
        CHECK (
            (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
            OR status <> 'confirmed'
        );

ALTER TABLE shots
    ADD COLUMN shot_goal TEXT NOT NULL DEFAULT 'legacy_import',
    ADD COLUMN branch_applicability JSONB NOT NULL DEFAULT '["live_room", "rendered_video"]'::jsonb,
    ADD COLUMN must_include JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN must_avoid JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT chk_shot_branches CHECK (jsonb_typeof(branch_applicability) = 'array'),
    ADD CONSTRAINT chk_shot_must_include CHECK (jsonb_typeof(must_include) = 'array'),
    ADD CONSTRAINT chk_shot_must_avoid CHECK (jsonb_typeof(must_avoid) = 'array');

CREATE TABLE IF NOT EXISTS shot_script_block_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shot_id UUID NOT NULL REFERENCES shots(id) ON DELETE CASCADE,
    script_block_id UUID NOT NULL REFERENCES content_script_blocks(id),
    source_order INTEGER NOT NULL,
    content_start_offset INTEGER,
    content_end_offset INTEGER,
    relation_type VARCHAR(32) NOT NULL DEFAULT 'derived_from',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (shot_id, script_block_id, source_order),
    CONSTRAINT chk_shot_source_order CHECK (source_order >= 0),
    CONSTRAINT chk_shot_source_offsets CHECK (
        (content_start_offset IS NULL AND content_end_offset IS NULL)
        OR (content_start_offset >= 0 AND content_end_offset > content_start_offset)
    ),
    CONSTRAINT chk_shot_source_relation CHECK (
        relation_type IN ('derived_from', 'quotes', 'summarizes', 'supports')
    )
);

CREATE INDEX IF NOT EXISTS idx_shot_script_sources_block
    ON shot_script_block_sources(script_block_id, shot_id);

ALTER TABLE production_variant_revisions
    ADD COLUMN source_project_revision_id UUID REFERENCES content_project_revisions(id),
    ADD COLUMN source_quality VARCHAR(32) NOT NULL DEFAULT 'verified',
    ADD COLUMN branch_target JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN material_snapshot_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN constraint_snapshot_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN expected_delivery_type VARCHAR(32),
    ADD COLUMN producer_role VARCHAR(64) NOT NULL DEFAULT 'producer',
    ADD COLUMN producer_strategy_revision VARCHAR(128) NOT NULL DEFAULT 'system_baseline.v1',
    ADD CONSTRAINT chk_variant_source_quality CHECK (source_quality IN ('verified', 'legacy_import')),
    ADD CONSTRAINT chk_variant_branch_target CHECK (jsonb_typeof(branch_target) = 'object'),
    ADD CONSTRAINT chk_variant_material_snapshot CHECK (jsonb_typeof(material_snapshot_ref) = 'object'),
    ADD CONSTRAINT chk_variant_constraint_snapshot CHECK (jsonb_typeof(constraint_snapshot_ref) = 'object'),
    ADD CONSTRAINT chk_variant_delivery_type CHECK (
        expected_delivery_type IN ('live_room_draft', 'rendered_video')
    );

UPDATE production_variant_revisions
SET source_quality = 'legacy_import'
WHERE source_project_revision_id IS NULL;

ALTER TABLE production_variant_revisions
    ADD CONSTRAINT chk_variant_project_source CHECK (
        source_project_revision_id IS NOT NULL OR source_quality = 'legacy_import'
    );

CREATE OR REPLACE FUNCTION protect_closed_loop_revision()
RETURNS TRIGGER AS $$
BEGIN
    -- Freshness is a rebuildable projection, not part of the immutable business input.
    IF TG_TABLE_NAME = 'production_variant_revisions'
       AND OLD.status IN ('confirmed', 'superseded')
       AND (to_jsonb(OLD) - ARRAY['stale', 'stale_reason_codes', 'updated_at']::text[])
           = (to_jsonb(NEW) - ARRAY['stale', 'stale_reason_codes', 'updated_at']::text[]) THEN
        RETURN NEW;
    END IF;
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

CREATE TABLE IF NOT EXISTS live_room_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    configuration_code VARCHAR(64) NOT NULL UNIQUE,
    variant_id UUID NOT NULL UNIQUE REFERENCES production_variants(id),
    variant_code VARCHAR(64) NOT NULL,
    current_revision_number INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at TIMESTAMPTZ,
    CONSTRAINT chk_live_room_configuration_revision CHECK (current_revision_number >= 0),
    CONSTRAINT chk_live_room_configuration_status CHECK (status IN ('draft', 'active', 'archived'))
);

CREATE TABLE IF NOT EXISTS live_room_configuration_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    configuration_id UUID NOT NULL REFERENCES live_room_configurations(id) ON DELETE CASCADE,
    configuration_code VARCHAR(64) NOT NULL,
    revision_number INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    schema_version VARCHAR(64) NOT NULL DEFAULT 'live-room-configuration.v1',
    production_variant_revision_id UUID NOT NULL REFERENCES production_variant_revisions(id),
    target_live_room_id VARCHAR(64) NOT NULL,
    expected_title VARCHAR(255) NOT NULL,
    build_mode VARCHAR(32) NOT NULL,
    inventory_snapshot_ref JSONB NOT NULL,
    site_protection_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_workbench_run_code VARCHAR(64),
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_by VARCHAR(128),
    confirmed_by VARCHAR(128),
    confirmed_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (configuration_id, revision_number),
    UNIQUE (configuration_code, revision_number),
    CONSTRAINT chk_live_room_configuration_revision_number CHECK (revision_number >= 1),
    CONSTRAINT chk_live_room_configuration_revision_status CHECK (
        status IN ('draft', 'confirmed', 'superseded')
    ),
    CONSTRAINT chk_live_room_configuration_build_mode CHECK (
        build_mode IN ('auto_write_draft', 'plan_only')
    ),
    CONSTRAINT chk_live_room_configuration_inventory CHECK (jsonb_typeof(inventory_snapshot_ref) = 'object'),
    CONSTRAINT chk_live_room_configuration_protection CHECK (jsonb_typeof(site_protection_policy) = 'object'),
    CONSTRAINT chk_live_room_configuration_payload CHECK (jsonb_typeof(configuration) = 'object'),
    CONSTRAINT chk_live_room_configuration_sha CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_live_room_configuration_confirmation CHECK (
        (status = 'confirmed' AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL)
        OR status <> 'confirmed'
    )
);

DROP TRIGGER IF EXISTS trg_live_room_configuration_revision_immutable
    ON live_room_configuration_revisions;
CREATE TRIGGER trg_live_room_configuration_revision_immutable
BEFORE UPDATE ON live_room_configuration_revisions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision();

CREATE TABLE IF NOT EXISTS legacy_production_variant_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(64) NOT NULL,
    source_code VARCHAR(80) NOT NULL,
    production_variant_revision_id UUID NOT NULL REFERENCES production_variant_revisions(id),
    live_room_configuration_revision_id UUID REFERENCES live_room_configuration_revisions(id),
    mapping_quality VARCHAR(32) NOT NULL DEFAULT 'verified',
    source_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    mapped_by VARCHAR(128) NOT NULL,
    mapped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_type, source_code),
    CONSTRAINT chk_legacy_variant_source_type CHECK (
        source_type IN ('maitu_workbench_run', 'video_production_job')
    ),
    CONSTRAINT chk_legacy_variant_mapping_quality CHECK (
        mapping_quality IN ('verified', 'legacy_import', 'partial', 'unknown')
    ),
    CONSTRAINT chk_legacy_variant_snapshot CHECK (jsonb_typeof(source_snapshot) = 'object')
);

ALTER TABLE maitu_workbench_runs
    ADD COLUMN production_variant_revision_id UUID REFERENCES production_variant_revisions(id),
    ADD COLUMN live_room_configuration_revision_id UUID REFERENCES live_room_configuration_revisions(id);

ALTER TABLE video_production_jobs
    ADD COLUMN production_variant_revision_id UUID REFERENCES production_variant_revisions(id);

CREATE OR REPLACE FUNCTION revision_child_parent_status(child_table TEXT, child_row JSONB)
RETURNS TEXT AS $$
DECLARE
    parent_status TEXT;
BEGIN
    CASE child_table
        WHEN 'content_script_blocks' THEN
            SELECT status INTO parent_status FROM content_script_revisions
            WHERE id = (child_row ->> 'script_revision_id')::uuid;
        WHEN 'program_segments' THEN
            SELECT status INTO parent_status FROM content_program_revisions
            WHERE id = (child_row ->> 'program_revision_id')::uuid;
        WHEN 'program_segment_script_block_adoptions' THEN
            SELECT revision.status INTO parent_status
            FROM program_segments AS segment
            JOIN content_program_revisions AS revision ON revision.id = segment.program_revision_id
            WHERE segment.id = (child_row ->> 'segment_id')::uuid;
        WHEN 'shots' THEN
            SELECT status INTO parent_status FROM shot_list_revisions
            WHERE id = (child_row ->> 'shot_list_revision_id')::uuid;
        WHEN 'shot_script_block_sources', 'shot_projection_links' THEN
            SELECT revision.status INTO parent_status
            FROM shots AS shot
            JOIN shot_list_revisions AS revision ON revision.id = shot.shot_list_revision_id
            WHERE shot.id = (child_row ->> 'shot_id')::uuid;
        ELSE
            RAISE EXCEPTION 'unsupported immutable revision child table: %', child_table;
    END CASE;
    RETURN parent_status;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION protect_closed_loop_revision_child()
RETURNS TRIGGER AS $$
DECLARE
    parent_status TEXT;
BEGIN
    IF TG_TABLE_NAME = 'shot_projection_links' THEN
        IF TG_OP = 'INSERT' THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'shot projection links are append-only';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        parent_status := revision_child_parent_status(TG_TABLE_NAME, to_jsonb(OLD));
        IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
            RAISE EXCEPTION 'immutable closed-loop revision child cannot be mutated';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        parent_status := revision_child_parent_status(TG_TABLE_NAME, to_jsonb(NEW));
        IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
            RAISE EXCEPTION 'immutable closed-loop revision child cannot be mutated';
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_content_script_block_immutable ON content_script_blocks;
CREATE TRIGGER trg_content_script_block_immutable
BEFORE INSERT OR UPDATE OR DELETE ON content_script_blocks
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision_child();

DROP TRIGGER IF EXISTS trg_program_segment_immutable ON program_segments;
CREATE TRIGGER trg_program_segment_immutable
BEFORE INSERT OR UPDATE OR DELETE ON program_segments
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision_child();

DROP TRIGGER IF EXISTS trg_program_segment_adoption_immutable ON program_segment_script_block_adoptions;
CREATE TRIGGER trg_program_segment_adoption_immutable
BEFORE INSERT OR UPDATE OR DELETE ON program_segment_script_block_adoptions
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision_child();

DROP TRIGGER IF EXISTS trg_shot_immutable ON shots;
CREATE TRIGGER trg_shot_immutable
BEFORE INSERT OR UPDATE OR DELETE ON shots
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision_child();

DROP TRIGGER IF EXISTS trg_shot_script_source_immutable ON shot_script_block_sources;
CREATE TRIGGER trg_shot_script_source_immutable
BEFORE INSERT OR UPDATE OR DELETE ON shot_script_block_sources
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision_child();

DROP TRIGGER IF EXISTS trg_shot_projection_immutable ON shot_projection_links;
CREATE TRIGGER trg_shot_projection_immutable
BEFORE INSERT OR UPDATE OR DELETE ON shot_projection_links
FOR EACH ROW EXECUTE FUNCTION protect_closed_loop_revision_child();
