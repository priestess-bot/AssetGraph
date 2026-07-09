# 麦兔直播间从0搭建能力设计

> 目标调整：素材替换只是 AssetGraph × Browser-use 的一个子能力。长期目标是形成“素材库 + Browser-use 现场”的联合调度能力：AssetGraph 负责素材、脚本、商品、数字人、音色、参考直播间和搭建蓝图；Browser-use 负责读取麦兔真实页面状态、执行 UI 操作、截图验证和结果回写。二者共同从空白麦兔直播间开始生成、搭建、校验并沉淀一整套可开播直播间。

## 1. 定位

AssetGraph 在“从0搭建直播间”链路中不是点击器，也不是单纯素材库，而是现场调度大脑：

```text
业务意图/商品资料/参考直播间
  -> 直播间蓝图 LiveRoomBlueprint
  -> 场景脚本 SceneScript
  -> 素材候选/选材 Asset Selection
  -> 搭建计划 BuildPlan
  -> Browser-use 操作计划 OperationPlan
  -> 麦兔真实页面执行
  -> 执行结果/截图/复盘回写
```

Browser-use 仍然是实际操作麦兔 UI 的执行器；AssetGraph 负责建模、推荐、决策、生成操作计划、检查安全条件、记录执行结果。

### 1.1 Loop 能力：素材库 + Browser-use 现场联合调度

这条主线强调的不是“有一个素材库，也有一个浏览器机器人”，而是一个持续运转的 Agent loop：

```text
Observe（观察现场）
  Browser-use 读取麦兔真实页面：登录态、URL、直播间、场景、图层、素材页签、文本框、截图

Plan（生成计划）
  AssetGraph 基于素材库、商品、脚本、数字人、音色、参考直播间和历史执行结果生成/修正蓝图与 BuildPlan

Act（执行小步）
  Browser-use 按 BuildPlan 执行一个小而可验证的 UI 动作，例如创建场景、插入素材、填写脚本、保存草稿

Verify（验证回写）
  Browser-use 重新读取页面和截图，AssetGraph 对比预期状态，判断成功、偏差、失败或需要人工确认

Learn（沉淀上下文）
  AssetGraph 记录现场状态、成功路径、失败类型、截图、重试任务、可复用模板和素材选择依据
```

也可以理解为两层协同：

```text
AssetGraph 素材库/知识层
  - 稳定素材编号、文件位置、分类、标签、embedding、候选推荐
  - 商品、脚本、数字人、音色、参考直播间结构
  - 蓝图/BuildPlan/操作计划/执行结果/失败重试

Browser-use 现场层
  - 读取当前麦兔真实页面：登录态、直播间、场景、图层、素材页签、脚本文本
  - 把现场状态回传给 AssetGraph，用于校准蓝图和 preflight
  - 按 AssetGraph 的操作计划执行 UI 动作，并截图/回写结果
```

调度循环应是：

```text
1. Browser-use 读取现场状态，形成 ReferenceRoomProfile / CurrentMaituState
2. AssetGraph 用素材库和知识图谱生成或修正 LiveRoomBlueprint
3. AssetGraph 为每个场景/图层/脚本块选择素材和话术
4. AssetGraph 生成 BuildPlan 与 Browser-use operations
5. Browser-use 做 preflight：现场是否仍与计划一致
6. Browser-use 执行一小步并回写截图、DOM状态、成功/失败
7. AssetGraph 根据回写继续调度下一步或生成重试/人工任务
```

因此 AssetGraph 的核心价值是**素材库决策 + 现场反馈调度**，而不只是离线生成一串点击指令。

## 2. 替换 vs 从0搭建

