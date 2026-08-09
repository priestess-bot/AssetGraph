import {
  asArray,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  postJson,
  requestJson,
} from "../workbench/api";

const ROOT = "/api/functional-live-room-plans";

export interface FunctionalLiveRoomPlan {
  planCode: string;
  projectCode: string;
  variantCode: string;
  configurationCode: string;
  targetLiveRoomId: string;
  expectedTitle: string;
  layoutReferenceHandoff?: {
    templateCode: string;
    revision: number;
    projectionFingerprint: string;
  };
  primaryTemplateCode?: string;
  secondaryTemplateCodes: string[];
  selectedAssetCodes: string[];
  requiredLooseAssetCodes: string[];
  selectedGroupCodes: string[];
  selectedMaterialPackCodes: string[];
  selectedAssetGapCodes: string[];
  assetGapWaivers: Record<string, string>;
  materialRoleOverrides: Record<string, string>;
  materialRoleModes: Record<string, "inherit" | "append" | "replace">;
  materialSelectionDecisions: Array<{
    role: string;
    shotCode?: string;
    strategy: string;
    selectedAssetCode: string;
    selectedScore: number;
    selectedScoreParts: Record<string, number>;
    selectionReasons: string[];
    candidateScores: Array<{
      assetCode: string;
      score: number;
      scoreParts: Record<string, number>;
    }>;
  }>;
  materialSnapshot: {
    assetCodes: string[];
    assets: Array<{
      assetCode: string;
      mediaKind?: string;
      materialRoles: string[];
      executionCapability: string;
      rightsStatus: string;
      rightsNote?: string;
      constraintProfile?: {
        profileCode: string;
        revision: number;
        fingerprint: string;
      };
      selectionSources: Array<{ kind: string; code: string }>;
    }>;
    materialPackRefs: Array<{
      packCode: string;
      revisionNumber: number;
      fingerprint: string;
      role: string;
    }>;
    assetGapRefs: Array<{
      gapCode: string;
      title: string;
      role: string;
      severity: string;
      status: string;
      sourceStatus: string;
      gapType: string;
      branchWaiverReason?: string;
      fingerprint: string;
    }>;
    roomConstraintOverrides: Record<string, RoomConstraintOverride>;
  };
  blueprint: {
    schema_version: string;
    scenes: Array<{
      scene_code: string;
      shot_code: string;
      title: string;
      layers: Array<{
        role: string;
        asset_code: string;
        execution_capability: string;
        normalized_geometry: {
          x: number;
          y: number;
          width: number;
          height: number;
        };
        z_order: number;
        system_managed: boolean;
        system_host_binding_fingerprint?: string;
      }>;
      script: string;
    }>;
  };
  buildPlan: {
    schema_version: string;
    build_plan_code?: string;
    target_live_room_id: string;
    go_live: boolean;
    operations: FunctionalLiveRoomBuildOperation[];
  };
  gateResults: Array<{
    gate: string;
    status: string;
    ruleCode: string;
    remediation?: string;
  }>;
  qualityReport: Record<string, unknown>;
  status: string;
  blockedReasons: string[];
  executionStatus: string;
  executionEvidence: Record<string, unknown>;
  executionJobCode?: string;
  roomInspectionCode?: string;
  executionMode?: string;
  executionAuthorityMode?: string;
  clonedFromPlanCode?: string;
  cloneContext: Record<string, unknown>;
  revisedFromPlanCode?: string;
  revisionContext: Record<string, unknown>;
  releaseCode?: string;
  releaseSnapshotArtifactCode?: string;
  releaseManifestFingerprint?: string;
  release?: {
    releaseCode: string;
    status: string;
    manifestCode: string;
    manifestFingerprint: string;
    snapshotArtifactCode: string;
  };
  updatedAt: string;
}

export interface FunctionalLiveRoomExecutionHandoff {
  planCode: string;
  buildPlanCode: string;
  targetLiveRoomId: string;
  expectedTitle: string;
  checkpointContract: string;
  sourcePlanFingerprint: string;
  operationCount: number;
  operationTypes: string[];
  operations: FunctionalLiveRoomBuildOperation[];
}

export interface FunctionalLiveRoomBuildOperation {
  kind: string;
  operationName: string;
  status: string;
  instruction: string;
  targetLiveRoomId?: string;
  expectedLiveRoomTitle?: string;
  sceneCode?: string;
  sceneIndex?: number;
  layerId?: string;
  layerType?: string;
  assetCode?: string;
  assetDisplayCode?: string;
  assetOriginalFilename?: string;
  assetLocalRelativePath?: string;
  materialId?: number;
  maituSourceMaterialId?: number;
  sourceMaterialType?: string;
  speakerId?: number;
  digitalHumanImageId?: number;
  role?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  zIndex?: number;
  scriptBlockCode?: string;
  scriptText?: string;
  raw: Record<string, unknown>;
}

export type MaituCapabilityStatus =
  | "verified"
  | "manual_only"
  | "unsupported";

