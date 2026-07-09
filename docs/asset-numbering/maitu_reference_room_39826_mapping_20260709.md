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
