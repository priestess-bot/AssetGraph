import { asArray, asNumber, asOptionalString, asString, isRecord, patchJson, postJson, requestJson } from "../workbench/api";

const ROOT = "/api/assets";

export type MaterialRole = "background" | "product_display" | "digital_human" | "brand_title" | "promotion_text" | "decoration_foreground" | "supporting_video" | "voice" | "background_music" | "sound_effect";
export type ExecutionCapability = "maitu_bound" | "local_only" | "reference_only" | "unavailable" | "unclassified";

export interface LibraryAsset {
  assetCode: string;
  title: string;
  originalFilename: string;
  assetType: string;
  mediaKind?: string;
  materialRoles: string[];
  executionCapability: ExecutionCapability;
  maituCategory?: string;
}

export interface AssetGroup {
  groupCode: string;
  title: string;
  description?: string;
  assetCodes: string[];
  assetCount: number;
}

export interface ConstraintRule {
  kind: string;
  hard: boolean;
  parameters: Record<string, unknown>;
}

export interface MaterialPack {
  packCode: string;
  title: string;
  role: string;
  description?: string;
  revisionNumber: number;
  status: "draft" | "published" | "archived";
  fingerprintSha256: string;
  entries: Array<{ selection_kind: "asset" | "group"; selection_code: string; mode: "required" | "optional" | "alternative"; min_occurrences: number; max_occurrences?: number }>;
  resolvedAssetCodes: string[];
}

export interface MaterialPackRevision {
  revisionNumber: number;
  entries: MaterialPack["entries"];
  fingerprintSha256: string;
  createdAt?: string;
}

export interface AssetGap {
  gapCode: string;
  title: string;
  role: string;
  severity: string;
  status: string;
  gapType: string;
  impactSummary?: string;
  alternativeAssetCodes: string[];
  resolutionAssetCode?: string;
  resolutionSnapshot: Record<string, unknown>;
  resolutionEvidence: Record<string, unknown>;
  waivedReason?: string;
  events: Array<{ eventCode: string; previousStatus?: string; status: string; actor?: string; createdAt?: string }>;
}

export interface MaterialSelectionPreview {
  role: string;
  carrierKind: string;
  candidates: Array<{ assetCode: string; title: string; score: number; scoreParts: Record<string, number>; reasons: string[]; constraintProfile?: { profileCode: string; revisionNumber: number } }>;
  excluded: Array<{ assetCode: string; title: string; exclusionCodes: string[] }>;
  unverifiedGates: string[];
}

function strings(value: unknown): string[] {
  return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []);
}

function asset(value: unknown): LibraryAsset | undefined {
  if (!isRecord(value)) return undefined;
  const assetCode = asString(value.asset_code);
  if (!assetCode) return undefined;
  return {
    assetCode,
    title: asString(value.title, asString(value.original_filename, assetCode)),
    originalFilename: asString(value.original_filename, assetCode),
    assetType: asString(value.asset_type),
    mediaKind: asOptionalString(value.media_kind),
    materialRoles: strings(value.material_roles),
    executionCapability: asString(value.execution_capability, "unclassified") as ExecutionCapability,
    maituCategory: asOptionalString(value.maitu_category),
  };
}

function group(value: unknown): AssetGroup | undefined {
  if (!isRecord(value)) return undefined;
  const groupCode = asString(value.group_code);
  if (!groupCode) return undefined;
  return { groupCode, title: asString(value.title, groupCode), description: asOptionalString(value.description), assetCodes: strings(value.asset_codes), assetCount: asNumber(value.asset_count) };
}

function pack(value: unknown): MaterialPack | undefined {
  if (!isRecord(value)) return undefined;
  const packCode = asString(value.pack_code);
  if (!packCode) return undefined;
  const entries = asArray(value.entries).flatMap((item) => isRecord(item) && (item.selection_kind === "asset" || item.selection_kind === "group") ? [{
    selection_kind: item.selection_kind as "asset" | "group",
    selection_code: asString(item.selection_code),
    mode: asString(item.mode, "optional") as "required" | "optional" | "alternative",
    min_occurrences: asNumber(item.min_occurrences),
    max_occurrences: typeof item.max_occurrences === "number" ? item.max_occurrences : undefined,
  }] : []);
  return { packCode, title: asString(value.title, packCode), role: asString(value.role), description: asOptionalString(value.description), revisionNumber: asNumber(value.revision_number), status: asString(value.status, "draft") as MaterialPack["status"], fingerprintSha256: asString(value.fingerprint_sha256), entries, resolvedAssetCodes: strings(value.resolved_asset_codes) };
}

