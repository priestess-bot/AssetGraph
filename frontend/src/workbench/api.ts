export type JsonRecord = Record<string, unknown>;

let accessToken: string | undefined;

export function setWorkbenchAccessToken(token?: string): void {
  accessToken = token?.trim() || undefined;
}

export function hasWorkbenchAccessToken(): boolean {
  return Boolean(accessToken);
}

export type OperationalState = "error" | "warning" | "insufficient_data" | "stale" | "reconcile_required";

export interface ProblemEvidence {
  kind: string;
  ref: string;
}

export interface WorkbenchProblem {
  code: string;
  state: OperationalState;
  message: string;
  impact: string;
  evidence: ProblemEvidence[];
  nextStep: string;
  retryable: boolean;
  traceId?: string;
}

export class WorkbenchApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
    readonly problem?: WorkbenchProblem,
  ) {
    super(message);
    this.name = "WorkbenchApiError";
  }
}

const OPERATIONAL_STATES = new Set<OperationalState>(["error", "warning", "insufficient_data", "stale", "reconcile_required"]);

export function normalizeProblem(value: unknown): WorkbenchProblem | undefined {
  if (!isRecord(value)) return undefined;
  const state = asString(value.state) as OperationalState;
  const code = asString(value.code);
  if (!code || !OPERATIONAL_STATES.has(state)) return undefined;
  const evidence = asArray(value.evidence).flatMap((item) => {
    if (!isRecord(item)) return [];
    const kind = asString(item.kind);
    const ref = asString(item.ref);
    return kind && ref ? [{ kind, ref }] : [];
  });
  return {
    code,
    state,
    message: asString(value.message, "请求未能完成"),
    impact: asString(value.impact, "当前操作未完成。"),
    evidence,
    nextStep: asString(value.next_step, "检查输入和证据后重试。"),
    retryable: asBoolean(value.retryable),
    traceId: asOptionalString(value.trace_id),
  };
}

export function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

export function asOptionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (!isRecord(value)) return [];
  for (const key of ["items", "results", "data", "rows"]) {
    if (Array.isArray(value[key])) return value[key] as unknown[];
  }
  return [];
}

function errorMessage(body: unknown, status: number): string {
  if (isRecord(body)) {
    const direct = asOptionalString(body.message) ?? asOptionalString(body.error_message);
    if (direct) return direct;
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  }
  if (status === 409) return "当前数据已经变化，请刷新后重试";
  if (status === 404) return "请求的对象不存在或尚未创建";
  if (status >= 500) return "服务暂时不可用，请稍后重试";
  return "请求未能完成，请检查输入后重试";
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init?.headers,
    },
  });

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  if (!response.ok) {
    const problem = isRecord(body) ? normalizeProblem(body.error) : undefined;
    throw new WorkbenchApiError(problem?.message ?? errorMessage(body, response.status), response.status, body, problem);
  }
  return body as T;
}

export function postJson<T>(path: string, payload?: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
}

export function patchJson<T>(path: string, payload: unknown): Promise<T> {
  return requestJson<T>(path, { method: "PATCH", body: JSON.stringify(payload) });
}

export function queryString(params: Record<string, string | number | boolean | null | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const value = query.toString();
  return value ? `?${value}` : "";
}
