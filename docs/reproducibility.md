# 跨机器复现指南

本仓库把复现分为三个层级，避免把“代码可复现”与第三方账号、27 GB 私有素材或模型权重混为一谈。

## 1. Core：任何干净机器必须通过

包含：后端、数据库迁移、Browser-use Worker 的 dry-run/in-memory 能力、全部自动化测试、Ruff、剧本 Skill 及引用文件。

前置条件：

- Git
- Python 3.11（支持范围 `>=3.11,<3.15`，CI 固定 3.11）
- uv 0.11.15
- Docker + Docker Compose（运行数据库集成测试时需要）

```bash
git clone https://github.com/Simommo888/AssetGraph.git
cd AssetGraph
python scripts/bootstrap_reproducible.py
```

该命令会：

1. 从 `.env.example` 创建 `.env`，为四个 Phase D 能力生成互不相同的随机密钥；
2. 严格按 `backend/uv.lock` 和 `workers/browser-use/uv.lock` 安装依赖；
3. 把仓库内 `jd-wine-livestream-scriptwriting` Skill 的完整文件集合安装到当前 Hermes home，并逐文件校验 SHA-256；
4. 执行仓库自包含校验。

启动基础设施并应用仓库内全部迁移：

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-infra
```

迁移器按 migration 单独提交，使用全局 advisory lock，并默认设置 5 秒锁超时和
15 分钟语句超时；已登记 migration 的 SHA-256 发生变化时立即失败。生产变更前还
必须按 `docs/operations/database-migration-rehearsal.md` 在隔离的生产数据副本执行
`scripts/rehearse_migrations.py`。干净库或 `synthetic_fixture` 报告不能替代真实副本
的耗时、锁、数据不变量和前向修复证据。

本地 PITR 与版本化对象恢复基线按
`docs/operations/disaster-recovery-baseline-runbook.md` 执行。该演练会启动独立的
PostgreSQL/MinIO、创建物理备份与 WAL 时间目标、破坏当前对象版本并恢复，再执行
marker、migration、业务不变量、物理页和跨存储 checksum 验证；它不修改当前应用
数据库，也不替代后续生产规模的 `CHK-7230`。

旧主链兼容门禁按 `docs/operations/legacy-compatibility-audit.md` 执行。先在隔离集成库
运行 PostgreSQL/API 兼容测试补齐六类代表性来源，再用
`scripts/audit_legacy_compatibility.py` 核对迁移校验和、来源/投影基数、只读与不确定性
语义、分页/详情 API、稳定错误码和 canonical 事实表零写入。报告不保存 DSN、令牌或
原始业务行；代表性报告只证明兼容契约，不证明生产容量或数据质量。

容量采集使用 `scripts/measure_capacity_baseline.py` 和
`docs/operations/capacity-baseline-input.v1.example.json`。集成库报告只能验证查询与
指纹契约并固定为不满足 `CHK-0110`；只有运行只读快照、对象存储全量对账、批准后的
并发上限/预测/成本/阈值输入全部存在时，报告才可能设置
`qualifies_for_chk_0110=true`。具体执行方式见
`docs/operations/capacity-baseline-measurement-2026-07-23.md`。

Phase 0 技术包与五方签字使用 `scripts/assemble_phase0_acceptance.py`。它对 Phase owner、
checklist 状态、容量/迁移/兼容/灾备/全量回归报告及证据文件统一计算技术指纹，再要求
product、engineering、data、security、operations 对同一指纹签署；任一证据变化都会
使旧签字失效。流程和拒绝占位的示例见
`docs/operations/phase-0-acceptance-package.md`。

启动后端：

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 2. Local AI：固定模型 revision

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-qwen-models
```

模型仓库和 commit 固定在 `reproducibility.lock.json`；服务完整传递依赖和 artifact hashes 固定在 `services/qwen3/uv.lock`。Qwen 服务独立支持 Python `>=3.11,<3.14`，bootstrap 固定用 Python 3.12 创建该环境；Core 仍支持 `>=3.11,<3.15`。服务源码位于 `services/qwen3/`。模型权重体积大，不进入 Git。

