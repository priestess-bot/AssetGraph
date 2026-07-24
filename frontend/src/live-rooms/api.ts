import { asArray, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

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
  blueprint: { schema_version: string; scenes: Array<{ scene_code: string; shot_code: string; title: string; layers: Array<{ role: string; asset_code: string; execution_capability: string; z_order: number }>; script: string }> };
  buildPlan: { schema_version: string; target_live_room_id: string; go_live: boolean; operations: Array<{ kind: string; scene_code?: string; asset_code?: string; role?: string; script_block_code?: string }> };
  status: string;
  blockedReasons: string[];
  executionStatus: string;
  executionEvidence: Record<string, unknown>;
  updatedAt: string;
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
    blueprint: {
      schema_version: asString(blueprint.schema_version),
      scenes: asArray(blueprint.scenes).flatMap((scene) => isRecord(scene) ? [{
        scene_code: asString(scene.scene_code), shot_code: asString(scene.shot_code), title: asString(scene.title), script: asString(scene.script),
        layers: asArray(scene.layers).flatMap((layer) => isRecord(layer) ? [{ role: asString(layer.role), asset_code: asString(layer.asset_code), execution_capability: asString(layer.execution_capability), z_order: typeof layer.z_order === "number" ? layer.z_order : 0 }] : []),
      }] : []),
    },
    buildPlan: {
      schema_version: asString(buildPlan.schema_version), target_live_room_id: asString(buildPlan.target_live_room_id), go_live: buildPlan.go_live === true,
      operations: asArray(buildPlan.operations).flatMap((operation) => isRecord(operation) ? [{ kind: asString(operation.kind), scene_code: asOptionalString(operation.scene_code), asset_code: asOptionalString(operation.asset_code), role: asOptionalString(operation.role), script_block_code: asOptionalString(operation.script_block_code) }] : []),
    },
    status: asString(value.status),
    blockedReasons: strings(value.blocked_reasons),
    executionStatus: asString(value.execution_status),
    executionEvidence: isRecord(value.execution_evidence) ? value.execution_evidence : {},
    updatedAt: asString(value.updated_at),
  };
}

export const functionalLiveRoomsApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(plan)),
  get: (planCode: string) => requestJson<unknown>(`${ROOT}/${planCode}`).then(plan),
  create: (payload: { project_code: string; target_live_room_id: string; expected_title: string; primary_template_code?: string; secondary_template_codes: string[]; asset_codes: string[]; group_codes: string[] }) => postJson<unknown>(ROOT, payload).then(plan),
  confirmExecution: (planCode: string) => postJson<unknown>(`${ROOT}/${planCode}/confirm-execution`, { confirmed: true }).then(plan),
};