export interface MaituCapabilityMatrix {
  schemaVersion: "maitu-capability-matrix.v1";
  adapterContract: string;
  contractFingerprint: string;
  source: string;
  canExecuteDraft: boolean;
  manualHandoffAvailable: boolean;
  unverifiedRequiredCapabilities: string[];
  capabilities: Array<{
    key: string;
    title: string;
    status: MaituCapabilityStatus;
    requiredForDraft: boolean;
    lastVerifiedAt?: string;
    evidenceLevel: string;
    evidenceRefs: string[];
    customerMessage: string;
  }>;
}

export const conservativeMaituCapabilityFallback: MaituCapabilityMatrix = {
  schemaVersion: "maitu-capability-matrix.v1",
  adapterContract: "unavailable",
  contractFingerprint: "",
  source: "client_fail_closed",
  canExecuteDraft: false,
  manualHandoffAvailable: true,
  unverifiedRequiredCapabilities: ["capability_matrix_unavailable"],
  capabilities: [],
};

export interface RoomConstraintOverride {
  reason: string;
  geometry?: { x: number; y: number; width: number; height: number };
  zOrder?: number;
  actorId?: string;
}

export interface FunctionalLiveRoomPlanInput {
  idempotency_key?: string;
  project_code: string;
  target_live_room_id: string;
  expected_title: string;
  layout_reference_handoff?: {
    template_code: string;
    revision: number;
    projection_fingerprint: string;
  };
  primary_template_code?: string;
  secondary_template_codes: string[];
  asset_codes: string[];
  required_loose_asset_codes?: string[];
  group_codes: string[];
  material_pack_codes: string[];
  asset_gap_codes: string[];
  asset_gap_waivers?: Record<string, string>;
  material_role_overrides: Record<string, string>;
  material_role_modes?: Record<string, "inherit" | "append" | "replace">;
  room_constraint_overrides: Record<string, RoomConstraintOverride>;
}

export interface FunctionalLiveRoomBlueprintRevisionInput {
  idempotency_key?: string;
  scenes: Array<{
    shot_code: string;
    sort_order: number;
    title: string;
    script: string;
    layers: Array<{
      role: string;
      asset_code: string;
      geometry: { x: number; y: number; width: number; height: number };
      z_order: number;
    }>;
  }>;
}

export interface LiveRoomInspectionScene {
  sceneId: string;
  name: string;
  orderNumber: number;
  materialCount: number;
}

