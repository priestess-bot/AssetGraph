-- Persist the frozen content-rule evidence attached to each literal ScriptBlock.
-- Existing historical blocks remain valid with an empty reference array.

ALTER TABLE content_script_blocks
    ADD COLUMN IF NOT EXISTS content_rule_refs JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE content_script_blocks
    ADD CONSTRAINT chk_content_script_block_content_rule_refs
    CHECK (jsonb_typeof(content_rule_refs) = 'array') NOT VALID;
