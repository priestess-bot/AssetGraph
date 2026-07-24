import {
  asArray,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  queryString,
  requestJson,
} from "../workbench/api";
import type {
  ConsoleCommandResult,
  ConsoleDraft,
  ConsoleEntityDetail,
  ConsoleEntityRelation,
  ConsoleEntityRevision,
  ConsoleNotification,
  ConsoleSearchResult,
  ConsoleSession,
  ConsoleTask,
} from "./types";


const ROOT = "/api/console";


function normalizeSession(value: unknown): ConsoleSession {
  if (!isRecord(value)) throw new Error("Invalid Console session response");
  return {
    operatorId: asString(value.operator_id),
    roles: asArray(value.roles).flatMap((role) => typeof role === "string" ? [role] : []),
    authScheme: "bearer_memory",
  };
}


function normalizeSearchResult(value: unknown): ConsoleSearchResult | undefined {
  if (!isRecord(value)) return undefined;
  const entityCode = asString(value.entity_code);
  const href = asString(value.href);
  if (!entityCode || !href) return undefined;
  return {
    entityType: asString(value.entity_type),
    entityCode,
    title: asString(value.title, entityCode),
    status: asString(value.status, "unknown"),
    revision: typeof value.revision === "number" ? value.revision : undefined,
    href,
    updatedAt: asString(value.updated_at),
  };
}


function normalizeTask(value: unknown): ConsoleTask | undefined {
  if (!isRecord(value)) return undefined;
  const itemCode = asString(value.item_code);
  const itemType = asString(value.item_type);
  if (!itemCode || (itemType !== "human_task" && itemType !== "workflow_run")) return undefined;
  return {
    itemCode,
    itemType,
    title: asString(value.title, itemCode),
    status: asString(value.status, "unknown"),
    priority: asNumber(value.priority, 100),
    summary: asString(value.summary, "待处理事项"),
    href: asString(value.href, `/governance/runs?run=${asString(value.run_code)}`),
    dueAt: asOptionalString(value.due_at),
    updatedAt: asString(value.updated_at),
    runCode: asString(value.run_code),
    progressCompleted: asNumber(value.progress_completed),
    progressTotal: asNumber(value.progress_total),
    ownerPrincipal: asOptionalString(value.owner_principal),
    claimedBy: asOptionalString(value.claimed_by),
  };
}


function normalizeNotification(value: unknown): ConsoleNotification | undefined {
  if (!isRecord(value)) return undefined;
  const code = asString(value.notification_code);
  const state = asString(value.state);
  if (!code || !["error", "warning", "reconcile_required"].includes(state)) return undefined;
  const rawEvidence = isRecord(value.evidence) ? value.evidence : {};
  return {
    notificationCode: code,
    state: state as ConsoleNotification["state"],
    title: asString(value.title, code),
    summary: asString(value.summary, "需要检查证据"),
    href: asString(value.href, "/governance/runs"),
    evidence: Object.entries(rawEvidence).map(([kind, ref]) => ({ kind, ref: String(ref) })),
    occurrenceCount: asNumber(value.occurrence_count, 1),
    occurredAt: asString(value.occurred_at),
    status: asString(value.status, "open"),
  };
}


function normalizeRevision(value: unknown): ConsoleEntityRevision | undefined {
  if (!isRecord(value)) return undefined;
  const revision = asNumber(value.revision);
  if (revision < 1) return undefined;
  return {
    revision,
    status: asString(value.status),
    schemaVersion: asString(value.schema_version),
    createdAt: asString(value.created_at),
    createdBy: asOptionalString(value.created_by),
    fingerprint: asOptionalString(value.fingerprint),
    snapshot: isRecord(value.snapshot) ? value.snapshot : {},
  };
}


function normalizeRelation(value: unknown): ConsoleEntityRelation | undefined {
  if (!isRecord(value)) return undefined;
  const entityCode = asString(value.entity_code);
  if (!entityCode) return undefined;
  return {
    relationType: asString(value.relation_type),
    entityType: asString(value.entity_type),
    entityCode,
    revision: typeof value.revision === "number" ? value.revision : undefined,
    status: asOptionalString(value.status),
    href: asOptionalString(value.href),
    mappingQuality: asString(value.mapping_quality, "unknown"),
  };
}


