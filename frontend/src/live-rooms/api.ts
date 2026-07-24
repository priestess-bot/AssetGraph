import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

const ROOT = "/api/functional-live-room-plans";

export interface FunctionalLiveRoomPlan {
  planCode: string;
  projectCode: string;
  variantCode: string;
  configurationCode: string;
  targetLiveRoomId: string;
  expectedTitle: string;
  primaryTemplateCode?: string;
  secondaryTemplateCodes: string[];
  selectedAssetCodes: string[];
  selectedGroupCodes: string[];
  selectedMaterialPackCodes: string[];
  materialRoleOverrides: Record<string, string>;
  materialSelectionDecisions: Array<{ role: string; shotCode?: string; strategy: string; selectedAssetCode: string; selectedScore: number; selectionReasons: string[]; candidateScores: Array<{ assetCode: string; score: number }> }>;
  materialSnapshot: {
    assetCodes: string[];
    assets: Array<{
      assetCode: string;
      mediaKind?: string;
      materialRoles: string[];
      executionCapability: string;
      constraintProfile?: { profileCode: string; revision: number; fingerprint: string };
      selectionSources: Array<{ kind: string; code: string }>;
    }>;
    materialPackRefs: Array<{ packCode: string; revisionNumber: number; fingerprint: string; role: string }>;
  };
  blueprint: { schema_version: string; scenes: Array<{ scene_code: string; shot_code: string; title: string; layers: Array<{ role: string; asset_code: string; execution_capability: string; z_order: number }>; script: string }> };
  buildPlan: { schema_version: string; build_plan_code?: string; target_live_room_id: string; go_live: boolean; operations: Array<{ kind: string; scene_code?: string; asset_code?: string; role?: string; script_block_code?: string }> };
  gateResults: Array<{ gate: string; status: string; ruleCode: string; remediation?: string }>;
  qualityReport: Record<string, unknown>;
  status: string;
  blockedReasons: string[];
  executionStatus: string;
  executionEvidence: Record<string, unknown>;
  clonedFromPlanCode?: string;
  cloneContext: Record<string, unknown>;
  releaseCode?: string;
  releaseSnapshotArtifactCode?: string;
  releaseManifestFingerprint?: string;
  release?: { releaseCode: string; status: string; manifestCode: string; manifestFingerprint: string; snapshotArtifactCode: string };
  updatedAt: string;
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
  return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []);
}

function plan(value: unknown): FunctionalLiveRoomPlan {
  if (!isRecord(value)) throw new Error("直播间计划响应无效");
  const planCode = asString(value.plan_code);
  if (!planCode) throw new Error("直播间计划缺少编码");
  const blueprint = isRecord(value.blueprint) ? value.blueprint : {};
  const buildPlan = isRecord(value.build_plan) ? value.build_plan : {};
  const inventorySnapshot = isRecord(buildPlan.inventory_snapshot) ? buildPlan.inventory_snapshot : {};
  const qualityReport = isRecord(value.quality_report) ? value.quality_report : {};
  const materialRoleOverrides = isRecord(qualityReport.material_role_overrides) ? Object.fromEntries(Object.entries(qualityReport.material_role_overrides).flatMap(([role, assetCode]) => typeof assetCode === "string" && assetCode ? [[role, assetCode]] : [])) : {};
  const materialSelectionDecisions = asArray(qualityReport.material_selection_decisions).flatMap((decision) => isRecord(decision) && asString(decision.role) && asString(decision.selected_asset_code) ? [{
    role: asString(decision.role), shotCode: asOptionalString(decision.shot_code), strategy: asString(decision.strategy), selectedAssetCode: asString(decision.selected_asset_code), selectedScore: asNumber(decision.selected_score), selectionReasons: strings(decision.selection_reasons), candidateScores: asArray(decision.candidate_scores).flatMap((candidate) => isRecord(candidate) && asString(candidate.asset_code) ? [{ assetCode: asString(candidate.asset_code), score: asNumber(candidate.score) }] : []),
  }] : []);
  return {
    planCode,
    projectCode: asString(value.project_code),
    variantCode: asString(value.variant_code),
    configurationCode: asString(value.configuration_code),
    targetLiveRoomId: asString(value.target_live_room_id),
    expectedTitle: asString(value.expected_title),
    primaryTemplateCode: asOptionalString(value.primary_template_code),
    secondaryTemplateCodes: strings(value.secondary_template_codes),
    selectedAssetCodes: strings(value.selected_asset_codes),
    selectedGroupCodes: strings(value.selected_group_codes),
    selectedMaterialPackCodes: strings(value.selected_material_pack_codes),
    materialRoleOverrides,
    materialSelectionDecisions,
    materialSnapshot: {
      assetCodes: strings(inventorySnapshot.asset_codes),
      assets: asArray(inventorySnapshot.assets).flatMap((asset) => isRecord(asset) && asString(asset.asset_code) ? [{
        assetCode: asString(asset.asset_code), mediaKind: asOptionalString(asset.media_kind), materialRoles: strings(asset.material_roles), executionCapability: asString(asset.execution_capability),
        constraintProfile: isRecord(asset.constraint_profile_ref) && asString(asset.constraint_profile_ref.profile_code) ? { profileCode: asString(asset.constraint_profile_ref.profile_code), revision: asNumber(asset.constraint_profile_ref.revision), fingerprint: asString(asset.constraint_profile_ref.fingerprint) } : undefined,
        selectionSources: asArray(asset.selection_sources).flatMap((source) => isRecord(source) && asString(source.kind) && asString(source.code) ? [{ kind: asString(source.kind), code: asString(source.code) }] : []),
      }] : []),
      materialPackRefs: asArray(inventorySnapshot.material_pack_refs).flatMap((pack) => isRecord(pack) && asString(pack.pack_code) ? [{ packCode: asString(pack.pack_code), revisionNumber: asNumber(pack.revision_number), fingerprint: asString(pack.fingerprint_sha256), role: asString(pack.role) }] : []),
    },
    blueprint: {
      schema_version: asString(blueprint.schema_version),
      scenes: asArray(blueprint.scenes).flatMap((scene) => isRecord(scene) ? [{
        scene_code: asString(scene.scene_code), shot_code: asString(scene.shot_code), title: asString(scene.title), script: asString(scene.script),
        layers: asArray(scene.layers).flatMap((layer) => isRecord(layer) ? [{ role: asString(layer.role, asString(layer.material_role)), asset_code: asString(layer.asset_code), execution_capability: asString(layer.execution_capability, isRecord(layer.asset_binding_ref) ? asString(layer.asset_binding_ref.execution_capability) : ""), z_order: typeof layer.z_order === "number" ? layer.z_order : 0 }] : []),
      }] : []),
    },
    buildPlan: {
      schema_version: asString(buildPlan.schema_version), build_plan_code: asOptionalString(buildPlan.build_plan_code), target_live_room_id: asString(buildPlan.target_live_room_id), go_live: buildPlan.go_live === true,
      operations: asArray(buildPlan.operations).flatMap((operation) => isRecord(operation) ? [{ kind: asString(operation.operation_type, asString(operation.kind)), scene_code: asOptionalString(operation.scene_code) ?? asOptionalString(operation.scene_name), asset_code: asOptionalString(operation.asset_code), role: asOptionalString(operation.role) ?? asOptionalString(operation.layer_type), script_block_code: asOptionalString(operation.script_block_code) }] : []),
    },
    gateResults: asArray(value.gate_results).flatMap((gate) => isRecord(gate) && asString(gate.gate) ? [{ gate: asString(gate.gate), status: asString(gate.status), ruleCode: asString(gate.rule_code), remediation: asOptionalString(gate.remediation) }] : []),
    qualityReport,
    status: asString(value.status),
    blockedReasons: strings(value.blocked_reasons),
    executionStatus: asString(value.execution_status),
    executionEvidence: isRecord(value.execution_evidence) ? value.execution_evidence : {},
    clonedFromPlanCode: asOptionalString(value.cloned_from_plan_code),
    cloneContext: isRecord(value.clone_context) ? value.clone_context : {},
    releaseCode: asOptionalString(value.release_code),
    releaseSnapshotArtifactCode: asOptionalString(value.release_snapshot_artifact_code),
    releaseManifestFingerprint: asOptionalString(value.release_manifest_fingerprint),
    release: isRecord(value.release) && asString(value.release.release_code) ? {
      releaseCode: asString(value.release.release_code), status: asString(value.release.status),
      manifestCode: asString(value.release.manifest_code), manifestFingerprint: asString(value.release.manifest_fingerprint),
      snapshotArtifactCode: asString(value.release.snapshot_artifact_code),
    } : undefined,
    updatedAt: asString(value.updated_at),
  };
}

