# AssetGraph

AssetGraph 是一个面向麦兔软件与数字人直播业务的多模态视频资产管理与智能分析系统，用来集中存放数字人直播录屏、切片、脚本、字幕、封面、商品素材、麦兔场景素材、评论数据和复盘内容，并通过多模态理解、向量检索和知识图谱，把每一场数字人直播沉淀为可检索、可分析、可复用的内容资产。

更简洁地说：AssetGraph 是数字人直播的视频资产大脑。

## 当前范围

- 素材编号：`AG-{TYPE}-{YYYYMMDD}-{SEQ}`
- 直播编号：`AG-LIVE-{YYYYMMDD}-{SEQ}`
- 数字人编号：`AG-DH-{YYYYMMDD}-{SEQ}`
- 音色编号：`AG-VOICE-{YYYYMMDD}-{SEQ}`
- 商品编号：`AG-PROD-{YYYYMMDD}-{SEQ}`
- 脚本编号：`AG-SCRIPT-{YYYYMMDD}-{SEQ}`
- 视频片段编号：`AG-SEG-{YYYYMMDD}-{SEQ}`
- 麦兔素材分类：以麦兔真实 UI 类型为准，核心类型包括数字分身、背景、装饰、视频、文本、模版；商品 PNG 贴片在麦兔中通常属于装饰，转场素材属于视频
- 素材编号映射：AssetGraph 保留全局 `AG-*` asset_code，同时通过 `display_code` / `local_file_code` / `entity_code` 保存 `MT-*`、`DH-*` 等麦兔/本地文件编号，避免系统编号和 Browser-use 友好编号混用
- 麦兔素材槽位编号：`MT-SLOT-{YYYYMMDD}-{SEQ}`
- 麦兔槽位管理：通过 `maitu_material_slots` 记录麦兔模板中的可替换位置、所需素材分类、接受文件类型、画幅和布局信息
- 麦兔候选素材推荐：通过槽位自动匹配 `maitu_category`、`asset_type`、场景、槽位编号和槽位名称，返回可替换素材及匹配原因
- 麦兔替换方案编号：`MT-PLAN-{YYYYMMDD}-{SEQ}`
- Browser use 执行编号：`MT-EXEC-{YYYYMMDD}-{SEQ}`
- Browser use 重试任务编号：`MT-RETRY-{YYYYMMDD}-{SEQ}`
- 麦兔替换方案管理：为麦兔项目/场景的一组槽位自动选择候选素材，记录每个槽位的选中素材、匹配分、匹配原因和缺失状态
- Browser use 操作计划：将麦兔替换方案转换为 Browser use 可理解的页面操作步骤；Browser use 负责实际打开麦兔软件并执行搭建/替换
- Browser use 执行结果回写：记录 Browser use 在麦兔中的执行状态、单槽位操作结果、错误信息和截图素材编号，形成可追踪闭环
- Browser use 失败分类与重试任务：记录 `failure_type`、`retryable`、`retry_instruction`，为可自动恢复的失败生成 `MT-RETRY-*` 任务
- Browser use 重试操作计划：将单个 `MT-RETRY-*` 任务转换为最小化重试步骤，只重试失败槽位并保持麦兔原布局
- Browser use 重试结果回写：接收重试执行状态、最近执行编号、截图和摘要，自动更新 retry task 状态与重试次数
- Browser use 重试队列：提供 `/api/maitu/retry-queue`，批量返回 pending、retryable、未超过最大尝试次数的重试任务及麦兔上下文
- Browser use 重试任务领取/释放：提供 claim-next/release API，将任务从 `pending` 锁定为 `in_progress`，记录 `claimed_by/claimed_at/claim_expires_at`，支持多 worker 并发处理
- Browser use 租约所有权与幂等回写：每次领取签发不可猜测 `claim_token` 并递增 `lease_version`，heartbeat/release/result 必须条件匹配；执行结果以 UUID `retry_execution_id` 原子去重
- Browser use 过期领取回收：提供 reclaim-expired API，将超时的 `in_progress` 任务释放回 `pending`，避免 worker 崩溃后任务永久卡死
- Browser use worker 一站式取活：提供 `/api/maitu/retry-worker/next`，自动回收过期任务、领取下一条任务并返回 Browser use 操作计划
- Browser use worker 执行协议：文档化 worker 从取任务、执行操作、成功回写、失败释放到人工介入的完整契约
- 麦兔素材库与 Browser-use 现场 loop：建立 Observe → Plan → Act → Verify → Learn 闭环；素材库负责稳定编号、检索、语义推荐、蓝图和计划，Browser-use 负责读取麦兔真实页面现场、执行小步 UI 操作、截图验证和结果回写，AssetGraph 再沉淀成功路径、失败类型、重试任务和可复用模板
- 麦兔从0搭建直播间：将用户选中的参考直播间抽成结构化 Profile，生成 LiveRoomBlueprint / SceneBlueprint / LayerBlueprint，再转换成 BuildPlan 和 Browser-use 操作计划；替换只是 BuildPlan 的子操作之一
- 麦兔参考直播间/蓝图 API ingestion：提供 `/api/maitu/live-room-blueprints/import-reference`、`GET /api/maitu/live-room-blueprints`、`GET /api/maitu/live-room-blueprints/{blueprint_code}`，把 Browser-use Observe-derived Profile/Blueprint artifact 持久化为后端对象
- 麦兔 BuildPlan dry-run：提供 `/api/maitu/live-room-build-plans`、`GET /api/maitu/live-room-build-plans/{build_plan_code}`、`GET /api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations`，把 `MT-BP-*` 蓝图转换为可审阅的 Browser-use 操作序列；worker 支持 `--build-plan-code MT-BUILD-* --dry-run` 打印安全摘要，默认只规划/预检，不点击正式开播
- 麦兔 BuildPlan 剧本上下文自动选材：`strategy=script_context_best_match` / `auto_select_assets=true` 会按 `script_blocks`、图层角色、`required_category`、`accepted_asset_types` 从素材库选 Top-1，写入 `selected_asset_code`、Browser-use 友好编号、本地文件码、匹配分和原因；模板预览 `MT-TPL-*` 只作为风格/结构索引，不能作为背景/装饰等直接图层素材；仍只进入 dry-run/预检，不真实上传替换
- 直播剧本生成 Stage 0：`POST /api/maitu/livestream-script-drafts` 从结构化、已核验的商品事实生成24小时循环纯口播、结构化段落与质量报告；不推断直播间商品总数，不使用未核验促销，不为目标时长重复内容
- 剧本驱动完整自动化：`POST /api/maitu/script-driven-build-pipelines` 一次运行剧本生成/质量门禁 → 场景计划 → 素材需求 → 真实素材选择 → 缺口报告 → 布局 → BuildPlan；质量未过时保留审阅产物但强制 `can_execute=false`，始终不授权正式开播
- 麦兔模板场景组件索引：导入 LiveRoomBlueprint 时同步物化 `TemplateScene / TemplateComponent` 索引，提供 `/api/maitu/live-room-template-scenes`、`/api/maitu/live-room-template-scenes/{scene_template_code}/components`，并让 `scene-components/by-script` 走正式组件索引返回单场景组件详情，不再依赖临时解析大 JSON
- 麦兔单场景 BuildPlan dry-run：提供 `POST /api/maitu/live-room-scene-build-plans`，输入剧本查询和目标脚本后先匹配一个 `TemplateScene`，再基于该场景的 `TemplateComponent` 生成 `preflight_scene_build_plan -> create_scene_from_template -> insert_template_component* -> add_script_block -> save_live_room` 的可审阅单场景计划；默认只生成计划，不真实上传/插入/开播
- 麦兔 BuildPlan 只读 preflight：worker 支持 `--build-plan-code MT-BUILD-* --preflight-build`，拉取 BuildPlan operations 并只读校验登录态、liveRoomId、场景、激活场景图层、直播脚本面板、`save_live_room=manual_review` 与禁开播规则；已支持单场景计划中的 `preflight_scene_build_plan`、`create_scene_from_template`、`insert_template_component`
- 麦兔 BuildPlan 非破坏性 UI 导航：worker 支持 `--build-plan-code MT-BUILD-* --non-destructive-build`，仅在 preflight 全绿后选择已有场景、打开素材页签/直播脚本页签并重新 Observe；单场景计划中的新建场景、插入模板组件、写脚本、保存均仍被阻断并可用 `--write-result` 回写 blocked 证据；仍禁止上传、替换、写脚本、保存和开播
- 麦兔 BuildPlan 执行证据回写：提供 `POST/GET /api/maitu/live-room-build-plans/{build_plan_code}/execution-results`，worker 支持 `--write-result` 将 blocked/completed 非破坏性执行结果、operation evidence、DOM/screenshot asset code 回写为 `MT-EXEC-*`
- 麦兔自然语言版式微调：提供 `/api/maitu/layout-adjustments` 与 `MT-ADJ-*` 调整计划，把“往右下挪一点/缩小一点/居中/贴右下”等反馈转成 `set_layer_transform` 几何目标、检查项和可验证 operation，模糊反馈进入人工复核
- 麦兔替换上下文：记录素材对应的麦兔项目、场景、图层、槽位、位置尺寸和 `replacement_policy`，默认保持原布局替换
- 直播素材索引：通过 `live_code` 聚合一场数字人直播的录屏、切片、封面、字幕、评论导出、脚本和复盘文档等素材
- 核心业务对象：`LiveSession`、`VideoSegment`、`DigitalHuman`、`VoiceProfile`、`Product`、`Script`、`ScriptBlock`
- 后端服务：FastAPI API、PostgreSQL repository、编号生成、测试覆盖
- 基础设施：PostgreSQL、MinIO、Neo4j、Milvus 本地开发配置
- 本地 Qwen3 embedding/reranker：通过 `D:/AI-Models/qwen3-service` 共享 HTTP 服务接入 `Qwen3-Embedding-4B` 与 `Qwen3-Reranker-4B`，AssetGraph 后端提供 `/api/rag/embeddings`、`/api/rag/rerank`、`/api/rag/qwen3/health`、基于本地 embedding artifact 的 `/api/assets/candidates`、槽位上下文推荐 `/api/maitu/slots/{slot_code}/candidate-assets?semantic=true`，以及 `strategy=semantic_best_match` 的替换方案自动选材

