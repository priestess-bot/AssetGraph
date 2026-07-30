import {
  asArray,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  postJson,
  requestJson,
} from "../workbench/api";

const ROOT = "/api/functional-operations";

export interface OperationSession {
  sessionCode: string;
  title: string;
  platform: string;
  externalSessionId?: string;
  accountId?: string;
  targetResourceId?: string;
  sourceTimezone: string;
  sourceEvidence: Record<string, unknown>;
  projectCode?: string;
  liveRoomPlanCode?: string;
  videoPlanCode?: string;
  boundContentKind?: string;
  boundContentCode?: string;
  boundContentRevision?: number;
  bindingStatus: string;
  variantCode?: string;
  releaseCode?: string;
  startedAt: string;
  endedAt: string;
  metrics: Record<string, number>;
  metricDefinitionRefs: MetricDefinitionRef[];
  sourceKind: string;
}

export interface OperationImportFinding {
  field: string;
  code: string;
  message: string;
}

export interface OperationBindingCandidate {
  contentKind: string;
  contentCode: string;
  contentRevision?: number;
  title?: string;
}

export interface OperationImportRow {
  rowNumber: number;
  rowFingerprintSha256: string;
  rawValues: Record<string, string>;
  normalizedPayload: Record<string, unknown>;
  validationErrors: OperationImportFinding[];
  validationWarnings: OperationImportFinding[];
  duplicateKind?: string;
  duplicateOfSessionCode?: string;
  bindingStatus: string;
  bindingCandidates: OperationBindingCandidate[];
  importStatus: string;
  importedSessionCode?: string;
  createdAt: string;
}

export interface OperationImportBatch {
  batchCode: string;
  originalFilename: string;
  fileKind: string;
  sourceChecksumSha256: string;
  fieldMapping: Record<string, string>;
  previewSummary: Record<string, number>;
  status: string;
  createdBy: string;
  confirmedBy?: string;
  confirmedAt?: string;
  createdAt: string;
  rows: OperationImportRow[];
}

export interface PendingOperationBinding {
  sessionCode: string;
  title: string;
  platform: string;
  externalSessionId?: string;
  startedAt: string;
  endedAt: string;
  bindingCode: string;
  revisionNumber: number;
  contentKind?: string;
  contentCode?: string;
  contentRevision?: number;
  candidates: OperationBindingCandidate[];
  evidenceNote: string;
  createdAt: string;
}

export interface MetricDefinitionRef {
  metricKey: string;
  metricCode: string;
  revisionNumber: number;
  name?: string;
  grain?: string;
  unit?: string;
  currency?: string;
  valueType?: string;
  aggregation?: string;
  eventTimeField?: string;
  timezone?: string;
  businessDayBoundary?: string;
  fingerprintSha256?: string;
}

export interface ContentExposure {
  exposureCode: string;
  sessionCode: string;
  planCode: string;
  variantCode: string;
  releaseCode?: string;
  sceneCode: string;
  startedAt: string;
  endedAt: string;
  sourceKind: string;
  evidenceNote: string;
  confidence: number;
  status: string;
  supersedesExposureCode?: string;
  supersededByExposureCode?: string;
  correctionReason?: string;
  contentKind: string;
  contentCode?: string;
  contentRevision?: number;
  scopeType: string;
  scopeCode?: string;
}

export interface ContentProjection {
  status: string;
  programSegment?: {
    segmentCode: string;
    programPhase?: string;
    semanticGoal?: string;
    productRefs: unknown[];
    ctaActions: unknown[];
  };
  scriptBlocks: Array<{
    blockCode: string;
    moduleType?: string;
    productRef?: string;
    templateModules: Array<{
      templateCode: string;
      revision?: number;
      moduleKey?: string;
    }>;
    ctaIntent: Record<string, unknown>;
  }>;
}

export interface TimeMapping {
  mappingCode: string;
  sessionCode: string;
  revisionNumber: number;
  status: string;
  sourceClock: string;
  sourceKind: string;
  sourceOffsetMs: number;
  driftPpm: number;
  coverageStartMs: number;
  coverageEndMs: number;
  evidenceNote: string;
  actor: string;
  createdAt: string;
}

export interface SessionMetricSnapshot {
  snapshotCode: string;
  sessionCode: string;
  metricKey: string;
  metricCode: string;
  metricRevision: number;
  aggregation: string;
  status: string;
  value?: number;
  sourceEventCount: number;
  eventTimeClock: string;
  valueJsonPointer?: string;
  numeratorJsonPointer?: string;
  denominatorJsonPointer?: string;
  sourceBatches: Array<{
    batchCode: string;
    sourceChecksum?: string;
    status: string;
    includedEventCount: number;
  }>;
  qualitySummary: Record<string, unknown>;
  fingerprintSha256: string;
  createdAt: string;
}

