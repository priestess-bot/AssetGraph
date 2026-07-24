import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

const ROOT = "/api/maitu/workbench/product-fact-cards";

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

export const knowledgeApi = {
  listProductFactCards: () => requestJson<unknown[]>(ROOT).then((items) => items.map(card)),
  createProductFactCard: (payload: ProductFactCardCreateInput) => postJson<unknown>(ROOT, payload).then(card),
  createProductFactCardVersion: (factCardCode: string, payload: ProductFactCardVersionCreateInput) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions`, payload),
  approveProductFactCardVersion: (factCardCode: string, versionNumber: number, approvedBy: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/approve`, { approved_by: approvedBy }),
  rejectProductFactCardVersion: (factCardCode: string, versionNumber: number, rejectedBy: string, reason: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(factCardCode)}/versions/${versionNumber}/reject`, { rejected_by: rejectedBy, reason }),
};
