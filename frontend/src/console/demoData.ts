import type { ConsoleEntityDetail, ConsoleNotification, ConsoleSearchResult, ConsoleSession, ConsoleTask } from "./types";


export const DEMO_SESSION: ConsoleSession = {
  operatorId: "operator.demo",
  roles: ["control_plane_operator"],
  authScheme: "bearer_memory",
};

export const DEMO_TASKS: ConsoleTask[] = [
  {
    itemCode: "TASK-REVIEW-0142",
    itemType: "human_task",
    title: "模板发布复核",
    status: "open",
    priority: 20,
    summary: "确认外部录屏模板仅用于内容策略与近似视觉参考",
    href: "/research/live-sources?view=drafts&template=DY-TPL-20260722-001",
    dueAt: "2026-07-23T13:30:00Z",
    updatedAt: "2026-07-23T10:18:00Z",
    runCode: "RUN-TEMPLATE-0142",
    progressCompleted: 3,
    progressTotal: 5,
    ownerPrincipal: "operator.demo",
  },
  {
    itemCode: "RUN-MAITU-0387",
    itemType: "workflow_run",
    title: "麦兔草稿写入",
    status: "waiting_human",
    priority: 40,
    summary: "目标房间现场指纹已变化，需要重新执行 preflight",
    href: "/production/live-rooms?run=MT-WB-RUN-001",
    updatedAt: "2026-07-23T10:04:00Z",
    runCode: "RUN-MAITU-0387",
    progressCompleted: 6,
    progressTotal: 8,
  },
  {
    itemCode: "RUN-CAPTURE-0201",
    itemType: "workflow_run",
    title: "直播录屏分析",
    status: "running",
    priority: 80,
    summary: "正在生成 ASR 与场景边界",
    href: "/research/live-sources?view=sessions&session=DY-CAP-20260722-003",
    updatedAt: "2026-07-23T10:22:00Z",
    runCode: "RUN-CAPTURE-0201",
    progressCompleted: 2,
    progressTotal: 4,
  },
];

export const DEMO_NOTIFICATIONS: ConsoleNotification[] = [
  {
    notificationCode: "ALERT-LINEAGE-009",
    state: "warning",
    title: "LINEAGE_INPUT_STALE",
    summary: "直播间配置引用的素材快照已有新版本",
    href: "/production/live-rooms?run=MT-WB-RUN-001",
    evidence: [{ kind: "snapshot", ref: "INV-20260722-004" }],
    occurrenceCount: 1,
    occurredAt: "2026-07-23T10:10:00Z",
    status: "open",
  },
  {
    notificationCode: "RELEASE:RELEASE-20260722-008",
    state: "reconcile_required",
    title: "RELEASE_RECONCILE_REQUIRED",
    summary: "外部写入结果尚未完成回读，不可重放",
    href: "/production/releases?release=RELEASE-20260722-008",
    evidence: [{ kind: "release", ref: "RELEASE-20260722-008" }],
    occurrenceCount: 1,
    occurredAt: "2026-07-23T09:52:00Z",
    status: "reconcile_required",
  },
];

export const DEMO_SEARCH: ConsoleSearchResult[] = [
  { entityType: "asset", entityCode: "AG-IMG-20260710-000101", title: "龙谕龙8商品主图", status: "ready", revision: 3, href: "/assets/library?asset=AG-IMG-20260710-000101", updatedAt: "2026-07-23T09:20:00Z" },
  { entityType: "content_project", entityCode: "CONTENT-20260722-004", title: "贺兰山东麓品鉴直播", status: "active", revision: 2, href: "/content/projects?project=CONTENT-20260722-004", updatedAt: "2026-07-23T09:40:00Z" },
  { entityType: "workflow_run", entityCode: "RUN-MAITU-0387", title: "麦兔草稿写入", status: "waiting_human", href: "/governance/runs?run=RUN-MAITU-0387", updatedAt: "2026-07-23T10:04:00Z" },
];

