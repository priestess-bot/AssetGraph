# 2026-07-07 麦兔素材槽位 API 推进计划

## 背景

上一轮已把麦兔素材分类、场景、图层、槽位和替换策略写入 `assets` 与 `live_assets`。本轮继续把 `maitu_material_slots` 从预留表推进成真实 API，让 Agent 能先理解麦兔模板中有哪些可替换槽位，再按槽位要求检索合适素材。

## 本轮目标

1. 增加麦兔槽位编号：`MT-SLOT-{YYYYMMDD}-{SEQ}`。
2. 实现麦兔槽位请求/响应模型。
3. 实现 `maitu_material_slots` repository。
4. 增加 FastAPI 路由：
   - `POST /api/maitu/slots`
   - `GET /api/maitu/slots`
   - `GET /api/maitu/slots/{slot_code}`
   - `PATCH /api/maitu/slots/{slot_code}`
   - `DELETE /api/maitu/slots/{slot_code}`
5. 支持按麦兔项目、场景、所需素材分类、槽位名称和关键词过滤槽位。
6. 增加 API 测试。

## 槽位模型

槽位用于表达：

```text
麦兔模板里的某个位置需要什么素材。
```

核心字段：

- `slot_code`：槽位编号，系统生成。
- `slot_name`：槽位名称，例如“商品主图”。
- `maitu_project_code`：麦兔项目编号。
- `scene_name` / `scene_index`：麦兔场景。
- `layer_name` / `layer_index`：麦兔图层。
- `required_category`：需要的麦兔素材分类。
- `accepted_asset_types`：接受的基础文件类型，如 `IMG`、`VID`。
- `aspect_ratio`：推荐画幅。
- `left_position` / `top_position` / `width` / `height` / `z_index`：布局信息。
- `replacement_policy`：替换策略，默认 `keep_layout`。

## Agent 使用方式

Agent 后续替换素材时应优先走两步：

```text
查询槽位
  -> 获取 required_category / accepted_asset_types / scene / layer / size
  -> 查询匹配素材
  -> 替换素材资源并保持布局
```

例如：

```text
GET /api/maitu/slots?scene_name=京东空白直播间&slot_name=商品主图
GET /api/assets?maitu_category=product_image&asset_type=IMG&maitu_slot_name=商品主图
```

## 验收标准

- 麦兔槽位 API 可创建、查询、更新、删除。
- 槽位编号稳定生成。
- 测试通过。
- Python 编译通过。
- SQL migration 解析通过。
