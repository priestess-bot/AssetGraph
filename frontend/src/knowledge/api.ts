import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

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
  status: string;
  createdBy?: string;
  approvedBy?: string;
  approvedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface SourceEvidenceCreateInput {
  source_type: "human" | "document" | "webpage" | "export";
  title: string;
  source_url?: string;
  excerpt: string;
  captured_at?: string;
  access_scope: string;
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
  validFrom?: string;
  validUntil?: string;
  status: string;
  createdBy?: string;
  approvedBy?: string;
  approvedAt?: string;
  fingerprint: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface FactClaimCreateInput {
  fact_title: string;
  claim: string;
  source_evidence_code: string;
  citation_excerpt: string;
  field_path?: string;
  valid_from?: string;
  valid_until?: string;
  created_by?: string;
  related_codes?: string[];
}

function card(value: unknown): ProductFactCard {
  if (!isRecord(value)) throw new Error("事实卡响应无效");
  const factCardCode = asString(value.fact_card_code);
  if (!factCardCode) throw new Error("事实卡缺少编码");
  return {
    factCardCode,
    title: asString(value.title, factCardCode),
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
    title: asString(value.title),
    sourceUrl: asOptionalString(value.source_url),
    excerpt: asString(value.excerpt),
    contentChecksum: asString(value.content_sha256),
    capturedAt: asOptionalString(value.captured_at),
    accessScope: asString(value.access_scope, "internal"),
    status: asString(value.status),
    createdBy: asOptionalString(value.created_by),
    approvedBy: asOptionalString(value.approved_by),
    approvedAt: asOptionalString(value.approved_at),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
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
    validFrom: asOptionalString(value.valid_from),
    validUntil: asOptionalString(value.valid_until),
    status: asString(value.status),
    createdBy: asOptionalString(value.created_by),
    approvedBy: asOptionalString(value.approved_by),
    approvedAt: asOptionalString(value.approved_at),
    fingerprint: asString(value.fingerprint_sha256),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
  };
}

export const knowledgeApi = {
  listProductFactCards: () => requestJson<unknown[]>(ROOT).then((items) => items.map(card)),
  createProductFactCard: (payload: ProductFactCardCreateInput) => postJson<unknown>(ROOT, payload).then(card),
  createProductFactCardVersion: (factCardCode: string, payload: ProductFactCardVersionCreateInput) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions`, payload),
  approveProductFactCardVersion: (factCardCode: string, versionNumber: number, approvedBy: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/approve`, { approved_by: approvedBy }),
  rejectProductFactCardVersion: (factCardCode: string, versionNumber: number, rejectedBy: string, reason: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/reject`, { rejected_by: rejectedBy, reason }),
  listProductFactCardUsage: (factCardCode: string, versionNumber: number) => requestJson<unknown[]>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/usage`).then((items) => items.map(usage)),
  listSourceEvidences: () => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/source-evidences`).then((items) => items.map(sourceEvidence)),
  createSourceEvidence: (payload: SourceEvidenceCreateInput) => postJson<unknown>(`${FUNCTIONAL_ROOT}/source-evidences`, payload).then(sourceEvidence),
  approveSourceEvidence: (evidenceCode: string, approvedBy: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/source-evidences/${encodeURIComponent(evidenceCode)}/approve`, { approved_by: approvedBy }).then(sourceEvidence),
  listFactClaims: () => requestJson<unknown[]>(`${FUNCTIONAL_ROOT}/fact-claims`).then((items) => items.map(factClaim)),
  createFactClaim: (payload: FactClaimCreateInput) => postJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims`, payload).then(factClaim),
  approveFactClaim: (claimCode: string, approvedBy: string) => postJson<unknown>(`${FUNCTIONAL_ROOT}/fact-claims/${encodeURIComponent(claimCode)}/approve`, { approved_by: approvedBy }).then(factClaim),
};
