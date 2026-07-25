import { asArray, asNumber, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

export interface WorkflowStep {
  stepCode: string;
  stepType: string;
  sortOrder: number;
  status: string;
  priority: number;
  attempt: number;
  maxAttempts: number;
  sideEffectLevel: string;
  timeoutSeconds: number;
  claimedBy?: string;
  leaseExpiresAt?: string;
  errorCode?: string;
  errorSummary?: string;
  dependsOn: string[];
}

export interface WorkflowHumanTask {
  taskCode: string;
  taskType: string;
  status: string;
  revision: number;
  priority: number;
  ownerPrincipal?: string;
  claimedBy?: string;
  dueAt?: string;
  expiresAt?: string;
  decision?: string;
  structuredReason?: Record<string, unknown>;
}

export interface WorkflowRun {
  runCode: string;
  workflowType: string;
  subjectType: string;
  subjectCode: string;
  subjectRevision?: number;
  status: string;
  priority: number;
  progressCompleted: number;
  progressTotal: number;
  queueReason?: string;
  waitingReason?: string;
  errorCode?: string;
  errorSummary?: string;
  requestedBy?: string;
  budget: Record<string, unknown>;
  actualCost: Record<string, unknown>;
  steps: WorkflowStep[];
  humanTasks: WorkflowHumanTask[];
  updatedAt?: string;
}

function strings(value: unknown): string[] { return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []); }

function step(value: unknown): WorkflowStep | undefined {
  if (!isRecord(value)) return undefined;
  const stepCode = asString(value.step_code);
  if (!stepCode) return undefined;
  return { stepCode, stepType: asString(value.step_type), sortOrder: asNumber(value.sort_order), status: asString(value.status), priority: asNumber(value.priority), attempt: asNumber(value.attempt), maxAttempts: asNumber(value.max_attempts), sideEffectLevel: asString(value.side_effect_level), timeoutSeconds: asNumber(value.timeout_seconds), claimedBy: asOptionalString(value.claimed_by), leaseExpiresAt: asOptionalString(value.lease_expires_at), errorCode: asOptionalString(value.error_code), errorSummary: asOptionalString(value.error_summary), dependsOn: strings(value.depends_on) };
}

function humanTask(value: unknown): WorkflowHumanTask | undefined {
  if (!isRecord(value)) return undefined;
  const taskCode = asString(value.task_code);
  if (!taskCode) return undefined;
  return { taskCode, taskType: asString(value.task_type), status: asString(value.status), revision: asNumber(value.revision), priority: asNumber(value.priority), ownerPrincipal: asOptionalString(value.owner_principal), claimedBy: asOptionalString(value.claimed_by), dueAt: asOptionalString(value.due_at), expiresAt: asOptionalString(value.expires_at), decision: asOptionalString(value.decision), structuredReason: isRecord(value.structured_reason) ? value.structured_reason : undefined };
}

function workflowRun(value: unknown): WorkflowRun {
  if (!isRecord(value)) throw new Error("运行详情响应无效");
  const runCode = asString(value.run_code);
  if (!runCode) throw new Error("运行详情缺少编码");
  return {
    runCode,
    workflowType: asString(value.workflow_type),
    subjectType: asString(value.subject_type),
    subjectCode: asString(value.subject_code),
    subjectRevision: typeof value.subject_revision === "number" ? value.subject_revision : undefined,
    status: asString(value.status),
    priority: asNumber(value.priority),
    progressCompleted: asNumber(value.progress_completed),
    progressTotal: asNumber(value.progress_total),
    queueReason: asOptionalString(value.queue_reason),
    waitingReason: asOptionalString(value.waiting_reason),
    errorCode: asOptionalString(value.error_code),
    errorSummary: asOptionalString(value.error_summary),
    requestedBy: asOptionalString(value.requested_by),
    budget: isRecord(value.budget) ? value.budget : {},
    actualCost: isRecord(value.actual_cost) ? value.actual_cost : {},
    steps: asArray(value.steps).flatMap((item) => step(item) ?? []),
    humanTasks: asArray(value.human_tasks).flatMap((item) => humanTask(item) ?? []),
    updatedAt: asOptionalString(value.updated_at),
  };
}

export const workflowRunsApi = {
  get: (runCode: string) => requestJson<unknown>(`/api/workflow-runs/${encodeURIComponent(runCode)}`).then(workflowRun),
  cancel: (runCode: string, reason: string) => postJson<unknown>(`/api/workflow-runs/${encodeURIComponent(runCode)}/cancel`, { reason }).then(workflowRun),
};