export interface LiveRoomInspection {
  inspectionCode: string;
  targetLiveRoomId: string;
  expectedTitle?: string;
  authorityMode: string;
  status: string;
  attempt: number;
  roomFingerprint?: string;
  result?: {
    actualTitle: string;
    isLive: boolean;
    hasLiveTrace: boolean;
    readEnvironment: string;
    sceneCount: number;
    scenes: LiveRoomInspectionScene[];
    capturedAt?: string;
    readyForGoLive: false;
    goLiveClicked: false;
  };
  errorMessage?: string;
  startedAt?: string;
  completedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface LiveRoomDraftExecution {
  executionJobCode: string;
  planCode?: string;
  sourceKind: string;
  status: string;
  stage: string;
  progressCurrent: number;
  progressTotal: number;
  stageEvents: Array<{
    stage: string;
    status: string;
    message?: string;
    progressCurrent?: number;
    progressTotal?: number;
    occurredAt?: string;
  }>;
  result: Record<string, unknown>;
  error?: {
    code?: string;
    message?: string;
    customerMessage?: string;
    nextStep?: string;
  };
  retryable: boolean;
  updatedAt?: string;
}

export interface ConfirmLiveRoomExecutionInput {
  draftMode: "replace_test_draft";
  roomInspectionCode: string;
  expectedRoomFingerprint: string;
  confirmedSceneIds: string[];
  idempotencyKey: string;
  testUseAcknowledged: true;
}

export interface FunctionalLiveRoomMaterialGapPreview {
  projectCode: string;
  projectRevisionNumber: number;
  shotListRevisionNumber: number;
  checkedAssetCodes: string[];
  gaps: Array<{
    diagnosticKey: string;
    role: string;
    title: string;
    severity: string;
    gapType: string;
    requiredShotCodes: string[];
    missingOccurrences: number;
    selectionMode: string;
    alternativeAssetCodes: string[];
    createPayload: {
      title: string;
      role: string;
      severity: string;
      gap_type: string;
      specification: Record<string, unknown>;
      source_context: Record<string, unknown>;
      impact_summary: string;
      alternative_asset_codes: string[];
    };
  }>;
}

export interface FunctionalLiveRoomTrace {
  planCode: string;
  contentChain: Record<string, unknown>;
  operations: Array<{
    operationId: string;
    operationType: string;
    operationName: string;
    sortOrder: number;
    targets: Array<{
      targetType: string;
      targetCode: string;
      relationType: string;
      shot?: { shotCode: string; shotGoal: string };
      programSegment?: { segmentCode: string; semanticGoal: string };
      scriptBlocks: Array<{ blockCode: string }>;
    }>;
  }>;
}

function strings(value: unknown): string[] {
  return asArray(value).flatMap((item) =>
    typeof item === "string" ? [item] : [],
  );
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function buildOperations(value: unknown): FunctionalLiveRoomBuildOperation[] {
  return asArray(value).flatMap((operation) => {
    if (!isRecord(operation)) return [];
    const kind = asString(
      operation.operation_type,
      asString(operation.kind),
    );
    if (!kind) return [];
    return [
      {
        kind,
        operationName: asString(operation.operation_name, kind),
        status: asString(operation.status, "planned"),
        instruction: asString(operation.instruction),
        targetLiveRoomId: asOptionalString(operation.target_live_room_id),
        expectedLiveRoomTitle: asOptionalString(
          operation.expected_live_room_title,
        ),
        sceneCode:
          asOptionalString(operation.scene_code) ??
          asOptionalString(operation.scene_name),
        sceneIndex: optionalNumber(operation.scene_index),
        layerId:
          asOptionalString(operation.layer_id) ??
          asOptionalString(operation.layer_name),
        layerType:
          asOptionalString(operation.layer_type) ??
          asOptionalString(operation.layer_role),
        assetCode:
          asOptionalString(operation.asset_code) ??
          asOptionalString(operation.selected_asset_code),
        assetDisplayCode:
          asOptionalString(operation.asset_display_code) ??
          asOptionalString(operation.selected_asset_display_code),
        assetOriginalFilename:
          asOptionalString(operation.asset_original_filename) ??
          asOptionalString(operation.selected_asset_original_filename),
        assetLocalRelativePath:
          asOptionalString(operation.asset_local_relative_path) ??
          asOptionalString(operation.selected_asset_local_relative_path),
        materialId:
          optionalNumber(operation.material_id) ??
          optionalNumber(operation.maitu_material_id),
        maituSourceMaterialId: optionalNumber(
          operation.maitu_source_material_id,
        ),
        sourceMaterialType: asOptionalString(operation.source_material_type),
        speakerId: optionalNumber(operation.speaker_id),
        digitalHumanImageId: optionalNumber(
          operation.digital_human_image_id,
        ),
        role:
          asOptionalString(operation.role) ??
          asOptionalString(operation.layer_type) ??
          asOptionalString(operation.layer_role),
        x: optionalNumber(operation.x),
        y: optionalNumber(operation.y),
        width: optionalNumber(operation.width),
        height: optionalNumber(operation.height),
        zIndex: optionalNumber(operation.z_index),
        scriptBlockCode: asOptionalString(operation.script_block_code),
        scriptText:
          asOptionalString(operation.script_text) ??
          asOptionalString(operation.script_block_content),
        raw: { ...operation },
      },
    ];
  });
}

function roomConstraintOverrides(
  value: unknown,
): Record<string, RoomConstraintOverride> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).flatMap(([assetCode, override]) => {
      if (!isRecord(override) || !asString(override.reason)) return [];
      const rawGeometry = isRecord(override.geometry)
        ? override.geometry
        : undefined;
      const geometry =
        rawGeometry &&
        ["x", "y", "width", "height"].every(
          (key) => typeof rawGeometry[key] === "number",
        )
          ? {
              x: asNumber(rawGeometry.x),
              y: asNumber(rawGeometry.y),
              width: asNumber(rawGeometry.width),
              height: asNumber(rawGeometry.height),
            }
          : undefined;
      return [
        [
          assetCode,
          {
            reason: asString(override.reason),
            geometry,
            zOrder:
              typeof override.z_order === "number"
                ? override.z_order
                : undefined,
            actorId: asOptionalString(override.actor_id),
          },
        ],
      ];
    }),
  );
}

function defaultLayerGeometry(role: string) {
  const defaults: Record<
    string,
    { x: number; y: number; width: number; height: number }
  > = {
    background: { x: 0, y: 0, width: 1, height: 1 },
    digital_human: { x: 0.08, y: 0.18, width: 0.36, height: 0.64 },
    product_display: { x: 0.52, y: 0.28, width: 0.4, height: 0.4 },
    product_image: { x: 0.52, y: 0.28, width: 0.4, height: 0.4 },
    promotion_text: { x: 0.08, y: 0.78, width: 0.84, height: 0.14 },
  };
  return { ...(defaults[role] ?? { x: 0.1, y: 0.1, width: 0.3, height: 0.3 }) };
}

function layerGeometry(value: unknown, role: string) {
  if (!isRecord(value)) return defaultLayerGeometry(role);
  const values = [value.x, value.y, value.width, value.height];
  if (!values.every((item) => typeof item === "number" && Number.isFinite(item))) {
    return defaultLayerGeometry(role);
  }
  return {
    x: asNumber(value.x),
    y: asNumber(value.y),
    width: asNumber(value.width),
    height: asNumber(value.height),
  };
}