function packRevision(value: unknown): MaterialPackRevision | undefined {
  if (!isRecord(value)) return undefined;
  const revisionNumber = asNumber(value.revision_number);
  const fingerprintSha256 = asString(value.fingerprint_sha256);
  if (!revisionNumber || !fingerprintSha256) return undefined;
  const entries = asArray(value.entries).flatMap((item) => isRecord(item) && (item.selection_kind === "asset" || item.selection_kind === "group") ? [{
    selection_kind: item.selection_kind as "asset" | "group",
    selection_code: asString(item.selection_code),
    mode: asString(item.mode, "optional") as "required" | "optional" | "alternative",
    min_occurrences: asNumber(item.min_occurrences),
    max_occurrences: typeof item.max_occurrences === "number" ? item.max_occurrences : undefined,
  }] : []);
  return { revisionNumber, entries, fingerprintSha256, createdAt: asOptionalString(value.created_at) };
}

function gap(value: unknown): AssetGap | undefined {
  if (!isRecord(value)) return undefined;
  const gapCode = asString(value.gap_code);
  if (!gapCode) return undefined;
  return {
    gapCode, title: asString(value.title, gapCode), role: asString(value.role), severity: asString(value.severity), status: asString(value.status), gapType: asString(value.gap_type, "material_missing"), impactSummary: asOptionalString(value.impact_summary), alternativeAssetCodes: strings(value.alternative_asset_codes), resolutionAssetCode: asOptionalString(value.resolution_asset_code), resolutionSnapshot: isRecord(value.resolution_snapshot) ? value.resolution_snapshot : {}, resolutionEvidence: isRecord(value.resolution_evidence) ? value.resolution_evidence : {}, waivedReason: asOptionalString(value.waived_reason),
    events: asArray(value.events).flatMap((event) => isRecord(event) && asString(event.status) ? [{ eventCode: asString(event.event_code), previousStatus: asOptionalString(event.previous_status), status: asString(event.status), actor: asOptionalString(event.actor), createdAt: asOptionalString(event.created_at) }] : []),
  };
}

function selectionPreview(value: unknown): MaterialSelectionPreview {
  if (!isRecord(value)) throw new Error("选材预览响应无效");
  return {
    role: asString(value.role), carrierKind: asString(value.carrier_kind),
    candidates: asArray(value.candidates).flatMap((item) => isRecord(item) && asString(item.asset_code) ? [{
      assetCode: asString(item.asset_code), title: asString(item.title, asString(item.asset_code)), score: asNumber(item.score), scoreParts: isRecord(item.score_parts) ? Object.fromEntries(Object.entries(item.score_parts).map(([key, score]) => [key, asNumber(score)])) : {}, reasons: strings(item.selection_reasons),
      constraintProfile: isRecord(item.constraint_profile) && asString(item.constraint_profile.profile_code) ? { profileCode: asString(item.constraint_profile.profile_code), revisionNumber: asNumber(item.constraint_profile.revision_number) } : undefined,
    }] : []),
    excluded: asArray(value.excluded).flatMap((item) => isRecord(item) && asString(item.asset_code) ? [{ assetCode: asString(item.asset_code), title: asString(item.title, asString(item.asset_code)), exclusionCodes: strings(item.exclusion_codes) }] : []),
    unverifiedGates: strings(value.unverified_gates),
  };
}

