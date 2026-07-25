from __future__ import annotations
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FactCreate(BaseModel):
    title: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    source_url: str | None = None
    related_codes: list[str] = Field(default_factory=list)


class FactRead(FactCreate):
    fact_code: str
    status: str
    created_at: datetime


class SourceEvidenceCreate(BaseModel):
    source_type: Literal["human", "document", "webpage", "export"]
    title: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=4096)
    excerpt: str = Field(min_length=1, max_length=20000)
    captured_at: datetime | None = None
    access_scope: str = Field(default="internal", min_length=1, max_length=64)
    extractor_strategy_ref: str = Field(default="manual_excerpt.v1", min_length=1, max_length=128)
    extraction_metadata: dict[str, object] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_captured_at(self) -> "SourceEvidenceCreate":
        if self.captured_at and self.captured_at.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        if not self.extractor_strategy_ref.strip():
            raise ValueError("extractor_strategy_ref must not be blank")
        return self


class SourceExtractionRunRead(BaseModel):
    extraction_run_code: str
    evidence_code: str
    extractor_strategy_ref: str
    input_fingerprint_sha256: str
    output_checksum_sha256: str
    extraction_metadata: dict[str, object] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime


class KnowledgeSearchValidationRead(BaseModel):
    lifecycle: Literal["approved", "not_approved"]
    source: Literal["approved", "not_approved", "not_required"]
    validity: Literal["valid", "outside_window"]
    scope: Literal["match", "mismatch", "not_scoped", "context_required"]
    rights: Literal["not_modeled"]
    content_eligible: bool
    authorization_eligible: bool
    blocking_rule_codes: list[str] = Field(default_factory=list)


class KnowledgeSearchHitRead(BaseModel):
    entity_type: Literal["product_fact_card", "fact_claim", "content_rule", "source_evidence"]
    entity_code: str
    title: str
    summary: str
    status: str
    revision_number: int | None = None
    source_evidence_code: str | None = None
    source_status: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    scope: dict[str, object] = Field(default_factory=dict)
    access_scope: str | None = None
    validation: KnowledgeSearchValidationRead
    created_at: datetime


class SourceEvidenceApprove(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)


class KnowledgeRevocation(BaseModel):
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_non_blank_values(self) -> "KnowledgeRevocation":
        if not self.actor.strip():
            raise ValueError("actor must not be blank")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        return self


class SourceEvidenceRevoke(KnowledgeRevocation):
    pass


class SourceEvidenceReject(KnowledgeRevocation):
    pass