function normalizeEntity(value: unknown): ConsoleEntityDetail {
  if (!isRecord(value) || !isRecord(value.diff)) throw new Error("Invalid Console entity response");
  const changeValues = asArray(value.diff.changes).flatMap((item) => {
    if (!isRecord(item)) return [];
    const change = asString(item.change);
    if (!["added", "removed", "changed"].includes(change)) return [];
    return [{
      path: asString(item.path),
      change: change as "added" | "removed" | "changed",
      before: item.before,
      after: item.after,
    }];
  });
  return {
    entityType: asString(value.entity_type),
    entityCode: asString(value.entity_code),
    title: asString(value.title),
    status: asString(value.status),
    currentRevision: asNumber(value.current_revision, 1),
    canonicalHref: asString(value.canonical_href),
    sourceOfTruth: asString(value.source_of_truth),
    revisions: asArray(value.revisions).flatMap((item) => normalizeRevision(item) ?? []),
    diff: {
      fromRevision: asNumber(value.diff.from_revision, 1),
      toRevision: asNumber(value.diff.to_revision, 1),
      available: value.diff.available === true,
      changes: changeValues,
    },
    sources: asArray(value.sources).flatMap((item) => normalizeRelation(item) ?? []),
    usedBy: asArray(value.used_by).flatMap((item) => normalizeRelation(item) ?? []),
  };
}


function normalizeDraft(value: unknown): ConsoleDraft | undefined {
  if (value === null || value === undefined) return undefined;
  if (!isRecord(value) || !isRecord(value.document)) throw new Error("Invalid Console draft response");
  const status = asString(value.status);
  if (status !== "active" && status !== "consumed") throw new Error("Invalid Console draft status");
  return {
    draftCode: asString(value.draft_code),
    entityType: asString(value.entity_type),
    entityCode: asString(value.entity_code),
    draftKind: asString(value.draft_kind),
    schemaVersion: asString(value.schema_version),
    draftRevision: asNumber(value.draft_revision),
    baseEntityRevision: asNumber(value.base_entity_revision),
    status,
    document: value.document,
    contentFingerprint: asString(value.content_fingerprint),
    createdBy: asString(value.created_by),
    updatedBy: asString(value.updated_by),
    createdAt: asString(value.created_at),
    updatedAt: asString(value.updated_at),
  };
}


function normalizeCommand(value: unknown): ConsoleCommandResult {
  if (!isRecord(value)) throw new Error("Invalid Console command response");
  const command = asString(value.command);
  if (!["confirm", "publish", "approve", "reject", "authorize"].includes(command)) {
    throw new Error("Invalid Console command type");
  }
  return {
    command: command as ConsoleCommandResult["command"],
    entityType: asString(value.entity_type),
    entityCode: asString(value.entity_code),
    entityRevision: typeof value.entity_revision === "number" ? value.entity_revision : undefined,
    status: asString(value.status),
    impact: asString(value.impact),
    receiptCode: asString(value.receipt_code),
    replayed: value.replayed === true,
    draftRevision: typeof value.draft_revision === "number" ? value.draft_revision : undefined,
    approvalCode: asOptionalString(value.approval_code),
    authorizationCode: asOptionalString(value.authorization_code),
    authorizationToken: asOptionalString(value.authorization_token),
    tokenAvailable: typeof value.token_available === "boolean" ? value.token_available : undefined,
    capability: asOptionalString(value.capability),
    targetType: asOptionalString(value.target_type),
    targetId: asOptionalString(value.target_id),
    expiresAt: asOptionalString(value.expires_at),
    layoutFidelity: asOptionalString(value.layout_fidelity),
    buildability: asOptionalString(value.buildability),
  };
}


