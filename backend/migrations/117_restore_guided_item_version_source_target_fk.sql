-- Migration 116 replaced lineage source constraints but also removed the
-- ownership constraint from each lineage row to its target item version.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'content_guided_item_version_sources'::regclass
          AND conname = 'fk_guided_item_version_source_target'
    ) THEN
        ALTER TABLE content_guided_item_version_sources
            ADD CONSTRAINT fk_guided_item_version_source_target
            FOREIGN KEY (item_version_id)
            REFERENCES content_guided_item_versions(id) ON DELETE CASCADE;
    END IF;
END
$$;