export interface ContentTimeline {
  sessionCode: string;
  startedAt: string;
  endedAt: string;
  totalSeconds: number;
  observedSeconds: number;
  coverageRatio: number;
  unobservedSeconds: number;
  status: string;
  missingPlanCodes: string[];
  timeMapping?: TimeMapping;
  alignmentCoverageRatio: number;
  spans: Array<{
    exposureCode: string;
    planCode: string;
    variantCode: string;
    releaseCode?: string;
    sceneCode: string;
    startedAt: string;
    endedAt: string;
    durationSeconds: number;
    sourceKind: string;
    confidence: number;
    scene: {
      sceneCode: string;
      shotCode?: string;
      title?: string;
      status: string;
    };
    content: ContentProjection;
    layers: Array<{
      layerBlueprintCode?: string;
      role?: string;
      assetCode?: string;
      executionCapability?: string;
    }>;
    sourceStartMs?: number;
    sourceEndMs?: number;
    alignmentStatus: string;
  }>;
}

export interface AttributionGroup {
  scopeType: string;
  scopeCode: string;
  displayLabel: string;
  average: number;
  sampleSize: number;
  sessionCodes: string[];
  sourceEvidence: {
    exposureCount: number;
    releaseBoundExposureCount: number;
    coverageSeconds: number;
    sourceKindCounts: Record<string, number>;
    sceneCodes: string[];
    releaseCodes: string[];
    averageConfidence?: number;
  };
  limitations: string[];
}

export interface AttributionDimensionGroup {
  dimensionType: string;
  dimensionCode: string;
  displayLabel: string;
  metricKey: string;
  descriptiveValueTotal: number;
  averagePerSession: number;
  sampleSize: number;
  sessionCodes: string[];
  exposureCodes: string[];
  observedDurationSeconds: number;
  evidenceLevel: string;
  effectSignalEligible: boolean;
  limitations: string[];
}

export interface AttributionReport {
  reportCode: string;
  metricKey: string;
  evidenceLevel: string;
  status: string;
  sessionCodes: string[];
  metricDefinitionRef?: MetricDefinitionRef;
  qualitySnapshot: {
    publicationScope: string;
    reasons: string[];
    eligibleForDescriptivePublication: boolean;
  };
  fingerprintSha256?: string;
  supersedesReportCode?: string;
  publishedBy?: string;
  publishedAt?: string;
  inputEvidence: {
    sessions: Array<{
      sessionCode: string;
      metricValue?: number;
      snapshotCode?: string;
      snapshotFingerprint?: string;
      eventTimeClock?: string;
      timeMappingCode?: string;
      timeMappingRevision?: number;
    }>;
    exposures: Array<{
      exposureCode: string;
      planCode: string;
      releaseCode?: string;
      sceneCode: string;
      sourceKind: string;
      confidence?: number;
    }>;
  };
  groups: AttributionGroup[];
  dimensionGroups: AttributionDimensionGroup[];
  sceneAllocations: Array<{
    scopeType: string;
    planCode: string;
    sceneCode: string;
    estimatedMetricValue: number;
    observedDurationSeconds: number;
    sourceSessionCodes: string[];
    sourceSessionCount: number;
    sourceKindCounts: Record<string, number>;
    releaseCodes: string[];
    averageConfidence?: number;
    allocationBasis: string;
    limitations: string[];
  }>;
  measuredSceneAllocations: Array<{
    scopeType: string;
    planCode: string;
    sceneCode: string;
    aggregation: string;
    measuredMetricValue?: number;
    numerator?: number;
    denominator?: number;
    eventCount: number;
    sourceSessionCodes: string[];
    sourceSnapshotCodes: string[];
    sourceBucketCodes: string[];
    sourceTimeMappingCodes: string[];
    releaseCodes: string[];
    allocationBasis: string;
    limitations: string[];
  }>;
  measuredSceneAllocationSummary: {
    candidateBucketCount: number;
    allocatedBucketCount: number;
    unallocatedBucketCount: number;
    sessionOnlyBucketCount: number;
    directSessionClockBucketCount: number;
    timeMappedBucketCount: number;
    timeMappingMissingBucketCount: number;
    timeMappingClockMismatchBucketCount: number;
    outsideTimeMappingCoverageBucketCount: number;
  };
  metadata: {
    method: string;
    metricGrain: string;
    selectedSessionCount: number;
    observedSessionCount: number;
    sessionOnlyCount: number;
    sourceKindCounts: Record<string, number>;
    releaseBoundExposureCount: number;
    metricDefinitionState: string;
    sceneAllocationMethod: string;
    sceneAllocationCount: number;
  };
  createdAt: string;
}