function trace(value: unknown): FunctionalLiveRoomTrace {
  if (!isRecord(value)) throw new Error("直播间追溯响应无效");
  return {
    planCode: asString(value.plan_code),
    contentChain: isRecord(value.content_chain) ? value.content_chain : {},
    operations: asArray(value.operations).flatMap((operation) => isRecord(operation) ? [{
      operationId: asString(operation.operation_id), operationType: asString(operation.operation_type), operationName: asString(operation.operation_name),
      sortOrder: typeof operation.sort_order === "number" ? operation.sort_order : 0,
      targets: asArray(operation.targets).flatMap((target) => isRecord(target) ? [{
        targetType: asString(target.target_type), targetCode: asString(target.target_code), relationType: asString(target.relation_type),
        shot: isRecord(target.shot) ? { shotCode: asString(target.shot.shot_code), shotGoal: asString(target.shot.shot_goal) } : undefined,
        programSegment: isRecord(target.program_segment) ? { segmentCode: asString(target.program_segment.segment_code), semanticGoal: asString(target.program_segment.semantic_goal) } : undefined,
        scriptBlocks: asArray(target.script_blocks).flatMap((block) => isRecord(block) && asString(block.block_code) ? [{ blockCode: asString(block.block_code) }] : []),
      }] : []),
    }] : []),
  };
}

export const functionalLiveRoomsApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(plan)),
  get: (planCode: string) => requestJson<unknown>(`${ROOT}/${planCode}`).then(plan),
  getTrace: (planCode: string) => requestJson<unknown>(`${ROOT}/${planCode}/trace`).then(trace),
  create: (payload: { project_code: string; target_live_room_id: string; expected_title: string; primary_template_code?: string; secondary_template_codes: string[]; asset_codes: string[]; group_codes: string[]; material_pack_codes: string[]; material_role_overrides: Record<string, string> }) => postJson<unknown>(ROOT, payload).then(plan),
  confirmExecution: (planCode: string) => postJson<unknown>(`${ROOT}/${planCode}/confirm-execution`, { confirmed: true }).then(plan),
  createReleaseCandidate: (planCode: string) => postJson<unknown>(`${ROOT}/${planCode}/release-candidate`, {}).then(plan),
  clone: (planCode: string, payload: { target_live_room_id: string; expected_title: string }) => postJson<unknown>(`${ROOT}/${planCode}/clone`, payload).then(plan),
};
