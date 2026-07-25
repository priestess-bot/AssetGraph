import { asArray, asOptionalString, asString, isRecord, postJson, requestJson } from "../workbench/api";

export interface MetricRevision {
  metricCode: string;
  revisionNumber: number;
  status: string;
  ownerPrincipal: string;
  metricStatus: string;
  name: string;
  description: string;
  grain?: string;
  unit: string;
  currency?: string;
  valueType: string;
  aggregation: string;
  numeratorExpression?: string;
  denominatorExpression?: string;
  dimensions: string[];
  eventContractRefs: Array<Record<string, unknown>>;
  eventTimeField?: string;
  timezone?: string;
  businessDayBoundary?: string;
  deduplicationKeys: string[];
  refundWindowDays?: number;
  nullRule: Record<string, unknown>;
  outlierRule: Record<string, unknown>;
  schemaCompatibility: Record<string, unknown>;
  qualitySlo: Record<string, unknown>;
  fingerprintSha256: string;
  effectiveAt?: string;
  createdAt?: string;
}

export interface DataContractRevision {
  contractCode: string;
  revisionNumber: number;
  status: string;
  ownerPrincipal: string;
  sourceSystem: string;
  schemaVersion: string;
  jsonSchema: Record<string, unknown>;
  eventIdPath: string;
  eventTimePath?: string;
  operationPath?: string;
  primaryKeyPaths: string[];
  upsertDeleteSemantics: Record<string, unknown>;
  latenessPolicy: Record<string, unknown>;
  compatibilityWindow: Record<string, unknown>;
  enumMappings: Record<string, unknown>;
  fieldClassifications: Record<string, string>;
  expectedVolume: Record<string, unknown>;
  qualitySlo: Record<string, unknown>;
  fingerprintSha256: string;
  createdAt?: string;
}

export interface DataContractConsumer {
  metricCode: string;
  revisionNumber: number;
  status: string;
  ownerPrincipal: string;
  name: string;
  eventContractRefs: Array<Record<string, unknown>>;
}

export interface DataQualityBatch {
  batchCode: string;
  contractCode: string;
  contractRevision: number;
  sourceBatchId: string;
  sourceChecksum?: string;
  status: string;
  rowCount: number;
  acceptedCount: number;
  quarantinedCount: number;
  rejectedCount: number;
  qualitySummary: Record<string, unknown>;
  sourceWatermark?: string;
  validatedAt?: string;
  createdAt?: string;
  replayed: boolean;
}

export interface DataQualityViolation {
  violationId: string;
  batchCode: string;
  eventId?: string;
  ruleCode: string;
  severity: string;
  fieldPath?: string;
  details: Record<string, unknown>;
  createdAt?: string;
}

export interface MetricRevisionWrite {
  owner_principal: string;
  expected_revision: number;
  activate: boolean;
  definition: Record<string, unknown>;
}

export interface DataContractRevisionWrite {
  owner_principal: string;
  activate: boolean;
  definition: Record<string, unknown>;
}

function stringList(value: unknown): string[] {
  return asArray(value).flatMap((item) => typeof item === "string" ? [item] : []);
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  return asArray(value).flatMap((item) => isRecord(item) ? [item] : []);
}

function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function metric(value: unknown): MetricRevision {
  if (!isRecord(value)) throw new Error("指标目录响应无效");
  return {
    metricCode: asString(value.metric_code),
    revisionNumber: typeof value.revision_number === "number" ? value.revision_number : 0,
    status: asString(value.status),
    ownerPrincipal: asString(value.owner_principal),
    metricStatus: asString(value.metric_status),
    name: asString(value.name),
    description: asString(value.description),
    grain: asOptionalString(value.grain),
    unit: asString(value.unit),
    currency: asOptionalString(value.currency),
    valueType: asString(value.value_type),
    aggregation: asString(value.aggregation),
    numeratorExpression: asOptionalString(value.numerator_expression),
    denominatorExpression: asOptionalString(value.denominator_expression),
    dimensions: stringList(value.dimensions),
    eventContractRefs: recordList(value.event_contract_refs),
    eventTimeField: asOptionalString(value.event_time_field),
    timezone: asOptionalString(value.timezone),
    businessDayBoundary: asOptionalString(value.business_day_boundary),
    deduplicationKeys: stringList(value.deduplication_keys),
    refundWindowDays: typeof value.refund_window_days === "number" ? value.refund_window_days : undefined,
    nullRule: record(value.null_rule),
    outlierRule: record(value.outlier_rule),
    schemaCompatibility: record(value.schema_compatibility),
    qualitySlo: record(value.quality_slo),
    fingerprintSha256: asString(value.fingerprint_sha256),
    effectiveAt: asOptionalString(value.effective_at),
    createdAt: asOptionalString(value.created_at),
  };
}