| 能力 | 当前 replacement plan | 从0搭建直播间 |
|---|---|---|
| 输入 | 已存在麦兔项目/场景/图层/槽位 | 商品、直播目标、参考模板、素材库、脚本 |
| 目标 | 在现有图层保持布局替换素材 | 创建直播间、创建/复制场景、插入图层、填脚本、配置商品/互动 |
| 核心对象 | `MaterialSlot`, `ReplacementPlan` | `LiveRoomBlueprint`, `SceneBlueprint`, `LayerBlueprint`, `BuildPlan` |
| 执行动作 | `replace_layer_asset` | `create_live_room`, `create_scene`, `insert_material_layer`, `set_layer_transform`, `add_script_block`, `configure_product`, `save_project` |
| 安全检查 | 场景/图层存在且素材文件存在 | 可创建权限、模板/素材齐全、图层坐标完整、脚本可写入、禁点开播 |
| 回写 | 单槽位替换结果 | 整个直播间搭建结果、每个场景/图层/脚本块状态、截图、失败重试任务 |

因此后续不能只围绕“把 A 替换成 B”，而要围绕“生成一个直播间搭建蓝图并执行”。

## 3. 核心对象

### 3.1 LiveRoomBlueprint

描述一个待搭建直播间的业务蓝图。

建议字段：

```json
{
  "blueprint_code": "MT-BP-20260709-000001",
  "title": "京东张裕品酒大师PRO直播间",
  "platform": "京东",
  "room_type": "blank|template_clone|reference_rebuild",
  "reference_room_id": "39826",
  "reference_room_name": "京东空白直播间-0707-1352",
  "product_codes": ["AG-PROD-..."],
  "digital_human_code": "AG-DH-...",
  "voice_profile_code": "AG-VOICE-...",
  "script_code": "AG-SCRIPT-...",
  "status": "draft|planned|ready|executing|built|failed",
  "description": "..."
}
```

### 3.2 SceneBlueprint

描述一场直播间中的一个麦兔场景。

```json
{
  "scene_code": "MT-SCENE-20260709-000001",
  "blueprint_code": "MT-BP-20260709-000001",
  "scene_name": "场景01",
  "scene_type": "讲品",
  "sort_order": 1,
  "goal": "产品总览介绍",
  "estimated_duration_seconds": 30,
  "script_block_codes": ["AG-SCRIPT-BLOCK-..."],
  "required_layers": []
}
```

麦兔 UI 当前可见中文场景类型应保留：

```text
讲品 / 特写 / 问答 / 过渡
```

内部可另做归一化：

```text
explain_product / closeup / qa / transition
```

### 3.3 LayerBlueprint

描述需要在场景中出现的图层。它既可以来自参考直播间，也可以由 Agent 新建。

```json
{
  "layer_code": "MT-LAYER-20260709-000001",
  "scene_code": "MT-SCENE-20260709-000001",
  "layer_name": "前景",
  "layer_role": "foreground_frame|background|product_image|product_video|digital_human|sticker|logo|text",
  "required_category": "floating_sticker",
  "accepted_asset_types": ["IMG"],
  "selected_asset_code": "AG-IMG-...",
  "left_position": 0,
  "top_position": 0,
  "width": 1080,
  "height": 1920,
  "z_index": 10,
  "replacement_policy": "keep_layout"
}
```

### 3.4 BuildPlan

`BuildPlan` 是从蓝图转成可执行步骤的中间层，对应当前 `ReplacementPlan` 的上位概念。

```json
{
  "build_plan_code": "MT-BUILD-20260709-000001",
  "blueprint_code": "MT-BP-20260709-000001",
  "target_app": "maitu",
  "executor": "browser_use",
  "status": "draft|ready|executing|succeeded|partial_failed|failed",
  "operations": [
    {
      "operation_type": "create_live_room",
      "operation_name": "创建空白直播间",
      "sort_order": 1,
      "status": "ready"
    },
    {
      "operation_type": "create_scene",
      "scene_name": "场景01",
      "scene_type": "讲品",
      "sort_order": 10,
      "status": "ready"
    },
    {
      "operation_type": "insert_material_layer",
      "scene_name": "场景01",
      "layer_name": "前景",
      "asset_code": "AG-IMG-...",
      "asset_display_code": "MT-DEC-0019",
      "sort_order": 20,
      "status": "ready"
    },
    {
      "operation_type": "add_script_block",
      "scene_name": "场景01",
      "script_block_content": "大家好，今天给大家介绍...",
      "sort_order": 90,
      "status": "ready"
    },
    {
      "operation_type": "save_live_room",
      "sort_order": 999,
      "status": "ready"
    }
  ]
}
```

