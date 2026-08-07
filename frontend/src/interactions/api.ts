import {
  asArray,
  asBoolean,
  asNumber,
  asOptionalString,
  asString,
  isRecord,
  postJson,
  queryString,
  requestJson,
} from "../workbench/api";

const ROOT = "/api/maitu/interactions";

export interface InteractionSource {
  sourceCode: string;
  externalAccountId?: number;
  accountName?: string;
  status: string;
  timezone: string;
  dailySyncTime: string;
  rescanDays: number;
  lastFullSyncAt?: string;
  lastIncrementalSyncAt?: string;
  nextSyncAt?: string;
  retryAfter?: string;
  lastErrorCode?: string;
  lastErrorMessage?: string;
  analysisConfigured: boolean;
}

export interface InteractionPlatform {
  externalPlatformId: number;
  platformCode: string;
  platformName: string;
  available: boolean;
  sessionCount: number;
  interactionCount: number;
  arrivalCount: number;
  effectiveCount: number;
  lastSessionAt?: string;
}

export interface LiveSession {
  id: string;
  externalSessionId: number;
  externalLiveRoomId: number;
  externalPlatformId: number;
  platformCode: string;
  platformName: string;
  platformLiveId?: string;
  title: string;
  liveRoomType?: string;
  startedAt: string;
  endedAt: string;
  durationSeconds: number;
  sourceInteractionCount?: number;
  storedInteractionCount: number;
  arrivalCount: number;
  effectiveCount: number;
  answeredCount: number;
  unansweredCount: number;
  syncComplete: boolean;
  lastInteractionSyncAt?: string;
}

export interface InteractionAnalysis {
  analyzerVersion: string;
  interactionForm: string;
  businessIntent: string;
  topicSummary: string;
  classificationReason: string;
  qualityApplicable: boolean;
  relevanceGrade?: string;
  completenessGrade?: string;
  resolutionGrade?: string;
  overallGrade?: string;
  confidence: number;
  reason?: string;
  createdAt: string;
}

export interface LiveInteraction {
  id: string;
  externalInteractionId: string;
  externalSessionId: number;
  sessionTitle: string;
  externalPlatformId: number;
  platformName: string;
  interactionType: number;
  content: string;
  normalizedContent: string;
  arrival: boolean;
  publisherName?: string;
  publisherRole?: string;
  itemId?: string;
  publishedAt?: string;
  digitalReplyContent?: string;
  digitalRepliedAt?: string;
  bulletReplyContent?: string;
  bulletRepliedAt?: string;
  answered: boolean;
  analysisStatus: string;
  topicStatus: string;
  topicCode?: string;
  topicTitle?: string;
  analysis?: InteractionAnalysis;
}

