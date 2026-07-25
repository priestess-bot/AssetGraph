-- A local, disposable graph projection. The authoritative records remain in
-- their source tables; a projection can always be rebuilt from them.

CREATE TABLE IF NOT EXISTS functional_knowledge_graph_projections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projection_code VARCHAR(64) NOT NULL UNIQUE,
    revision_number INTEGER NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    ontology_version VARCHAR(64) NOT NULL,
    embedding_version VARCHAR(64),
    source_watermark JSONB NOT NULL,
    snapshot_fingerprint_sha256 CHAR(64) NOT NULL,
    node_count INTEGER NOT NULL DEFAULT 0,
    edge_count INTEGER NOT NULL DEFAULT 0,
    created_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_functional_knowledge_graph_projection_revision CHECK (revision_number >= 1),
    CONSTRAINT chk_functional_knowledge_graph_projection_status CHECK (status IN ('completed', 'superseded')),
    CONSTRAINT chk_functional_knowledge_graph_projection_watermark CHECK (jsonb_typeof(source_watermark) = 'object'),
    CONSTRAINT chk_functional_knowledge_graph_projection_fingerprint CHECK (snapshot_fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS functional_knowledge_graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projection_id UUID NOT NULL REFERENCES functional_knowledge_graph_projections(id) ON DELETE CASCADE,
    node_type VARCHAR(64) NOT NULL,
    node_code VARCHAR(128) NOT NULL,
    revision_number INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(32),
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_fingerprint_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (projection_id, node_type, node_code, revision_number),
    CONSTRAINT chk_functional_knowledge_graph_node_revision CHECK (revision_number >= 0),
    CONSTRAINT chk_functional_knowledge_graph_node_properties CHECK (jsonb_typeof(properties) = 'object'),
    CONSTRAINT chk_functional_knowledge_graph_node_fingerprint CHECK (source_fingerprint_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_functional_knowledge_graph_nodes_projection_type
    ON functional_knowledge_graph_nodes(projection_id, node_type, node_code);

CREATE TABLE IF NOT EXISTS functional_knowledge_graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projection_id UUID NOT NULL REFERENCES functional_knowledge_graph_projections(id) ON DELETE CASCADE,
    source_node_id UUID NOT NULL REFERENCES functional_knowledge_graph_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES functional_knowledge_graph_nodes(id) ON DELETE CASCADE,
    relationship_type VARCHAR(64) NOT NULL,
    assertion_kind VARCHAR(32) NOT NULL DEFAULT 'recorded_fact',
    confidence NUMERIC(5,4),
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (projection_id, source_node_id, target_node_id, relationship_type, assertion_kind),
    CONSTRAINT chk_functional_knowledge_graph_edge_assertion CHECK (assertion_kind IN ('recorded_fact', 'derived_projection', 'descriptive_association')),
    CONSTRAINT chk_functional_knowledge_graph_edge_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT chk_functional_knowledge_graph_edge_window CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from),
    CONSTRAINT chk_functional_knowledge_graph_edge_evidence CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_functional_knowledge_graph_edges_projection_source
    ON functional_knowledge_graph_edges(projection_id, source_node_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_functional_knowledge_graph_edges_projection_target
    ON functional_knowledge_graph_edges(projection_id, target_node_id, relationship_type);