function metricDefinitionRef(value: unknown): MetricDefinitionRef | undefined {
  if (!isRecord(value)) return undefined;
  const metricKey = asString(value.metric_key);
  const metricCode = asString(value.metric_code);
  const revisionNumber = asNumber(value.revision_number);
  if (!metricKey || !metricCode || !revisionNumber) return undefined;
  return {
    metricKey,
    metricCode,
    revisionNumber,
    name: asOptionalString(value.name),
    grain: asOptionalString(value.grain),
    unit: asOptionalString(value.unit),
    currency: asOptionalString(value.currency),
    valueType: asOptionalString(value.value_type),
    aggregation: asOptionalString(value.aggregation),
    eventTimeField: asOptionalString(value.event_time_field),
    timezone: asOptionalString(value.timezone),
    businessDayBoundary: asOptionalString(value.business_day_boundary),
    fingerprintSha256: asOptionalString(value.fingerprint_sha256),
  };
}

export interface SchedulePlan {
  scheduleCode: string;
  title: string;
  roomId: string;
  startsAt: string;
  durationMinutes: number;
  status: string;
  conflictCodes: string[];
}

const strings = (value: unknown) =>
  asArray(value).flatMap((item) => (typeof item === "string" ? [item] : []));

function session(value: unknown): OperationSession {
  if (!isRecord(value)) throw new Error("运营场次响应无效");
  return {
    sessionCode: asString(value.session_code),
    title: asString(value.title),
    platform: asString(value.platform),
    externalSessionId: asOptionalString(value.external_session_id),
    accountId: asOptionalString(value.account_id),
    targetResourceId: asOptionalString(value.target_resource_id),
    sourceTimezone: asString(value.source_timezone, "UTC"),
    sourceEvidence: isRecord(value.source_evidence) ? value.source_evidence : {},
    projectCode: asOptionalString(value.content_project_code),
    liveRoomPlanCode: asOptionalString(value.live_room_plan_code),
    videoPlanCode: asOptionalString(value.video_plan_code),
    boundContentKind: asOptionalString(value.bound_content_kind),
    boundContentCode: asOptionalString(value.bound_content_code),
    boundContentRevision:
      typeof value.bound_content_revision === "number"
        ? value.bound_content_revision
        : undefined,
    bindingStatus: asString(value.binding_status, "pending"),
    variantCode: asOptionalString(value.variant_code),
    releaseCode: asOptionalString(value.release_code),
    startedAt: asString(value.started_at),
    endedAt: asString(value.ended_at),
    metrics: isRecord(value.metrics)
      ? Object.fromEntries(
          Object.entries(value.metrics).map(([key, item]) => [
            key,
            typeof item === "number" ? item : 0,
          ]),
        )
      : {},
    metricDefinitionRefs: asArray(value.metric_definition_refs).flatMap(
      (reference) => {
        const parsed = metricDefinitionRef(reference);
        return parsed ? [parsed] : [];
      },
    ),
    sourceKind: asString(value.source_kind),
  };
}

function importFinding(value: unknown): OperationImportFinding | undefined {
  if (!isRecord(value)) return undefined;
  const field = asString(value.field);
  const code = asString(value.code);
  const message = asString(value.message);
  return field && code && message ? { field, code, message } : undefined;
}

function bindingCandidate(value: unknown): OperationBindingCandidate | undefined {
  if (!isRecord(value)) return undefined;
  const contentKind = asString(value.content_kind);
  const contentCode = asString(value.content_code);
  if (!contentKind || !contentCode) return undefined;
  return {
    contentKind,
    contentCode,
    contentRevision:
      typeof value.content_revision === "number"
        ? value.content_revision
        : undefined,
    title: asOptionalString(value.title),
  };
}

