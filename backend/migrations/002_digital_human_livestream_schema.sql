-- AssetGraph digital-human livestream schema extension
-- Adds first-class business objects for the digital-human livestream asset graph.

CREATE TABLE IF NOT EXISTS business_sequences (
    sequence_date DATE NOT NULL,
    object_type VARCHAR(32) NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sequence_date, object_type)
);

CREATE TABLE IF NOT EXISTS digital_humans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    digital_human_code VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    persona TEXT,
    gender VARCHAR(32),
    style VARCHAR(128),
    version VARCHAR(64),
    provider VARCHAR(128),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_digital_humans_name ON digital_humans(name);
CREATE INDEX IF NOT EXISTS idx_digital_humans_provider ON digital_humans(provider);

CREATE TABLE IF NOT EXISTS voice_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voice_code VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(128) NOT NULL,
    provider VARCHAR(128),
    gender VARCHAR(32),
    style VARCHAR(128),
    speed VARCHAR(64),
    emotion VARCHAR(64),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_voice_profiles_name ON voice_profiles(name);
CREATE INDEX IF NOT EXISTS idx_voice_profiles_provider ON voice_profiles(provider);

CREATE TABLE IF NOT EXISTS products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    brand VARCHAR(128),
    category VARCHAR(128),
    selling_points TEXT,
    pain_points TEXT,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);

CREATE TABLE IF NOT EXISTS scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    script_code VARCHAR(40) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    product_id UUID REFERENCES products(id),
    script_type VARCHAR(64) NOT NULL DEFAULT 'livestream',
    version VARCHAR(64),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_scripts_product_id ON scripts(product_id);
CREATE INDEX IF NOT EXISTS idx_scripts_script_type ON scripts(script_type);

CREATE TABLE IF NOT EXISTS script_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    script_id UUID NOT NULL REFERENCES scripts(id),
    block_type VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    estimated_duration_seconds NUMERIC(12, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_script_blocks_script_id ON script_blocks(script_id);
CREATE INDEX IF NOT EXISTS idx_script_blocks_block_type ON script_blocks(block_type);

ALTER TABLE live_sessions
    ADD COLUMN IF NOT EXISTS digital_human_id UUID REFERENCES digital_humans(id),
    ADD COLUMN IF NOT EXISTS voice_profile_id UUID REFERENCES voice_profiles(id),
    ADD COLUMN IF NOT EXISTS script_id UUID REFERENCES scripts(id);

CREATE INDEX IF NOT EXISTS idx_live_sessions_digital_human_id ON live_sessions(digital_human_id);
CREATE INDEX IF NOT EXISTS idx_live_sessions_voice_profile_id ON live_sessions(voice_profile_id);
CREATE INDEX IF NOT EXISTS idx_live_sessions_script_id ON live_sessions(script_id);

CREATE TABLE IF NOT EXISTS video_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    segment_code VARCHAR(40) NOT NULL UNIQUE,
    live_id UUID NOT NULL REFERENCES live_sessions(id),
    asset_id UUID REFERENCES assets(id),
    asset_code VARCHAR(32),
    live_code VARCHAR(40) NOT NULL,
    title VARCHAR(255),
    start_time_seconds NUMERIC(12, 3) NOT NULL,
    end_time_seconds NUMERIC(12, 3) NOT NULL,
    transcript TEXT,
    product_id UUID REFERENCES products(id),
    digital_human_id UUID REFERENCES digital_humans(id),
    voice_profile_id UUID REFERENCES voice_profiles(id),
    script_block_id UUID REFERENCES script_blocks(id),
    quality_score NUMERIC(5, 4),
    reuse_score NUMERIC(5, 4),
    status VARCHAR(32) NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_time_seconds > start_time_seconds)
);

CREATE INDEX IF NOT EXISTS idx_video_segments_segment_code ON video_segments(segment_code);
CREATE INDEX IF NOT EXISTS idx_video_segments_live_id ON video_segments(live_id);
CREATE INDEX IF NOT EXISTS idx_video_segments_live_code ON video_segments(live_code);
CREATE INDEX IF NOT EXISTS idx_video_segments_asset_code ON video_segments(asset_code);
CREATE INDEX IF NOT EXISTS idx_video_segments_product_id ON video_segments(product_id);
CREATE INDEX IF NOT EXISTS idx_video_segments_digital_human_id ON video_segments(digital_human_id);
CREATE INDEX IF NOT EXISTS idx_video_segments_script_block_id ON video_segments(script_block_id);

CREATE TABLE IF NOT EXISTS interaction_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    live_id UUID NOT NULL REFERENCES live_sessions(id),
    segment_id UUID REFERENCES video_segments(id),
    event_time_seconds NUMERIC(12, 3),
    event_type VARCHAR(64) NOT NULL,
    content TEXT,
    external_user_id VARCHAR(128),
    sentiment VARCHAR(32),
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_interaction_events_live_id ON interaction_events(live_id);
CREATE INDEX IF NOT EXISTS idx_interaction_events_segment_id ON interaction_events(segment_id);
CREATE INDEX IF NOT EXISTS idx_interaction_events_event_type ON interaction_events(event_type);
