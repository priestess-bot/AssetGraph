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

启动基础设施并应用 001–021 全部迁移：

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies --skip-skill --with-infra
```

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

## 素材数据迁移（私有生产语料，不属于公开 Core）

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

校验文件存在性和大小：

```bash
python scripts/verify_reproducibility.py --external
```

完整计算 131 个 SHA-256（读取约 27 GB，耗时较长）：

```bash
python scripts/verify_reproducibility.py --verify-asset-hashes
```

## 剧本 Skill

源码和所有引用文件均位于：

```text
skills/creative/jd-wine-livestream-scriptwriting/
```

Bootstrap 默认安装它。也可以只安装 Skill：

```bash
python scripts/bootstrap_reproducible.py --skip-dependencies
```

`reproducibility.lock.json` 固定 Skill 版本及每个文件 SHA-256；`scripts/verify_reproducibility.py` 会检查缺文件、断链和内容漂移。

## 验收命令

以下命令分别执行，兼容 PowerShell、cmd 和 POSIX shell：

```text
python scripts/verify_reproducibility.py
uv run --project backend pytest -q
uv run --project backend ruff check backend/app backend/tests scripts services/qwen3
uv run --project workers/browser-use pytest -q
uv run --project workers/browser-use ruff check workers/browser-use/src workers/browser-use/tests
```

GitHub Actions 的 `reproducibility` 工作流会在 Ubuntu + Python 3.11 + 全新 PostgreSQL 上从锁文件安装、执行迁移并运行全部测试。
