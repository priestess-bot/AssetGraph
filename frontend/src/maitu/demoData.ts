import type {
  AnalysisConflict,
  InventorySyncJob,
  PlanRevision,
  ProductFactCard,
  ProductionRequirement,
  ProductionRun,
  VideoAnalysisItem,
} from "./types";

export const DEMO_FACT_CARDS: ProductFactCard[] = [
  {
    fact_card_code: "FACT-DEMO-001",
    title: "夏日聚餐选酒事实卡",
    product_name: "品酒大师 PRO",
    product_code: "AG-PROD-DEMO-001",
    current_version: 3,
    approved_version: 3,
    status: "approved",
    verified_facts: ["750mL 瓶装规格", "适合冷藏后搭配聚餐餐食", "仅使用已授权品牌素材"],
    positioning: "为城市朋友聚餐提供不依赖复杂术语的选酒思路",
    updated_at: "2026-07-20T08:30:00Z",
  },
];

export const DEMO_INVENTORY_JOBS: InventorySyncJob[] = [
  {
    sync_job_code: "SYNC-DEMO-001",
    status: "succeeded",
    source: "maitu_material_library",
    progress_percent: 100,
    discovered_count: 131,
    imported_count: 131,
    failed_count: 0,
    snapshot: {
      snapshot_code: "INV-DEMO-20260720-001",
      fingerprint: "0bd10257d36a5c1e7a8916e92b8dfa14a2626e38a8e19fe51fa96e1e42a74d5a",
      quality: "complete",
      item_count: 131,
      category_counts: { "背景": 34, "装饰": 56, "视频": 29, "模版": 12 },
      created_at: "2026-07-20T08:45:00Z",
    },
    created_at: "2026-07-20T08:42:00Z",
    updated_at: "2026-07-20T08:45:00Z",
  },
];

export const DEMO_RUNS: ProductionRun[] = [
  {
    run_code: "MT-RUN-DEMO-001",
    title: "夏日朋友聚餐选酒",
    topic: "不讲复杂术语，帮聚餐人群快速选一瓶清爽红酒",
    status: "ready",
    fact_card_code: "FACT-DEMO-001",
    fact_card_version: 3,
    inventory_snapshot_code: "INV-DEMO-20260720-001",
    target_live_room_id: "39826",
    target_duration_minutes: 12,
    build_mode: "draft_with_placeholders",
    current_plan_revision: 2,
    open_requirement_count: 1,
    critical_conflict_count: 0,
    created_at: "2026-07-20T09:00:00Z",
    updated_at: "2026-07-20T09:18:00Z",
  },
];

export const DEMO_REQUIREMENTS: ProductionRequirement[] = [
  {
    requirement_code: "REQ-DEMO-001",
    scene_name: "开场钩子",
    label: "竖版聚餐氛围视频",
    need_type: "scene_video",
    category: "视频",
    priority: "critical",
    status: "decided",
    description: "首屏 3 秒内建立夏日朋友聚餐语境。",
    candidates: [
      { asset_code: "AG-VID-20260709-000018", title: "朋友聚餐举杯实拍", category: "视频", match_score: 0.91, analysis_source: "gpt_5_6_sol" },
    ],
    decision: { revision: 1, decision: "selected", selected_asset_code: "AG-VID-20260709-000018", reason: "语境和画幅最匹配" },
  },
  {
    requirement_code: "REQ-DEMO-002",
    scene_name: "产品讲解",
    label: "透明底产品主视觉",
    need_type: "product_image",
    category: "装饰",
    priority: "required",
    status: "decided",
    candidates: [
      { asset_code: "AG-IMG-20260709-000042", title: "品酒大师 PRO 瓶身正面", category: "装饰", match_score: 0.96 },
    ],
    decision: { revision: 1, decision: "selected", selected_asset_code: "AG-IMG-20260709-000042", reason: "主体完整且边缘清晰" },
  },
  {
    requirement_code: "REQ-DEMO-003",
    scene_name: "行动引导",
    label: "合规行动提示装饰",
    need_type: "cta_sticker",
    category: "装饰",
    priority: "optional",
    status: "open",
    candidates: [],
    description: "无候选时可延后，不阻断草稿生成。",
  },
];

