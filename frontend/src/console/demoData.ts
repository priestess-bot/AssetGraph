import type { ConsoleBusinessOverview, ConsoleNotification, ConsoleSearchResult, ConsoleSession, ConsoleTask } from "./types";


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
    href: "/templates?view=recordings",
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
    href: "/templates?view=recordings",
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

export const DEMO_BUSINESS_OVERVIEW: ConsoleBusinessOverview = {
  fromDate: "2026-06-29T00:00:00Z",
  toDate: "2026-07-28T23:59:59Z",
  metrics: [
    { key: "projects", label: "新建内容项目", value: 18, previousValue: 13, unit: "个" },
    { key: "live_rooms", label: "直播间方案", value: 14, previousValue: 9, unit: "份" },
    { key: "videos", label: "成片制作", value: 11, previousValue: 8, unit: "条" },
    { key: "sessions", label: "已关联场次", value: 32, previousValue: 21, unit: "场" },
  ],
  trend: Array.from({ length: 15 }, (_, index) => ({
    date: new Date(Date.UTC(2026, 6, 14 + index)).toISOString(),
    projects: [0, 1, 1, 0, 2, 1, 0, 2, 1, 3, 0, 2, 1, 2, 2][index],
    liveRooms: [0, 1, 0, 1, 1, 1, 0, 2, 1, 1, 1, 2, 0, 1, 2][index],
    videos: [0, 0, 1, 0, 1, 1, 1, 0, 1, 2, 1, 0, 1, 1, 1][index],
    sessions: [1, 3, 2, 1, 3, 2, 0, 4, 1, 3, 2, 2, 1, 3, 4][index],
  })),
  rankings: [
    { projectCode: "CONTENT-20260722-004", title: "贺兰山东麓品鉴直播", sessionCount: 8, lastSessionAt: "2026-07-27T13:20:00Z" },
    { projectCode: "CONTENT-20260718-002", title: "盛夏清凉家居专场", sessionCount: 6, lastSessionAt: "2026-07-26T12:10:00Z" },
    { projectCode: "CONTENT-20260712-009", title: "轻食早餐新品首发", sessionCount: 5, lastSessionAt: "2026-07-25T11:10:00Z" },
    { projectCode: "CONTENT-20260709-006", title: "通勤护肤组合推荐", sessionCount: 4, lastSessionAt: "2026-07-24T10:10:00Z" },
  ],
  coverage: { readyAssets: 186, publishedTemplates: 12, approvedFacts: 74, boundSessions: 32, totalSessions: 36 },
  recentProjects: [
    { projectCode: "CONTENT-20260722-004", title: "贺兰山东麓品鉴直播", status: "active", hasLiveRoom: true, hasVideo: true, sessionCount: 8, updatedAt: "2026-07-28T09:40:00Z" },
    { projectCode: "CONTENT-20260718-002", title: "盛夏清凉家居专场", status: "active", hasLiveRoom: true, hasVideo: false, sessionCount: 6, updatedAt: "2026-07-27T07:20:00Z" },
    { projectCode: "CONTENT-20260712-009", title: "轻食早餐新品首发", status: "draft", hasLiveRoom: false, hasVideo: false, sessionCount: 0, updatedAt: "2026-07-26T05:10:00Z" },
  ],
};

export const DEMO_SEARCH: ConsoleSearchResult[] = [
  { entityType: "asset", entityCode: "AG-IMG-20260710-000101", title: "龙谕龙8商品主图", status: "ready", revision: 3, href: "/assets?asset=AG-IMG-20260710-000101", updatedAt: "2026-07-23T09:20:00Z" },
  { entityType: "content_project", entityCode: "CONTENT-20260722-004", title: "贺兰山东麓品鉴直播", status: "active", revision: 2, href: "/projects?project=CONTENT-20260722-004", updatedAt: "2026-07-23T09:40:00Z" },
];