function contract(value: unknown): DataContractRevision {
  if (!isRecord(value)) throw new Error("数据契约响应无效");
  const classifications = Object.fromEntries(
    Object.entries(record(value.field_classifications)).flatMap(([key, item]) => typeof item === "string" ? [[key, item]] : []),
  );
  return {
    contractCode: asString(value.contract_code),
    revisionNumber: typeof value.revision_number === "number" ? value.revision_number : 0,
    status: asString(value.status),
    ownerPrincipal: asString(value.owner_principal),
    sourceSystem: asString(value.source_system),
    schemaVersion: asString(value.schema_version),
    jsonSchema: record(value.json_schema),
    eventIdPath: asString(value.event_id_path),
    eventTimePath: asOptionalString(value.event_time_path),
    operationPath: asOptionalString(value.operation_path),
    primaryKeyPaths: stringList(value.primary_key_paths),
    upsertDeleteSemantics: record(value.upsert_delete_semantics),
    latenessPolicy: record(value.lateness_policy),
    compatibilityWindow: record(value.compatibility_window),
    enumMappings: record(value.enum_mappings),
    fieldClassifications: classifications,
    expectedVolume: record(value.expected_volume),
    qualitySlo: record(value.quality_slo),
    fingerprintSha256: asString(value.fingerprint_sha256),
    createdAt: asOptionalString(value.created_at),
  };
}

function consumer(value: unknown): DataContractConsumer {
  if (!isRecord(value)) throw new Error("数据契约消费者响应无效");
  return {
    metricCode: asString(value.metric_code),
    revisionNumber: typeof value.revision_number === "number" ? value.revision_number : 0,
    status: asString(value.status),
    ownerPrincipal: asString(value.owner_principal),
    name: asString(value.name),
    eventContractRefs: recordList(value.event_contract_refs),
  };
}

function batch(value: unknown): DataQualityBatch {
  if (!isRecord(value)) throw new Error("事件批次响应无效");
  return {
    batchCode: asString(value.batch_code),
    contractCode: asString(value.contract_code),
    contractRevision: typeof value.contract_revision === "number" ? value.contract_revision : 0,
    sourceBatchId: asString(value.source_batch_id),
    sourceChecksum: asOptionalString(value.source_checksum),
    status: asString(value.status),
    rowCount: typeof value.row_count === "number" ? value.row_count : 0,
    acceptedCount: typeof value.accepted_count === "number" ? value.accepted_count : 0,
    quarantinedCount: typeof value.quarantined_count === "number" ? value.quarantined_count : 0,
    rejectedCount: typeof value.rejected_count === "number" ? value.rejected_count : 0,
    qualitySummary: record(value.quality_summary),
    sourceWatermark: asOptionalString(value.source_watermark),
    validatedAt: asOptionalString(value.validated_at),
    createdAt: asOptionalString(value.created_at),
    replayed: value.replayed === true,
  };
}

function qualityViolation(value: unknown): DataQualityViolation {
  if (!isRecord(value)) throw new Error("事件批次违规响应无效");
  return {
    violationId: asString(value.violation_id),
    batchCode: asString(value.batch_code),
    eventId: asOptionalString(value.event_id),
    ruleCode: asString(value.rule_code),
    severity: asString(value.severity),
    fieldPath: asOptionalString(value.field_path),
    details: record(value.details),
    createdAt: asOptionalString(value.created_at),
  };
}

const ROOT = "/api/data-governance";

export const dataGovernanceApi = {
  listMetrics: () => requestJson<unknown[]>(`${ROOT}/metrics`).then((items) => items.map(metric)),
  listMetricRevisions: (metricCode: string) => requestJson<unknown[]>(`${ROOT}/metrics/${encodeURIComponent(metricCode)}/revisions`).then((items) => items.map(metric)),
  createMetricRevision: (metricCode: string, payload: MetricRevisionWrite) => postJson<unknown>(`${ROOT}/metrics/${encodeURIComponent(metricCode)}/revisions`, payload).then(metric),
  listContracts: () => requestJson<unknown[]>(`${ROOT}/contracts`).then((items) => items.map(contract)),
  listContractRevisions: (contractCode: string) => requestJson<unknown[]>(`${ROOT}/contracts/${encodeURIComponent(contractCode)}/revisions`).then((items) => items.map(contract)),
  listContractConsumers: (contractCode: string) => requestJson<unknown[]>(`${ROOT}/contracts/${encodeURIComponent(contractCode)}/consumers`).then((items) => items.map(consumer)),
  createContractRevision: (contractCode: string, revision: number, payload: DataContractRevisionWrite) => postJson<unknown>(`${ROOT}/contracts/${encodeURIComponent(contractCode)}/revisions/${revision}`, payload).then(contract),
  listQualityBatches: () => requestJson<unknown[]>(`${ROOT}/batches`).then((items) => items.map(batch)),
  listQualityBatchViolations: (batchCode: string) => requestJson<unknown[]>(`${ROOT}/batches/${encodeURIComponent(batchCode)}/violations`).then((items) => items.map(qualityViolation)),
  ingestEventBatch: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/batches`, payload).then(batch),
};