class SourceEvidenceRead(SourceEvidenceCreate):
    evidence_code: str
    content_sha256: str
    status: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    extraction_runs: list[SourceExtractionRunRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class FactClaimCreate(BaseModel):
    fact_title: str = Field(min_length=1, max_length=255)
    claim: str = Field(min_length=1, max_length=10000)
    source_evidence_code: str = Field(min_length=1, max_length=64)
    citation_excerpt: str = Field(min_length=1, max_length=20000)
    citation_start_offset: int | None = Field(default=None, ge=0)
    citation_end_offset: int | None = Field(default=None, ge=1)
    field_path: str | None = Field(default=None, max_length=255)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_by: str | None = Field(default=None, max_length=128)
    related_codes: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_window(self) -> "FactClaimCreate":
        if self.valid_from and self.valid_from.tzinfo is None:
            raise ValueError("valid_from must include a timezone")
        if self.valid_until and self.valid_until.tzinfo is None:
            raise ValueError("valid_until must include a timezone")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        if (self.citation_start_offset is None) != (self.citation_end_offset is None):
            raise ValueError("citation_start_offset and citation_end_offset must be supplied together")
        if self.citation_start_offset is not None and self.citation_end_offset is not None and self.citation_end_offset <= self.citation_start_offset:
            raise ValueError("citation_end_offset must be later than citation_start_offset")
        return self


class FactClaimApprove(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)


class FactClaimRevoke(KnowledgeRevocation):
    pass


class FactClaimReject(KnowledgeRevocation):
    pass


ContentRuleKind = Literal["content_guidance", "compliance_rule", "term", "expression_ban"]
ContentRuleDirective = Literal["guidance", "must_include", "must_avoid"]


class ContentRuleCreate(BaseModel):
    rule_kind: ContentRuleKind
    directive: ContentRuleDirective
    title: str = Field(min_length=1, max_length=255)
    rule_text: str = Field(min_length=1, max_length=10000)
    scope: dict[str, object] = Field(default_factory=dict)
    source_evidence_code: str | None = Field(default=None, min_length=1, max_length=64)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_content_rule(self) -> "ContentRuleCreate":
        if self.rule_kind == "expression_ban" and self.directive != "must_avoid":
            raise ValueError("expression_ban must use the must_avoid directive")
        if self.rule_kind in {"compliance_rule", "term", "expression_ban"} and not self.source_evidence_code:
            raise ValueError("source_evidence_code is required for compliance, term, and expression-ban rules")
        if self.valid_from and self.valid_from.tzinfo is None:
            raise ValueError("valid_from must include a timezone")
        if self.valid_until and self.valid_until.tzinfo is None:
            raise ValueError("valid_until must include a timezone")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        return self


class ContentRuleApprove(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)


class ContentRuleRevoke(KnowledgeRevocation):
    pass


class ContentRuleReject(KnowledgeRevocation):
    pass


class ContentRuleRead(BaseModel):
    rule_code: str
    rule_kind: ContentRuleKind
    directive: ContentRuleDirective
    title: str
    rule_text: str
    scope: dict[str, object]
    source_evidence_code: str | None = None
    source_title: str | None = None
    source_status: str | None = None
    source_content_sha256: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: str
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    fingerprint_sha256: str
    created_at: datetime
    updated_at: datetime


class FactClaimLineageUseRead(BaseModel):
    relation_type: str
    object_type: str
    object_code: str
    revision_number: int | None = None
    status: str
    created_at: datetime


class FactClaimLineageRead(BaseModel):
    claim_code: str
    fact_code: str
    fact_title: str
    claim_status: str
    fact_status: str
    source_evidence_code: str
    source_title: str
    source_status: str
    uses: list[FactClaimLineageUseRead] = Field(default_factory=list)


class FactClaimRead(BaseModel):
    claim_code: str
    fact_code: str
    fact_title: str
    source_evidence_code: str
    source_title: str
    source_status: str
    field_path: str | None = None
    claim: str
    citation_excerpt: str
    citation_start_offset: int | None = None
    citation_end_offset: int | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: str
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    fingerprint_sha256: str
    created_at: datetime
    updated_at: datetime


class KnowledgeGraphProjectionRebuild(BaseModel):
    actor: str = Field(default="console_operator", min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_actor(self) -> "KnowledgeGraphProjectionRebuild":
        if not self.actor.strip():
            raise ValueError("actor must not be blank")
        return self


class KnowledgeGraphNodeRead(BaseModel):
    node_type: str
    node_code: str
    revision_number: int
    status: str | None = None
    properties: dict[str, object] = Field(default_factory=dict)
    source_fingerprint_sha256: str
    created_at: datetime


class KnowledgeGraphEdgeRead(BaseModel):
    source_node_type: str
    source_node_code: str
    source_revision_number: int
    target_node_type: str
    target_node_code: str
    target_revision_number: int
    relationship_type: str
    assertion_kind: str
    confidence: float | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    evidence: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class KnowledgeGraphProjectionRead(BaseModel):
    projection_code: str
    revision_number: int
    status: str
    ontology_version: str
    embedding_version: str | None = None
    source_watermark: dict[str, object] = Field(default_factory=dict)
    current_source_watermark: dict[str, object] = Field(default_factory=dict)
    snapshot_fingerprint_sha256: str
    node_count: int
    edge_count: int
    created_by: str | None = None
    created_at: datetime
    is_stale: bool
    nodes: list[KnowledgeGraphNodeRead] = Field(default_factory=list)
    edges: list[KnowledgeGraphEdgeRead] = Field(default_factory=list)
