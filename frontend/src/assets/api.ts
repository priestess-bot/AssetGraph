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
  entries: Array<{ selection_kind: "asset" | "group"; selection_code: string; mode: "required" | "optional" | "alternative"; min_occurrences: number; max_occurrences?: number }>;
  resolvedAssetCodes: string[];
}

export interface AssetGap {
  gapCode: string;
  title: string;
  role: string;
  severity: string;
  status: string;
  resolutionAssetCode?: string;
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
  return { packCode, title: asString(value.title, packCode), role: asString(value.role), description: asOptionalString(value.description), revisionNumber: asNumber(value.revision_number), entries, resolvedAssetCodes: strings(value.resolved_asset_codes) };
}

function gap(value: unknown): AssetGap | undefined {
  if (!isRecord(value)) return undefined;
  const gapCode = asString(value.gap_code);
  if (!gapCode) return undefined;
  return { gapCode, title: asString(value.title, gapCode), role: asString(value.role), severity: asString(value.severity), status: asString(value.status), resolutionAssetCode: asOptionalString(value.resolution_asset_code) };
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
  listPacks: () => requestJson<unknown[]>(`${ROOT}/material-packs`).then((rows) => rows.flatMap((row) => pack(row) ?? [])),
  createPack: (payload: { title: string; role: string; description?: string; entries: MaterialPack["entries"] }) => postJson<unknown>(`${ROOT}/material-packs`, payload).then((value) => {
    const result = pack(value);
    if (!result) throw new Error("素材包响应无效");
    return result;
  }),
  listGaps: () => requestJson<unknown[]>(`${ROOT}/gaps`).then((rows) => rows.flatMap((row) => gap(row) ?? [])),
  createGap: (payload: { title: string; role: string; severity: string }) => postJson<unknown>(`${ROOT}/gaps`, payload).then((value) => {
    const result = gap(value);
    if (!result) throw new Error("素材缺口响应无效");
    return result;
  }),
  updateGap: (gapCode: string, payload: { status: string; resolution_asset_code?: string }) => patchJson<unknown>(`${ROOT}/gaps/${gapCode}`, payload).then((value) => {
    const result = gap(value);
    if (!result) throw new Error("素材缺口响应无效");
    return result;
  }),
};