## 4. Browser-use operation type 扩展

当前已支持/设计：

```text
replace_layer_asset
retry_replace_layer_asset
retry_asset_upload_and_replace
retry_save_project
recover_login_then_retry
retry_browser_use_operation
```

从0搭建需要新增一组操作类型：

| operation_type | 含义 | 是否会改动麦兔 |
|---|---|---:|
| `open_live_manage` | 打开直播间管理页 | 否 |
| `create_blank_live_room` | 点击创建直播间并选择空白直播间 | 是 |
| `rename_live_room` | 设置直播间标题 | 是 |
| `configure_platform` | 选择京东/淘宝等平台 | 是 |
| `create_product_entry` | 创建/选择商品 | 是 |
| `create_scene` | 创建场景并设置场景类型 | 是 |
| `select_scene` | 选择已有场景 | 否/低风险 |
| `insert_material_layer` | 从素材页签插入背景/装饰/视频/数字人 | 是 |
| `set_layer_transform` | 设置图层坐标、尺寸、层级 | 是 |
| `set_layer_name` | 重命名图层 | 是 |
| `add_script_block` | 写入直播脚本文本 | 是 |
| `configure_interaction` | 配置直播互动/问答 | 是 |
| `save_live_room` | 保存直播间 | 是 |
| `preflight_build_plan` | 只读检查搭建计划 | 否 |

硬性安全规则：

- 默认永远不点击 `正式开播`。
- 没有 `ready_to_execute=true` 不执行 mutating operation。
- 没有截图/页面状态回写不宣称真实成功。
- 创建/保存类操作必须记录 `MT-EXEC-*` 执行结果。

## 5. 从参考直播间到蓝图

用户选中的参考直播间 `39826 / 京东空白直播间-0707-1352` 当前已可作为模板来源。

可抽取：

```text
Room
- liveRoomId: 39826
- room_name: 京东空白直播间-0707-1352
- platform: 京东版

Scenes
- 场景01..场景07
- type: 讲品

Scene01 Layers
- 前景
- 品酒大师(PRO）
- png
- gif-01
- 标题+logo
- 珠珠-亲和
- 微信图片_20260618221607_11_15

Workbench
- 直播脚本
- 直播互动
- 账号授权
```

这类参考直播间应沉淀为 `ReferenceRoomProfile` 或 `LiveRoomBlueprint` 初稿，而不是只作为 replacement plan 的临时上下文。

## 6. MVP 路线

### 阶段 A：参考直播间抽取

目标：把用户手动选择的麦兔直播间抽成结构化 JSON/Markdown。

输入：当前 Browser-use 页面。

输出：

```text
reference_room_profile.json
- room_id
- room_name
- platform
- scenes[]
- active_scene
- layers[]
- material_tabs[]
- script_text[]
```

当前已完成一版 Markdown 映射、Browser-use Observe JSON artifact，以及 Plan 环最小版抽取器：

```text
docs/asset-numbering/maitu_reference_room_39826_mapping_20260709.md
docs/asset-numbering/current_maitu_state_39826_20260709.json
docs/asset-numbering/reference_room_profile_39826_20260709.json
docs/asset-numbering/live_room_blueprint_39826_20260709.json
docs/asset-numbering/live_room_blueprint_39826_20260709.md
```

Observe 命令：

```bash
cd workers/browser-use
python -m browser_use_worker --observe-maitu
```

Plan 抽取命令：

```bash
./backend/.venv/Scripts/python scripts/extract_maitu_reference_room.py \
  --observed-state docs/asset-numbering/current_maitu_state_39826_20260709.json \
  --output-dir docs/asset-numbering \
  --date-stamp 20260709
```

