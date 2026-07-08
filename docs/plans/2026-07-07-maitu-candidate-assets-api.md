# 2026-07-07 麦兔槽位候选素材 API 推进计划

## 背景

上一轮已实现麦兔素材槽位 API。Agent 现在可以知道麦兔模板里有哪些可替换槽位，但仍需要自己拼接素材查询条件。为了降低 Agent 使用成本，本轮增加“根据槽位自动推荐候选素材”的 API。

## 本轮目标

新增：

```http
GET /api/maitu/slots/{slot_code}/candidate-assets
```

该接口根据槽位信息自动查找候选素材：

- `required_category` 匹配 `assets.maitu_category`
- `accepted_asset_types` 匹配 `assets.asset_type`
- `maitu_project_code`、`scene_name`、`slot_name`、`slot_code` 用于排序加分
- 返回 `match_score` 与 `match_reasons`，让 Agent 知道为什么推荐该素材

## 匹配逻辑

基础过滤：

```text
assets.deleted_at IS NULL
assets.maitu_category = slot.required_category
assets.asset_type IN slot.accepted_asset_types  # 如果槽位设置了 accepted_asset_types
```

排序加分：

- 麦兔项目一致
- 场景一致
- 槽位名称一致
- 素材的 `maitu_slot_code` 直接等于当前 `slot_code`

## 返回示例

```json
{
  "slot_code": "MT-SLOT-20260707-000001",
  "required_category": "product_image",
  "accepted_asset_types": ["IMG"],
  "assets": [
    {
      "asset_code": "AG-IMG-20260707-000001",
      "asset_type": "IMG",
      "title": "胶原蛋白商品主图-白底款",
      "original_filename": "collagen-main.png",
      "maitu_category": "product_image",
      "maitu_scene_name": "京东空白直播间",
      "maitu_slot_name": "商品主图",
      "match_score": 1.0,
      "match_reasons": [
        "maitu_category matches required_category: product_image",
        "asset_type accepted: IMG",
        "scene_name matches: 京东空白直播间",
        "maitu_slot_code matches: MT-SLOT-20260707-000001"
      ]
    }
  ]
}
```

## 验收标准

- 可通过槽位编号获取候选素材。
- 候选素材包含匹配分和匹配原因。
- 不存在槽位返回 404。
- 测试通过、编译通过、SQL migration 解析通过。
