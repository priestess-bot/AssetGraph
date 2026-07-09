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

### 1.1 素材库 + Browser-use 现场联合调度

这条主线强调的不是“有一个素材库，也有一个浏览器机器人”，而是两者闭环协同：

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

当前已完成一版 Markdown 映射：

```text
docs/asset-numbering/maitu_reference_room_39826_mapping_20260709.md
```

下一步应补 JSON artifact 和 API ingestion。

### 阶段 B：蓝图建模 API

新增 API：

```http
POST /api/maitu/live-room-blueprints
GET  /api/maitu/live-room-blueprints
GET  /api/maitu/live-room-blueprints/{blueprint_code}
POST /api/maitu/live-room-blueprints/{blueprint_code}/scenes
POST /api/maitu/live-room-blueprints/{blueprint_code}/layers
```

先不执行 UI，只保存计划对象。

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

新增：

```http
POST /api/maitu/live-room-build-plans
GET  /api/maitu/live-room-build-plans/{build_plan_code}
GET  /api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations
```

要求先支持：

```text
blueprint -> operations JSON -> dry-run -> preflight
```

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