function plan(value: unknown): FunctionalLiveRoomPlan {
  if (!isRecord(value)) throw new Error("直播间计划响应无效");
  const planCode = asString(value.plan_code);
  if (!planCode) throw new Error("直播间计划缺少编码");
  const blueprint = isRecord(value.blueprint) ? value.blueprint : {};
  const buildPlan = isRecord(value.build_plan) ? value.build_plan : {};
  const inventorySnapshot = isRecord(buildPlan.inventory_snapshot)
    ? buildPlan.inventory_snapshot
    : {};
  const qualityReport = isRecord(value.quality_report)
    ? value.quality_report
    : {};
  const materialRoleOverrides = isRecord(qualityReport.material_role_overrides)
    ? Object.fromEntries(
        Object.entries(qualityReport.material_role_overrides).flatMap(
          ([role, assetCode]) =>
            typeof assetCode === "string" && assetCode
              ? [[role, assetCode]]
              : [],
        ),
      )
    : {};
  const materialRoleModes = isRecord(qualityReport.material_role_modes)
    ? Object.fromEntries(
        Object.entries(qualityReport.material_role_modes).flatMap(
          ([role, mode]) =>
            typeof mode === "string" &&
            ["inherit", "append", "replace"].includes(mode)
              ? [[role, mode as "inherit" | "append" | "replace"]]
              : [],
        ),
      )
    : {};
  const numericScoreParts = (value: unknown): Record<string, number> =>
    isRecord(value)
      ? Object.fromEntries(
          Object.entries(value).flatMap(([key, score]) =>
            typeof score === "number" && Number.isFinite(score)
              ? [[key, score]]
              : [],
          ),
        )
      : {};
  const materialSelectionDecisions = asArray(
    qualityReport.material_selection_decisions,
  ).flatMap((decision) =>
    isRecord(decision) &&
    asString(decision.role) &&
    asString(decision.selected_asset_code)
      ? [
          {
            role: asString(decision.role),
            shotCode: asOptionalString(decision.shot_code),
            strategy: asString(decision.strategy),
            selectedAssetCode: asString(decision.selected_asset_code),
            selectedScore: asNumber(decision.selected_score),
            selectedScoreParts: numericScoreParts(
              decision.selected_score_parts,
            ),
            selectionReasons: strings(decision.selection_reasons),
            candidateScores: asArray(decision.candidate_scores).flatMap(
              (candidate) =>
                isRecord(candidate) && asString(candidate.asset_code)
                  ? [
                      {
                        assetCode: asString(candidate.asset_code),
                        score: asNumber(candidate.score),
                        scoreParts: numericScoreParts(candidate.score_parts),
                      },
                    ]
                  : [],
            ),
          },
        ]
      : [],
  );
  return {
    planCode,
    projectCode: asString(value.project_code),
    variantCode: asString(value.variant_code),
    configurationCode: asString(value.configuration_code),
    targetLiveRoomId: asString(value.target_live_room_id),
    expectedTitle: asString(value.expected_title),
    layoutReferenceHandoff:
      isRecord(inventorySnapshot.layout_reference_handoff) &&
      asString(inventorySnapshot.layout_reference_handoff.template_code) &&
      typeof inventorySnapshot.layout_reference_handoff.revision === "number" &&
      asString(inventorySnapshot.layout_reference_handoff.projection_fingerprint)
        ? {
            templateCode: asString(
              inventorySnapshot.layout_reference_handoff.template_code,
            ),
            revision: asNumber(
              inventorySnapshot.layout_reference_handoff.revision,
            ),
            projectionFingerprint: asString(
              inventorySnapshot.layout_reference_handoff
                .projection_fingerprint,
            ),
          }
        : undefined,
    primaryTemplateCode: asOptionalString(value.primary_template_code),
    secondaryTemplateCodes: strings(value.secondary_template_codes),
    selectedAssetCodes: strings(value.selected_asset_codes),
    requiredLooseAssetCodes: strings(
      inventorySnapshot.required_loose_asset_codes,
    ),
    selectedGroupCodes: strings(value.selected_group_codes),
    selectedMaterialPackCodes: strings(value.selected_material_pack_codes),
    selectedAssetGapCodes: strings(value.selected_asset_gap_codes),
    assetGapWaivers: isRecord(inventorySnapshot.asset_gap_waivers)
      ? Object.fromEntries(
          Object.entries(inventorySnapshot.asset_gap_waivers).flatMap(
            ([gapCode, reason]) =>
              typeof reason === "string" && reason ? [[gapCode, reason]] : [],
          ),
        )
      : {},
    materialRoleOverrides,
    materialRoleModes,
    materialSelectionDecisions,
    materialSnapshot: {
      assetCodes: strings(inventorySnapshot.asset_codes),
      assets: asArray(inventorySnapshot.assets).flatMap((asset) =>
        isRecord(asset) && asString(asset.asset_code)
          ? [
              {
                assetCode: asString(asset.asset_code),
                mediaKind: asOptionalString(asset.media_kind),
                materialRoles: strings(asset.material_roles),
                executionCapability: asString(asset.execution_capability),
                rightsStatus: asString(asset.rights_status, "pending"),
                rightsNote: asOptionalString(asset.rights_note),
                constraintProfile:
                  isRecord(asset.constraint_profile_ref) &&
                  asString(asset.constraint_profile_ref.profile_code)
                    ? {
                        profileCode: asString(
                          asset.constraint_profile_ref.profile_code,
                        ),
                        revision: asNumber(
                          asset.constraint_profile_ref.revision,
                        ),
                        fingerprint: asString(
                          asset.constraint_profile_ref.fingerprint,
                        ),
                      }
                    : undefined,
                selectionSources: asArray(asset.selection_sources).flatMap(
                  (source) =>
                    isRecord(source) &&
                    asString(source.kind) &&
                    asString(source.code)
                      ? [
                          {
                            kind: asString(source.kind),
                            code: asString(source.code),
                          },
                        ]
                      : [],
                ),
              },
            ]
          : [],
      ),
      materialPackRefs: asArray(inventorySnapshot.material_pack_refs).flatMap(
        (pack) =>
          isRecord(pack) && asString(pack.pack_code)
            ? [
                {
                  packCode: asString(pack.pack_code),
                  revisionNumber: asNumber(pack.revision_number),
                  fingerprint: asString(pack.fingerprint_sha256),
                  role: asString(pack.role),
                },
              ]
            : [],
      ),
      assetGapRefs: asArray(inventorySnapshot.asset_gap_refs).flatMap((gap) =>
        isRecord(gap) && asString(gap.gap_code)
          ? [
              {
                gapCode: asString(gap.gap_code),
                title: asString(gap.title, asString(gap.gap_code)),
                role: asString(gap.role),
                severity: asString(gap.severity),
                status: asString(gap.status),
                sourceStatus: asString(gap.source_status, asString(gap.status)),
                gapType: asString(gap.gap_type),
                branchWaiverReason: isRecord(gap.branch_waiver)
                  ? asOptionalString(gap.branch_waiver.reason)
                  : undefined,
                fingerprint: asString(gap.fingerprint_sha256),
              },
            ]
          : [],
      ),
      roomConstraintOverrides: roomConstraintOverrides(
        inventorySnapshot.room_constraint_overrides,
      ),
    },
    blueprint: {
      schema_version: asString(blueprint.schema_version),
      scenes: asArray(blueprint.scenes).flatMap((scene) =>
        isRecord(scene)
          ? [
              {
                scene_code: asString(scene.scene_code),
                shot_code: asString(scene.shot_code),
                title: asString(scene.title),
                script: asString(scene.script),
                layers: asArray(scene.layers).flatMap((layer) =>
                  isRecord(layer)
                    ? (() => {
                      const role = asString(
                          layer.role,
                          asString(layer.material_role),
                        );
                        const constraintEvidence = isRecord(
                          layer.constraint_evidence,
                        )
                          ? layer.constraint_evidence
                          : {};
                        return [
                          {
                            role,
                          asset_code: asString(layer.asset_code),
                          execution_capability: asString(
                            layer.execution_capability,
                            isRecord(layer.asset_binding_ref)
                              ? asString(
                                  layer.asset_binding_ref.execution_capability,
                                )
                              : "",
                          ),
                          normalized_geometry: layerGeometry(
                            layer.normalized_geometry,
                            role,
                          ),
                          z_order:
                            typeof layer.z_order === "number"
                              ? layer.z_order
                              : 0,
                          system_managed:
                            layer.system_managed === true
                            || constraintEvidence.system_managed === true,
                          system_host_binding_fingerprint: asOptionalString(
                            layer.system_host_binding_fingerprint
                            ?? constraintEvidence.system_host_binding_fingerprint,
                          ),
                          },
                        ];
                      })()
                    : [],
                ),
              },
            ]
          : [],
      ),
    },
    buildPlan: {
      schema_version: asString(buildPlan.schema_version),
      build_plan_code: asOptionalString(buildPlan.build_plan_code),
      target_live_room_id: asString(buildPlan.target_live_room_id),
      go_live: buildPlan.go_live === true,
      operations: buildOperations(buildPlan.operations),
    },
    gateResults: asArray(value.gate_results).flatMap((gate) =>
      isRecord(gate) && asString(gate.gate)
        ? [
            {
              gate: asString(gate.gate),
              status: asString(gate.status),
              ruleCode: asString(gate.rule_code),
              remediation: asOptionalString(gate.remediation),
            },
          ]
        : [],
    ),
    qualityReport,
    status: asString(value.status),
    blockedReasons: strings(value.blocked_reasons),
    executionStatus: asString(value.execution_status),
    executionEvidence: isRecord(value.execution_evidence)
      ? value.execution_evidence
      : {},
    executionJobCode: asOptionalString(value.execution_job_code),
    roomInspectionCode: asOptionalString(value.room_inspection_code),
    executionMode: asOptionalString(value.execution_mode),
    executionAuthorityMode: asOptionalString(value.execution_authority_mode),
    clonedFromPlanCode: asOptionalString(value.cloned_from_plan_code),
    cloneContext: isRecord(value.clone_context) ? value.clone_context : {},
    revisedFromPlanCode: asOptionalString(value.revised_from_plan_code),
    revisionContext: isRecord(value.revision_context)
      ? value.revision_context
      : {},
    releaseCode: asOptionalString(value.release_code),
    releaseSnapshotArtifactCode: asOptionalString(
      value.release_snapshot_artifact_code,
    ),
    releaseManifestFingerprint: asOptionalString(
      value.release_manifest_fingerprint,
    ),
    release:
      isRecord(value.release) && asString(value.release.release_code)
        ? {
            releaseCode: asString(value.release.release_code),
            status: asString(value.release.status),
            manifestCode: asString(value.release.manifest_code),
            manifestFingerprint: asString(value.release.manifest_fingerprint),
            snapshotArtifactCode: asString(
              value.release.snapshot_artifact_code,
            ),
          }
        : undefined,
    updatedAt: asString(value.updated_at),
  };
}

