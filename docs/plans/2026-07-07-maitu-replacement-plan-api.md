# 2026-07-07 麦兔素材替换方案 API 推进计划

## 背景

前几轮已经完成：

1. 麦兔素材分类与替换上下文。
2. 麦兔素材槽位 API。
3. 根据槽位查询候选素材 API。

本轮继续向“麦兔直播间自动组装/替换决策系统”推进：让 AssetGraph 可以为一组麦兔槽位生成完整的素材替换方案。

## 本轮目标

新增替换方案编号：

```text
MT-PLAN-{YYYYMMDD}-{SEQ}
```

新增 API：

```http
POST /api/maitu/replacement-plans
GET  /api/maitu/replacement-plans
GET  /api/maitu/replacement-plans/{plan_code}
```

## 替换方案含义

一个 replacement plan 表示：

```text
针对某个麦兔项目/场景
  -> 有哪些素材槽位需要替换
  -> 每个槽位选择哪个素材
  -> 该素材为什么被选中
  -> 哪些槽位缺少合适素材
```

## 生成逻辑

创建方案时，可以指定：

- `maitu_project_code`
- `scene_name`
- `slot_codes`
- `strategy`

如果传入 `slot_codes`，则只为这些槽位生成替换项。

如果不传 `slot_codes`，则按 `maitu_project_code` 和 `scene_name` 找到对应槽位，再逐一生成替换项。

每个槽位的素材选择逻辑复用：

```http
GET /api/maitu/slots/{slot_code}/candidate-assets
```

并默认选择 `match_score` 最高的候选素材。

## 返回示例

```json
{
  "plan_code": "MT-PLAN-20260707-000001",
  "plan_name": "京东空白直播间商品素材替换方案",
  "maitu_project_code": "MT-PROJ-20260707-000001",
  "scene_name": "京东空白直播间",
  "status": "draft",
  "strategy": "best_match",
  "items": [
    {
      "slot_code": "MT-SLOT-20260707-000001",
      "slot_name": "商品主图",
      "required_category": "product_image",
      "selected_asset_code": "AG-IMG-20260707-000001",
      "selected_asset_title": "胶原蛋白商品主图-白底款",
      "match_score": 1.0,
      "status": "selected"
    }
  ]
}
```

## 验收标准

- 可创建替换方案。
- 可按项目/场景/状态查询替换方案。
- 可按 `plan_code` 查询方案详情和 items。
- 方案 item 能记录选中的素材编号、标题、匹配分和匹配原因。
- 没有候选素材的槽位应标记为 `missing`。
- 测试通过、编译通过、SQL migration 解析通过。