## 目录结构

```text
backend/                AssetGraph FastAPI 后端、RAG API、数据库迁移
  app/
    api/routes/         API 路由
    core/               配置与核心能力
    schemas/            请求/响应模型
    services/           业务服务
  migrations/           SQL migration
  tests/                测试目录
workers/
  browser-use/          麦兔 Browser-use worker，同仓部署/迁移
    src/browser_use_worker/
    tests/
docs/                   设计文档
infra/                  本地基础设施
scripts/                辅助脚本
素材/                   本地麦兔素材目录；大文件不进 Git
```

## 本地开发

复制环境变量示例：

```bash
cp .env.example .env
```

启动基础设施：

```bash
docker compose -f infra/docker-compose.yml up -d
```

启动本地 Qwen3 embedding/reranker 共享服务：

```bash
cd /d/AI-Models/qwen3-service
./start_qwen3_service.sh
curl http://127.0.0.1:8010/health
```

启动后端开发服务：

```bash
cd backend
pip install -e .
uvicorn app.main:app --reload
```

应用本地 PostgreSQL migration：

```bash
cd backend
for f in migrations/*.sql; do docker exec -i assetgraph-postgres psql -U assetgraph -d assetgraph -v ON_ERROR_STOP=1 < "$f"; done
```

通过后端 API 导入本地麦兔素材 inventory（API-first，不直接写数据库）：

