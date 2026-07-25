import { asArray, asOptionalString, asString, isRecord, requestJson, postJson } from "../workbench/api";

const ROOT = "/api/broadcast-schedules";

export interface BroadcastSchedule {
  scheduleCode: string;
  revisionNumber: number;
  title: string;
  releaseCode: string;
  releaseFingerprint?: string;
  targetAccountId: string;
  targetRoomId: string;
  platform: string;
  timezone: string;
  startsAt: string;
  endsAt: string;
  owner: string;
  promotionDependencies: string[];
  inventoryDependencies: string[];
  conflictStrategy: string;
  stopConditions: string[];
  status: string;
  validationResult: Record<string, unknown>;
  fingerprint: string;
  createdAt?: string;
}

export interface BroadcastScheduleCreate {
  title: string;
  release_code: string;
  target_account_id: string;
  target_room_id: string;
  platform: string;
  timezone: string;
  starts_at: string;
  ends_at: string;
  owner: string;
  promotion_dependencies: string[];
  inventory_dependencies: string[];
  conflict_strategy: string;
  stop_conditions: string[];
}

function strings(value: unknown): string[] {
  return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []);
}

function schedule(value: unknown): BroadcastSchedule {
  if (!isRecord(value)) throw new Error("排播计划响应无效");
  const scheduleCode = asString(value.schedule_code);
  if (!scheduleCode) throw new Error("排播计划缺少编码");
  return {
    scheduleCode,
    revisionNumber: Number(value.revision_number ?? 0),
    title: asString(value.title),
    releaseCode: asString(value.release_code),
    releaseFingerprint: asOptionalString(value.release_fingerprint_sha256),
    targetAccountId: asString(value.target_account_id),
    targetRoomId: asString(value.target_room_id),
    platform: asString(value.platform),
    timezone: asString(value.timezone),
    startsAt: asString(value.starts_at),
    endsAt: asString(value.ends_at),
    owner: asString(value.owner),
    promotionDependencies: strings(value.promotion_dependencies),
    inventoryDependencies: strings(value.inventory_dependencies),
    conflictStrategy: asString(value.conflict_strategy),
    stopConditions: strings(value.stop_conditions),
    status: asString(value.status),
    validationResult: isRecord(value.validation_result) ? value.validation_result : {},
    fingerprint: asString(value.fingerprint_sha256),
    createdAt: asOptionalString(value.created_at),
  };
}

export const broadcastSchedulesApi = {
  list: () => requestJson<unknown[]>(ROOT).then((rows) => rows.map(schedule)),
  create: (payload: BroadcastScheduleCreate) => postJson<unknown>(ROOT, payload).then(schedule),
  validate: (scheduleCode: string) => postJson<unknown>(`${ROOT}/${encodeURIComponent(scheduleCode)}/validate`, {}).then(schedule),
};