Observe 命令只读执行，不点击保存/开播；它输出当前麦兔现场状态，包括登录态、URL、直播间 ID、直播间名称、场景、图层、素材页签、Workbench 页签和脚本文本。Plan 抽取器把该状态沉淀为 `ReferenceRoomProfile` 和 `LiveRoomBlueprint` 初稿，保留场景顺序、当前激活场景图层、图层角色/素材分类推断、脚本块和执行安全规则。

下一步应补 API ingestion。

### 阶段 B：蓝图建模 API

已新增 API：

```http
POST /api/maitu/live-room-blueprints/import-reference
GET  /api/maitu/live-room-blueprints?reference_room_id=39826&status=draft
GET  /api/maitu/live-room-blueprints/{blueprint_code}
```

当前实现先不执行 UI，只把 `ReferenceRoomProfile` 与 `LiveRoomBlueprint` 作为后端持久化对象保存：

- `maitu_reference_room_profiles` 保存 Browser-use Observe-derived Profile，包括场景列表、当前激活场景图层、素材页签、Workbench 页签和脚本文本。
- `maitu_live_room_blueprints` 保存蓝图主体，包括场景蓝图、图层蓝图、脚本块、安全规则和原始 blueprint JSON。
- `POST /import-reference` 支持按 `profile_code` / `blueprint_code` 幂等 upsert，方便同一参考直播间多次观察后刷新蓝图。

真实 smoke test 已用 `39826 / 京东空白直播间-0707-1352` artifact 调通：

```text
POST status 201
blueprint_code MT-BP-20260709-39826
profile_code MT-REF-20260709-39826
scene_count 7
layer_count_scene01 7
script_blocks 1
GET list status 200
GET one status 200
```

### 阶段 C：素材/脚本自动填充

基于蓝图每个 `LayerBlueprint` 调用现有候选素材检索：

```text
LayerBlueprint -> required_category + accepted_asset_types + layer_role + scene goal
  -> /api/assets/candidates 或 /api/maitu/slots/{slot_code}/candidate-assets?semantic=true
  -> selected_asset_code
```

脚本来源：

```text
商品资料 + 直播目标 + 已有脚本模板 + 用户要求
  -> Script + ScriptBlock
  -> add_script_block operations
```

### 阶段 D：BuildPlan 与 dry-run

已新增：

```http
POST /api/maitu/live-room-build-plans
GET  /api/maitu/live-room-build-plans/{build_plan_code}
GET  /api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations
```

当前支持：

```text
blueprint -> operations JSON -> dry-run/browser-use operation plan
```

生成规则：

- 先生成 `preflight_build_plan`，要求只读确认页面/登录态/直播间/场景仍匹配。
- 对蓝图内每个场景生成 `select_scene`。
- 对已观测图层生成 `replace_layer_asset` 规划操作，保留 `layer_role`、`required_category`、`accepted_asset_types`、`replacement_policy=keep_layout`。
- 对脚本块生成 `add_script_block`。
- 最后生成 `save_live_room`，但状态为 `manual_review`；默认不点击正式开播。

真实 smoke test 已用后端对象 `MT-BP-20260709-39826` 生成：

```text
POST build status 201
build_plan_code MT-BUILD-20260709-000001
blueprint_code MT-BP-20260709-39826
operation_count 17
first_operation preflight_build_plan
last_operation save_live_room manual_review
GET build status 200
GET operations status 200
```

当前还可以在创建 BuildPlan 时启用剧本上下文自动选材：

```bash
curl -X POST "http://127.0.0.1:8000/api/maitu/live-room-build-plans" \
  -H "Content-Type: application/json" \
  -d '{"blueprint_code":"MT-BP-20260709-39826","plan_name":"39826 script-context asset selection","strategy":"script_context_best_match","auto_select_assets":true}'
```

它会把 `script_blocks` 文本、图层角色、`required_category`、`accepted_asset_types` 与素材库元数据做规则化 Top-1 匹配，并把以下字段写入 `replace_layer_asset` operation。