### 商业短视频生产链路

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-video-demo
```

该入口按 `workers/video-production/uv.lock` 创建 Python 3.12 TTS 环境，下载并校验 `reproducibility.lock.json` 固定的 Kokoro 模型、配置和中文音色 SHA-256，同时执行 `npm ci` 与工作台前端生产构建。可通过 `ASSETGRAPH_KOKORO_MODEL_ROOT` 将模型缓存放在外部数据盘，通过 `ASSETGRAPH_VIDEO_PRODUCTION_ROOT` 指定成片与中间产物目录。

安装完成后单独验证生产链路所需的 FFmpeg、字体、三个 Kokoro 文件和五个固定素材；该检查不要求完整私有生产语料：

```bash
python scripts/verify_reproducibility.py --video-demo
```

运行时分别启动：

```bash
uv run --project workers/video-production assetgraph-kokoro-tts
uv run --project backend python scripts/run_video_production_worker.py
uv run --project backend uvicorn app.main:app --host 0.0.0.0 --port 8000
```

旧 `/demo/` 页面已移除。TTS 与视频 Worker 只需本机访问；任务和成片通过 FastAPI 的 `/api/video-productions` 与 Artifact API 创建、轮询和下载，不读取服务器绝对路径。

## 3. Real Maitu：需要外部现场状态

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-browser-use
```

Browser-use 固定到 `reproducibility.lock.json` 中的 commit。真实麦兔执行还必须具备：

- 桌面环境和可见 Chrome；
- 合法麦兔账号及登录态；
- `ASSETGRAPH_ASSETS_ROOT` 指向本地素材根目录；
- 麦兔目标直播间仍是安全草稿；
- 不点击正式开播。

这些账号、Cookie 和第三方直播间状态不能安全地提交到公开 Git 仓库。

在 VNC 桌面终端启动可见 Chrome，并只监听本机 CDP 端口。登录状态保存在独立 profile 中，不应提交到仓库：

```bash
export BROWSER_USE_CDP_URL=http://127.0.0.1:9223
export BROWSER_USE_SESSION_NAME=assetgraph-maitu-vnc
google-chrome \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9223 \
  --user-data-dir="$HOME/.local/share/assetgraph-maitu-chrome" \
  https://live2.maituai.com/LiveManage
```

登录后另开终端执行只读探针；探针不会上传、保存或开播：

```bash
cd workers/browser-use
uv run python -m browser_use_worker --probe-maitu
```

真实生产工作台从统一 `/console/` 的内容项目进入，也支持稳定深链
`/production/live-rooms`。旧 `/maitu/` 浏览器入口已经退役，不再构建、挂载或
提供迁移重定向；领域 API 和 Worker 不受影响。在线生成必须先登记有效的
外部处理方条款与 secret-reference 凭据，并配置 `DEEPSEEK_API_KEY`、已批准的
`DEEPSEEK_PROCESSING_REGION` 和可写的版本化 evidence 对象存储；缺少任一项时
生成策略 fail closed。完成这些部署配置后再启动后端和队列 Worker：

```bash
python scripts/run_maitu_workbench_worker.py
python scripts/run_material_analysis_worker.py --lease-seconds 900 --heartbeat-seconds 60
```

第一个 Worker 通过已登录的可见 Chrome 同步麦兔资源快照，并且只执行已通过
preflight、绑定到新建空白草稿房间的任务。第二个 Worker 分析当前计划选中的本地
视频，长时间抽帧和模型调用期间使用独立数据库连接续租。素材分析使用
`OPENAI_API_KEY` 和已批准的 `OPENAI_PROCESSING_REGION`，同样要求有效处理条款、
secret-reference 凭据与 evidence 存储。可恢复的模型请求按
`ONLINE_MODEL_MAX_ATTEMPTS` 做有界重试；尝试耗尽后任务进入 `failed`，由
`POST /api/maitu/workbench/video-analysis-jobs/{analysis_code}/retry` 明确重新排队，
不做无限自动重试。Gemini 只接受人工从网页粘贴且绑定素材指纹的 JSON，不需要在
服务端保存 Gemini 凭据，也不构成在线 provider 调用。

## 4. Douyin Live Research：固定第三方 sidecar

