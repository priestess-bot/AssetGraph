import {
  asArray,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  patchJson,
  postJson,
  requestJson,
} from "../workbench/api";

const ROOT = "/api/assets";

export type MaterialRole =
  | "background"
  | "product_display"
  | "digital_human"
  | "brand_title"
  | "promotion_text"
  | "decoration_foreground"
  | "supporting_video"
  | "voice"
  | "background_music"
  | "sound_effect";
export type ExecutionCapability =
  | "maitu_bound"
  | "local_only"
  | "reference_only"
  | "unavailable"
  | "unclassified";

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

export interface ConstraintProfileRevision {
  profileCode: string;
  assetCode: string;
  revisionNumber: number;
  constraints: ConstraintRule[];
  fingerprintSha256: string;
  createdAt?: string;
}

export interface AssetEffectSummary {
  effectCode: string;
  revisionNumber: number;
  attributionReportCode: string;
  metricKey: string;
  evidenceLevel: string;
  status: string;
  selectedSessionCount: number;
  automaticRecommendationMinimumSessionCount: number;
  automaticRecommendationEligible: boolean;
  recommendationBlockers: string[];
  note: string;
  approvedAt?: string;
  createdAt?: string;
}

export interface MaterialPack {
  packCode: string;
  title: string;
  packKind: "total" | "classification";
  role?: string;
  description?: string;
  revisionNumber: number;
  status: "draft" | "published" | "superseded" | "archived";
  revisionStatus: "draft" | "published" | "superseded" | "archived";
  publishedRevisionNumber?: number;
  fingerprintSha256: string;
  entries: MaterialPackEntry[];
  exclusiveRoles: string[];
  packConstraints: Array<Record<string, unknown>>;
  resolvedAssetCodes: string[];
  resolvedEntries: Array<{
    entryKey: string;
    materialRole?: string;
    mode: string;
    resolvedAssetCodes: string[];
  }>;
}

export interface MaterialPackEntry {
  selection_kind: "asset" | "group" | "category_pack";
  selection_code: string;
  material_role?: string;
  mode: "required" | "optional" | "alternative";
  min_occurrences: number;
  max_occurrences?: number;
  applicable_scope: {
    kind: "whole_room" | "scene_types" | "scene_codes";
    scene_types: string[];
    scene_codes: string[];
  };
  pack_constraints: Array<Record<string, unknown>>;
  alternative_set_key?: string;
}

export interface MaterialPackRevision {
  revisionNumber: number;
  entries: MaterialPack["entries"];
  fingerprintSha256: string;
  status: string;
  exclusiveRoles: string[];
  packConstraints: Array<Record<string, unknown>>;
  createdAt?: string;
}

export interface AssetGap {
  gapCode: string;
  title: string;
  role: string;
  severity: string;
  status: string;
  gapType: string;
  specification: Record<string, unknown>;
  sourceContext: Record<string, unknown>;
  impactSummary?: string;
  alternativeAssetCodes: string[];
  resolutionAssetCode?: string;
  resolutionSnapshot: Record<string, unknown>;
  resolutionEvidence: Record<string, unknown>;
  waivedReason?: string;
  events: Array<{
    eventCode: string;
    previousStatus?: string;
    status: string;
    actor?: string;
    createdAt?: string;
  }>;
}

export interface MaterialSelectionPreview {
  role: string;
  carrierKind: string;
  candidates: Array<{
    assetCode: string;
    title: string;
    score: number;
    scoreParts: Record<string, number>;
    reasons: string[];
    qualifiedEffectRefs: Array<{
      effectCode: string;
      revisionNumber: number;
      metricKey: string;
      selectedSessionCount: number;
    }>;
    constraintProfile?: { profileCode: string; revisionNumber: number };
  }>;
  excluded: Array<{
    assetCode: string;
    title: string;
    exclusionCodes: string[];
  }>;
  unverifiedGates: string[];
}

