import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";
import { knowledgeTitle } from "./presentation";

const ROOT = "/api/maitu/workbench/product-fact-cards";
const FUNCTIONAL_ROOT = "/api/functional-knowledge";

export interface ProductFactCardVersion {
  versionCode: string;
  versionNumber: number;
  status: string;
  content: Record<string, unknown>;
  changeReason?: string;
  createdBy?: string;
  approvedBy?: string;
  rejectedBy?: string;
  rejectionReason?: string;
  createdAt?: string;
  approvedAt?: string;
}

export interface ProductFactCard {
  factCardCode: string;
  title: string;
  productCode?: string;
  status: string;
  currentApprovedVersion?: number;
  createdAt?: string;
  updatedAt?: string;
  versions: ProductFactCardVersion[];
}

export interface ProductFactCardUsage {
  relationType: string;
  objectType: string;
  objectCode: string;
  revisionNumber?: number;
  status: string;
  createdAt?: string;
}

export interface ProductFactCardContentInput {
  product_name: string;
  product_code?: string;
  brand?: string;
  category?: string;
  positioning: string;
  verified_facts: string[];
  tasting_notes?: string[];
  scenarios?: string[];
  selection_guidance?: string;
  objection_response?: string;
  asset_keywords?: string[];
  verified_promotion_claims?: string[];
  unverified_promotion_claims?: string[];
  compliance_notes?: string[];
  source_references?: Array<Record<string, unknown>>;
  valid_from?: string;
  valid_until?: string;
  applicable_platforms?: string[];
}

export interface ProductFactCardCreateInput {
  title: string;
  product_code?: string;
  content: ProductFactCardContentInput;
  change_reason?: string;
  created_by?: string;
  approve?: boolean;
  approved_by?: string;
}

export interface ProductFactCardVersionCreateInput {
  content: ProductFactCardContentInput;
  change_reason: string;
  created_by?: string;
  approve?: boolean;
  approved_by?: string;
}

