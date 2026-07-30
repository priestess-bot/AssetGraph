ALTER TABLE live_room_templates
    ADD COLUMN IF NOT EXISTS archive_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_live_room_templates_active_kind
    ON live_room_templates(template_kind, updated_at DESC)
    WHERE archived_at IS NULL;