export interface MaterialPackResolutionPreview {
  packRefs: Array<{
    packCode: string;
    packKind: string;
    revisionNumber: number;
    fingerprintSha256: string;
    role?: string;
  }>;
  resolvedAssetCodes: string[];
  entryRequirements: Array<{
    packCode: string;
    entryKey: string;
    mode: string;
    materialRole?: string;
    candidateAssetCodes: string[];
    minOccurrences: number;
    maxOccurrences?: number;
  }>;
  conflicts: Array<{
    code: string;
    materialRole?: string;
    packCodes?: string[];
    remediation?: string;
  }>;
  fingerprintSha256: string;
}

function strings(value: unknown): string[] {
  return asArray(value).flatMap((item) =>
    typeof item === "string" ? [item] : [],
  );
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
    executionCapability: asString(
      value.execution_capability,
      "unclassified",
    ) as ExecutionCapability,
    maituCategory: asOptionalString(value.maitu_category),
  };
}

function group(value: unknown): AssetGroup | undefined {
  if (!isRecord(value)) return undefined;
  const groupCode = asString(value.group_code);
  if (!groupCode) return undefined;
  return {
    groupCode,
    title: asString(value.title, groupCode),
    description: asOptionalString(value.description),
    assetCodes: strings(value.asset_codes),
    assetCount: asNumber(value.asset_count),
  };
}

function pack(value: unknown): MaterialPack | undefined {
  if (!isRecord(value)) return undefined;
  const packCode = asString(value.pack_code);
  if (!packCode) return undefined;
  const entries = asArray(value.entries).flatMap((item) =>
    isRecord(item) &&
    (item.selection_kind === "asset" ||
      item.selection_kind === "group" ||
      item.selection_kind === "category_pack")
      ? [
          {
            selection_kind:
              item.selection_kind as MaterialPackEntry["selection_kind"],
            selection_code: asString(item.selection_code),
            material_role: asOptionalString(item.material_role),
            mode: asString(item.mode, "optional") as
              "required" | "optional" | "alternative",
            min_occurrences: asNumber(item.min_occurrences),
            max_occurrences:
              typeof item.max_occurrences === "number"
                ? item.max_occurrences
                : undefined,
            applicable_scope: isRecord(item.applicable_scope)
              ? {
                  kind: asString(
                    item.applicable_scope.kind,
                    "whole_room",
                  ) as MaterialPackEntry["applicable_scope"]["kind"],
                  scene_types: strings(item.applicable_scope.scene_types),
                  scene_codes: strings(item.applicable_scope.scene_codes),
                }
              : {
                  kind: "whole_room" as const,
                  scene_types: [],
                  scene_codes: [],
                },
            pack_constraints: asArray(item.pack_constraints).flatMap(
              (constraint) => (isRecord(constraint) ? [constraint] : []),
            ),
            alternative_set_key: asOptionalString(item.alternative_set_key),
          },
        ]
      : [],
  );
  return {
    packCode,
    title: asString(value.title, packCode),
    packKind: asString(value.pack_kind, "total") as MaterialPack["packKind"],
    role: asOptionalString(value.role),
    description: asOptionalString(value.description),
    revisionNumber: asNumber(value.revision_number),
    status: asString(value.status, "draft") as MaterialPack["status"],
    revisionStatus: asString(
      value.revision_status,
      asString(value.status, "draft"),
    ) as MaterialPack["revisionStatus"],
    publishedRevisionNumber:
      typeof value.published_revision_number === "number"
        ? value.published_revision_number
        : undefined,
    fingerprintSha256: asString(value.fingerprint_sha256),
    entries,
    exclusiveRoles: strings(value.exclusive_roles),
    packConstraints: asArray(value.pack_constraints).flatMap((constraint) =>
      isRecord(constraint) ? [constraint] : [],
    ),
    resolvedAssetCodes: strings(value.resolved_asset_codes),
    resolvedEntries: asArray(value.resolved_entries).flatMap((entry) =>
      isRecord(entry) && asString(entry.entry_key)
        ? [
            {
              entryKey: asString(entry.entry_key),
              materialRole: asOptionalString(entry.material_role),
              mode: asString(entry.mode),
              resolvedAssetCodes: strings(entry.resolved_asset_codes),
            },
          ]
        : [],
    ),
  };
}