重要规则：`MT-TPL-*` / `模板预览` 是直播风格与结构索引，不是可直接插入的背景图或装饰图。BuildPlan 直接图层选材会排除模板预览资产；后续应通过模板索引到组成模板的背景、装饰、数字人、商品图、视频、文本等模块，再分别搭建。

```text
selected_asset_code
selected_asset_title
selected_asset_display_code
selected_asset_local_file_code
selected_asset_original_filename
selected_asset_local_relative_path
selected_asset_browser_use_hint
match_score
match_reasons
selection_source
```

真实 smoke：`MT-BUILD-20260709-000003` 生成了 17 个 operations，其中 7 个图层 operation 均写入 selected asset；背景图层选择为 `AG-IMG-20260709-000045 / MT-BG-0004`，没有再选择 `MT-TPL-0001` 模板预览图；first selected 为 `AG-IMG-20260709-000069 / MT-DEC-0024`。这一步仍然只生成/展示计划，不会上传素材、不替换图层、不保存草稿。

当前 Browser-use worker 已接入 `GET /live-room-build-plans/{build_plan_code}/browser-use-operations` 的 BuildPlan dry-run、只读 preflight、非破坏性 UI 导航和执行证据回写：

```bash
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --dry-run
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build --skip-browser-probe
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build --write-result
```

worker dry-run 会：

- 拉取 `MT-BUILD-*` operations。
- 输出每个 operation 的 `safe_action` 摘要。
- 对已自动选材的 `replace_layer_asset` 同步展示 `selected_asset_code`、`selected_asset_display_code`、`selected_asset_local_file_code`、`match_score`、`match_reasons`。
- 将 `replace_layer_asset` 渲染为 `planned_layer_asset_replacement_not_executed`。
- 将 `add_script_block` 渲染为 `planned_script_block_not_executed`。
- 将 `save_live_room(manual_review)` 渲染为 `manual_review_save_not_executed`。
- 如果发现 `save_live_room` 非 `manual_review` 或 instruction 试图点击“正式开播”，直接返回 failed。
- 不打开浏览器、不点击、不写脚本、不保存、不开播。

preflight 会检查：

- BuildPlan operations 非空。
- operation type 是否在安全 allowlist：`preflight_build_plan`、`select_scene`、`replace_layer_asset`、`add_script_block`、`save_live_room`。
- `save_live_room` 必须保持 `manual_review`。
- instruction 不允许包含真实开播动作。
- 当前麦兔状态是否登录。
- liveRoomId 是否匹配。
- 场景是否存在。
- 当前激活场景内目标图层是否可见。
- `直播脚本` workbench tab 是否可用。

non-destructive build 会在真实 preflight 全绿后才继续，且只允许：

- 选择已有场景 `select_scene`。
- 根据 `required_category` 打开已有素材页签，例如背景/装饰/视频/数字分身。
- 打开 `直播脚本` workbench tab。
- 每个动作后重新 Observe。

仍然禁止：上传素材、插入/替换图层、写入脚本、保存草稿、点击正式开播。

执行证据回写新增接口：

```http
POST /api/maitu/live-room-build-plans/{build_plan_code}/execution-results
GET  /api/maitu/live-room-build-plans/{build_plan_code}/execution-results
GET  /api/maitu/live-room-build-plans/{build_plan_code}/execution-results/{execution_code}
```

`--write-result` 会把非破坏性 run 的总体状态、failure type、摘要、每个 action 的 operation index/type/action/status/details，以及可选 `screenshot_asset_code` / `dom_snapshot_asset_code` 回写成 `MT-EXEC-*`。如果 preflight 未全绿，worker 仍然不会点击 UI，但会回写一个 `blocked` execution result，方便后端审计和后续 retry/人工处理。

真实 smoke：

