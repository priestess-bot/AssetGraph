# 麦兔参考直播间结构映射（2026-07-09）

本文件记录用户在可见麦兔真实页面中手动选择的参考直播间，只读探测所得结构。用于后续将 AssetGraph 的 `maitu_project_code`、`scene_name`、`layer_name`、slot 和 Browser-use 操作计划对齐真实麦兔页面。

## 页面状态

- URL: `https://live2.maituai.com/LiveRoom?liveRoomId=39826`
- 页面标题: `MyTwins麦兔直播`
- 直播间 ID: `39826`
- 直播间名称: `京东空白直播间-0707-1352`
- 平台: `京东版`
- 当前为只读探测：未替换素材，未点击保存/开播。

## 场景列表

当前左侧项目列表显示 7 个场景，均为 `已激活 / 讲品`：

| 场景 | 状态 | 类型 | 当前选中 |
|---|---|---|---|
| 场景01 | 已激活 | 讲品 | 是 |
| 场景02 | 已激活 | 讲品 | 否 |
| 场景03 | 已激活 | 讲品 | 否 |
| 场景04 | 已激活 | 讲品 | 否 |
| 场景05 | 已激活 | 讲品 | 否 |
| 场景06 | 已激活 | 讲品 | 否 |
| 场景07 | 已激活 | 讲品 | 否 |

## 当前场景01图层

当前可见图层列表：

1. `前景`
2. `品酒大师(PRO）`
3. `png`
4. `gif-01`
5. `标题+logo`
6. `珠珠-亲和`
7. `微信图片_20260618221607_11_15`

这些名称是后续 AssetGraph slot 的候选 `layer_name`。真实执行前，Browser-use preflight 必须确认目标 `layer_name` 或 `slot_name` 在当前页面可见，避免替换到错误图层。

## 素材/面板入口

画面编辑区域可见素材类别标签：

- `数字分身`（当前激活）
- `背景`
- `装饰`
- `视频`
- `文本`
- `模版`

右侧 Workbench 标签：

- `直播脚本`（当前激活）
- `直播互动`
- `账号授权`

当前脚本文本框有一段品酒大师系列介绍文本，说明该参考直播间已有可用直播脚本上下文。

## 与当前 AssetGraph smoke plan 的差异

当前历史 smoke plan：

- plan: `MT-PLAN-20260709-000001`
- slot: `MT-SLOT-20260709-000001`
- plan project: `MT-PROJ-LOCAL-SMOKE`
- plan scene: `本地向量检索验证场景`
- plan layer: `商品讲解视频图层`
- selected asset: `AG-VID-20260709-000052` / `MT-VID-0024`

真实参考直播间：

- liveRoomId: `39826`
- room name: `京东空白直播间-0707-1352`
- visible scene: `场景01`
- visible layers: `前景`, `品酒大师(PRO）`, `png`, `gif-01`, `标题+logo`, `珠珠-亲和`, `微信图片_20260618221607_11_15`

因此当前 smoke plan 不能直接执行：它的目标场景/图层并不存在于用户选中的参考直播间。下一步应为 `39826 / 场景01` 创建真实槽位映射，再基于真实可见图层生成新的 replacement plan。

## 建议的下一步 AssetGraph 建模

建议新增或更新真实槽位，示例：

```json
{
  "maitu_project_code": "39826",
  "scene_name": "场景01",
  "slot_name": "场景01-前景素材槽位",
  "layer_name": "前景",
  "required_category": "product_video 或 decoration/background（需按实际替换目标确认）",
  "accepted_asset_types": ["VID 或 IMG"],
  "replacement_policy": "keep_layout"
}
```

在没有确认哪个图层需要被替换为视频前，不应自动把 `MT-VID-0024` 应用到任何图层。

## 已创建 AssetGraph 真实槽位映射

2026-07-09 已基于上述真实页面结构，在 AssetGraph 中为 `39826 / 场景01` 创建 7 个槽位：