function roomInspection(value: unknown): LiveRoomInspection {
  if (!isRecord(value)) throw new Error("直播间检查响应无效");
  const inspectionCode = asString(value.inspection_code);
  const targetLiveRoomId = asString(value.target_live_room_id);
  if (!inspectionCode || !targetLiveRoomId) throw new Error("直播间检查缺少必要信息");
  const rawResult = isRecord(value.result) ? value.result : undefined;
  return {
    inspectionCode,
    targetLiveRoomId,
    expectedTitle: asOptionalString(value.expected_title),
    authorityMode: asString(value.authority_mode, "worker_readback"),
    status: asString(value.status, "queued"),
    attempt: asNumber(value.attempt),
    roomFingerprint: asOptionalString(value.room_fingerprint),
    result: rawResult ? {
      actualTitle: asString(rawResult.actual_title),
      isLive: rawResult.is_live === true,
      hasLiveTrace: rawResult.has_live_trace === true,
      readEnvironment: asString(rawResult.read_environment),
      sceneCount: asNumber(rawResult.scene_count),
      scenes: asArray(rawResult.scenes).flatMap((scene, index) => isRecord(scene) && asString(scene.scene_id) ? [{
        sceneId: asString(scene.scene_id),
        name: asString(scene.name, `场景 ${index + 1}`),
        orderNumber: asNumber(scene.order_num, index + 1),
        materialCount: asNumber(scene.material_count),
      }] : []),
      capturedAt: asOptionalString(rawResult.captured_at),
      readyForGoLive: false,
      goLiveClicked: false,
    } : undefined,
    errorMessage: asOptionalString(value.error_message),
    startedAt: asOptionalString(value.started_at),
    completedAt: asOptionalString(value.completed_at),
    createdAt: asOptionalString(value.created_at),
    updatedAt: asOptionalString(value.updated_at),
  };
}