```bash
python scripts/import_assets.py \
  --inventory docs/asset-numbering/asset_inventory_20260709.json \
  --assets-root 素材 \
  --api-base-url http://127.0.0.1:8000 \
  --expected-count 131 \
  --report-output docs/asset-numbering/import_report_20260709_api_metadata_full.json

# 如需同时上传原始文件到 MinIO，增加 --upload-files；建议先用 --limit 小批量验证。
```

生成素材检索文本、embedding artifact，并调用候选素材推荐接口：

```bash
python scripts/build_asset_retrieval_documents.py \
  --documents-output docs/asset-numbering/asset_retrieval_documents_20260709.jsonl \
  --summary-output docs/asset-numbering/asset_retrieval_documents_20260709.md \
  --embeddings-output docs/asset-numbering/asset_retrieval_embeddings_20260709.jsonl \
  --embed \
  --embedding-batch-size 8 \
  --embedding-dimensions 1024

curl "http://127.0.0.1:8000/api/assets/candidates?q=找适合品酒大师商品讲解的视频素材&asset_type=VID&top_k=5"

# 槽位已入库后，可用槽位上下文自动召回候选素材。
curl "http://127.0.0.1:8000/api/maitu/slots/MT-SLOT-20260709-000001/candidate-assets?semantic=true&q=找适合品酒大师商品讲解的视频素材&limit=5"

# 生成替换方案时也可用语义最佳匹配自动选材。
curl -X POST "http://127.0.0.1:8000/api/maitu/replacement-plans" \
  -H "Content-Type: application/json" \
  -d '{"plan_name":"语义自动选材方案","slot_codes":["MT-SLOT-20260709-000001"],"strategy":"semantic_best_match","description":"找适合品酒大师商品讲解的视频素材"}'

# 输出 Browser-use 操作计划；operation 会包含 asset_display_code、local_file_code、原文件名和 browser_use_hint。
curl "http://127.0.0.1:8000/api/maitu/replacement-plans/MT-PLAN-20260709-000001/browser-use-operations"
```