export interface SyncRun {
  runCode: string;
  syncMode: string;
  targetExternalSessionId?: number;
  status: string;
  attempt: number;
  resultSummary: Record<string, unknown>;
  errorCode?: string;
  errorMessage?: string;
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface AnalysisSummary {
  analyzerVersion: string;
  analysisConfigured: boolean;
  total: number;
  analyzed: number;
  pending: number;
  answered: number;
  unanswered: number;
  forms: Record<string, number>;
  intents: Record<string, number>;
  grades: Record<string, number>;
}

export interface IntentBreakdown {
  businessIntent: string;
  label: string;
  total: number;
  answered: number;
  unanswered: number;
  answerRate: number;
  good: number;
  fair: number;
  poor: number;
}

export interface AnalysisDashboard {
  analyzerVersion: string;
  analysisConfigured: boolean;
  total: number;
  classified: number;
  classificationPending: number;
  topicPending: number;
  answered: number;
  unanswered: number;
  qualityEvaluated: number;
  intents: IntentBreakdown[];
}

export interface InteractionTopic {
  topicCode: string;
  title: string;
  businessIntent: string;
  total: number;
  answered: number;
  unanswered: number;
  answerRate: number;
  good: number;
  fair: number;
  poor: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

function numberMap(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  return Object.fromEntries(
    Object.entries(value).flatMap(([key, item]) =>
      typeof item === "number" && Number.isFinite(item) ? [[key, item]] : [],
    ),
  );
}

function source(value: unknown): InteractionSource {
  if (!isRecord(value)) throw new Error("互动数据源响应无效");
  return {
    sourceCode: asString(value.source_code),
    externalAccountId:
      typeof value.external_account_id === "number" ? value.external_account_id : undefined,
    accountName: asOptionalString(value.account_name),
    status: asString(value.status, "unbound"),
    timezone: asString(value.timezone, "Asia/Shanghai"),
    dailySyncTime: asString(value.daily_sync_time, "02:00"),
    rescanDays: asNumber(value.rescan_days, 7),
    lastFullSyncAt: asOptionalString(value.last_full_sync_at),
    lastIncrementalSyncAt: asOptionalString(value.last_incremental_sync_at),
    nextSyncAt: asOptionalString(value.next_sync_at),
    retryAfter: asOptionalString(value.retry_after),
    lastErrorCode: asOptionalString(value.last_error_code),
    lastErrorMessage: asOptionalString(value.last_error_message),
    analysisConfigured: asBoolean(value.analysis_configured),
  };
}

function platform(value: unknown): InteractionPlatform {
  if (!isRecord(value)) throw new Error("直播平台响应无效");
  return {
    externalPlatformId: asNumber(value.external_platform_id),
    platformCode: asString(value.platform_code),
    platformName: asString(value.platform_name),
    available: asBoolean(value.is_available),
    sessionCount: asNumber(value.session_count),
    interactionCount: asNumber(value.interaction_count),
    arrivalCount: asNumber(value.arrival_count),
    effectiveCount: asNumber(value.effective_count),
    lastSessionAt: asOptionalString(value.last_session_at),
  };
}

function liveSession(value: unknown): LiveSession {
  if (!isRecord(value)) throw new Error("直播场次响应无效");
  return {
    id: asString(value.id),
    externalSessionId: asNumber(value.external_session_id),
    externalLiveRoomId: asNumber(value.external_live_room_id),
    externalPlatformId: asNumber(value.external_platform_id),
    platformCode: asString(value.platform_code),
    platformName: asString(value.platform_name),
    platformLiveId: asOptionalString(value.platform_live_id),
    title: asString(value.title, "未命名直播场次"),
    liveRoomType: asOptionalString(value.live_room_type),
    startedAt: asString(value.started_at),
    endedAt: asString(value.ended_at),
    durationSeconds: asNumber(value.duration_seconds),
    sourceInteractionCount:
      typeof value.source_interaction_count === "number"
        ? value.source_interaction_count
        : undefined,
    storedInteractionCount: asNumber(value.stored_interaction_count),
    arrivalCount: asNumber(value.arrival_count),
    effectiveCount: asNumber(value.effective_count),
    answeredCount: asNumber(value.answered_count),
    unansweredCount: asNumber(value.unanswered_count),
    syncComplete: asBoolean(value.is_sync_complete),
    lastInteractionSyncAt: asOptionalString(value.last_interaction_sync_at),
  };
}

function analysis(value: unknown): InteractionAnalysis | undefined {
  if (!isRecord(value)) return undefined;
  return {
    analyzerVersion: asString(value.analyzer_version),
    interactionForm: asString(value.interaction_form),
    businessIntent: asString(value.business_intent),
    topicSummary: asString(value.topic_summary),
    classificationReason: asString(value.classification_reason),
    qualityApplicable: asBoolean(value.quality_applicable),
    relevanceGrade: asOptionalString(value.relevance_grade),
    completenessGrade: asOptionalString(value.completeness_grade),
    resolutionGrade: asOptionalString(value.resolution_grade),
    overallGrade: asOptionalString(value.overall_grade),
    confidence: asNumber(value.confidence),
    reason: asOptionalString(value.reason),
    createdAt: asString(value.created_at),
  };
}

function interaction(value: unknown): LiveInteraction {
  if (!isRecord(value)) throw new Error("用户互动响应无效");
  return {
    id: asString(value.id),
    externalInteractionId: asString(value.external_interaction_id),
    externalSessionId: asNumber(value.external_session_id),
    sessionTitle: asString(value.session_title),
    externalPlatformId: asNumber(value.external_platform_id),
    platformName: asString(value.platform_name),
    interactionType: asNumber(value.interaction_type),
    content: typeof value.content === "string" ? value.content : "",
    normalizedContent:
      typeof value.normalized_content === "string" ? value.normalized_content : "",
    arrival: asBoolean(value.is_arrival),
    publisherName: asOptionalString(value.publisher_name),
    publisherRole: asOptionalString(value.publisher_role),
    itemId: asOptionalString(value.item_id),
    publishedAt: asOptionalString(value.published_at),
    digitalReplyContent: asOptionalString(value.digital_reply_content),
    digitalRepliedAt: asOptionalString(value.digital_replied_at),
    bulletReplyContent: asOptionalString(value.bullet_reply_content),
    bulletRepliedAt: asOptionalString(value.bullet_replied_at),
    answered: asBoolean(value.is_answered),
    analysisStatus: asString(value.analysis_status, "pending"),
    topicStatus: asString(value.topic_status, "pending"),
    topicCode: asOptionalString(value.topic_code),
    topicTitle: asOptionalString(value.topic_title),
    analysis: analysis(value.analysis),
  };
}

function intentBreakdown(value: unknown): IntentBreakdown {
  if (!isRecord(value)) throw new Error("意图统计响应无效");
  return {
    businessIntent: asString(value.business_intent),
    label: asString(value.label),
    total: asNumber(value.total),
    answered: asNumber(value.answered),
    unanswered: asNumber(value.unanswered),
    answerRate: asNumber(value.answer_rate),
    good: asNumber(value.good),
    fair: asNumber(value.fair),
    poor: asNumber(value.poor),
  };
}

function interactionTopic(value: unknown): InteractionTopic {
  if (!isRecord(value)) throw new Error("问题组响应无效");
  return {
    topicCode: asString(value.topic_code),
    title: asString(value.title),
    businessIntent: asString(value.business_intent),
    total: asNumber(value.total),
    answered: asNumber(value.answered),
    unanswered: asNumber(value.unanswered),
    answerRate: asNumber(value.answer_rate),
    good: asNumber(value.good),
    fair: asNumber(value.fair),
    poor: asNumber(value.poor),
  };
}

function page<T>(value: unknown, parser: (item: unknown) => T): Page<T> {
  if (!isRecord(value)) throw new Error("分页响应无效");
  return {
    items: asArray(value.items).map(parser),
    total: asNumber(value.total),
    limit: asNumber(value.limit, 50),
    offset: asNumber(value.offset),
  };
}

function syncRun(value: unknown): SyncRun {
  if (!isRecord(value)) throw new Error("同步任务响应无效");
  return {
    runCode: asString(value.run_code),
    syncMode: asString(value.sync_mode),
    targetExternalSessionId:
      typeof value.target_external_session_id === "number"
        ? value.target_external_session_id
        : undefined,
    status: asString(value.status),
    attempt: asNumber(value.attempt),
    resultSummary: isRecord(value.result_summary) ? value.result_summary : {},
    errorCode: asOptionalString(value.error_code),
    errorMessage: asOptionalString(value.error_message),
    startedAt: asOptionalString(value.started_at),
    completedAt: asOptionalString(value.completed_at),
    createdAt: asString(value.created_at),
    updatedAt: asString(value.updated_at),
  };
}

export const interactionsApi = {
  source: () => requestJson<unknown>(`${ROOT}/source`).then(source),
  platforms: () =>
    requestJson<unknown[]>(`${ROOT}/platforms`).then((items) => items.map(platform)),
  sessions: (params: { platformId?: number; search?: string; limit?: number; offset?: number }) =>
    requestJson<unknown>(
      `${ROOT}/sessions${queryString({
        platform_id: params.platformId,
        search: params.search,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      })}`,
    ).then((value) => page(value, liveSession)),
  sessionItems: (params: {
    externalSessionId: number;
    includeArrivals?: boolean;
    answered?: boolean;
    search?: string;
    limit?: number;
    offset?: number;
  }) =>
    requestJson<unknown>(
      `${ROOT}/sessions/${params.externalSessionId}/items${queryString({
        include_arrivals: params.includeArrivals ?? false,
        answered: params.answered,
        search: params.search,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      })}`,
    ).then((value) => page(value, interaction)),
  analysisSummary: () =>
    requestJson<unknown>(`${ROOT}/analysis/summary`).then((value) => {
      if (!isRecord(value)) throw new Error("互动分析汇总响应无效");
      return {
        analyzerVersion: asString(value.analyzer_version),
        analysisConfigured: asBoolean(value.analysis_configured),
        total: asNumber(value.total),
        analyzed: asNumber(value.analyzed),
        pending: asNumber(value.pending),
        answered: asNumber(value.answered),
        unanswered: asNumber(value.unanswered),
        forms: numberMap(value.forms),
        intents: numberMap(value.intents),
        grades: numberMap(value.grades),
      } satisfies AnalysisSummary;
    }),
  analysisDashboard: (params: { platformId?: number; externalSessionId?: number } = {}) =>
    requestJson<unknown>(
      `${ROOT}/analysis/dashboard${queryString({
        platform_id: params.platformId,
        external_session_id: params.externalSessionId,
      })}`,
    ).then((value) => {
      if (!isRecord(value)) throw new Error("互动分析仪表盘响应无效");
      return {
        analyzerVersion: asString(value.analyzer_version),
        analysisConfigured: asBoolean(value.analysis_configured),
        total: asNumber(value.total),
        classified: asNumber(value.classified),
        classificationPending: asNumber(value.classification_pending),
        topicPending: asNumber(value.topic_pending),
        answered: asNumber(value.answered),
        unanswered: asNumber(value.unanswered),
        qualityEvaluated: asNumber(value.quality_evaluated),
        intents: asArray(value.intents).map(intentBreakdown),
      } satisfies AnalysisDashboard;
    }),
  analysisTopics: (params: {
    businessIntent?: string;
    platformId?: number;
    externalSessionId?: number;
    limit?: number;
    offset?: number;
  } = {}) =>
    requestJson<unknown>(
      `${ROOT}/analysis/topics${queryString({
        business_intent: params.businessIntent,
        platform_id: params.platformId,
        external_session_id: params.externalSessionId,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      })}`,
    ).then((value) => page(value, interactionTopic)),
  analysisItems: (params: {
    platformId?: number;
    externalSessionId?: number;
    answered?: boolean;
    interactionForm?: string;
    businessIntent?: string;
    overallGrade?: string;
    topicCode?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }) =>
    requestJson<unknown>(
      `${ROOT}/analysis/items${queryString({
        platform_id: params.platformId,
        external_session_id: params.externalSessionId,
        answered: params.answered,
        interaction_form: params.interactionForm,
        business_intent: params.businessIntent,
        overall_grade: params.overallGrade,
        topic_code: params.topicCode,
        search: params.search,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      })}`,
    ).then((value) => page(value, interaction)),
  syncRuns: () =>
    requestJson<unknown[]>(`${ROOT}/sync-runs?limit=20`).then((items) =>
      items.map(syncRun),
    ),
  startSync: (payload: {
    syncMode?: "full" | "incremental" | "session";
    targetExternalSessionId?: number;
  } = {}) =>
    postJson<unknown>(`${ROOT}/sync-runs`, {
      sync_mode: payload.syncMode ?? "incremental",
      target_external_session_id: payload.targetExternalSessionId,
      requested_by: "console-operator",
    }).then(syncRun),
};