function draftExecution(value: unknown): LiveRoomDraftExecution {
  if (!isRecord(value)) throw new Error("草稿执行响应无效");
  const error = isRecord(value.error) ? value.error : undefined;
  const executionJobCode = asString(value.execution_job_code, asString(value.job_code));
  if (!executionJobCode) throw new Error("草稿执行缺少任务信息");
  const progress = isRecord(value.progress) ? value.progress : {};
  return {
    executionJobCode,
    planCode: asOptionalString(value.plan_code),
    sourceKind: asString(value.source_kind, "functional_live_room_plan"),
    status: asString(value.status, "queued"),
    stage: asString(value.stage, asString(value.status, "queued")),
    progressCurrent: asNumber(value.progress_current, asNumber(progress.current)),
    progressTotal: asNumber(value.progress_total, asNumber(progress.total)),
    stageEvents: asArray(value.stage_events).flatMap((event) => isRecord(event) && asString(event.stage) ? [{
      stage: asString(event.stage),
      status: asString(event.status),
      message: asOptionalString(event.customer_message) ?? asOptionalString(event.message),
      progressCurrent: typeof event.progress_current === "number" ? event.progress_current : undefined,
      progressTotal: typeof event.progress_total === "number" ? event.progress_total : undefined,
      occurredAt: asOptionalString(event.occurred_at) ?? asOptionalString(event.created_at),
    }] : []),
    result: isRecord(value.result) ? value.result : {},
    error: error ? {
      code: asOptionalString(error.code),
      message: asOptionalString(error.message),
      customerMessage: asOptionalString(error.customer_message),
      nextStep: asOptionalString(error.next_step),
    } : undefined,
    retryable: value.retryable === true || asString(value.status) === "failed",
    updatedAt: asOptionalString(value.updated_at),
  };
}

