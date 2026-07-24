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
  variantCode?: string;
  releaseCode?: string;
  startedAt: string;
  endedAt: string;
  metrics: Record<string, number>;
  metricDefinitionRefs: MetricDefinitionRef[];
  sourceKind: string;
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

export interface AttributionReport {
  reportCode: string;
  metricKey: string;
  evidenceLevel: string;
  sessionCodes: string[];
  metricDefinitionRef?: MetricDefinitionRef;
  groups: AttributionGroup[];
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

function report(value: unknown): AttributionReport {
  if (!isRecord(value)) throw new Error("归因响应无效");
  const raw = isRecord(value.results) ? value.results : {};
  const groupsRaw = isRecord(raw.groups) ? raw.groups : raw;
  const metadata = isRecord(raw.metadata) ? raw.metadata : {};
  return {
    reportCode: asString(value.report_code),
    metricKey: asString(value.metric_key),
    evidenceLevel: asString(value.evidence_level),
    sessionCodes: strings(value.session_codes),
    metricDefinitionRef: metricDefinitionRef(value.metric_definition_ref),
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
  listSessions: () => requestJson<unknown[]>(`${ROOT}/sessions`).then((rows) => rows.map(session)),
  createSession: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/sessions`, payload).then(session),
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
  listSchedules: () => requestJson<unknown[]>(`${ROOT}/schedule-plans`).then((rows) => rows.map(schedule)),
  createSchedule: (payload: Record<string, unknown>) => postJson<unknown>(`${ROOT}/schedule-plans`, payload).then(schedule),
};