export const assetLibraryApi = {
  listAssets: () => requestJson<unknown[]>(ROOT).then((rows) => rows.flatMap((row) => asset(row) ?? [])),
  createAsset: (payload: { title: string; original_filename: string; asset_type: string; media_kind?: string; material_roles: string[]; execution_capability: ExecutionCapability }) => postJson<unknown>(ROOT, payload).then((value) => {
    const result = asset(value);
    if (!result) throw new Error("素材创建响应无效");
    return result;
  }),
  updateClassification: (assetCode: string, payload: { media_kind?: string; material_roles: string[]; execution_capability: ExecutionCapability }) => patchJson<unknown>(`${ROOT}/${assetCode}/classification`, payload).then((value) => {
    const result = asset(value);
    if (!result) throw new Error("素材分类响应无效");
    return result;
  }),
  updateClassifications: (payload: { asset_codes: string[]; media_kind: string; material_roles: string[]; execution_capability: ExecutionCapability }) => requestJson<unknown[]>(`${ROOT}/batch-classification`, { method: "PATCH", body: JSON.stringify(payload) }).then((rows) => rows.flatMap((row) => asset(row) ?? [])),
  listGroups: () => requestJson<unknown[]>(`${ROOT}/groups`).then((rows) => rows.flatMap((row) => group(row) ?? [])),
  createGroup: (payload: { title: string; description?: string; asset_codes: string[] }) => postJson<unknown>(`${ROOT}/groups`, payload).then((value) => {
    const result = group(value);
    if (!result) throw new Error("分组响应无效");
    return result;
  }),
  replaceGroupMembers: (groupCode: string, assetCodes: string[]) => requestJson<unknown>(`${ROOT}/groups/${groupCode}/members`, { method: "PUT", body: JSON.stringify({ asset_codes: assetCodes }) }).then((value) => {
    const result = group(value);
    if (!result) throw new Error("分组成员响应无效");
    return result;
  }),
  getConstraintProfile: (assetCode: string) => requestJson<{ constraints: ConstraintRule[] }>(`${ROOT}/${assetCode}/constraint-profile`),
  writeConstraintProfile: (assetCode: string, constraints: ConstraintRule[]) => postJson<{ constraints: ConstraintRule[] }>(`${ROOT}/${assetCode}/constraint-profile`, { constraints }),
  previewSelection: (payload: { role: string; carrier_kind: "live_room" | "rendered_video" }) => postJson<unknown>(`${ROOT}/selection-preview`, payload).then(selectionPreview),
  listPacks: () => requestJson<unknown[]>(`${ROOT}/material-packs`).then((rows) => rows.flatMap((row) => pack(row) ?? [])),
  createPack: (payload: { title: string; role: string; description?: string; entries: MaterialPack["entries"] }) => postJson<unknown>(`${ROOT}/material-packs`, payload).then((value) => {
    const result = pack(value);
    if (!result) throw new Error("素材包响应无效");
    return result;
  }),
  publishPack: (packCode: string) => postJson<unknown>(`${ROOT}/material-packs/${packCode}/publish`, {}).then((value) => {
    const result = pack(value);
    if (!result) throw new Error("素材包发布响应无效");
    return result;
  }),
  listPackRevisions: (packCode: string) => requestJson<unknown[]>(`${ROOT}/material-packs/${packCode}/revisions`).then((rows) => rows.flatMap((row) => packRevision(row) ?? [])),
  createPackRevision: (packCode: string, payload: { expected_revision: number; entries: MaterialPack["entries"] }) => postJson<unknown>(`${ROOT}/material-packs/${packCode}/revisions`, payload).then((value) => {
    const result = pack(value);
    if (!result) throw new Error("素材包修订响应无效");
    return result;
  }),
  listGaps: () => requestJson<unknown[]>(`${ROOT}/gaps`).then((rows) => rows.flatMap((row) => gap(row) ?? [])),
  createGap: (payload: { title: string; role: string; severity: string; gap_type?: string; impact_summary?: string; alternative_asset_codes?: string[] }) => postJson<unknown>(`${ROOT}/gaps`, payload).then((value) => {
    const result = gap(value);
    if (!result) throw new Error("素材缺口响应无效");
    return result;
  }),
  updateGap: (gapCode: string, payload: { status: string; resolution_asset_code?: string; waiver_reason?: string; actor?: string; resolution_evidence?: Record<string, unknown> }) => patchJson<unknown>(`${ROOT}/gaps/${gapCode}`, payload).then((value) => {
    const result = gap(value);
    if (!result) throw new Error("素材缺口响应无效");
    return result;
  }),
};
