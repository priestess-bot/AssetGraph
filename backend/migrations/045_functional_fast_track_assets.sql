-- Functional fast-track material library.  This migration is additive: old
-- asset_type/maitu_category fields remain source and compatibility metadata.

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS media_kind VARCHAR(32),
    ADD COLUMN IF NOT EXISTS material_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS execution_capability VARCHAR(32) NOT NULL DEFAULT 'unclassified';

ALTER TABLE assets
    ADD CONSTRAINT chk_assets_media_kind_fast_track
        CHECK (media_kind IS NULL OR media_kind IN ('image', 'video', 'audio', 'digital_human', 'text', 'template_preview', 'document')),
    ADD CONSTRAINT chk_assets_material_roles_fast_track
        CHECK (jsonb_typeof(material_roles) = 'array'),
    ADD CONSTRAINT chk_assets_execution_capability_fast_track
        CHECK (execution_capability IN ('maitu_bound', 'local_only', 'reference_only', 'unavailable', 'unclassified'));

CREATE INDEX IF NOT EXISTS idx_assets_media_kind_fast_track
    ON assets (media_kind) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_assets_execution_capability_fast_track
    ON assets (execution_capability) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_assets_material_roles_fast_track
    ON assets USING GIN (material_roles);

CREATE TABLE IF NOT EXISTS asset_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asset_group_members (
    group_id UUID NOT NULL REFERENCES asset_groups(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_asset_group_members_asset ON asset_group_members(asset_id);

CREATE TABLE IF NOT EXISTS asset_constraint_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_code VARCHAR(64) NOT NULL UNIQUE,
    asset_id UUID NOT NULL UNIQUE REFERENCES assets(id) ON DELETE CASCADE,
    asset_code VARCHAR(64) NOT NULL UNIQUE,
    current_revision INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_asset_constraint_profiles_revision CHECK (current_revision >= 0)
);

CREATE TABLE IF NOT EXISTS asset_constraint_profile_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES asset_constraint_profiles(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(profile_id, revision_number),
    CONSTRAINT chk_asset_constraint_profile_rules CHECK (jsonb_typeof(constraints) = 'array'),
    CONSTRAINT chk_asset_constraint_profile_fingerprint CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS material_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    role VARCHAR(64) NOT NULL,
    description TEXT,
    current_revision INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_material_packs_status CHECK (status IN ('draft', 'published', 'archived')),
    CONSTRAINT chk_material_packs_revision CHECK (current_revision >= 0)
);

CREATE TABLE IF NOT EXISTS material_pack_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id UUID NOT NULL REFERENCES material_packs(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    entries JSONB NOT NULL DEFAULT '[]'::jsonb,
    fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(pack_id, revision_number),
    CONSTRAINT chk_material_pack_entries CHECK (jsonb_typeof(entries) = 'array'),
    CONSTRAINT chk_material_pack_fingerprint CHECK (fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS asset_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gap_code VARCHAR(64) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    role VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'medium',
    status VARCHAR(32) NOT NULL DEFAULT 'open',
    specification JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    resolution_asset_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_asset_gaps_severity CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT chk_asset_gaps_status CHECK (status IN ('open', 'candidate_found', 'resolved', 'waived', 'obsolete')),
    CONSTRAINT chk_asset_gaps_specification CHECK (jsonb_typeof(specification) = 'object'),
    CONSTRAINT chk_asset_gaps_source_context CHECK (jsonb_typeof(source_context) = 'object')
);
CREATE INDEX IF NOT EXISTS idx_asset_gaps_status ON asset_gaps(status, created_at DESC);
