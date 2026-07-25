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
    created_by: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_captured_at(self) -> "SourceEvidenceCreate":
        if self.captured_at and self.captured_at.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        return self


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
    created_at: datetime
    updated_at: datetime


class FactClaimCreate(BaseModel):
    fact_title: str = Field(min_length=1, max_length=255)
    claim: str = Field(min_length=1, max_length=10000)
    source_evidence_code: str = Field(min_length=1, max_length=64)
    citation_excerpt: str = Field(min_length=1, max_length=20000)
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