export const consoleApi = {
  session: (token?: string) => requestJson<unknown>(`${ROOT}/session`, token ? {
    headers: { Authorization: `Bearer ${token}` },
  } : undefined).then(normalizeSession),
  search: (query: string) => requestJson<unknown>(`${ROOT}/search${queryString({ q: query })}`)
    .then((value) => asArray(value).flatMap((item) => normalizeSearchResult(item) ?? [])),
  tasks: () => requestJson<unknown>(`${ROOT}/tasks`)
    .then((value) => asArray(value).flatMap((item) => normalizeTask(item) ?? [])),
  notifications: () => requestJson<unknown>(`${ROOT}/notifications`)
    .then((value) => asArray(value).flatMap((item) => normalizeNotification(item) ?? [])),
  entity: (entityType: string, entityCode: string, fromRevision?: number, toRevision?: number) =>
    requestJson<unknown>(
      `${ROOT}/entities/${encodeURIComponent(entityType)}/${encodeURIComponent(entityCode)}`
      + queryString({ from_revision: fromRevision, to_revision: toRevision }),
    ).then(normalizeEntity),
  draft: (entityType: string, entityCode: string, draftKind: string) =>
    requestJson<unknown>(
      `${ROOT}/drafts/${encodeURIComponent(entityType)}/${encodeURIComponent(entityCode)}/${encodeURIComponent(draftKind)}`,
    ).then(normalizeDraft),
  saveDraft: (
    entityType: string,
    entityCode: string,
    draftKind: string,
    payload: { expectedRevision: number; baseEntityRevision: number; document: Record<string, unknown> },
  ) => requestJson<unknown>(
    `${ROOT}/drafts/${encodeURIComponent(entityType)}/${encodeURIComponent(entityCode)}/${encodeURIComponent(draftKind)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        expected_revision: payload.expectedRevision,
        base_entity_revision: payload.baseEntityRevision,
        schema_version: "console-draft.v1",
        document: payload.document,
      }),
    },
  ).then(normalizeDraft).then((value) => {
    if (!value) throw new Error("Console draft save returned no document");
    return value;
  }),
  confirmContentProject: (
    projectCode: string,
    payload: { expectedEntityRevision: number; expectedDraftRevision: number; idempotencyKey: string },
  ) => requestJson<unknown>(`${ROOT}/content-projects/${encodeURIComponent(projectCode)}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      expected_entity_revision: payload.expectedEntityRevision,
      expected_draft_revision: payload.expectedDraftRevision,
      idempotency_key: payload.idempotencyKey,
    }),
  }).then(normalizeCommand),
  publishTemplate: (
    templateCode: string,
    payload: { expectedRevision: number; reasonCode: string; summary: string; idempotencyKey: string },
  ) => requestJson<unknown>(`${ROOT}/live-room-templates/${encodeURIComponent(templateCode)}/publish`, {
    method: "POST",
    body: JSON.stringify({
      expected_revision: payload.expectedRevision,
      structured_reason: { reason_code: payload.reasonCode, summary: payload.summary },
      idempotency_key: payload.idempotencyKey,
    }),
  }).then(normalizeCommand),
  decideRelease: (
    releaseCode: string,
    payload: { expectedManifestRevision: number; decision: "approve" | "reject"; reasonCode: string; summary: string; approvedScope: Record<string, unknown>; idempotencyKey: string },
  ) => requestJson<unknown>(`${ROOT}/releases/${encodeURIComponent(releaseCode)}/decision`, {
    method: "POST",
    body: JSON.stringify({
      expected_manifest_revision: payload.expectedManifestRevision,
      decision: payload.decision,
      structured_reason: { reason_code: payload.reasonCode, summary: payload.summary },
      approved_scope: payload.approvedScope,
      idempotency_key: payload.idempotencyKey,
    }),
  }).then(normalizeCommand),
  issueAuthorization: (
    runCode: string,
    payload: { taskCode: string; expectedTaskRevision: number; idempotencyKey: string },
  ) => requestJson<unknown>(`${ROOT}/workflow-runs/${encodeURIComponent(runCode)}/authorize`, {
    method: "POST",
    body: JSON.stringify({
      task_code: payload.taskCode,
      expected_task_revision: payload.expectedTaskRevision,
      idempotency_key: payload.idempotencyKey,
    }),
  }).then(normalizeCommand),
};
