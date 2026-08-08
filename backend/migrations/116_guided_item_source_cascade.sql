-- Guided lineage rows belong to the same project tree. Deleting a project must
-- be able to cascade through both the source and target sides of that lineage.

DO $$
DECLARE
    constraint_row RECORD;
BEGIN
    FOR constraint_row IN
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_schema = current_schema()
          AND table_name = 'content_guided_item_version_sources'
          AND constraint_type = 'FOREIGN KEY'
    LOOP
        EXECUTE format(
            'ALTER TABLE content_guided_item_version_sources DROP CONSTRAINT %I',
            constraint_row.constraint_name
        );
    END LOOP;
END
$$;

ALTER TABLE content_guided_item_version_sources
    ADD CONSTRAINT fk_guided_item_source_revision
        FOREIGN KEY (source_node_revision_id)
        REFERENCES content_guided_node_revisions(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_guided_item_source_item_version
        FOREIGN KEY (source_item_version_id)
        REFERENCES content_guided_item_versions(id) ON DELETE CASCADE;