function importBatch(value: unknown): OperationImportBatch {
  if (!isRecord(value)) throw new Error("运营导入批次响应无效");
  return {
    batchCode: asString(value.batch_code),
    originalFilename: asString(value.original_filename),
    fileKind: asString(value.file_kind),
    sourceChecksumSha256: asString(value.source_checksum_sha256),
    fieldMapping: isRecord(value.field_mapping)
      ? Object.fromEntries(
          Object.entries(value.field_mapping).flatMap(([key, item]) =>
            typeof item === "string" ? [[key, item]] : [],
          ),
        )
      : {},
    previewSummary: isRecord(value.preview_summary)
      ? Object.fromEntries(
          Object.entries(value.preview_summary).flatMap(([key, item]) =>
            typeof item === "number" ? [[key, item]] : [],
          ),
        )
      : {},
    status: asString(value.status),
    createdBy: asString(value.created_by),
    confirmedBy: asOptionalString(value.confirmed_by),
    confirmedAt: asOptionalString(value.confirmed_at),
    createdAt: asString(value.created_at),
    rows: asArray(value.rows).flatMap((row) => {
      if (!isRecord(row)) return [];
      return [
        {
          rowNumber: asNumber(row.row_number),
          rowFingerprintSha256: asString(row.row_fingerprint_sha256),
          rawValues: isRecord(row.raw_values)
            ? Object.fromEntries(
                Object.entries(row.raw_values).flatMap(([key, item]) =>
                  typeof item === "string" ? [[key, item]] : [],
                ),
              )
            : {},
          normalizedPayload: isRecord(row.normalized_payload)
            ? row.normalized_payload
            : {},
          validationErrors: asArray(row.validation_errors).flatMap((item) => {
            const parsed = importFinding(item);
            return parsed ? [parsed] : [];
          }),
          validationWarnings: asArray(row.validation_warnings).flatMap((item) => {
            const parsed = importFinding(item);
            return parsed ? [parsed] : [];
          }),
          duplicateKind: asOptionalString(row.duplicate_kind),
          duplicateOfSessionCode: asOptionalString(
            row.duplicate_of_session_code,
          ),
          bindingStatus: asString(row.binding_status),
          bindingCandidates: asArray(row.binding_candidates).flatMap((item) => {
            const parsed = bindingCandidate(item);
            return parsed ? [parsed] : [];
          }),
          importStatus: asString(row.import_status),
          importedSessionCode: asOptionalString(row.imported_session_code),
          createdAt: asString(row.created_at),
        },
      ];
    }),
  };
}

function pendingBinding(value: unknown): PendingOperationBinding {
  if (!isRecord(value)) throw new Error("待处理内容绑定响应无效");
  return {
    sessionCode: asString(value.session_code),
    title: asString(value.title),
    platform: asString(value.platform),
    externalSessionId: asOptionalString(value.external_session_id),
    startedAt: asString(value.started_at),
    endedAt: asString(value.ended_at),
    bindingCode: asString(value.binding_code),
    revisionNumber: asNumber(value.revision_number),
    contentKind: asOptionalString(value.content_kind),
    contentCode: asOptionalString(value.content_code),
    contentRevision:
      typeof value.content_revision === "number"
        ? value.content_revision
        : undefined,
    candidates: asArray(value.candidates).flatMap((item) => {
      const parsed = bindingCandidate(item);
      return parsed ? [parsed] : [];
    }),
    evidenceNote: asString(value.evidence_note),
    createdAt: asString(value.created_at),
  };
}

function exposure(value: unknown): ContentExposure {
  if (!isRecord(value)) throw new Error("内容曝光响应无效");
  return {
    exposureCode: asString(value.exposure_code),
    sessionCode: asString(value.session_code),
    planCode: asString(value.plan_code),
    variantCode: asString(value.variant_code),
    releaseCode: asOptionalString(value.release_code),
    sceneCode: asString(value.scene_code),
    startedAt: asString(value.started_at),
    endedAt: asString(value.ended_at),
    sourceKind: asString(value.source_kind),
    evidenceNote: asString(value.evidence_note),
    confidence: asNumber(value.confidence),
    status: asString(value.status),
    supersedesExposureCode: asOptionalString(value.supersedes_exposure_code),
    supersededByExposureCode: asOptionalString(value.superseded_by_exposure_code),
    correctionReason: asOptionalString(value.correction_reason),
    contentKind: asString(value.content_kind, "live_room_plan"),
    contentCode: asOptionalString(value.content_code),
    contentRevision:
      typeof value.content_revision === "number"
        ? value.content_revision
        : undefined,
    scopeType: asString(value.scope_type, "maitu_scene"),
    scopeCode: asOptionalString(value.scope_code),
  };
}

function contentProjection(value: unknown): ContentProjection {
  const raw = isRecord(value) ? value : {};
  const segment = isRecord(raw.program_segment) ? raw.program_segment : undefined;
  return {
    status: asString(raw.status, "missing_source_projection"),
    programSegment: segment
      ? {
          segmentCode: asString(segment.segment_code),
          programPhase: asOptionalString(segment.program_phase),
          semanticGoal: asOptionalString(segment.semantic_goal),
          productRefs: asArray(segment.product_refs),
          ctaActions: asArray(segment.cta_actions),
        }
      : undefined,
    scriptBlocks: asArray(raw.script_blocks).flatMap((block) => {
      if (!isRecord(block)) return [];
      const blockCode = asString(block.block_code);
      if (!blockCode) return [];
      return [
        {
          blockCode,
          moduleType: asOptionalString(block.module_type),
          productRef: asOptionalString(block.product_ref),
          templateModules: asArray(block.template_modules).flatMap((module) => {
            if (!isRecord(module)) return [];
            const templateCode = asString(module.template_code);
            return templateCode
              ? [
                  {
                    templateCode,
                    revision:
                      typeof module.revision === "number"
                        ? module.revision
                        : undefined,
                    moduleKey: asOptionalString(module.module_key),
                  },
                ]
              : [];
          }),
          ctaIntent: isRecord(block.cta_intent) ? block.cta_intent : {},
        },
      ];
    }),
  };
}