export interface SourceEvidence {
  evidenceCode: string;
  sourceType: string;
  title: string;
  sourceUrl?: string;
  excerpt: string;
  contentChecksum: string;
  capturedAt?: string;
  accessScope: string;
  extractorStrategyRef: string;
  extractionMetadata: Record<string, unknown>;
  extractionRuns: SourceExtractionRun[];
  status: string;
  createdBy?: string;
  approvedBy?: string;
  approvedAt?: string;
  revokedBy?: string;
  revokedAt?: string;
  revokedReason?: string;
  rejectedBy?: string;
  rejectedAt?: string;
  rejectionReason?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface SourceExtractionRun {
  extractionRunCode: string;
  evidenceCode: string;
  extractorStrategyRef: string;
  inputFingerprint: string;
  outputChecksum: string;
  extractionMetadata: Record<string, unknown>;
  createdBy?: string;
  createdAt?: string;
}

export interface KnowledgeSearchValidation {
  lifecycle: "approved" | "not_approved";
  source: "approved" | "not_approved" | "not_required";
  validity: "valid" | "outside_window";
  scope: "match" | "mismatch" | "not_scoped" | "context_required";
  rights: "not_modeled";
  contentEligible: boolean;
  authorizationEligible: boolean;
  blockingRuleCodes: string[];
}

export interface KnowledgeSearchHit {
  entityType: "product_fact_card" | "fact_claim" | "content_rule" | "source_evidence";
  entityCode: string;
  title: string;
  summary: string;
  status: string;
  revisionNumber?: number;
  sourceEvidenceCode?: string;
  sourceStatus?: string;
  validFrom?: string;
  validUntil?: string;
  scope: Record<string, unknown>;
  accessScope?: string;
  validation: KnowledgeSearchValidation;
  createdAt?: string;
}

export interface SourceEvidenceCreateInput {
  source_type: "human" | "document" | "webpage" | "export";
  title: string;
  source_url?: string;
  excerpt: string;
  captured_at?: string;
  access_scope: string;
  extractor_strategy_ref?: string;
  extraction_metadata?: Record<string, unknown>;
  created_by?: string;
}

export interface FactClaim {
  claimCode: string;
  factCode: string;
  factTitle: string;
  sourceEvidenceCode: string;
  sourceTitle: string;
  sourceStatus: string;
  fieldPath?: string;
  claim: string;
  citationExcerpt: string;
  citationStartOffset?: number;
  citationEndOffset?: number;
  validFrom?: string;
  validUntil?: string;
  status: string;
  createdBy?: string;
  approvedBy?: string;
  approvedAt?: string;
  revokedBy?: string;
  revokedAt?: string;
  revokedReason?: string;
  rejectedBy?: string;
  rejectedAt?: string;
  rejectionReason?: string;
  fingerprint: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface FactClaimCreateInput {
  fact_title: string;
  claim: string;
  source_evidence_code: string;
  citation_excerpt: string;
  citation_start_offset?: number;
  citation_end_offset?: number;
  field_path?: string;
  valid_from?: string;
  valid_until?: string;
  created_by?: string;
  related_codes?: string[];
}

export interface ContentRule {
  ruleCode: string;
  ruleKind: "content_guidance" | "compliance_rule" | "term" | "expression_ban";
  directive: "guidance" | "must_include" | "must_avoid";
  title: string;
  ruleText: string;
  scope: Record<string, unknown>;
  sourceEvidenceCode?: string;
  sourceTitle?: string;
  sourceStatus?: string;
  sourceContentChecksum?: string;
  validFrom?: string;
  validUntil?: string;
  status: string;
  createdBy?: string;
  approvedBy?: string;
  approvedAt?: string;
  revokedBy?: string;
  revokedAt?: string;
  revokedReason?: string;
  rejectedBy?: string;
  rejectedAt?: string;
  rejectionReason?: string;
  fingerprint: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface ContentRuleCreateInput {
  rule_kind: ContentRule["ruleKind"];
  directive: ContentRule["directive"];
  title: string;
  rule_text: string;
  scope?: Record<string, unknown>;
  source_evidence_code?: string;
  valid_from?: string;
  valid_until?: string;
  created_by?: string;
}

export interface FactClaimLineageUse {
  relationType: string;
  objectType: string;
  objectCode: string;
  revisionNumber?: number;
  status: string;
  createdAt?: string;
}

export interface FactClaimLineage {
  claimCode: string;
  factCode: string;
  factTitle: string;
  claimStatus: string;
  factStatus: string;
  sourceEvidenceCode: string;
  sourceTitle: string;
  sourceStatus: string;
  uses: FactClaimLineageUse[];
}

export interface KnowledgeGraphNode {
  nodeType: string;
  nodeCode: string;
  revisionNumber: number;
  status?: string;
  properties: Record<string, unknown>;
  sourceFingerprint: string;
  createdAt?: string;
}

export interface KnowledgeGraphEdge {
  sourceNodeType: string;
  sourceNodeCode: string;
  sourceRevisionNumber: number;
  targetNodeType: string;
  targetNodeCode: string;
  targetRevisionNumber: number;
  relationshipType: string;
  assertionKind: string;
  confidence?: number;
  validFrom?: string;
  validUntil?: string;
  evidence: Record<string, unknown>;
  createdAt?: string;
}

export interface KnowledgeGraphProjection {
  projectionCode: string;
  revisionNumber: number;
  status: string;
  ontologyVersion: string;
  embeddingVersion?: string;
  sourceWatermark: Record<string, unknown>;
  currentSourceWatermark: Record<string, unknown>;
  snapshotFingerprint: string;
  nodeCount: number;
  edgeCount: number;
  createdBy?: string;
  createdAt?: string;
  isStale: boolean;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
}

export type KnowledgeGraphSearchScope = "all" | "product" | "topic" | "template" | "material";

export interface KnowledgeGraphLineageResult {
  match: KnowledgeGraphNode;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  truncated: boolean;
}

export interface KnowledgeGraphSearchResult {
  query: string;
  scope: KnowledgeGraphSearchScope;
  projectionCode?: string;
  projectionRevision?: number;
  isStale: boolean;
  results: KnowledgeGraphLineageResult[];
}

function card(value: unknown): ProductFactCard {
  if (!isRecord(value)) throw new Error("事实卡响应无效");
  const factCardCode = asString(value.fact_card_code);
  if (!factCardCode) throw new Error("事实卡缺少编码");
  return {
    factCardCode,
    title: knowledgeTitle(asString(value.title, factCardCode), "未命名事实卡"),
    productCode: asOptionalString(value.product_code),
    status: asString(value.status),
    currentApprovedVersion: typeof value.current_approved_version === "number" ? value.current_approved_version : undefined,
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
    versions: asArray(value.versions).flatMap((item) => isRecord(item) ? [{
      versionCode: asString(item.version_code),
      versionNumber: asNumber(item.version_number),
      status: asString(item.status),
      content: isRecord(item.content) ? item.content : {},
      changeReason: asOptionalString(item.change_reason),
      createdBy: asOptionalString(item.created_by),
      approvedBy: asOptionalString(item.approved_by),
      rejectedBy: asOptionalString(item.rejected_by),
      rejectionReason: asOptionalString(item.rejection_reason),
      createdAt: asOptionalString(item.created_at),
      approvedAt: asOptionalString(item.approved_at),
    }] : []),
  };
}

function usage(value: unknown): ProductFactCardUsage {
  if (!isRecord(value)) throw new Error("事实使用记录响应无效");
  const objectCode = asString(value.object_code);
  if (!objectCode) throw new Error("事实使用记录缺少对象编码");
  return {
    relationType: asString(value.relation_type, "uses_fact_card"),
    objectType: asString(value.object_type, "unknown"),
    objectCode,
    revisionNumber: typeof value.revision_number === "number" ? value.revision_number : undefined,
    status: asString(value.status, "unknown"),
    createdAt: asOptionalString(value.created_at),
  };
}

function sourceEvidence(value: unknown): SourceEvidence {
  if (!isRecord(value)) throw new Error("来源证据响应无效");
  const evidenceCode = asString(value.evidence_code);
  if (!evidenceCode) throw new Error("来源证据缺少编码");
  return {
    evidenceCode,
    sourceType: asString(value.source_type),
    title: knowledgeTitle(asString(value.title), "未命名来源"),
    sourceUrl: asOptionalString(value.source_url),
    excerpt: asString(value.excerpt),
    contentChecksum: asString(value.content_sha256),
    capturedAt: asOptionalString(value.captured_at),
    accessScope: asString(value.access_scope, "internal"),
    extractorStrategyRef: asString(value.extractor_strategy_ref, "manual_excerpt.v1"),
    extractionMetadata: isRecord(value.extraction_metadata) ? value.extraction_metadata : {},
    extractionRuns: asArray(value.extraction_runs).flatMap((run) => isRecord(run) && asString(run.extraction_run_code) && asString(run.evidence_code) ? [{
      extractionRunCode: asString(run.extraction_run_code),
      evidenceCode: asString(run.evidence_code),
      extractorStrategyRef: asString(run.extractor_strategy_ref, "manual_excerpt.v1"),
      inputFingerprint: asString(run.input_fingerprint_sha256),
      outputChecksum: asString(run.output_checksum_sha256),
      extractionMetadata: isRecord(run.extraction_metadata) ? run.extraction_metadata : {},
      createdBy: asOptionalString(run.created_by),
      createdAt: asOptionalString(run.created_at),
    }] : []),
    status: asString(value.status),
    createdBy: asOptionalString(value.created_by),
    approvedBy: asOptionalString(value.approved_by),
    approvedAt: asOptionalString(value.approved_at),
    revokedBy: asOptionalString(value.revoked_by),
    revokedAt: asOptionalString(value.revoked_at),
    revokedReason: asOptionalString(value.revoked_reason),
    rejectedBy: asOptionalString(value.rejected_by),
    rejectedAt: asOptionalString(value.rejected_at),
    rejectionReason: asOptionalString(value.rejection_reason),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
  };
}

function knowledgeSearchHit(value: unknown): KnowledgeSearchHit {
  if (!isRecord(value)) throw new Error("知识检索响应无效");
  const entityCode = asString(value.entity_code);
  const rawType = asString(value.entity_type);
  if (!entityCode || !["product_fact_card", "fact_claim", "content_rule", "source_evidence"].includes(rawType)) {
    throw new Error("知识检索结果缺少实体标识");
  }
  const rawValidation = isRecord(value.validation) ? value.validation : {};
  return {
    entityType: rawType as KnowledgeSearchHit["entityType"],
    entityCode,
    title: asString(value.title),
    summary: asString(value.summary),
    status: asString(value.status),
    revisionNumber: typeof value.revision_number === "number" ? value.revision_number : undefined,
    sourceEvidenceCode: asOptionalString(value.source_evidence_code),
    sourceStatus: asOptionalString(value.source_status),
    validFrom: asOptionalString(value.valid_from),
    validUntil: asOptionalString(value.valid_until),
    scope: isRecord(value.scope) ? value.scope : {},
    accessScope: asOptionalString(value.access_scope),
    validation: {
      lifecycle: asString(rawValidation.lifecycle, "not_approved") as KnowledgeSearchValidation["lifecycle"],
      source: asString(rawValidation.source, "not_required") as KnowledgeSearchValidation["source"],
      validity: asString(rawValidation.validity, "outside_window") as KnowledgeSearchValidation["validity"],
      scope: asString(rawValidation.scope, "not_scoped") as KnowledgeSearchValidation["scope"],
      rights: "not_modeled",
      contentEligible: rawValidation.content_eligible === true,
      authorizationEligible: rawValidation.authorization_eligible === true,
      blockingRuleCodes: asArray(rawValidation.blocking_rule_codes).flatMap((item) => typeof item === "string" ? [item] : []),
    },
    createdAt: asOptionalString(value.created_at),
  };
}

function factClaim(value: unknown): FactClaim {
  if (!isRecord(value)) throw new Error("事实声明响应无效");
  const claimCode = asString(value.claim_code);
  if (!claimCode) throw new Error("事实声明缺少编码");
  return {
    claimCode,
    factCode: asString(value.fact_code),
    factTitle: asString(value.fact_title),
    sourceEvidenceCode: asString(value.source_evidence_code),
    sourceTitle: asString(value.source_title),
    sourceStatus: asString(value.source_status),
    fieldPath: asOptionalString(value.field_path),
    claim: asString(value.claim),
    citationExcerpt: asString(value.citation_excerpt),
    citationStartOffset: typeof value.citation_start_offset === "number" ? value.citation_start_offset : undefined,
    citationEndOffset: typeof value.citation_end_offset === "number" ? value.citation_end_offset : undefined,
    validFrom: asOptionalString(value.valid_from),
    validUntil: asOptionalString(value.valid_until),
    status: asString(value.status),
    createdBy: asOptionalString(value.created_by),
    approvedBy: asOptionalString(value.approved_by),
    approvedAt: asOptionalString(value.approved_at),
    revokedBy: asOptionalString(value.revoked_by),
    revokedAt: asOptionalString(value.revoked_at),
    revokedReason: asOptionalString(value.revoked_reason),
    rejectedBy: asOptionalString(value.rejected_by),
    rejectedAt: asOptionalString(value.rejected_at),
    rejectionReason: asOptionalString(value.rejection_reason),
    fingerprint: asString(value.fingerprint_sha256),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
  };
}

function contentRule(value: unknown): ContentRule {
  if (!isRecord(value)) throw new Error("内容规则响应无效");
  const ruleCode = asString(value.rule_code);
  if (!ruleCode) throw new Error("内容规则缺少编码");
  const ruleKind = asString(value.rule_kind) as ContentRule["ruleKind"];
  const directive = asString(value.directive) as ContentRule["directive"];
  return {
    ruleCode,
    ruleKind,
    directive,
    title: asString(value.title),
    ruleText: asString(value.rule_text),
    scope: isRecord(value.scope) ? value.scope : {},
    sourceEvidenceCode: asOptionalString(value.source_evidence_code),
    sourceTitle: asOptionalString(value.source_title),
    sourceStatus: asOptionalString(value.source_status),
    sourceContentChecksum: asOptionalString(value.source_content_sha256),
    validFrom: asOptionalString(value.valid_from),
    validUntil: asOptionalString(value.valid_until),
    status: asString(value.status),
    createdBy: asOptionalString(value.created_by),
    approvedBy: asOptionalString(value.approved_by),
    approvedAt: asOptionalString(value.approved_at),
    revokedBy: asOptionalString(value.revoked_by),
    revokedAt: asOptionalString(value.revoked_at),
    revokedReason: asOptionalString(value.revoked_reason),
    rejectedBy: asOptionalString(value.rejected_by),
    rejectedAt: asOptionalString(value.rejected_at),
    rejectionReason: asOptionalString(value.rejection_reason),
    fingerprint: asString(value.fingerprint_sha256),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
  };
}

function factClaimLineage(value: unknown): FactClaimLineage {
  if (!isRecord(value)) throw new Error("事实声明使用链响应无效");
  const claimCode = asString(value.claim_code);
  if (!claimCode) throw new Error("事实声明使用链缺少编码");
  return {
    claimCode,
    factCode: asString(value.fact_code),
    factTitle: asString(value.fact_title),
    claimStatus: asString(value.claim_status),
    factStatus: asString(value.fact_status),
    sourceEvidenceCode: asString(value.source_evidence_code),
    sourceTitle: asString(value.source_title),
    sourceStatus: asString(value.source_status),
    uses: asArray(value.uses).flatMap((item) => {
      if (!isRecord(item)) return [];
      const objectCode = asString(item.object_code);
      if (!objectCode) return [];
      return [{
        relationType: asString(item.relation_type, "derived_from"),
        objectType: asString(item.object_type, "unknown"),
        objectCode,
        revisionNumber: typeof item.revision_number === "number" ? item.revision_number : undefined,
        status: asString(item.status, "unknown"),
        createdAt: asOptionalString(item.created_at),
      }];
    }),
  };
}

function graphNode(value: unknown): KnowledgeGraphNode | undefined {
  if (!isRecord(value) || !asString(value.node_type) || !asString(value.node_code)) return undefined;
  return {
    nodeType: asString(value.node_type), nodeCode: asString(value.node_code), revisionNumber: asNumber(value.revision_number),
    status: asOptionalString(value.status), properties: isRecord(value.properties) ? value.properties : {},
    sourceFingerprint: asString(value.source_fingerprint_sha256), createdAt: asOptionalString(value.created_at),
  };
}

function graphEdge(value: unknown): KnowledgeGraphEdge | undefined {
  if (!isRecord(value) || !asString(value.source_node_code) || !asString(value.target_node_code)) return undefined;
  return {
    sourceNodeType: asString(value.source_node_type), sourceNodeCode: asString(value.source_node_code), sourceRevisionNumber: asNumber(value.source_revision_number),
    targetNodeType: asString(value.target_node_type), targetNodeCode: asString(value.target_node_code), targetRevisionNumber: asNumber(value.target_revision_number),
    relationshipType: asString(value.relationship_type), assertionKind: asString(value.assertion_kind),
    confidence: typeof value.confidence === "number" ? value.confidence : undefined,
    validFrom: asOptionalString(value.valid_from), validUntil: asOptionalString(value.valid_until),
    evidence: isRecord(value.evidence) ? value.evidence : {}, createdAt: asOptionalString(value.created_at),
  };
}

function graphProjection(value: unknown): KnowledgeGraphProjection {
  if (!isRecord(value)) throw new Error("知识图谱投影响应无效");
  const projectionCode = asString(value.projection_code);
  if (!projectionCode) throw new Error("知识图谱投影缺少编码");
  return {
    projectionCode,
    revisionNumber: asNumber(value.revision_number),
    status: asString(value.status),
    ontologyVersion: asString(value.ontology_version),
    embeddingVersion: asOptionalString(value.embedding_version),
    sourceWatermark: isRecord(value.source_watermark) ? value.source_watermark : {},
    currentSourceWatermark: isRecord(value.current_source_watermark) ? value.current_source_watermark : {},
    snapshotFingerprint: asString(value.snapshot_fingerprint_sha256),
    nodeCount: asNumber(value.node_count),
    edgeCount: asNumber(value.edge_count),
    createdBy: asOptionalString(value.created_by),
    createdAt: asOptionalString(value.created_at),
    isStale: value.is_stale === true,
    nodes: asArray(value.nodes).flatMap((item) => graphNode(item) ?? []),
    edges: asArray(value.edges).flatMap((item) => graphEdge(item) ?? []),
  };
}

function graphSearchResult(value: unknown): KnowledgeGraphSearchResult {
  if (!isRecord(value)) throw new Error("知识来源链检索响应无效");
  return {
    query: asString(value.query),
    scope: asString(value.scope, "all") as KnowledgeGraphSearchScope,
    projectionCode: asOptionalString(value.projection_code),
    projectionRevision: typeof value.projection_revision === "number" ? value.projection_revision : undefined,
    isStale: value.is_stale === true,
    results: asArray(value.results).flatMap((item) => {
      if (!isRecord(item)) return [];
      const match = graphNode(item.match);
      if (!match) return [];
      return [{
        match,
        nodes: asArray(item.nodes).flatMap((node) => graphNode(node) ?? []),
        edges: asArray(item.edges).flatMap((edge) => graphEdge(edge) ?? []),
        truncated: item.truncated === true,
      }];
    }),
  };
}

export const knowledgeApi = {
  listProductFactCards: () => requestJson<unknown[]>(ROOT).then((items) => items.map(card)),
  createProductFactCard: (payload: ProductFactCardCreateInput) => postJson<unknown>(ROOT, payload).then(card),
  createProductFactCardVersion: (factCardCode: string, payload: ProductFactCardVersionCreateInput) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions`, payload),
  approveProductFactCardVersion: (factCardCode: string, versionNumber: number, approvedBy: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/approve`, { approved_by: approvedBy }),
  rejectProductFactCardVersion: (factCardCode: string, versionNumber: number, rejectedBy: string, reason: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/reject`, { rejected_by: rejectedBy, reason }),
  listProductFactCardUsage: (factCardCode: string, versionNumber: number) => requestJson<unknown[]>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/usage`).then((items) => items.map(usage)),
  searchKnowledge: (query: string, platform?: string, asOf?: string) => {
    const params = new URLSearchParams({ q: query.trim() });
    if (platform?.trim()) params.set("platform", platform.trim());
    if (asOf?.trim()) params.set("as_of", asOf.trim());
    return requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/search?${params}`).then((items) => items.map(knowledgeSearchHit));
  },
  listSourceEvidences: () => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/source-evidences`).then((items) => items.map(sourceEvidence)),
  listSourceExtractionRuns: (evidenceCode: string) => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/source-evidences/${encodeURIComponent(evidenceCode)}/extraction-runs`).then((items) => items.flatMap((item) => isRecord(item) && asString(item.extraction_run_code) && asString(item.evidence_code) ? [{ extractionRunCode: asString(item.extraction_run_code), evidenceCode: asString(item.evidence_code), extractorStrategyRef: asString(item.extractor_strategy_ref, "manual_excerpt.v1"), inputFingerprint: asString(item.input_fingerprint_sha256), outputChecksum: asString(item.output_checksum_sha256), extractionMetadata: isRecord(item.extraction_metadata) ? item.extraction_metadata : {}, createdBy: asOptionalString(item.created_by), createdAt: asOptionalString(item.created_at) }] : [])),
  createSourceEvidence: (payload: SourceEvidenceCreateInput) => postJson<unknown>(`${FUNCTIONAL_ROOT}/source-evidences`, payload).then(sourceEvidence),
  approveSourceEvidence: (evidenceCode: string, approvedBy: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/source-evidences/${encodeURIComponent(evidenceCode)}/approve`, { approved_by: approvedBy }).then(sourceEvidence),
  rejectSourceEvidence: (evidenceCode: string, actor: string, reason: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/source-evidences/${encodeURIComponent(evidenceCode)}/reject`, { actor, reason }).then(sourceEvidence),
  revokeSourceEvidence: (evidenceCode: string, actor: string, reason: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/source-evidences/${encodeURIComponent(evidenceCode)}/revoke`, { actor, reason }).then(sourceEvidence),
  listContentRules: () => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/content-rules`).then((items) => items.map(contentRule)),
  searchContentRules: (query: string) => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/content-rules?q=${encodeURIComponent(query.trim())}`).then((items) => items.map(contentRule)),
  createContentRule: (payload: ContentRuleCreateInput) => postJson<unknown>(`${FUNCTIONAL_ROOT}/content-rules`, payload).then(contentRule),
  approveContentRule: (ruleCode: string, approvedBy: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/content-rules/${encodeURIComponent(ruleCode)}/approve`, { approved_by: approvedBy }).then(contentRule),
  rejectContentRule: (ruleCode: string, actor: string, reason: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/content-rules/${encodeURIComponent(ruleCode)}/reject`, { actor, reason }).then(contentRule),
  revokeContentRule: (ruleCode: string, actor: string, reason: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/content-rules/${encodeURIComponent(ruleCode)}/revoke`, { actor, reason }).then(contentRule),
  listFactClaims: () => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/fact-claims`).then((items) => items.map(factClaim)),
  searchFactClaims: (query: string) => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/fact-claims?q=${encodeURIComponent(query.trim())}`).then((items) => items.map(factClaim)),
  getFactClaimLineage: (claimCode: string) => requestJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims/${encodeURIComponent(claimCode)}/lineage`).then(factClaimLineage),
  currentGraphProjection: () => requestJson<unknown>(`${FUNCTIONAL_ROOT}/graph-projections/current`).then((value) => value === null ? null : graphProjection(value)),
  searchGraphLineage: (query: string, scope: KnowledgeGraphSearchScope = "all") => {
    const params = new URLSearchParams({ q: query.trim(), scope });
    return requestJson<unknown>(`${FUNCTIONAL_ROOT}/graph-search?${params}`).then(graphSearchResult);
  },
  getGraphProjection: (projectionCode: string) => requestJson<unknown>(`${FUNCTIONAL_ROOT}/graph-projections/${encodeURIComponent(projectionCode)}`).then(graphProjection),
  rebuildGraphProjection: (actor = "console_operator") => postJson<unknown>(`${FUNCTIONAL_ROOT}/graph-projections/rebuild`, { actor }).then(graphProjection),
  createFactClaim: (payload: FactClaimCreateInput) => postJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims`, payload).then(factClaim),
  approveFactClaim: (claimCode: string, approvedBy: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims/${encodeURIComponent(claimCode)}/approve`, { approved_by: approvedBy }).then(factClaim),
  rejectFactClaim: (claimCode: string, actor: string, reason: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims/${encodeURIComponent(claimCode)}/reject`, { actor, reason }).then(factClaim),
  revokeFactClaim: (claimCode: string, actor: string, reason: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims/${encodeURIComponent(claimCode)}/revoke`, { actor, reason }).then(factClaim),
};