function packRevision(value: unknown): MaterialPackRevision | undefined {
  if (!isRecord(value)) return undefined;
  const revisionNumber = asNumber(value.revision_number);
  const fingerprintSha256 = asString(value.fingerprint_sha256);
  if (!revisionNumber || !fingerprintSha256) return undefined;
  const entries = asArray(value.entries).flatMap((item) =>
    isRecord(item) &&
    (item.selection_kind === "asset" ||
      item.selection_kind === "group" ||
      item.selection_kind === "category_pack")
      ? [
          {
            selection_kind:
              item.selection_kind as MaterialPackEntry["selection_kind"],
            selection_code: asString(item.selection_code),
            material_role: asOptionalString(item.material_role),
            mode: asString(item.mode, "optional") as
              "required" | "optional" | "alternative",
            min_occurrences: asNumber(item.min_occurrences),
            max_occurrences:
              typeof item.max_occurrences === "number"
                ? item.max_occurrences
                : undefined,
            applicable_scope: isRecord(item.applicable_scope)
              ? {
                  kind: asString(
                    item.applicable_scope.kind,
                    "whole_room",
                  ) as MaterialPackEntry["applicable_scope"]["kind"],
                  scene_types: strings(item.applicable_scope.scene_types),
                  scene_codes: strings(item.applicable_scope.scene_codes),
                }
              : {
                  kind: "whole_room" as const,
                  scene_types: [],
                  scene_codes: [],
                },
            pack_constraints: asArray(item.pack_constraints).flatMap(
              (constraint) => (isRecord(constraint) ? [constraint] : []),
            ),
            alternative_set_key: asOptionalString(item.alternative_set_key),
          },
        ]
      : [],
  );
  return {
    revisionNumber,
    entries,
    fingerprintSha256,
    createdAt: asOptionalString(value.created_at),
    status: asString(value.status, "draft"),
    exclusiveRoles: strings(value.exclusive_roles),
    packConstraints: asArray(value.pack_constraints).flatMap((constraint) =>
      isRecord(constraint) ? [constraint] : [],
    ),
  };
}

function gap(value: unknown): AssetGap | undefined {
  if (!isRecord(value)) return undefined;
  const gapCode = asString(value.gap_code);
  if (!gapCode) return undefined;
  return {
    gapCode,
    title: asString(value.title, gapCode),
    role: asString(value.role),
    severity: asString(value.severity),
    status: asString(value.status),
    gapType: asString(value.gap_type, "material_missing"),
    specification: isRecord(value.specification) ? value.specification : {},
    sourceContext: isRecord(value.source_context) ? value.source_context : {},
    impactSummary: asOptionalString(value.impact_summary),
    alternativeAssetCodes: strings(value.alternative_asset_codes),
    resolutionAssetCode: asOptionalString(value.resolution_asset_code),
    resolutionSnapshot: isRecord(value.resolution_snapshot)
      ? value.resolution_snapshot
      : {},
    resolutionEvidence: isRecord(value.resolution_evidence)
      ? value.resolution_evidence
      : {},
    waivedReason: asOptionalString(value.waived_reason),
    events: asArray(value.events).flatMap((event) =>
      isRecord(event) && asString(event.status)
        ? [
            {
              eventCode: asString(event.event_code),
              previousStatus: asOptionalString(event.previous_status),
              status: asString(event.status),
              actor: asOptionalString(event.actor),
              createdAt: asOptionalString(event.created_at),
            },
          ]
        : [],
    ),
  };
}