function timeMapping(value: unknown): TimeMapping | undefined {
  if (!isRecord(value)) return undefined;
  const mappingCode = asString(value.mapping_code);
  const sessionCode = asString(value.session_code);
  const revisionNumber = asNumber(value.revision_number);
  if (!mappingCode || !sessionCode || !revisionNumber) return undefined;
  return {
    mappingCode,
    sessionCode,
    revisionNumber,
    status: asString(value.status),
    sourceClock: asString(value.source_clock),
    sourceKind: asString(value.source_kind),
    sourceOffsetMs: asNumber(value.source_offset_ms),
    driftPpm: asNumber(value.drift_ppm),
    coverageStartMs: asNumber(value.coverage_start_ms),
    coverageEndMs: asNumber(value.coverage_end_ms),
    evidenceNote: asString(value.evidence_note),
    actor: asString(value.actor),
    createdAt: asString(value.created_at),
  };
}

function sessionMetricSnapshot(value: unknown): SessionMetricSnapshot {
  if (!isRecord(value)) throw new Error("会话指标快照响应无效");
  return {
    snapshotCode: asString(value.snapshot_code),
    sessionCode: asString(value.session_code),
    metricKey: asString(value.metric_key),
    metricCode: asString(value.metric_code),
    metricRevision: asNumber(value.metric_revision),
    aggregation: asString(value.aggregation),
    status: asString(value.status),
    value: typeof value.value === "number" ? value.value : undefined,
    sourceEventCount: asNumber(value.source_event_count),
    eventTimeClock: asString(value.event_time_clock, "session_utc"),
    valueJsonPointer: asOptionalString(value.value_json_pointer),
    numeratorJsonPointer: asOptionalString(value.numerator_json_pointer),
    denominatorJsonPointer: asOptionalString(value.denominator_json_pointer),
    sourceBatches: asArray(value.source_batches).flatMap((batch) => {
      if (!isRecord(batch)) return [];
      const batchCode = asString(batch.batch_code);
      return batchCode
        ? [{
            batchCode,
            sourceChecksum: asOptionalString(batch.source_checksum),
            status: asString(batch.status),
            includedEventCount: asNumber(batch.included_event_count),
          }]
        : [];
    }),
    qualitySummary: isRecord(value.quality_summary) ? value.quality_summary : {},
    fingerprintSha256: asString(value.fingerprint_sha256),
    createdAt: asString(value.created_at),
  };
}

function timeline(value: unknown): ContentTimeline {
  if (!isRecord(value)) throw new Error("内容时间线响应无效");
  return {
    sessionCode: asString(value.session_code),
    startedAt: asString(value.started_at),
    endedAt: asString(value.ended_at),
    totalSeconds: asNumber(value.total_seconds),
    observedSeconds: asNumber(value.observed_seconds),
    coverageRatio: asNumber(value.coverage_ratio),
    unobservedSeconds: asNumber(value.unobserved_seconds),
    status: asString(value.status),
    missingPlanCodes: strings(value.missing_plan_codes),
    timeMapping: timeMapping(value.time_mapping),
    alignmentCoverageRatio: asNumber(value.alignment_coverage_ratio),
    spans: asArray(value.spans).flatMap((span) => {
      if (!isRecord(span)) return [];
      const scene = isRecord(span.scene) ? span.scene : {};
      return [
        {
          exposureCode: asString(span.exposure_code),
          planCode: asString(span.plan_code),
          variantCode: asString(span.variant_code),
          releaseCode: asOptionalString(span.release_code),
          sceneCode: asString(span.scene_code),
          startedAt: asString(span.started_at),
          endedAt: asString(span.ended_at),
          durationSeconds: asNumber(span.duration_seconds),
          sourceKind: asString(span.source_kind),
          confidence: asNumber(span.confidence),
          scene: {
            sceneCode: asString(scene.scene_code),
            shotCode: asOptionalString(scene.shot_code),
            title: asOptionalString(scene.title),
            status: asString(scene.status),
          },
          content: contentProjection(span.content),
          layers: asArray(span.layers).flatMap((layer) =>
            isRecord(layer)
              ? [
                  {
                    layerBlueprintCode: asOptionalString(
                      layer.layer_blueprint_code,
                    ),
                    role: asOptionalString(layer.role),
                    assetCode: asOptionalString(layer.asset_code),
                    executionCapability: asOptionalString(
                      layer.execution_capability,
                    ),
                  },
                ]
              : [],
          ),
          sourceStartMs:
            typeof span.source_start_ms === "number"
              ? span.source_start_ms
              : undefined,
          sourceEndMs:
            typeof span.source_end_ms === "number"
              ? span.source_end_ms
              : undefined,
          alignmentStatus: asString(span.alignment_status, "unmapped"),
        },
      ];
    }),
  };
}

