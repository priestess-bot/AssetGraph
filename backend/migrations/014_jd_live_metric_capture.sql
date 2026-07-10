-- AssetGraph JD live backend metric capture extension
-- Stores synchronized JD dashboard metric samples while the foreground Maitu agent is live.

CREATE TABLE IF NOT EXISTS maitu_jd_live_metric_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_session_code VARCHAR(64) NOT NULL UNIQUE,
    build_plan_code VARCHAR(64),
    frontend_execution_code VARCHAR(64),
    live_room_id VARCHAR(64),
    jd_live_id VARCHAR(128),
    jd_shop_name VARCHAR(255),
    dashboard_url TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    capture_interval_seconds INTEGER NOT NULL DEFAULT 30,
    sync_start_mode VARCHAR(64) NOT NULL DEFAULT 'with_frontend_agent',
    current_scene_name VARCHAR(128),
    current_scene_index INTEGER,
    metric_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    scene_schedule JSONB NOT NULL DEFAULT '[]'::jsonb,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    result_summary TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_sessions_build_plan_code ON maitu_jd_live_metric_sessions(build_plan_code);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_sessions_front_exec ON maitu_jd_live_metric_sessions(frontend_execution_code);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_sessions_live_room_id ON maitu_jd_live_metric_sessions(live_room_id);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_sessions_jd_live_id ON maitu_jd_live_metric_sessions(jd_live_id);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_sessions_status ON maitu_jd_live_metric_sessions(status);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_sessions_created_at ON maitu_jd_live_metric_sessions(created_at);

CREATE TABLE IF NOT EXISTS maitu_jd_live_metric_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_session_id UUID NOT NULL REFERENCES maitu_jd_live_metric_sessions(id),
    capture_session_code VARCHAR(64) NOT NULL,
    sample_index INTEGER NOT NULL,
    sampled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    scene_name VARCHAR(128),
    scene_index INTEGER,
    frontend_event_code VARCHAR(64),
    live_elapsed_seconds INTEGER,
    online_viewers INTEGER,
    average_stay_seconds NUMERIC(12, 3),
    product_click_rate NUMERIC(8, 6),
    product_conversion_rate NUMERIC(8, 6),
    gmv NUMERIC(14, 2),
    uv_value NUMERIC(14, 4),
    product_exposures INTEGER,
    product_clicks INTEGER,
    transaction_count INTEGER,
    transaction_amount NUMERIC(14, 2),
    traffic_sources JSONB NOT NULL DEFAULT '{}'::jsonb,
    interaction_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    screenshot_asset_code VARCHAR(64),
    dom_snapshot_asset_code VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'captured',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(capture_session_code, sample_index)
);

CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_samples_session_code ON maitu_jd_live_metric_samples(capture_session_code);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_samples_sampled_at ON maitu_jd_live_metric_samples(sampled_at);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_samples_scene_name ON maitu_jd_live_metric_samples(scene_name);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_samples_scene_index ON maitu_jd_live_metric_samples(scene_index);
CREATE INDEX IF NOT EXISTS idx_maitu_jd_metric_samples_status ON maitu_jd_live_metric_samples(status);