```text
worker dry-run:
status dry_run
ready_to_execute false
operation_count 17
planned_mutation_count 8
manual_review_count 1
safety_violation_count 0

--skip-browser-probe:
status warning
ready_to_execute false
operation_count 17
18 passed, 0 warning, 0 failure, 1 skipped

real browser probe:
status failed
ready_to_execute false
19 passed, 0 warning, 1 failure
failure: Maitu login page is visible; manual login is required before BuildPlan execution

non-destructive build on current unauthenticated browser:
status blocked
failure_count 1
allowed_action_count 0
reason: preflight is not green, so no UI navigation was executed

non-destructive build --write-result:
POST /api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/execution-results -> 201 Created
execution_code MT-EXEC-20260709-000001
execution_status blocked
mode non_destructive
operation_results[0].action_type preflight_gate
```

这说明当前已能安全地阻止未登录状态下的自主搭建执行。

### 阶段 D+：自然语言版式微调闭环

已新增第一版后端 planner/API：

```http
POST /api/maitu/layout-adjustments
GET  /api/maitu/layout-adjustments/{adjustment_code}
```

核心对象：

```text
MT-ADJ-{YYYYMMDD}-{SEQ}
```

输入示例：

```json
{
  "build_plan_code": "MT-BUILD-20260709-000001",
  "scene_name": "场景01",
  "layer_name": "商品图",
  "user_instruction": "商品图往右下挪一点，缩小一点，别挡主播",
  "before_geometry": {"x": 100, "y": 200, "width": 400, "height": 300},
  "canvas_width": 1080,
  "canvas_height": 1920
}
```

输出会把自然语言转为可验证的几何目标和 Browser-use operation：

```text
adjustment_code MT-ADJ-20260709-000001
status planned
target_geometry x=130 y=230 width=380 height=285
operation_type set_layer_transform
checks within_canvas passed
```

已支持的自然语言模式：

- 方向微调：`往左/往右/往上/往下/往右下挪一点`
- 显式像素：`往左50px`、`往上30px`
- 缩放：`缩小一点`、`放大一点`、`缩小10%`
- 对齐：`水平居中`
- 锚点：`放到右下角，留点边距`
- 模糊反馈：`调好看点` -> `manual_required`，不盲动

这只是“文本 -> 几何目标 -> operation”的第一步。真正精准还需要下一步由 Browser-use 执行 `set_layer_transform` 后重新 Observe，比较 `target_geometry` 与 `actual_geometry`，误差超过阈值则继续补偿或回滚。

### 阶段 E：真实执行器逐步放开

执行放开顺序：

1. 只读定位：打开页面、确认登录、确认按钮/页签/场景区域。
2. 非破坏性动作：打开创建弹窗但不提交，关闭弹窗。
3. 创建空白直播间草稿，但不配置素材。
4. 插入一个背景图层并保存草稿。
5. 创建多场景、多图层、多脚本块。
6. 回写执行结果、截图、失败重试任务。

## 7. 和现有能力的复用关系

已存在能力可以直接复用：

- `assets` 素材库与本地文件映射。
- `asset_retrieval_documents_20260709.jsonl` / embeddings。
- `/api/assets/candidates` 自然语言候选素材。
- `/api/maitu/slots` 槽位注册。
- `/api/maitu/slots/{slot_code}/candidate-assets?semantic=true` 槽位语义选材。
- `replacement_plans` 可作为 BuildPlan 的子集/兼容层。
- Browser-use `--dry-run` / `--preflight` 安全门禁。
- `MT-EXEC-*` / `MT-RETRY-*` 执行和重试闭环。

需要新增的关键能力：

- 参考直播间抽取器。
- LiveRoomBlueprint / SceneBlueprint / LayerBlueprint 持久化。
- BuildPlan 持久化。
- 从蓝图生成 Browser-use operations。
- 创建/插入/配置类 operation 的真实执行器。

## 8. 下一步实现切入点

建议先实现最小闭环：

```text
当前麦兔页面（用户手动选中参考直播间）
  -> scripts/extract_maitu_reference_room.py
  -> docs/asset-numbering/reference_room_39826.json
  -> POST /api/maitu/live-room-blueprints/import-reference
  -> 生成 blueprint + scenes + layers
  -> 生成 build plan dry-run
```

这样能把“参考直播间结构”正式从临时文档升级为系统对象，再逐步接入从0创建直播间的 Browser-use 执行器。