function executionHandoff(value: unknown): FunctionalLiveRoomExecutionHandoff {
  if (!isRecord(value)) throw new Error("麦兔 Worker 交接响应无效");
  const planCode = asString(value.plan_code);
  const buildPlanCode = asString(value.build_plan_code);
  const sourcePlanFingerprint = asString(value.source_plan_fingerprint);
  if (!planCode || !buildPlanCode || !sourcePlanFingerprint) {
    throw new Error("麦兔 Worker 交接缺少固定计划信息");
  }
  return {
    planCode,
    buildPlanCode,
    targetLiveRoomId: asString(value.target_live_room_id),
    expectedTitle: asString(value.expected_title),
    checkpointContract: asString(value.checkpoint_contract),
    sourcePlanFingerprint,
    operationCount: asNumber(value.operation_count),
    operationTypes: strings(value.operation_types),
    operations: buildOperations(value.operations),
  };
}

function materialGapPreview(value: unknown): FunctionalLiveRoomMaterialGapPreview {
  if (!isRecord(value)) throw new Error("直播间素材缺口诊断响应无效");
  return {
    projectCode: asString(value.project_code),
    projectRevisionNumber: asNumber(value.project_revision_number),
    shotListRevisionNumber: asNumber(value.shot_list_revision_number),
    checkedAssetCodes: strings(value.checked_asset_codes),
    gaps: asArray(value.gaps).flatMap((item) => {
      if (!isRecord(item)) return [];
      const diagnosticKey = asString(item.diagnostic_key);
      const role = asString(item.role);
      const createPayload = item.create_payload;
      if (!diagnosticKey || !role || !isRecord(createPayload)) return [];
      return [
        {
          diagnosticKey,
          role,
          title: asString(item.title, `缺少可执行 ${role} 素材`),
          severity: asString(item.severity, "high"),
          gapType: asString(item.gap_type, "role_coverage"),
          requiredShotCodes: strings(item.required_shot_codes),
          missingOccurrences: asNumber(item.missing_occurrences),
          selectionMode: asString(item.selection_mode, "append"),
          alternativeAssetCodes: strings(item.alternative_asset_codes),
          createPayload: {
            title: asString(createPayload.title),
            role: asString(createPayload.role),
            severity: asString(createPayload.severity, "high"),
            gap_type: asString(createPayload.gap_type, "role_coverage"),
            specification: isRecord(createPayload.specification)
              ? createPayload.specification
              : {},
            source_context: isRecord(createPayload.source_context)
              ? createPayload.source_context
              : {},
            impact_summary: asString(createPayload.impact_summary),
            alternative_asset_codes: strings(createPayload.alternative_asset_codes),
          },
        },
      ];
    }),
  };
}

function maituCapabilityMatrix(value: unknown): MaituCapabilityMatrix {
  if (!isRecord(value)) throw new Error("麦兔能力响应无效");
  if (value.schema_version !== "maitu-capability-matrix.v1") {
    throw new Error("麦兔能力契约版本不受支持");
  }
  const contractFingerprint = asString(value.contract_fingerprint);
  if (!/^[0-9a-f]{64}$/.test(contractFingerprint)) {
    throw new Error("麦兔能力契约缺少有效指纹");
  }
  return {
    schemaVersion: value.schema_version,
    adapterContract: asString(value.adapter_contract),
    contractFingerprint,
    source: asString(value.source),
    canExecuteDraft: value.can_execute_draft === true,
    manualHandoffAvailable: value.manual_handoff_available === true,
    unverifiedRequiredCapabilities: strings(
      value.unverified_required_capabilities,
    ),
    capabilities: asArray(value.capabilities).flatMap((item) => {
      if (!isRecord(item)) return [];
      const key = asString(item.key);
      const title = asString(item.title);
      const status = asString(item.status);
      if (
        !key ||
        !title ||
        !["verified", "manual_only", "unsupported"].includes(status)
      )
        return [];
      return [
        {
          key,
          title,
          status: status as MaituCapabilityStatus,
          requiredForDraft: item.required_for_draft === true,
          lastVerifiedAt: asOptionalString(item.last_verified_at),
          evidenceLevel: asString(item.evidence_level),
          evidenceRefs: strings(item.evidence_refs),
          customerMessage: asString(item.customer_message),
        },
      ];
    }),
  };
}

