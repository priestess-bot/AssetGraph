CREATE TABLE IF NOT EXISTS functional_decision_logs (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), decision_code VARCHAR(64) NOT NULL UNIQUE, project_code VARCHAR(64), attribution_report_code VARCHAR(64), observation TEXT NOT NULL, recommendation TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS functional_experiments (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), experiment_code VARCHAR(64) NOT NULL UNIQUE, title VARCHAR(255) NOT NULL, metric_key VARCHAR(80) NOT NULL, variants JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), CONSTRAINT chk_functional_experiment_variants CHECK (jsonb_typeof(variants)='array')
);
CREATE TABLE IF NOT EXISTS functional_experiment_outcomes (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), experiment_code VARCHAR(64) NOT NULL REFERENCES functional_experiments(experiment_code) ON DELETE CASCADE, subject_key VARCHAR(255) NOT NULL, variant_key VARCHAR(80) NOT NULL, metric_value NUMERIC NOT NULL, UNIQUE(experiment_code,subject_key)
);