function counts(value: unknown): Record<string, number> {
  return isRecord(value)
    ? Object.fromEntries(
        Object.entries(value).flatMap(([key, item]) =>
          typeof item === "number" ? [[key, item]] : [],
        ),
      )
    : {};
}

function attributionInputEvidence(value: unknown): AttributionReport["inputEvidence"] {
  const raw = isRecord(value) ? value : {};
  return {
    sessions: asArray(raw.sessions).flatMap((item) => {
      if (!isRecord(item)) return [];
      const sessionCode = asString(item.session_code);
      if (!sessionCode) return [];
      const snapshot = isRecord(item.metric_snapshot) ? item.metric_snapshot : {};
      const mapping = isRecord(item.time_mapping) ? item.time_mapping : {};
      return [{
        sessionCode,
        metricValue: typeof item.metric_value === "number" ? item.metric_value : undefined,
        snapshotCode: asOptionalString(snapshot.snapshot_code),
        snapshotFingerprint: asOptionalString(snapshot.fingerprint_sha256),
        eventTimeClock: asOptionalString(snapshot.event_time_clock),
        timeMappingCode: asOptionalString(mapping.mapping_code),
        timeMappingRevision: typeof mapping.revision_number === "number" ? mapping.revision_number : undefined,
      }];
    }),
    exposures: asArray(raw.active_exposures).flatMap((item) => {
      if (!isRecord(item)) return [];
      const exposureCode = asString(item.exposure_code);
      const planCode = asString(item.plan_code);
      const sceneCode = asString(item.scene_code);
      if (!exposureCode || !planCode || !sceneCode) return [];
      return [{
        exposureCode,
        planCode,
        releaseCode: asOptionalString(item.release_code),
        sceneCode,
        sourceKind: asString(item.source_kind),
        confidence: typeof item.confidence === "number" ? item.confidence : undefined,
      }];
    }),
  };
}

