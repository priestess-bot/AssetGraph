# 2026-07-07 Browser use 操作计划 API 推进计划

## 背景

实际操作麦兔软件搭建直播间、替换素材、保存项目的执行者是 Browser use。AssetGraph 不直接控制麦兔软件，而是负责提供素材、槽位、候选素材、替换方案，以及 Browser use 可理解的操作步骤。

因此，本轮把已有 replacement plan 转换为 Browser use operation plan。

## 系统分工

```text
AssetGraph = 资产、槽位、候选素材、替换方案、操作步骤生成
Browser use = 打开麦兔软件并实际执行页面操作
麦兔软件 = 最终直播间搭建与素材替换工具
```

## 本轮目标

新增 API：

```http
GET /api/maitu/replacement-plans/{plan_code}/browser-use-operations
```

该接口把替换方案转换成 Browser use 可执行/可理解的步骤。

## 返回结构

```json
{
  "plan_code": "MT-PLAN-20260707-000001",
  "executor": "browser_use",
  "target_app": "maitu",
  "maitu_project_code": "MT-PROJ-20260707-000001",
  "scene_name": "京东空白直播间",
  "operations": [
    {
      "operation_type": "replace_layer_asset",
      "slot_code": "MT-SLOT-20260707-000001",
      "slot_name": "商品主图",
      "scene_name": "京东空白直播间",
      "layer_name": "layer_8",
      "asset_code": "AG-IMG-20260707-000001",
      "asset_title": "胶原蛋白商品主图-白底款",
      "replacement_policy": "keep_layout",
      "status": "ready",
      "instruction": "进入麦兔项目 MT-PROJ-20260707-000001 的“京东空白直播间”场景，找到layer_8图层/槽位，将素材替换为 AG-IMG-20260707-000001（胶原蛋白商品主图-白底款），替换策略为 keep_layout；保持原图层位置和尺寸不变，替换后保存项目。"
    }
  ]
}
```

## 缺失素材处理

如果 replacement plan item 没有选中素材，则生成：

```text
operation_type = resolve_missing_slot_asset
status = missing_asset
```

提示 Browser use / Agent 先补充素材或人工选择素材，不应盲目执行替换。

## 验收标准

- 可把 replacement plan 转换为 Browser use 操作步骤。
- 操作步骤包含场景、图层、槽位、素材编号、素材标题、替换策略和自然语言 instruction。
- 不存在 plan 返回 404。
- 测试通过、编译通过、SQL migration 解析通过。
