-- Attach immutable normalized events to their imported source batch. Existing
-- events remain valid historical rows with a NULL batch link.

ALTER TABLE data_quality_batches
    ADD COLUMN IF NOT EXISTS source_checksum CHAR(64);

ALTER TABLE data_quality_batches
    DROP CONSTRAINT IF EXISTS chk_data_quality_batch_source_checksum,
    ADD CONSTRAINT chk_data_quality_batch_source_checksum CHECK (
        source_checksum IS NULL OR source_checksum ~ '^[0-9a-f]{64}$'
    );

ALTER TABLE standard_events
    ADD COLUMN IF NOT EXISTS quality_batch_id UUID REFERENCES data_quality_batches(id);

CREATE INDEX IF NOT EXISTS idx_standard_events_quality_batch
    ON standard_events (quality_batch_id, event_time)
    WHERE quality_batch_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_data_quality_batches_contract_created
    ON data_quality_batches (contract_id, created_at DESC);