function trace(value: unknown): FunctionalLiveRoomTrace {
  if (!isRecord(value)) throw new Error("直播间追溯响应无效");
  return {
    planCode: asString(value.plan_code),
    contentChain: isRecord(value.content_chain) ? value.content_chain : {},
    operations: asArray(value.operations).flatMap((operation) =>
      isRecord(operation)
        ? [
            {
              operationId: asString(operation.operation_id),
              operationType: asString(operation.operation_type),
              operationName: asString(operation.operation_name),
              sortOrder:
                typeof operation.sort_order === "number"
                  ? operation.sort_order
                  : 0,
              targets: asArray(operation.targets).flatMap((target) =>
                isRecord(target)
                  ? [
                      {
                        targetType: asString(target.target_type),
                        targetCode: asString(target.target_code),
                        relationType: asString(target.relation_type),
                        shot: isRecord(target.shot)
                          ? {
                              shotCode: asString(target.shot.shot_code),
                              shotGoal: asString(target.shot.shot_goal),
                            }
                          : undefined,
                        programSegment: isRecord(target.program_segment)
                          ? {
                              segmentCode: asString(
                                target.program_segment.segment_code,
                              ),
                              semanticGoal: asString(
                                target.program_segment.semantic_goal,
                              ),
                            }
                          : undefined,
                        scriptBlocks: asArray(target.script_blocks).flatMap(
                          (block) =>
                            isRecord(block) && asString(block.block_code)
                              ? [{ blockCode: asString(block.block_code) }]
                              : [],
                        ),
                      },
                    ]
                  : [],
              ),
            },
          ]
        : [],
    ),
  };
}

export const functionalLiveRoomsApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(plan)),
  maituCapabilities: () =>
    requestJson<unknown>(`${ROOT}/maitu-capabilities`).then(
      maituCapabilityMatrix,
    ),
  get: (planCode: string) =>
    requestJson<unknown>(`${ROOT}/${planCode}`).then(plan),
  getTrace: (planCode: string) =>
    requestJson<unknown>(`${ROOT}/${planCode}/trace`).then(trace),
  create: (payload: FunctionalLiveRoomPlanInput) =>
    postJson<unknown>(ROOT, {
      ...payload,
      required_loose_asset_codes: payload.required_loose_asset_codes ?? [],
      material_role_modes: payload.material_role_modes ?? {},
      room_constraint_overrides: Object.fromEntries(
        Object.entries(payload.room_constraint_overrides).map(
          ([assetCode, override]) => [
            assetCode,
            {
              reason: override.reason,
              geometry: override.geometry,
              z_order: override.zOrder,
            },
          ],
        ),
      ),
    }).then(plan),
  previewMaterialGaps: (payload: Pick<
    FunctionalLiveRoomPlanInput,
    "project_code" | "asset_codes" | "group_codes" | "material_pack_codes" | "material_role_modes"
  >) =>
    postJson<unknown>(`${ROOT}/material-gap-preview`, {
      ...payload,
      material_role_modes: payload.material_role_modes ?? {},
    }).then(materialGapPreview),
  createRoomInspection: (payload: { targetLiveRoomId: string; expectedTitle?: string; idempotencyKey: string }) =>
    postJson<unknown>(`${ROOT}/room-inspections`, {
      target_live_room_id: payload.targetLiveRoomId,
      expected_title: payload.expectedTitle || undefined,
      idempotency_key: payload.idempotencyKey,
      authority_mode: "worker_readback",
    }).then(roomInspection),
  getRoomInspection: (inspectionCode: string) =>
    requestJson<unknown>(`${ROOT}/room-inspections/${encodeURIComponent(inspectionCode)}`).then(roomInspection),
  confirmExecution: (planCode: string, input?: ConfirmLiveRoomExecutionInput) =>
    postJson<unknown>(`${ROOT}/${planCode}/confirm-execution`, {
      confirmed: true,
      ...(input ? {
        draft_mode: input.draftMode,
        room_inspection_code: input.roomInspectionCode,
        expected_room_fingerprint: input.expectedRoomFingerprint,
        confirmed_scene_ids: input.confirmedSceneIds,
        idempotency_key: input.idempotencyKey,
        test_use_acknowledged: input.testUseAcknowledged,
      } : {}),
    }).then(plan),
  getExecution: (planCode: string) =>
    requestJson<unknown>(`${ROOT}/${planCode}/execution`).then(draftExecution),
  retryExecution: (planCode: string) =>
    postJson<unknown>(`${ROOT}/${planCode}/execution/retry`, {}).then(draftExecution),
  reconcileExecution: (planCode: string) =>
    postJson<unknown>(`${ROOT}/${planCode}/execution/reconcile`, {
      acknowledged_by: "live-room-product-operator",
      note: "从直播间配置页确认重新读取麦兔现场并继续对账。",
    }).then(draftExecution),
  executionHandoff: (planCode: string) =>
    requestJson<unknown>(`${ROOT}/${planCode}/execution-handoff`).then(
      executionHandoff,
    ),
  syncExecution: (planCode: string) =>
    postJson<unknown>(`${ROOT}/${planCode}/sync-execution`, {}).then(plan),
  createReleaseCandidate: (planCode: string) =>
    postJson<unknown>(`${ROOT}/${planCode}/release-candidate`, {}).then(plan),
  clone: (
    planCode: string,
    payload: { target_live_room_id: string; expected_title: string },
  ) => postJson<unknown>(`${ROOT}/${planCode}/clone`, payload).then(plan),
  reviseBlueprint: (
    planCode: string,
    payload: FunctionalLiveRoomBlueprintRevisionInput,
  ) =>
    postJson<unknown>(
      `${ROOT}/${planCode}/blueprint-revisions`,
      payload,
    ).then(plan),
};