运行 Browser-use worker 配置检查 / dry-run：

```bash
cd workers/browser-use
python -m browser_use_worker --check-config
python -m browser_use_worker --once --dry-run

# Observe 环：结构化读取当前麦兔现场状态（直播间、场景、图层、素材页签、脚本文本）。
python -m browser_use_worker --observe-maitu

# Plan 环最小版：把 Observe JSON 转成 ReferenceRoomProfile + LiveRoomBlueprint artifact。
cd ../..
./backend/.venv/Scripts/python scripts/extract_maitu_reference_room.py \
  --observed-state docs/asset-numbering/current_maitu_state_39826_20260709.json \
  --output-dir docs/asset-numbering \
  --date-stamp 20260709

# API ingestion：把 Profile/Blueprint artifact 持久化为后端对象。
./backend/.venv/Scripts/python - <<'PY'
from pathlib import Path
import json, urllib.request
base = 'http://127.0.0.1:8000'
payload = {
    'reference_profile': json.loads(Path('docs/asset-numbering/reference_room_profile_39826_20260709.json').read_text(encoding='utf-8')),
    'blueprint': json.loads(Path('docs/asset-numbering/live_room_blueprint_39826_20260709.json').read_text(encoding='utf-8')),
}
req = urllib.request.Request(
    base + '/api/maitu/live-room-blueprints/import-reference',
    data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
print(urllib.request.urlopen(req).read().decode('utf-8'))
PY

# BuildPlan dry-run：从后端蓝图生成可审阅 Browser-use 操作序列。
curl -X POST "http://127.0.0.1:8000/api/maitu/live-room-build-plans" \
  -H "Content-Type: application/json" \
  -d '{"blueprint_code":"MT-BP-20260709-39826","plan_name":"39826 参考直播间 BuildPlan dry-run","strategy":"reference_rebuild_dry_run"}'

# BuildPlan 剧本上下文自动选材：只写入 selected_asset_* 与 match_reasons；仍不上传、不替换、不保存。
# 注意：MT-TPL-* 模板预览只作为风格/结构索引，不能作为背景/装饰等直接图层素材。
curl -X POST "http://127.0.0.1:8000/api/maitu/live-room-build-plans" \
  -H "Content-Type: application/json" \
  -d '{"blueprint_code":"MT-BP-20260709-39826","plan_name":"39826 script-context asset selection","strategy":"script_context_best_match","auto_select_assets":true}'

curl "http://127.0.0.1:8000/api/maitu/live-room-build-plans/MT-BUILD-20260709-000001/browser-use-operations"

# BuildPlan worker dry-run：拉取 MT-BUILD-* operations 并只打印安全摘要；不打开浏览器、不点击、不保存。
cd workers/browser-use
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --dry-run
cd ../..

# BuildPlan 只读 preflight：拉取 MT-BUILD-* operations 并校验当前麦兔页面；不点击、不保存、不开播。
cd workers/browser-use
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build

# API-only smoke 可跳过浏览器探测；结果应是 warning 且 ready_to_execute=false。
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build --skip-browser-probe

# BuildPlan 非破坏性 UI 导航：必须先真实 preflight 全绿；只选择已有场景/打开页签/重新 Observe。
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build

# BuildPlan 执行证据回写：即使 preflight blocked，也把 blocked/completed 摘要与 operation results 回写为 MT-EXEC-*。
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --non-destructive-build --write-result
cd ../..

# 自然语言版式微调：把用户反馈转成可验证的 set_layer_transform 目标。
curl -X POST "http://127.0.0.1:8000/api/maitu/layout-adjustments" \
  -H "Content-Type: application/json" \
  -d '{"build_plan_code":"MT-BUILD-20260709-000001","scene_name":"场景01","layer_name":"商品图","user_instruction":"商品图往右下挪一点，缩小一点，别挡主播","before_geometry":{"x":100,"y":200,"width":400,"height":300},"canvas_width":1080,"canvas_height":1920}'

# 对指定替换方案直接做 Browser-use 操作计划 dry-run，不领取 retry queue。
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --dry-run

# 真实执行前做只读安全预检：检查 operation plan、素材编号/文件、本地文件和麦兔登录态。
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight

# API/文件 smoke test 可跳过浏览器探测；此时结果会是 warning 且 ready_to_execute=false。
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight --skip-browser-probe
```