`reproducibility.lock.json` 固定 StreamCap `v1.0.3` 和 douyinLive `v2.0.24` 的源码 commit、许可证与发布二进制 SHA-256。安装后初始化仅本机可读的运行配置并校验 sidecar：

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-live-research-tools
uv run --project workers/live-research assetgraph-live-research init-config
uv run --project workers/live-research assetgraph-live-research verify-sidecars

# 无观察目标时 scheduler 不启动录制；其余队列 Worker 保持空闲。
uv run --project workers/live-research assetgraph-live-research scheduler
uv run --project workers/live-research assetgraph-live-research retention
uv run --project workers/live-research assetgraph-live-research clip-worker
uv run --project workers/live-research assetgraph-live-research analysis-worker
```

生产运行需要分别启动 `scheduler`、`retention`、`clip-worker` 和 `analysis-worker`。
所有内部 API 请求使用 `ASSETGRAPH_SCRIPT_LAYOUT_WORKER_TOKEN` 和 worker identity；
数据根由 `ASSETGRAPH_LIVE_RESEARCH_ROOT` 指向外部数据盘。创建抖音观察目标前不会
启动真实录制；需要 ASR/视觉/模板聚合时还需配置 OpenAI 与 DeepSeek 凭据、对应的
已批准处理区域、有效处理条款和版本化 evidence 存储。Worker 必须先取得策略授权，
再调用外部服务并持久化调用证据；证据写入失败时不得提交成功状态。

## 5. 素材数据迁移（私有生产语料，不属于公开 Core）

原始素材约 27 GB，包含第三方/业务现场内容，不能在未确认授权时上传到公开 GitHub。它不属于 Core 源码复现前置条件；仓库提交了 131 条生产素材的路径、大小和 SHA-256 清单，并提供可校验迁移工具：

```text
docs/asset-numbering/asset_inventory_20260709.json
scripts/asset_corpus_bundle.py
```

在拥有素材的源机器创建迁移包（会先逐文件校验 SHA-256，任一漂移即失败）：

```bash
python scripts/asset_corpus_bundle.py create --assets-root /path/to/source-assets --output /path/to/private-transfer/assetgraph-corpus.tar
```

通过加密硬盘、受控对象存储或其他获授权渠道传输该私有 tar；目标机器恢复时先比对仓库内可信 inventory，再在同盘临时目录逐文件校验，全部通过后才替换目标目录：

```bash
python scripts/asset_corpus_bundle.py restore --bundle /path/to/private-transfer/assetgraph-corpus.tar --assets-root /path/to/restored-assets
```

然后设置 `ASSETGRAPH_ASSETS_ROOT`。POSIX shell：

```bash
export ASSETGRAPH_ASSETS_ROOT=/path/to/restored-assets
```

PowerShell：

```powershell
$env:ASSETGRAPH_ASSETS_ROOT = "D:\\path\\to\\restored-assets"
```

校验完整私有生产语料的文件存在性和大小：

```bash
python scripts/verify_reproducibility.py --external
```

`--external` 使用 `asset_inventory` 的完整私有生产语料契约；它与只覆盖可运行短视频闭环五个素材的 `--video-demo` 检查相互独立。

完整计算 131 个 SHA-256（读取约 27 GB，耗时较长）：

```bash
python scripts/verify_reproducibility.py --verify-asset-hashes
```

## 6. 剧本 Skill

源码和所有引用文件均位于：

```text
skills/creative/jd-wine-livestream-scriptwriting/
```

Bootstrap 默认安装它。也可以只安装 Skill：

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies
```

`reproducibility.lock.json` 固定 Skill 版本及每个文件 SHA-256；`scripts/verify_reproducibility.py` 会检查缺文件、断链和内容漂移。

## 7. 验收命令

以下命令分别执行，兼容 PowerShell、cmd 和 POSIX shell：

```text
python scripts/verify_reproducibility.py
uv run --project backend pytest -q
uv run --project backend ruff check backend/app backend/tests scripts services/qwen3
uv run --project workers/browser-use pytest -q
uv run --project workers/browser-use ruff check workers/browser-use/src workers/browser-use/tests
```

GitHub Actions 的 `reproducibility` 工作流会在 Ubuntu + Python 3.11 + 全新 PostgreSQL 上从锁文件安装、执行迁移并运行全部测试。
