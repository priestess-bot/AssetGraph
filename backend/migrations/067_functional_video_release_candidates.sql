-- Immutable local snapshots for rendered-video release candidates. A candidate
-- is reviewable only; approval and delivery remain separate release commands.

CREATE TABLE IF NOT EXISTS functional_video_plan_release_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL UNIQUE REFERENCES functional_video_plans(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL UNIQUE REFERENCES artifact_refs(id) ON DELETE RESTRICT,
    artifact_code VARCHAR(80) NOT NULL UNIQUE,
    snapshot_fingerprint_sha256 CHAR(64) NOT NULL,
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_video_release_snapshot_sha
        CHECK (snapshot_fingerprint_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_functional_video_release_snapshot_object
        CHECK (jsonb_typeof(snapshot) = 'object')
);

ALTER TABLE functional_video_plans
    ADD COLUMN IF NOT EXISTS release_code VARCHAR(80) UNIQUE REFERENCES releases(release_code),
    ADD COLUMN IF NOT EXISTS release_snapshot_artifact_code VARCHAR(80)
        REFERENCES artifact_refs(artifact_code),
    ADD COLUMN IF NOT EXISTS release_manifest_fingerprint CHAR(64);

ALTER TABLE functional_video_plans
    ADD CONSTRAINT chk_functional_video_release_manifest_sha
        CHECK (
            release_manifest_fingerprint IS NULL
            OR release_manifest_fingerprint ~ '^[0-9a-f]{64}$'
        );