## 文档

- `docs/final-goal.md`：项目最终目标，定义数字人直播视频多模态资产图谱的长期愿景、核心对象和 MVP 闭环。
- `docs/mvp-architecture.md`：MVP 架构、编号规范、数据库表结构、MinIO 路径、Milvus collection、Neo4j schema 和 API 清单。
- `docs/maitu-function-map.md`：麦兔功能地图与 AssetGraph 建模参考，记录首页、数字分身、素材管理、商品库、直播记录、直播间编辑器、互动配置和场景类型。
- `docs/maitu-live-room-builder.md`：从0搭建麦兔直播间的能力设计，定义 ReferenceRoomProfile、LiveRoomBlueprint、SceneBlueprint、LayerBlueprint、BuildPlan 和 Browser-use 创建/插入/保存类 operation；`scripts/extract_maitu_reference_room.py` 可把 Observe JSON 转成参考直播间 Profile/蓝图 artifact。
- `docs/livestream-script-generation-pipeline.md`：剧本生成 Stage 0 与完整自动化质量契约，定义结构化事实输入、纯口播输出、范围/时长/促销门禁，以及剧本到场景、素材、布局和 BuildPlan 的追溯关系。
- `docs/asset-numbering/asset_naming_rules_20260709_v3_browser_use.md`：Browser use 友好的麦兔素材编号与重命名预案，按数字分身/背景/装饰/视频/模版等麦兔真实类型设计，包含用途、主体、角色、标签和重复素材组。
- `docs/asset-numbering/duplicate_asset_analysis_20260709.md`：麦兔素材重复原因分析，说明数字分身封面/预览、默认音色封面、重复 material_id 指向同一 URL 等来源，并给出去重建模建议。
- `docs/asset-numbering/rename_execution_summary_20260709.md`：V3 Browser-use 友好素材重命名执行结果，记录执行策略、manifest、回滚清单和复查统计。
- `docs/asset-numbering/asset_inventory_summary_20260709.md`：本地素材扫描结果摘要，统计 131 个素材的类型、麦兔分类、重复组和解析状态。
- `docs/asset-numbering/asset_inventory_20260709.json` / `.csv`：从 `D:/AssetGraph/素材` 扫描生成的结构化素材清单，每条素材包含 file_code、sha256、maitu_category、tags、browser_use_hint 和后续导入 `POST /api/assets` 的 `asset_create_payload`。
- `docs/asset-numbering/assetgraph_import_quality_report_20260709.md` / `.json`：通过后端 API 对 131 条已入库素材生成的质量检查报告，覆盖字段缺失、local_file_code 唯一性、标签覆盖率、重复组和分类分布。
- `docs/asset-numbering/asset_retrieval_documents_20260709.jsonl` / `asset_retrieval_embeddings_20260709.jsonl` / `.md`：由 `/api/assets` 生成的 Agent/RAG 检索文本与 Qwen3 embedding artifact，每条素材一条检索文档，embedding 维度 1024。
- `docs/browser-use-integration.md`：AssetGraph 与 Browser-use 同仓一体化布局，说明 backend、worker、scripts、infra 和素材目录如何一起部署/迁移。
- 本地 Qwen3 检索接口：`GET /api/rag/qwen3/health`、`POST /api/rag/embeddings`、`POST /api/rag/rerank`、`GET /api/assets/candidates`、`GET /api/maitu/slots/{slot_code}/candidate-assets?semantic=true`，以及 `POST /api/maitu/replacement-plans` 的 `strategy=semantic_best_match` 自动选材；默认连接 `http://127.0.0.1:8010` 的 D 盘共享模型服务。
- `docs/worker-protocols/maitu-browser-use-retry-worker.md`：Browser use retry worker 执行协议，定义取任务、执行、成功回写、失败释放和人工介入流程。
