-- Material packs are versioned selection contracts.  The selected revision is
-- immutable and never relies on a later group membership change.

ALTER TABLE material_packs
    ADD COLUMN IF NOT EXISTS pack_kind VARCHAR(32) NOT NULL DEFAULT 'total',
    ADD COLUMN IF NOT EXISTS published_revision INTEGER;

ALTER TABLE material_packs
    ALTER COLUMN role DROP NOT NULL;

ALTER TABLE material_packs
    DROP CONSTRAINT IF EXISTS chk_material_packs_status;
ALTER TABLE material_packs
    ADD CONSTRAINT chk_material_packs_status
        CHECK (status IN ('draft', 'published', 'superseded', 'archived'));
ALTER TABLE material_packs
    ADD CONSTRAINT chk_material_packs_kind
        CHECK (pack_kind IN ('total', 'classification'));
ALTER TABLE material_packs
    ADD CONSTRAINT chk_material_packs_published_revision
        CHECK (published_revision IS NULL OR published_revision > 0);

-- Existing packs retain their current published revision.  They are treated
-- as total packs because the previous single role column did not constrain
-- the role composition of group members.
UPDATE material_packs
SET published_revision = current_revision
WHERE status = 'published' AND published_revision IS NULL;

ALTER TABLE material_pack_revisions
    ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS exclusive_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS pack_constraints JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE material_pack_revisions
    ADD CONSTRAINT chk_material_pack_revision_status
        CHECK (status IN ('draft', 'published', 'superseded', 'archived')),
    ADD CONSTRAINT chk_material_pack_revision_exclusive_roles
        CHECK (jsonb_typeof(exclusive_roles) = 'array'),
    ADD CONSTRAINT chk_material_pack_revision_constraints
        CHECK (jsonb_typeof(pack_constraints) = 'array');

UPDATE material_pack_revisions revision
SET status = CASE
    WHEN pack.status = 'published' AND revision.revision_number = pack.current_revision THEN 'published'
    WHEN revision.revision_number < pack.current_revision THEN 'superseded'
    ELSE 'draft'
END
FROM material_packs pack
WHERE revision.pack_id = pack.id
  AND revision.status = 'draft';

CREATE INDEX IF NOT EXISTS idx_material_packs_published_revision
    ON material_packs (published_revision)
    WHERE published_revision IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_material_pack_revisions_status
    ON material_pack_revisions (pack_id, status, revision_number DESC);
