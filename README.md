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
- Browser use 过期领取回收：提供 reclaim-expired API，将超时的 `in_progress` 任务释放回 `pending`，避免 worker 崩溃后任务永久卡死
- Browser use worker 一站式取活：提供 `/api/maitu/retry-worker/next`，自动回收过期任务、领取下一条任务并返回 Browser use 操作计划
- Browser use worker 执行协议：文档化 worker 从取任务、执行操作、成功回写、失败释放到人工介入的完整契约
- 麦兔替换上下文：记录素材对应的麦兔项目、场景、图层、槽位、位置尺寸和 `replacement_policy`，默认保持原布局替换
- 直播素材索引：通过 `live_code` 聚合一场数字人直播的录屏、切片、封面、字幕、评论导出、脚本和复盘文档等素材
- 核心业务对象：`LiveSession`、`VideoSegment`、`DigitalHuman`、`VoiceProfile`、`Product`、`Script`、`ScriptBlock`
- 后端服务：FastAPI API、PostgreSQL repository、编号生成、测试覆盖
- 基础设施：PostgreSQL、MinIO、Neo4j、Milvus 本地开发配置
- 本地 Qwen3 embedding/reranker：通过 `D:/AI-Models/qwen3-service` 共享 HTTP 服务接入 `Qwen3-Embedding-4B` 与 `Qwen3-Reranker-4B`，AssetGraph 后端提供 `/api/rag/embeddings`、`/api/rag/rerank` 和 `/api/rag/qwen3/health`

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

运行 Browser-use worker 配置检查 / dry-run：

```bash
cd workers/browser-use
python -m browser_use_worker --check-config
python -m browser_use_worker --once --dry-run
```

## 文档

- `docs/final-goal.md`：项目最终目标，定义数字人直播视频多模态资产图谱的长期愿景、核心对象和 MVP 闭环。
- `docs/mvp-architecture.md`：MVP 架构、编号规范、数据库表结构、MinIO 路径、Milvus collection、Neo4j schema 和 API 清单。
- `docs/maitu-function-map.md`：麦兔功能地图与 AssetGraph 建模参考，记录首页、数字分身、素材管理、商品库、直播记录、直播间编辑器、互动配置和场景类型。
- `docs/asset-numbering/asset_naming_rules_20260709_v3_browser_use.md`：Browser use 友好的麦兔素材编号与重命名预案，按数字分身/背景/装饰/视频/模版等麦兔真实类型设计，包含用途、主体、角色、标签和重复素材组。
- `docs/asset-numbering/duplicate_asset_analysis_20260709.md`：麦兔素材重复原因分析，说明数字分身封面/预览、默认音色封面、重复 material_id 指向同一 URL 等来源，并给出去重建模建议。
- `docs/asset-numbering/rename_execution_summary_20260709.md`：V3 Browser-use 友好素材重命名执行结果，记录执行策略、manifest、回滚清单和复查统计。
- `docs/asset-numbering/asset_inventory_summary_20260709.md`：本地素材扫描结果摘要，统计 131 个素材的类型、麦兔分类、重复组和解析状态。
- `docs/asset-numbering/asset_inventory_20260709.json` / `.csv`：从 `D:/AssetGraph/素材` 扫描生成的结构化素材清单，每条素材包含 file_code、sha256、maitu_category、tags、browser_use_hint 和后续导入 `POST /api/assets` 的 `asset_create_payload`。
- `docs/browser-use-integration.md`：AssetGraph 与 Browser-use 同仓一体化布局，说明 backend、worker、scripts、infra 和素材目录如何一起部署/迁移。
- 本地 Qwen3 检索接口：`GET /api/rag/qwen3/health`、`POST /api/rag/embeddings`、`POST /api/rag/rerank`，默认连接 `http://127.0.0.1:8010` 的 D 盘共享模型服务。
- `docs/worker-protocols/maitu-browser-use-retry-worker.md`：Browser use retry worker 执行协议，定义取任务、执行、成功回写、失败释放和人工介入流程。