function report(value: unknown): AttributionReport {
  if (!isRecord(value)) throw new Error("归因响应无效");
  const raw = isRecord(value.results) ? value.results : {};
  const groupsRaw = isRecord(raw.groups) ? raw.groups : raw;
  const metadata = isRecord(raw.metadata) ? raw.metadata : {};
  const quality = isRecord(value.quality_snapshot)
    ? value.quality_snapshot
    : {};
  return {
    reportCode: asString(value.report_code),
    metricKey: asString(value.metric_key),
    evidenceLevel: asString(value.evidence_level),
    status: asString(value.status, "legacy"),
    sessionCodes: strings(value.session_codes),
    metricDefinitionRef: metricDefinitionRef(value.metric_definition_ref),
    qualitySnapshot: {
      publicationScope: asString(quality.publication_scope, "descriptive_only"),
      reasons: strings(quality.reasons),
      eligibleForDescriptivePublication:
        quality.eligible_for_descriptive_publication === true,
    },
    fingerprintSha256: asOptionalString(value.fingerprint_sha256),
    supersedesReportCode: asOptionalString(value.supersedes_report_code),
    publishedBy: asOptionalString(value.published_by),
    publishedAt: asOptionalString(value.published_at),
    inputEvidence: attributionInputEvidence(value.input_snapshot),
    groups: Object.entries(groupsRaw).flatMap(([key, item]) => {
      if (!isRecord(item)) return [];
      const evidence = isRecord(item.source_evidence)
        ? item.source_evidence
        : {};
      return [
        {
          scopeType: asString(item.scope_type, "legacy"),
          scopeCode: asString(item.scope_code, key),
          displayLabel: asString(item.display_label, key),
          average: asNumber(item.average),
          sampleSize: asNumber(item.sample_size),
          sessionCodes: strings(item.session_codes),
          sourceEvidence: {
            exposureCount: asNumber(evidence.exposure_count),
            releaseBoundExposureCount: asNumber(
              evidence.release_bound_exposure_count,
            ),
            coverageSeconds: asNumber(evidence.coverage_seconds),
            sourceKindCounts: counts(evidence.source_kind_counts),
            sceneCodes: strings(evidence.scene_codes),
            releaseCodes: strings(evidence.release_codes),
            averageConfidence:
              typeof evidence.average_confidence === "number"
                ? evidence.average_confidence
                : undefined,
          },
          limitations: strings(item.limitations),
        },
      ];
    }),
    dimensionGroups: asArray(raw.dimension_groups).flatMap((item) => {
      if (!isRecord(item)) return [];
      const dimensionType = asString(item.dimension_type);
      const dimensionCode = asString(item.dimension_code);
      if (!dimensionType || !dimensionCode) return [];
      return [{
        dimensionType,
        dimensionCode,
        displayLabel: asString(item.display_label, dimensionCode),
        metricKey: asString(item.metric_key, asString(value.metric_key)),
        descriptiveValueTotal: asNumber(item.descriptive_value_total),
        averagePerSession: asNumber(item.average_per_session),
        sampleSize: asNumber(item.sample_size),
        sessionCodes: strings(item.session_codes),
        exposureCodes: strings(item.exposure_codes),
        observedDurationSeconds: asNumber(item.observed_duration_seconds),
        evidenceLevel: asString(item.evidence_level, "descriptive"),
        effectSignalEligible: item.effect_signal_eligible === true,
        limitations: strings(item.limitations),
      }];
    }),
    sceneAllocations: asArray(raw.scene_allocations).flatMap((item) => {
      if (!isRecord(item)) return [];
      const planCode = asString(item.plan_code);
      const sceneCode = asString(item.scene_code);
      if (!planCode || !sceneCode) return [];
      return [{
        scopeType: asString(item.scope_type, "observed_scene_duration_allocation"),
        planCode,
        sceneCode,
        estimatedMetricValue: asNumber(item.estimated_metric_value),
        observedDurationSeconds: asNumber(item.observed_duration_seconds),
        sourceSessionCodes: strings(item.source_session_codes),
        sourceSessionCount: asNumber(item.source_session_count),
        sourceKindCounts: counts(item.source_kind_counts),
        releaseCodes: strings(item.release_codes),
        averageConfidence: typeof item.average_confidence === "number" ? item.average_confidence : undefined,
        allocationBasis: asString(item.allocation_basis),
        limitations: strings(item.limitations),
      }];
    }),
    measuredSceneAllocations: asArray(raw.measured_scene_allocations).flatMap((item) => {
      if (!isRecord(item)) return [];
      const planCode = asString(item.plan_code);
      const sceneCode = asString(item.scene_code);
      if (!planCode || !sceneCode) return [];
      return [{
        scopeType: asString(item.scope_type, "measured_event_time_bucket"),
        planCode,
        sceneCode,
        aggregation: asString(item.aggregation),
        measuredMetricValue: typeof item.measured_metric_value === "number" ? item.measured_metric_value : undefined,
        numerator: typeof item.numerator === "number" ? item.numerator : undefined,
        denominator: typeof item.denominator === "number" ? item.denominator : undefined,
        eventCount: asNumber(item.event_count),
        sourceSessionCodes: strings(item.source_session_codes),
        sourceSnapshotCodes: strings(item.source_snapshot_codes),
        sourceBucketCodes: strings(item.source_bucket_codes),
        sourceTimeMappingCodes: strings(item.source_time_mapping_codes),
        releaseCodes: strings(item.release_codes),
        allocationBasis: asString(item.allocation_basis),
        limitations: strings(item.limitations),
      }];
    }),
    measuredSceneAllocationSummary: (() => {
      const summary = isRecord(raw.measured_scene_allocation_summary)
        ? raw.measured_scene_allocation_summary
        : {};
      return {
        candidateBucketCount: asNumber(summary.candidate_bucket_count),
        allocatedBucketCount: asNumber(summary.allocated_bucket_count),
        unallocatedBucketCount: asNumber(summary.unallocated_bucket_count),
        sessionOnlyBucketCount: asNumber(summary.session_only_bucket_count),
        directSessionClockBucketCount: asNumber(summary.direct_session_clock_bucket_count),
        timeMappedBucketCount: asNumber(summary.time_mapped_bucket_count),
        timeMappingMissingBucketCount: asNumber(summary.time_mapping_missing_bucket_count),
        timeMappingClockMismatchBucketCount: asNumber(summary.time_mapping_clock_mismatch_bucket_count),
        outsideTimeMappingCoverageBucketCount: asNumber(summary.outside_time_mapping_coverage_bucket_count),
      };
    })(),
    metadata: {
      method: asString(metadata.method, "legacy_session_summary"),
      metricGrain: asString(metadata.metric_grain, "operation_session"),
      selectedSessionCount: asNumber(
        metadata.selected_session_count,
        strings(value.session_codes).length,
      ),
      observedSessionCount: asNumber(metadata.observed_session_count),
      sessionOnlyCount: asNumber(metadata.session_only_count),
      sourceKindCounts: counts(metadata.source_kind_counts),
      releaseBoundExposureCount: asNumber(
        metadata.release_bound_exposure_count,
      ),
      metricDefinitionState: asString(
        metadata.metric_definition_state,
        "metric_unpinned",
      ),
      sceneAllocationMethod: asString(metadata.scene_allocation_method),
      sceneAllocationCount: asNumber(metadata.scene_allocation_count),
    },
    createdAt: asString(value.created_at),
  };
}