export const DEMO_PLAN_REVISIONS: PlanRevision[] = [
  {
    revision: 2,
    status: "ready",
    input_fingerprint: "b7ad1cc0414f9c9c79dd5724dcb201536c6ce19255cb341d1cb198ab8f4cb162",
    build_plan_code: "MT-BUILD-DEMO-002",
    can_execute: true,
    scene_count: 4,
    selected_count: 7,
    missing_count: 1,
    gaps: [{ code: "OPTIONAL_CTA", severity: "warning", message: "行动提示装饰未选择，草稿将保留占位", requirement_code: "REQ-DEMO-003" }],
    scenes: [
      { scene_name: "开场钩子", scene_goal: "建立聚餐选酒的真实难题", duration_seconds: 45, script: "聚餐选酒不用先背复杂术语，先看今晚吃什么。", composition_intent: "主播中景，问题标题位于上方安全区", material_intents: ["聚餐氛围视频", "品牌背景"] },
      { scene_name: "产品讲解", scene_goal: "用已核验事实缩小选择", duration_seconds: 90, script: "先看瓶身与规格，再把口感放进餐桌场景。", composition_intent: "产品主视觉居中，事实条在底部安全区", material_intents: ["产品主图", "事实标题"] },
    ],
    generation: { provider: "deepseek", model: "deepseek-chat", prompt_version: "maitu-scene-plan.v1", latency_ms: 1380 },
    created_at: "2026-07-20T09:18:00Z",
  },
  {
    revision: 1,
    status: "superseded",
    can_execute: false,
    scene_count: 4,
    selected_count: 6,
    missing_count: 2,
    gaps: [{ code: "OPENING_VIDEO", severity: "critical", message: "开场视频尚未确认", requirement_code: "REQ-DEMO-001" }],
    scenes: [],
    created_at: "2026-07-20T09:08:00Z",
  },
];

export const DEMO_VIDEO_ANALYSES: VideoAnalysisItem[] = [
  {
    analysis_code: "VAN-DEMO-001",
    run_code: "MT-RUN-DEMO-001",
    requirement_code: "REQ-DEMO-001",
    asset_code: "AG-VID-20260709-000018",
    asset_fingerprint: "e3a0b86b0e8c23ad2fa7f555e86f092cefc70f04689b7433d8c790fe7213697d",
    asset_title: "朋友聚餐举杯实拍",
    selected: true,
    provisional_source: "gpt_5_6_sol",
    provisional_summary: "竖版中近景，三人举杯，暖色餐桌；适合开场但主体靠近字幕安全区。",
    gemini_status: "succeeded",
    gemini_summary: "检测到三位成年人、酒杯与餐盘；建议裁切顶部 4%，保留右下 CTA 空间。",
    conflict_count: 1,
    updated_at: "2026-07-20T09:14:00Z",
  },
  {
    analysis_code: "VAN-DEMO-002",
    run_code: "MT-RUN-DEMO-001",
    asset_code: "AG-VID-20260709-000027",
    asset_fingerprint: "10b2cbff6bc9ec8d62c9db937e93c83fe4af49201e0b35b0886c1c2ac0a44a53",
    asset_title: "酒液与杯壁微距",
    selected: false,
    provisional_source: "keyframe",
    provisional_summary: "微距酒液画面，色彩稳定，尚未完成完整视频分析。",
    gemini_status: "not_requested",
    conflict_count: 0,
  },
];

export const DEMO_ANALYSIS_CONFLICTS: AnalysisConflict[] = [
  {
    conflict_code: "CONFLICT-DEMO-001",
    analysis_code: "VAN-DEMO-001",
    field: "subtitle_safe_area",
    severity: "warning",
    provisional_value: "底部字幕区无遮挡",
    gemini_value: "00:02-00:04 酒杯进入底部字幕区",
  },
];
