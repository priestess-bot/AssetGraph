# 2026-07-07 麦兔素材分类与槽位元数据推进计划

## 背景

AssetGraph 不只是通用数字人直播素材库，还要服务麦兔软件的直播间生产流程。素材入库时不仅要有稳定的 `asset_code` 和可读名称，还要记录它在麦兔中的用途分类、场景、图层、槽位和替换策略，方便 Agent 后续准确查找素材并按原布局完成替换。

## 本轮目标

1. 在素材入库模型中区分：
   - `asset_type`：文件类型，如 `IMG`、`VID`、`AUD`、`DOC`。
   - `maitu_category`：麦兔业务用途，如 `product_image`、`background_image`、`digital_human_video`。
2. 给 `assets` 表补充麦兔元数据字段。
3. 给 `live_assets` 关联关系补充麦兔场景/图层/槽位上下文。
4. 增加素材列表过滤能力，便于 Agent 按编号、名称、分类、场景、槽位查找素材。
5. 预留 `maitu_material_slots` 表，用于后续沉淀麦兔模板中的可替换素材槽位。
6. 增加测试，确保素材入库后可保留麦兔分类、图层位置和替换策略。

## 麦兔分类原则

不要把麦兔业务用途混进 `asset_type`。

```text
asset_type      = IMG / VID / AUD / DOC / OTH
maitu_category  = product_image / background_image / digital_human_video / ...
```

`asset_type` 解决“它是什么文件”；`maitu_category` 解决“它在麦兔里干什么”。

## 第一批麦兔分类

- `digital_human_video`
- `background_video`
- `background_image`
- `product_image`
- `product_video`
- `banner_image`
- `price_card`
- `floating_sticker`
- `subtitle_file`
- `voice_audio`
- `bgm_audio`
- `sound_effect`
- `script_text`
- `comment_export`
- `replay_recording`
- `highlight_clip`
- `analysis_doc`

## 替换策略

- `keep_layout`：默认策略，只替换资源，保持麦兔原场景/图层位置尺寸。
- `fit_cover`
- `fit_contain`
- `crop_center`
- `stretch`
- `manual_only`

## 验收标准

- `POST /api/assets` 支持麦兔分类和场景/图层/槽位字段。
- `GET /api/assets` 支持按 `asset_type`、`maitu_category`、`maitu_scene_name`、`maitu_slot_name`、关键词过滤。
- `POST /api/lives/{live_code}/assets` 支持记录素材在麦兔直播间中的替换上下文。
- 测试通过、Python 编译通过、SQL migration 解析通过。