function schedule(value: unknown): SchedulePlan {
  if (!isRecord(value)) throw new Error("排播响应无效");
  return {
    scheduleCode: asString(value.schedule_code),
    title: asString(value.title),
    roomId: asString(value.target_live_room_id),
    startsAt: asString(value.starts_at),
    durationMinutes: asNumber(value.duration_minutes),
    status: asString(value.status),
    conflictCodes: strings(value.conflict_codes),
  };
}

export const operationsApi = {
  importTemplateUrl: (format: "csv" | "xlsx") =>
    `${ROOT}/import-template?format=${format}`,
  importSourceUrl: (batchCode: string) =>
    `${ROOT}/import-batches/${encodeURIComponent(batchCode)}/source`,
  previewImport: (file: File) => {
    const form = new FormData();
    form.set("file", file);
    form.set("actor", "functional-operator");
    return requestJson<unknown>(`${ROOT}/import-batches/preview`, {
      method: "POST",
      body: form,
    }).then(importBatch);
  },
  listImportBatches: () =>
    requestJson<unknown[]>(`${ROOT}/import-batches`).then((rows) =>
      rows.map(importBatch),
    ),
  confirmImportBatch: (batchCode: string) =>
    postJson<unknown>(
      `${ROOT}/import-batches/${encodeURIComponent(batchCode)}/confirm`,
      { actor: "functional-operator" },
    ).then(importBatch),
  listPendingBindings: () =>
    requestJson<unknown[]>(`${ROOT}/pending-bindings`).then((rows) =>
      rows.map(pendingBinding),
    ),
  resolveSessionBinding: (
    sessionCode: string,
    payload: Record<string, unknown>,
  ) =>
    postJson<unknown>(
      `${ROOT}/sessions/${encodeURIComponent(sessionCode)}/binding`,
      payload,
    ),
  listSessions: () => requestJson<unknown[]>(`${ROOT}/sessions`).then((rows) => rows.map(session)),
  createSession: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/sessions`, payload).then(session),
  listSessionMetricSnapshots: (sessionCode: string) => requestJson<unknown[]>(`${ROOT}/sessions/${encodeURIComponent(sessionCode)}/metric-snapshots`).then((rows) => rows.map(sessionMetricSnapshot)),
  createSessionMetricSnapshot: (sessionCode: string, payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/sessions/${encodeURIComponent(sessionCode)}/metric-snapshots`, payload).then(sessionMetricSnapshot),
  getContentTimeline: (sessionCode: string) => requestJson<unknown>(`${ROOT}/sessions/${encodeURIComponent(sessionCode)}/content-timeline`).then(timeline),
  listTimeMappings: (sessionCode: string) => requestJson<unknown[]>(`${ROOT}/sessions/${encodeURIComponent(sessionCode)}/time-mappings`).then((rows) => rows.flatMap((row) => {
    const parsed = timeMapping(row);
    return parsed ? [parsed] : [];
  })),
  createTimeMapping: (sessionCode: string, payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/sessions/${encodeURIComponent(sessionCode)}/time-mappings`, payload).then((row) => {
    const parsed = timeMapping(row);
    if (!parsed) throw new Error("时间对齐响应无效");
    return parsed;
  }),
  listExposures: () => requestJson<unknown[]>(`${ROOT}/exposures`).then((rows) => rows.map(exposure)),
  createExposure: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/exposures`, payload).then(exposure),
  correctExposure: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/exposure-corrections`, payload).then(exposure),
  listReports: () => requestJson<unknown[]>(`${ROOT}/attribution-reports`).then((rows) => rows.map(report)),
  createReport: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/attribution-reports`, payload).then(report),
  publishDescriptiveReport: (reportCode: string) => postJson<unknown>(`${ROOT}/attribution-reports/${encodeURIComponent(reportCode)}/publish-descriptive`, { actor: "functional-operator" }).then(report),
  rerunReport: (reportCode: string) => postJson<unknown>(`${ROOT}/attribution-reports/${encodeURIComponent(reportCode)}/rerun`, {}).then(report),
  listSchedules: () => requestJson<unknown[]>(`${ROOT}/schedule-plans`).then((rows) => rows.map(schedule)),
  createSchedule: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/schedule-plans`, payload).then(schedule),
};