export const DEMO_ENTITY: ConsoleEntityDetail = {
  entityType: "asset",
  entityCode: "AG-IMG-20260710-000101",
  title: "龙谕龙8商品主图",
  status: "ready",
  currentRevision: 3,
  canonicalHref: "/assets/library?asset=AG-IMG-20260710-000101",
  sourceOfTruth: "postgresql",
  revisions: [
    { revision: 3, status: "ready", schemaVersion: "asset-metadata.v1", createdAt: "2026-07-23T09:20:00Z", createdBy: "operator.demo", fingerprint: "c".repeat(64), snapshot: { title: "龙谕龙8商品主图", material_role: ["product_image"], rights_status: "approved", placement: { region: "product_table" } } },
    { revision: 2, status: "ready", schemaVersion: "asset-metadata.v1", createdAt: "2026-07-22T08:15:00Z", createdBy: "operator.demo", fingerprint: "b".repeat(64), snapshot: { title: "龙谕龙8主图", material_role: ["product_image"], rights_status: "approved", placement: { region: "lower_third" } } },
    { revision: 1, status: "draft", schemaVersion: "asset-metadata.v1", createdAt: "2026-07-21T07:10:00Z", createdBy: "operator.demo", fingerprint: "a".repeat(64), snapshot: { title: "龙谕商品图", material_role: ["product_image"], rights_status: "pending", placement: { region: "lower_third" } } },
  ],
  diff: {
    fromRevision: 2,
    toRevision: 3,
    available: true,
    changes: [
      { path: "$.placement.region", change: "changed", before: "lower_third", after: "product_table" },
      { path: "$.title", change: "changed", before: "龙谕龙8主图", after: "龙谕龙8商品主图" },
    ],
  },
  sources: [
    { relationType: "imported_from", entityType: "source_system", entityCode: "maitu", mappingQuality: "verified" },
  ],
  usedBy: [
    { relationType: "used_by_run", entityType: "workflow_run", entityCode: "RUN-MAITU-0387", status: "waiting_human", href: "/governance/runs?run=RUN-MAITU-0387", mappingQuality: "verified" },
    { relationType: "used_by_release", entityType: "release", entityCode: "RELEASE-20260722-008", status: "reconcile_required", href: "/production/releases?release=RELEASE-20260722-008", mappingQuality: "verified" },
  ],
};


export const DEMO_CONTENT_ENTITY: ConsoleEntityDetail = {
  entityType: "content_project",
  entityCode: "CONTENT-20260722-004",
  title: "贺兰山东麓品鉴直播",
  status: "draft",
  currentRevision: 1,
  canonicalHref: "/content/projects?project=CONTENT-20260722-004",
  sourceOfTruth: "postgresql",
  revisions: [
    {
      revision: 1,
      status: "draft",
      schemaVersion: "content-project.v1",
      createdAt: "2026-07-23T09:40:00Z",
      createdBy: "operator.demo",
      fingerprint: "d".repeat(64),
      snapshot: {
        generation_goal: "为首次接触产区的观众建立清晰认知，并引导进入品鉴环节",
        content: { theme: "贺兰山东麓风土", audience: "葡萄酒入门消费者" },
        source_revision_refs: [],
        producer_role: "human_business",
        producer_strategy_revision: "human_input.v1",
      },
    },
  ],
  diff: { fromRevision: 1, toRevision: 1, available: true, changes: [] },
  sources: [
    { relationType: "cites", entityType: "fact_card", entityCode: "FACT-WINE-REGION-008", revision: 2, mappingQuality: "verified" },
  ],
  usedBy: [],
};


export const DEMO_ENTITIES: Record<string, ConsoleEntityDetail> = {
  [DEMO_ENTITY.entityCode]: DEMO_ENTITY,
  [DEMO_CONTENT_ENTITY.entityCode]: DEMO_CONTENT_ENTITY,
};