| slot_code | slot_name | layer_name | required_category | accepted_asset_types |
|---|---|---|---|---|
| `MT-SLOT-20260709-000002` | 场景01-前景素材槽位 | 前景 | `floating_sticker` | `IMG` |
| `MT-SLOT-20260709-000003` | 场景01-品酒大师(PRO）数字人槽位 | 品酒大师(PRO） | `digital_human_video` | `IMG`, `VID` |
| `MT-SLOT-20260709-000004` | 场景01-png装饰槽位 | png | `floating_sticker` | `IMG` |
| `MT-SLOT-20260709-000005` | 场景01-gif-01动效装饰槽位 | gif-01 | `floating_sticker` | `IMG` |
| `MT-SLOT-20260709-000006` | 场景01-标题+logo槽位 | 标题+logo | `floating_sticker` | `IMG` |
| `MT-SLOT-20260709-000007` | 场景01-珠珠-亲和数字人槽位 | 珠珠-亲和 | `digital_human_video` | `IMG`, `VID` |
| `MT-SLOT-20260709-000008` | 场景01-背景图槽位 | 微信图片_20260618221607_11_15 | `background_image` | `IMG` |

## 真实槽位语义选材 smoke test

对背景图槽位 `MT-SLOT-20260709-000008` 运行 semantic candidate：

- query: `微信图片_20260618221607_11_15 直播背景`
- Top1: `AG-IMG-20260709-000045` / `MT-BG-0004`
- title: `背景 - 直播背景 - 微信图片_20260618221607_11_15`
- score: `0.800581`

已基于该槽位生成真实 replacement plan：

- plan_code: `MT-PLAN-20260709-000002`
- project: `39826`
- scene: `场景01`
- layer: `微信图片_20260618221607_11_15`
- selected asset: `AG-IMG-20260709-000045` / `MT-BG-0004`
- replacement policy: `keep_layout`

Browser-use preflight 结果：

```text
status: passed
ready_to_execute: true
summary: Preflight passed: 9 passed, 0 warning(s), 0 failure(s), 0 skipped.
```

这说明新的真实 plan 已经和当前麦兔页面、场景、图层、本地素材文件对齐；但仍未执行真实替换/保存。

## 已生成 ReferenceRoomProfile / LiveRoomBlueprint artifact

2026-07-09 已把 Browser-use Observe 输出升级为 Plan 环输入：

```text
docs/asset-numbering/reference_room_profile_39826_20260709.json
docs/asset-numbering/live_room_blueprint_39826_20260709.json
docs/asset-numbering/live_room_blueprint_39826_20260709.md
```

抽取命令：

```bash
./backend/.venv/Scripts/python scripts/extract_maitu_reference_room.py \
  --observed-state docs/asset-numbering/current_maitu_state_39826_20260709.json \
  --output-dir docs/asset-numbering \
  --date-stamp 20260709
```

结果摘要：

- profile_code: `MT-REF-20260709-39826`
- blueprint_code: `MT-BP-20260709-39826`
- scenes: 7
- active scene layers: 7
- script blocks: 1

当前蓝图只包含激活场景 `场景01` 的已观测图层；其他场景先保留场景顺序和类型，后续需要 Browser-use 逐场景点击观察后再补齐图层。

## 已通过后端 API ingestion

已新增并真实调用：

```http
POST /api/maitu/live-room-blueprints/import-reference
GET  /api/maitu/live-room-blueprints?reference_room_id=39826&status=draft
GET  /api/maitu/live-room-blueprints/MT-BP-20260709-39826
```

真实 smoke test 返回：

```text
POST status 201
blueprint_code MT-BP-20260709-39826
profile_code MT-REF-20260709-39826
scene_count 7
layer_count_scene01 7
script_blocks 1
GET list status 200
list_count 1
GET one status 200
room_name 京东空白直播间-0707-1352
```

这一步把 artifact 层升级为后端持久化对象。下一步可以从 `MT-BP-20260709-39826` 生成 BuildPlan dry-run，而不是继续依赖临时 JSON 文件。
