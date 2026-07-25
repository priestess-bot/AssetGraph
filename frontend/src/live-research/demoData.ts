import type { AnalysisRun, CaptureSession, CaptureTimeline, ClipJob, ResearchOverview, RoomTemplate, TemplateProjection, WatchTarget } from "./types";

export const DEMO_RESEARCH_OVERVIEW: ResearchOverview = {
  enabled_target_count: 3,
  live_target_count: 1,
  recording_session_count: 1,
  analysis_queue_count: 2,
  draft_template_count: 2,
  expiring_recording_count: 1,
};

export const DEMO_WATCH_TARGETS: WatchTarget[] = [
  {
    target_code: "DY-WATCH-DEMO-001",
    platform: "douyin",
    display_name: "葡萄酒品牌自播间",
    room_url: "https://live.douyin.com/123456789",
    room_id: "123456789",
    account_name: "品牌官方直播",
    status: "enabled",
    live_state: "recording",
    recorder_health: "healthy",
    interaction_health: "healthy",
    last_live_at: "2026-07-20T07:42:00Z",
    last_checked_at: "2026-07-20T09:36:00Z",
  },
  {
    target_code: "DY-WATCH-DEMO-002",
    platform: "douyin",
    display_name: "餐饮场景参考间",
    room_url: "https://live.douyin.com/987654321",
    status: "enabled",
    live_state: "offline",
    recorder_health: "healthy",
    interaction_health: "degraded",
    last_live_at: "2026-07-18T12:05:00Z",
    last_checked_at: "2026-07-20T09:35:00Z",
    next_retry_at: "2026-07-20T09:40:00Z",
  },
  {
    target_code: "DY-WATCH-DEMO-003",
    platform: "douyin",
    display_name: "已暂停观察样本",
    room_url: "https://live.douyin.com/456789123",
    status: "paused",
    live_state: "offline",
    recorder_health: "offline",
    interaction_health: "offline",
    last_live_at: "2026-07-12T04:20:00Z",
  },
];

export const DEMO_CAPTURE_SESSIONS: CaptureSession[] = [
  {
    session_code: "DY-CAP-DEMO-001",
    target_code: "DY-WATCH-DEMO-001",
    title: "夏日聚餐专场 · 07/20",
    status: "completed",
    started_at: "2026-07-20T07:42:00Z",
    finalized_at: "2026-07-20T08:46:00Z",
    duration_seconds: 3840,
    expires_at: "2026-08-19T08:46:00Z",
    recording_available: true,
    recorder_health: "healthy",
    interaction_health: "healthy",
    interaction_event_count: 18420,
    analysis_status: "succeeded",
    template_code: "DY-TPL-DEMO-001",
  },
  {
    session_code: "DY-CAP-DEMO-002",
    target_code: "DY-WATCH-DEMO-002",
    title: "周末餐桌场景参考",
    status: "completed",
    started_at: "2026-06-22T10:12:00Z",
    finalized_at: "2026-06-22T11:01:00Z",
    duration_seconds: 2940,
    expires_at: "2026-07-22T11:01:00Z",
    recording_available: true,
    recorder_health: "healthy",
    interaction_health: "degraded",
    interaction_event_count: 6260,
    analysis_status: "running",
  },
  {
    session_code: "DY-CAP-DEMO-003",
    target_code: "DY-WATCH-DEMO-001",
    title: "品牌日直播",
    status: "recording",
    started_at: "2026-07-20T09:14:00Z",
    duration_seconds: 1420,
    recording_available: true,
    recorder_health: "healthy",
    interaction_health: "healthy",
    interaction_event_count: 4128,
  },
];

export const DEMO_TIMELINE: CaptureTimeline = {
  session_code: "DY-CAP-DEMO-001",
  duration_seconds: 3840,
  keyframes: [
    { at_seconds: 0, label: "开播承接" }, { at_seconds: 42, label: "问题钩子" }, { at_seconds: 118, label: "产品近景" }, { at_seconds: 196, label: "餐食搭配" }, { at_seconds: 270, label: "互动回答" },
  ],
  asr_segments: [
    { start_seconds: 22, end_seconds: 55, text: "聚餐选酒不用先背复杂术语，先看今晚吃什么。", confidence: 0.94 },
    { start_seconds: 96, end_seconds: 142, text: "这段先看瓶身，再把口感放到餐桌场景里说。", confidence: 0.91 },
    { start_seconds: 232, end_seconds: 284, text: "评论区问得最多的是冷藏温度，我们统一说明。", confidence: 0.89 },
  ],
  visual_segments: [
    { start_seconds: 0, end_seconds: 68, label: "主播半身 + 品牌背景", confidence: 0.91 },
    { start_seconds: 68, end_seconds: 180, label: "产品主视觉 + 卖点条", confidence: 0.88 },
    { start_seconds: 180, end_seconds: 320, label: "餐桌 B-roll + 右下主播窗", confidence: 0.84 },
  ],
  interaction_buckets: [
    { start_seconds: 30, end_seconds: 60, total_count: 74, dominant_type: "comment", summary: "选酒问题集中出现" },
    { start_seconds: 115, end_seconds: 145, total_count: 121, dominant_type: "like", summary: "产品近景互动峰值" },
    { start_seconds: 250, end_seconds: 280, total_count: 98, dominant_type: "comment", summary: "温度与搭配提问" },
  ],
  media_gaps: [],
};