function selectionPreview(value: unknown): MaterialSelectionPreview {
  if (!isRecord(value)) throw new Error("选材预览响应无效");
  return {
    role: asString(value.role),
    carrierKind: asString(value.carrier_kind),
    candidates: asArray(value.candidates).flatMap((item) =>
      isRecord(item) && asString(item.asset_code)
        ? [
            {
              assetCode: asString(item.asset_code),
              title: asString(item.title, asString(item.asset_code)),
              score: asNumber(item.score),
              scoreParts: isRecord(item.score_parts)
                ? Object.fromEntries(
                    Object.entries(item.score_parts).map(([key, score]) => [
                      key,
                      asNumber(score),
                    ]),
                  )
                : {},
              reasons: strings(item.selection_reasons),
              qualifiedEffectRefs: asArray(item.qualified_effect_refs).flatMap(
                (effect) =>
                  isRecord(effect) && asString(effect.effect_code)
                    ? [
                        {
                          effectCode: asString(effect.effect_code),
                          revisionNumber: asNumber(effect.revision_number),
                          metricKey: asString(effect.metric_key),
                          selectedSessionCount: Math.max(
                            0,
                            asNumber(effect.selected_session_count),
                          ),
                        },
                      ]
                    : [],
              ),
              constraintProfile:
                isRecord(item.constraint_profile) &&
                asString(item.constraint_profile.profile_code)
                  ? {
                      profileCode: asString(
                        item.constraint_profile.profile_code,
                      ),
                      revisionNumber: asNumber(
                        item.constraint_profile.revision_number,
                      ),
                    }
                  : undefined,
            },
          ]
        : [],
    ),
    excluded: asArray(value.excluded).flatMap((item) =>
      isRecord(item) && asString(item.asset_code)
        ? [
            {
              assetCode: asString(item.asset_code),
              title: asString(item.title, asString(item.asset_code)),
              exclusionCodes: strings(item.exclusion_codes),
            },
          ]
        : [],
    ),
    unverifiedGates: strings(value.unverified_gates),
  };
}

function packResolution(value: unknown): MaterialPackResolutionPreview {
  if (!isRecord(value)) throw new Error("素材包解析响应无效");
  return {
    packRefs: asArray(value.pack_refs).flatMap((pack) =>
      isRecord(pack) && asString(pack.pack_code)
        ? [
            {
              packCode: asString(pack.pack_code),
              packKind: asString(pack.pack_kind),
              revisionNumber: asNumber(pack.revision_number),
              fingerprintSha256: asString(pack.fingerprint_sha256),
              role: asOptionalString(pack.role),
            },
          ]
        : [],
    ),
    resolvedAssetCodes: strings(value.resolved_asset_codes),
    entryRequirements: asArray(value.entry_requirements).flatMap((item) =>
      isRecord(item) && asString(item.pack_code) && asString(item.entry_key)
        ? [
            {
              packCode: asString(item.pack_code),
              entryKey: asString(item.entry_key),
              mode: asString(item.mode),
              materialRole: asOptionalString(item.material_role),
              candidateAssetCodes: strings(item.resolved_asset_codes),
              minOccurrences: asNumber(item.min_occurrences),
              maxOccurrences:
                typeof item.max_occurrences === "number"
                  ? item.max_occurrences
                  : undefined,
            },
          ]
        : [],
    ),
    conflicts: asArray(value.conflicts).flatMap((conflict) =>
      isRecord(conflict) && asString(conflict.code)
        ? [
            {
              code: asString(conflict.code),
              materialRole: asOptionalString(conflict.material_role),
              packCodes: strings(conflict.pack_codes),
              remediation: asOptionalString(conflict.remediation),
            },
          ]
        : [],
    ),
    fingerprintSha256: asString(value.fingerprint_sha256),
  };
}

function constraintProfileRevision(value: unknown): ConstraintProfileRevision {
  if (!isRecord(value)) throw new Error("约束 Profile 响应无效");
  const profileCode = asString(value.profile_code);
  const assetCode = asString(value.asset_code);
  if (!profileCode || !assetCode) throw new Error("约束 Profile 缺少编码");
  return {
    profileCode,
    assetCode,
    revisionNumber: asNumber(value.revision_number),
    constraints: asArray(value.constraints).flatMap((rule) =>
      isRecord(rule) && asString(rule.kind)
        ? [
            {
              kind: asString(rule.kind),
              hard: rule.hard !== false,
              parameters: isRecord(rule.parameters) ? rule.parameters : {},
            },
          ]
        : [],
    ),
    fingerprintSha256: asString(value.fingerprint_sha256),
    createdAt: asOptionalString(value.created_at),
  };
}

