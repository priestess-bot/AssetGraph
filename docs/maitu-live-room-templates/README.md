# 麦兔直播间模板库

这是 AssetGraph 的麦兔直播间模板库。模板库保存的是可复用的直播间结构、图层、脚本和及格线规则；不是单张模板预览图库。

## 当前默认基准模板

- 模板编码：`MT-TEMPLATE-38336-ZHANGYU-SUMMER`
- 模板名称：`张裕夏日主题`
- 来源直播间：`38336`
- 平台：`京东`
- 角色：第一个模板；以后京东葡萄酒直播间的最低及格线
- 结构：10 个商品、38 个场景、38 段脚本、31 个唯一视觉素材、307 次图层摆放

## 文件

- `index.json`：模板库索引，可按 `default_baseline_template_code` 找到默认基准。
- `38336-zhangyu-summer-baseline.md`：人类可审阅的结构说明。
- `38336-zhangyu-summer-baseline.json`：完整结构化模板，含每个商品、场景、图层、脚本、坐标、尺寸和素材 URL。
- `38336-zhangyu-summer-blueprint-import.json`：兼容现有后端 `/api/maitu/live-room-blueprints/import-reference` 的导入 payload。

## 硬规则

1. `MT-TPL-*` / 模板预览图只作风格和结构索引，不能当背景或装饰直接插入直播间。
2. 新直播间必须按模块搭建：背景/底图、品牌标题与 logo、前景/装饰、商品贴片/动图、数字人、商品特写视频、直播脚本。
3. 本模板的及格线是多商品、多场景、逐商品脚本；不能退化成单背景 + 单脚本。
4. 真实麦兔执行只能到草稿/自动保存边界，禁止点击正式开播。

## 后端导入命令（后端和数据库启动后）

```bash
cd /path/to/AssetGraph
uv run --project backend python scripts/import_reference_blueprint.py --payload docs/maitu-live-room-templates/38336-zhangyu-summer-blueprint-import.json
```

## 通过剧本反查模板

后端 `GET /api/maitu/live-room-blueprints` 支持 `q` 参数，会搜索蓝图编码、标题、直播间名、场景 JSON、剧本 `script_blocks` 和原始 profile/blueprint。

示例：

```bash
curl --get 'http://127.0.0.1:8000/api/maitu/live-room-blueprints' \
  --data-urlencode 'q=贺兰山东麓'
```

应能返回 `MT-BP-20260709-38336-TEMPLATE` / `张裕夏日主题`。

## 通过某个场景剧本反查该场景组件

后端 `GET /api/maitu/live-room-blueprints/scene-components/by-script` 支持用一段场景剧本文案反查匹配场景，并返回该场景的所有组件/图层，而不是只返回直播间。

当前实现会优先走正式物化索引：

```text
LiveRoomBlueprint -> TemplateScene -> TemplateComponent
```

因此返回体中的 `component_index_source` 应为 `template_component_index`。索引可直接查询：

```bash
curl --get 'http://127.0.0.1:8000/api/maitu/live-room-template-scenes' \
  --data-urlencode 'reference_room_id=38336' \
  --data-urlencode 'q=贺兰山东麓'

curl 'http://127.0.0.1:8000/api/maitu/live-room-template-scenes/MT-TPL-SCENE-38336-001/components'
```

示例：

```bash
curl --get 'http://127.0.0.1:8000/api/maitu/live-room-blueprints/scene-components/by-script' \
  --data-urlencode 'reference_room_id=38336' \
  --data-urlencode 'q=龙谕的葡萄园，在宁夏贺兰山东麓'
```

返回结果按匹配场景分组，每个结果包含：

- `matched_scene_names`：匹配到的场景名。
- `matched_script_blocks`：命中的剧本块。
- `components`：该场景去重后的组件清单。
- `component_placements`：该场景每个图层的完整摆放信息，包含素材名、类型、角色、`material_id`、坐标、尺寸、层级、数字人/音色关联等。

## 生成单场景搭建计划 dry-run

后端 `POST /api/maitu/live-room-scene-build-plans` 支持用一段剧本先匹配一个模板场景，再基于该场景的组件索引生成单场景 BuildPlan。该接口只生成可审阅计划，不真实上传、插入、保存或开播。

示例：

```bash
curl -X POST 'http://127.0.0.1:8000/api/maitu/live-room-scene-build-plans' \
  -H 'Content-Type: application/json' \
  -d '{
    "reference_room_id": "38336",
    "script_query": "龙谕的葡萄园，在宁夏贺兰山东麓",
    "target_script_content": "今天我们用张裕夏日主题的结构讲龙谕龙8，突出贺兰山东麓风土。",
    "plan_name": "龙谕龙8 单场景复刻 dry-run"
  }'
```

期望操作序列：

```text
preflight_scene_build_plan
create_scene_from_template
insert_template_component * N
add_script_block
save_live_room(manual_review)
```