export const DEMO_CLIP_JOBS: ClipJob[] = [
  {
    clip_job_code: "DY-CLIP-JOB-DEMO-001",
    session_code: "DY-CAP-DEMO-001",
    in_seconds: 92,
    out_seconds: 148,
    title: "产品近景与卖点展开",
    status: "succeeded",
    permanent: true,
    clip_code: "AG-SEG-DEMO-001",
    checksum_sha256: "41120a44ef993e0a68e71d8613b0e177a4c56adf68b580887c32fe4c871c2dc1",
    created_at: "2026-07-20T09:06:00Z",
  },
];

export const DEMO_ANALYSIS_RUNS: AnalysisRun[] = [
  { analysis_run_code: "DY-AN-DEMO-001", session_code: "DY-CAP-DEMO-001", status: "succeeded", progress_percent: 100, asr_status: "succeeded", visual_status: "succeeded", structure_status: "succeeded", result_template_code: "DY-TPL-DEMO-001", updated_at: "2026-07-20T09:12:00Z" },
  { analysis_run_code: "DY-AN-DEMO-002", session_code: "DY-CAP-DEMO-002", status: "running", progress_percent: 62, asr_status: "succeeded", visual_status: "running", structure_status: "queued", updated_at: "2026-07-20T09:35:00Z" },
];

export const DEMO_TEMPLATES: RoomTemplate[] = [
  {
    template_code: "DY-TPL-DEMO-001",
    title: "问题钩子到餐桌场景转换",
    source_session_code: "DY-CAP-DEMO-001",
    source_type: "external_flat_video",
    templateKind: "layout_hypothesis",
    latest_revision: 2,
    status: "draft",
    layout_fidelity: "approximate",
    buildability: "reference_only",
    contentReadiness: "review_required",
    contentStrategy: { targetCategory: "", compatibilityTags: [], programOutline: [], durationPolicy: {}, moduleRecipes: [], productRotationPolicy: {}, interactionPolicy: {}, conversionPolicy: {}, hostStyle: {}, materialCues: [], reviewedExamples: [], removedSourceFactCategories: [] },
    scenes: [
      { title: "问题钩子", start_seconds: 22, end_seconds: 68, purpose: "用真实聚餐难题建立代入", script_pattern: "聚餐选酒不用先……", interaction_cue: "读取高频选择困难问题", material_slots: ["品牌背景", "主播"], components: [{ role: "host", label: "主播区域", x: .12, y: .17, width: .76, height: .68, confidence: .82 }, { role: "title", label: "问题标题", x: .08, y: .08, width: .84, height: .11, confidence: .76 }] },
      { title: "产品近景", start_seconds: 68, end_seconds: 180, purpose: "从瓶身视觉过渡到已核验事实", script_pattern: "先看瓶身，再把口感放进场景", interaction_cue: "产品出现后观察点赞峰值", material_slots: ["产品主图", "卖点标题"], components: [{ role: "product", label: "产品主视觉", x: .18, y: .22, width: .5, height: .59, confidence: .88 }, { role: "fact_strip", label: "事实条", x: .08, y: .78, width: .84, height: .12, confidence: .73 }] },
      { title: "餐桌搭配", start_seconds: 180, end_seconds: 320, purpose: "用餐桌 B-roll 解释选择依据", script_pattern: "今晚吃什么，再决定往哪个方向选", interaction_cue: "聚合搭配与温度问题", material_slots: ["餐桌视频", "主播小窗"], components: [{ role: "video", label: "餐桌 B-roll", x: 0, y: 0, width: 1, height: 1, confidence: .9 }, { role: "host_pip", label: "主播小窗", x: .66, y: .56, width: .29, height: .34, confidence: .79 }] },
    ],
    updated_at: "2026-07-20T09:12:00Z",
  },
  {
    template_code: "DY-TPL-DEMO-002",
    title: "餐食搭配三段式",
    source_session_code: "DY-CAP-DEMO-002",
    source_type: "external_flat_video",
    templateKind: "layout_hypothesis",
    latest_revision: 1,
    published_revision: 1,
    status: "published",
    layout_fidelity: "approximate",
    buildability: "reference_only",
    contentReadiness: "review_required",
    contentStrategy: { targetCategory: "", compatibilityTags: [], programOutline: [], durationPolicy: {}, moduleRecipes: [], productRotationPolicy: {}, interactionPolicy: {}, conversionPolicy: {}, hostStyle: {}, materialCues: [], reviewedExamples: [], removedSourceFactCategories: [] },
    scenes: [],
    published_version_code: "DY-TPLV-DEMO-002-R1",
    updated_at: "2026-07-19T04:25:00Z",
  },
];

export const DEMO_PROJECTION: TemplateProjection = {
  template_code: "DY-TPL-DEMO-001",
  revision: 2,
  production_eligible: true,
  reference_capabilities: ["场景顺序", "场景目标", "时长节奏", "素材槽位需求", "互动提示"],
  executable_capabilities: [],
  blocked_operations: ["insert_template_component", "set_exact_geometry", "bind_maitu_material_id"],
  warnings: ["来源是外部平面视频，只能作为参考模板参与生产规划。"],
};