function assetEffectSummary(value: unknown): AssetEffectSummary {
  if (!isRecord(value)) throw new Error("素材效果响应无效");
  const effectCode = asString(value.effect_code);
  if (!effectCode) throw new Error("素材效果缺少编码");
  return {
    effectCode,
    revisionNumber: asNumber(value.revision_number),
    attributionReportCode: asString(value.attribution_report_code),
    metricKey: asString(value.metric_key),
    evidenceLevel: asString(value.evidence_level),
    status: asString(value.status),
    selectedSessionCount: Math.max(0, asNumber(value.selected_session_count)),
    automaticRecommendationMinimumSessionCount: Math.max(
      1,
      asNumber(value.automatic_recommendation_minimum_session_count, 3),
    ),
    automaticRecommendationEligible:
      value.automatic_recommendation_eligible === true,
    recommendationBlockers: strings(value.recommendation_blockers),
    note: asString(value.note),
    approvedAt: asOptionalString(value.approved_at),
    createdAt: asOptionalString(value.created_at),
  };
}

export const assetLibraryApi = {
  listAssets: () =>
    requestJson<unknown[]>(ROOT).then((rows) =>
      rows.flatMap((row) => asset(row) ?? []),
    ),
  createAsset: (payload: {
    title: string;
    original_filename: string;
    asset_type: string;
    media_kind?: string;
    material_roles: string[];
    execution_capability: ExecutionCapability;
  }) =>
    postJson<unknown>(ROOT, payload).then((value) => {
      const result = asset(value);
      if (!result) throw new Error("素材创建响应无效");
      return result;
    }),
  updateClassification: (
    assetCode: string,
    payload: {
      media_kind?: string;
      material_roles: string[];
      execution_capability: ExecutionCapability;
    },
  ) =>
    patchJson<unknown>(`${ROOT}/${assetCode}/classification`, payload).then(
      (value) => {
        const result = asset(value);
        if (!result) throw new Error("素材分类响应无效");
        return result;
      },
    ),
  updateClassifications: (payload: {
    asset_codes: string[];
    media_kind: string;
    material_roles: string[];
    execution_capability: ExecutionCapability;
  }) =>
    requestJson<unknown[]>(`${ROOT}/batch-classification`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }).then((rows) => rows.flatMap((row) => asset(row) ?? [])),
  listGroups: () =>
    requestJson<unknown[]>(`${ROOT}/groups`).then((rows) =>
      rows.flatMap((row) => group(row) ?? []),
    ),
  createGroup: (payload: {
    title: string;
    description?: string;
    asset_codes: string[];
  }) =>
    postJson<unknown>(`${ROOT}/groups`, payload).then((value) => {
      const result = group(value);
      if (!result) throw new Error("分组响应无效");
      return result;
    }),
  replaceGroupMembers: (groupCode: string, assetCodes: string[]) =>
    requestJson<unknown>(`${ROOT}/groups/${groupCode}/members`, {
      method: "PUT",
      body: JSON.stringify({ asset_codes: assetCodes }),
    }).then((value) => {
      const result = group(value);
      if (!result) throw new Error("分组成员响应无效");
      return result;
    }),
  listEffectSummaries: (assetCode: string) =>
    requestJson<unknown[]>(`${ROOT}/${assetCode}/effects`).then((rows) =>
      rows.map(assetEffectSummary),
    ),
  getConstraintProfile: (assetCode: string) =>
    requestJson<unknown>(`${ROOT}/${assetCode}/constraint-profile`).then(
      constraintProfileRevision,
    ),
  listConstraintProfileRevisions: (assetCode: string) =>
    requestJson<unknown[]>(
      `${ROOT}/${assetCode}/constraint-profile/revisions`,
    ).then((rows) => rows.map(constraintProfileRevision)),
  writeConstraintProfile: (assetCode: string, constraints: ConstraintRule[]) =>
    postJson<unknown>(`${ROOT}/${assetCode}/constraint-profile`, {
      constraints,
    }).then(constraintProfileRevision),
  promoteRoomConstraintOverride: (
    assetCode: string,
    payload: {
      plan_code: string;
      expected_revision: number;
      actor: string;
      reason: string;
    },
  ) =>
    postJson<unknown>(
      `${ROOT}/${assetCode}/constraint-profile/promote-room-override`,
      payload,
    ).then(constraintProfileRevision),
  previewSelection: (payload: {
    role: string;
    carrier_kind: "live_room" | "rendered_video";
  }) =>
    postJson<unknown>(`${ROOT}/selection-preview`, payload).then(
      selectionPreview,
    ),
  resolvePacks: (
    packCodes: string[],
    roleModes: Record<string, "inherit" | "append" | "replace"> = {},
  ) =>
    postJson<unknown>(`${ROOT}/material-packs/resolve`, {
      pack_codes: packCodes,
      role_modes: roleModes,
    }).then(packResolution),
  listPacks: () =>
    requestJson<unknown[]>(`${ROOT}/material-packs`).then((rows) =>
      rows.flatMap((row) => pack(row) ?? []),
    ),
  createPack: (payload: {
    title: string;
    pack_kind: "total" | "classification";
    role?: string;
    description?: string;
    entries: MaterialPack["entries"];
    exclusive_roles?: string[];
    pack_constraints?: Array<Record<string, unknown>>;
  }) =>
    postJson<unknown>(`${ROOT}/material-packs`, payload).then((value) => {
      const result = pack(value);
      if (!result) throw new Error("素材包响应无效");
      return result;
    }),
  publishPack: (packCode: string) =>
    postJson<unknown>(`${ROOT}/material-packs/${packCode}/publish`, {}).then(
      (value) => {
        const result = pack(value);
        if (!result) throw new Error("素材包发布响应无效");
        return result;
      },
    ),
  listPackRevisions: (packCode: string) =>
    requestJson<unknown[]>(`${ROOT}/material-packs/${packCode}/revisions`).then(
      (rows) => rows.flatMap((row) => packRevision(row) ?? []),
    ),
  createPackRevision: (
    packCode: string,
    payload: {
      expected_revision: number;
      entries: MaterialPack["entries"];
      exclusive_roles?: string[];
      pack_constraints?: Array<Record<string, unknown>>;
    },
  ) =>
    postJson<unknown>(
      `${ROOT}/material-packs/${packCode}/revisions`,
      payload,
    ).then((value) => {
      const result = pack(value);
      if (!result) throw new Error("素材包修订响应无效");
      return result;
    }),
  listGaps: () =>
    requestJson<unknown[]>(`${ROOT}/gaps`).then((rows) =>
      rows.flatMap((row) => gap(row) ?? []),
    ),
  createGap: (payload: {
    title: string;
    role: string;
    severity: string;
    gap_type?: string;
    specification?: Record<string, unknown>;
    source_context?: Record<string, unknown>;
    impact_summary?: string;
    alternative_asset_codes?: string[];
  }) =>
    postJson<unknown>(`${ROOT}/gaps`, payload).then((value) => {
      const result = gap(value);
      if (!result) throw new Error("素材缺口响应无效");
      return result;
    }),
  updateGap: (
    gapCode: string,
    payload: {
      status: string;
      resolution_asset_code?: string;
      actor?: string;
      resolution_evidence?: Record<string, unknown>;
    },
  ) =>
    patchJson<unknown>(`${ROOT}/gaps/${gapCode}`, payload).then((value) => {
      const result = gap(value);
      if (!result) throw new Error("素材缺口响应无效");
      return result;
    }),
};
