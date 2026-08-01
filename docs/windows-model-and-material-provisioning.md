# Windows 模型与素材部署指南

本文用于在 Windows 主机上补齐 AssetGraph 的本地模型、字体、直播录制工具和私有素材。它是
[Windows 原生开发](windows-development.md)和[跨机器复现指南](reproducibility.md)的现场部署补充。

## 先确认两套素材基线

仓库里同时存在两套不同时间点的素材契约，不能直接混用：

| 契约 | 用途 | 规模 | 当前状态 |
| --- | --- | ---: | --- |
| `current_asset_inventory.json` | 当前产品验收、63 份素材约束、麦兔绑定和视频 Demo | 63 份，约 12.6 GiB | 当前产品基线；本机已完成全量 SHA-256 校验 |
| `asset_inventory_20260709.json` | 更早的全量生产素材快照 | 131 份，约 26.8 GiB | 私有历史快照；必须从拥有完整源文件的机器迁移 |

当前 Linux 主机的素材目录对 131 份旧清单缺少 76 份且有 6 份大小不匹配，因此不能用它制作可信的
131 份迁移包。要尽快恢复已经验收通过的产品体验，应先迁移 63 份当前基线。131 份旧快照找到完整
源文件后再单独迁移，不能直接覆盖当前 63 份目录。

## 1. 同步代码和准备磁盘

在 Windows 仓库根目录执行：

```powershell
git pull --ff-only origin master
git rev-parse --short HEAD
# 应为 6aa7ad7 或其后续提交

$dataRoot = "D:\AssetGraphData"
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataRoot "models") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataRoot "assets-current-63") | Out-Null
```

模型、63 份素材和解包临时目录建议放在空间充足的数据盘。若迁移包也放在本机，恢复 63 份素材时
至少预留约 30 GiB；同时下载 Qwen 两个模型、Kokoro 和依赖后，建议预留 60 GiB 以上。完整 131
份私有语料另行计算，不要把 Git 仓库目录当作唯一数据盘。

先完成基础初始化：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Setup-AssetGraph.ps1
```

## 2. 下载 Qwen3 Embedding/Reranker

`bootstrap_reproducible.py`按 `reproducibility.lock.json` 中的固定 revision 下载模型。Windows
主机先安装 Hugging Face CLI；官方安装方式见
<https://huggingface.co/docs/huggingface_hub/en/guides/cli>。

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://hf.co/cli/install.ps1 | iex"
# 关闭并重新打开 PowerShell 后确认
hf --help

python scripts\bootstrap_reproducible.py `
  --skip-dependencies --skip-skill --with-qwen-models
```

默认目录为：

```text
.external\models\qwen3-4b\Qwen3-Embedding-4B
.external\models\qwen3-4b\Qwen3-Reranker-4B
```

如果模型放到数据盘，直接按锁文件的两个 repository/revision 下载到自定义目录，并设置
`QWEN3_EMBEDDING_PATH`、`QWEN3_RERANKER_PATH`；不要改成未锁定的模型版本。

例如：

```powershell
hf download Qwen/Qwen3-Embedding-4B `
  --revision 5cf2132abc99cad020ac570b19d031efec650f2b `
  --local-dir D:\AssetGraphData\models\Qwen3-Embedding-4B
hf download Qwen/Qwen3-Reranker-4B `
  --revision 22e683669bc0f0bd69640a1354a6d0aebcfeede5 `
  --local-dir D:\AssetGraphData\models\Qwen3-Reranker-4B

$env:QWEN3_EMBEDDING_PATH = "D:\AssetGraphData\models\Qwen3-Embedding-4B"
$env:QWEN3_RERANKER_PATH = "D:\AssetGraphData\models\Qwen3-Reranker-4B"
```

## 3. 下载 Kokoro、中文音色和字体

视频 Demo 的引导命令会检查 `ffmpeg`、`ffprobe`、`fc-match` 和 `npm`，所以先补齐 FontConfig
和 `Noto Sans CJK SC`。

MSYS2 的 UCRT64 FontConfig 包提供 `fc-match.exe`，官方包说明见
<https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-fontconfig>：

```powershell
winget install --id MSYS2.MSYS2 --exact
C:\msys64\usr\bin\bash.exe -lc "pacman --noconfirm -Syuu"
C:\msys64\usr\bin\bash.exe -lc "pacman --noconfirm -Syuu"
C:\msys64\usr\bin\bash.exe -lc "pacman --noconfirm --needed -S mingw-w64-ucrt-x86_64-fontconfig"
$env:PATH = "C:\msys64\ucrt64\bin;$env:PATH"
```

从 Noto CJK 官方 `Sans2.004` 发布页
<https://github.com/notofonts/noto-cjk/releases/tag/Sans2.004> 下载并安装
`08_NotoSansCJKsc.zip` 中的字体。安装完成后验证：

```powershell
fc-cache.exe -f
fc-match.exe -f "%{family}" "Noto Sans CJK SC"
```

输出必须包含 `Noto Sans CJK SC`。随后下载并校验 Kokoro 模型、配置和中文音色：

```powershell
python scripts\bootstrap_reproducible.py `
  --skip-dependencies --skip-skill --with-video-demo
```

该命令按锁文件下载 `kokoro-v1_0.pth`、`config.json` 和 `voices/zm_yunyang.pt`，并执行前端构建。

## 4. 下载 StreamCap 和 douyinLive

先运行仓库引导：

```powershell
python scripts\bootstrap_reproducible.py `
  --skip-dependencies --skip-skill --with-live-research-tools
```

Windows 版本的引导会拉取 StreamCap 源码并创建 Python 环境，但当前版本不会自动把 douyinLive
Linux 二进制替换成 Windows `.exe`。请手动下载官方 v2.0.24 Windows AMD64 包：

```powershell
$archive = Join-Path $env:TEMP "douyinLive-v2.0.24-79453ece4a44-windows-amd64.zip"
$url = "https://github.com/jwwsjlm/douyinLive/releases/download/v2.0.24/douyinLive-v2.0.24-79453ece4a44-windows-amd64.zip"
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne "cc1cc9df433337c62263d7925da77ab17622603bbb554f1c27d3cbe9048cce4f") {
    throw "douyinLive Windows archive checksum mismatch"
}
$extractRoot = Join-Path $env:TEMP "assetgraph-douyinlive-v2.0.24"
Expand-Archive -LiteralPath $archive -DestinationPath $extractRoot -Force
New-Item -ItemType Directory -Force -Path .\.external\bin | Out-Null
Copy-Item -LiteralPath (Join-Path $extractRoot "douyinLive.exe") `
  -Destination .\.external\bin\douyinLive.exe -Force
```

在每个运行 live-research 命令的 PowerShell 会话中显式设置 Windows 路径：

```powershell
$env:ASSETGRAPH_STREAMCAP_CHECKOUT = (Resolve-Path .\.external\StreamCap).Path
$env:ASSETGRAPH_STREAMCAP_PYTHON = (Resolve-Path .\.external\streamcap-venv\Scripts\python.exe).Path
$env:ASSETGRAPH_DOUYINLIVE_BINARY = (Resolve-Path .\.external\bin\douyinLive.exe).Path

uv run --project workers/live-research assetgraph-live-research verify-sidecars
uv run --project workers/live-research assetgraph-live-research init-config
```

校验输出应同时包含 StreamCap `v1.0.3` 和 douyinLive `v2.0.24` 及对应锁定 commit。

## 5. 迁移当前 63 份素材

### 在拥有当前源文件的机器创建迁移包

当前产品基线的目录和 catalog 位于本机运行数据盘。创建迁移包前，必须确认源目录属于当前
`current_asset_inventory.json`，不要拿旧 131 清单调用这一步：

```bash
backend/.venv/bin/python scripts/asset_corpus_bundle.py create \
  --inventory /DATA/Downloads/AssetGraph/catalog/current_asset_inventory.json \
  --assets-root /DATA/Downloads/AssetGraph/素材 \
  --output /受控传输目录/assetgraph-current-63.tar
```

同时通过受控渠道传输以下三个文件：

```text
assetgraph-current-63.tar
current_asset_inventory.json
inventory-observation.json
```

迁移包包含每个文件的大小和 SHA-256；创建阶段任意文件不匹配都会失败。私有素材不要提交到
GitHub，也不要把 Cookie、API key 或麦兔登录态放进迁移包。

### Windows 恢复和设置素材根目录

```powershell
python scripts\asset_corpus_bundle.py restore `
  --bundle E:\private-transfer\assetgraph-current-63.tar `
  --assets-root D:\AssetGraphData\assets-current-63 `
  --trusted-inventory E:\private-transfer\current_asset_inventory.json
```

在 `.env` 中新增或更新：

```dotenv
ASSETGRAPH_ASSETS_ROOT=D:/AssetGraphData/assets-current-63
```

如果只在当前 PowerShell 会话验收，也可以先执行：

```powershell
$env:ASSETGRAPH_ASSETS_ROOT = "D:\AssetGraphData\assets-current-63"
```

### 导入数据库并恢复约束

启动 PostgreSQL、MinIO、后端和前端后，先 dry-run，再正式导入。后端和素材在同一台机器时不要
使用 `--upload-files`，这样预览路由会直接读取本地素材，不会把 13 GiB 再复制一份到 MinIO：

```powershell
python scripts\import_assets.py `
  --inventory E:\private-transfer\current_asset_inventory.json `
  --assets-root D:\AssetGraphData\assets-current-63 `
  --expected-count 63 --dry-run

python scripts\import_assets.py `
  --inventory E:\private-transfer\current_asset_inventory.json `
  --assets-root D:\AssetGraphData\assets-current-63 `
  --expected-count 63
```

dry-run 应报告 `planned_count=63`、`invalid_count=0`。正式导入可重复执行，默认按
`local_file_code` 跳过已有行。

使用随素材一起传输的 catalog 和麦兔 inventory observation 恢复产品端已经验收过的用途、尺寸、
缩放、图层约束以及 `37200/7717/3760` 绑定：

```powershell
$backendPython = ".\backend\.venv\Scripts\python.exe"
& $backendPython scripts\bootstrap_material_library.py `
  --catalog E:\private-transfer\current_asset_inventory.json `
  --inventory-observation E:\private-transfer\inventory-observation.json `
  --assets-root D:\AssetGraphData\assets-current-63 `
  --expected-count 63 --apply `
  --report-output data\material-bootstrap-windows.json
```

## 6. 启动本地模型服务并验收

`Start-AssetGraph.ps1` 当前只启动工作台、FastAPI 和 MinIO；Qwen 与 TTS 需要各自在独立终端
启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Start-AssetGraph.ps1 -NoBrowser

# 终端 A：Qwen3，监听 8010
Push-Location services\qwen3
.\.venv\Scripts\python.exe .\qwen3_shared_server.py

# 终端 B：Kokoro TTS，监听 8020
uv run --project workers/video-production assetgraph-kokoro-tts
```

模型服务启动后，用一次实际请求触发懒加载。下面的请求只打印摘要，不把向量内容写入日志：

```powershell
$headers = @{ Authorization = "Bearer local-no-auth" }
$embeddingBody = @{ input = "张裕品酒大师PRO"; model = "qwen3-embedding-4b-local"; dimensions = 1024 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/v1/embeddings `
  -Headers $headers -ContentType "application/json" -Body $embeddingBody | Select-Object object, model, usage

$rerankBody = @{ query = "张裕品酒大师PRO"; documents = @("品酒大师产品介绍", "其他内容"); model = "qwen3-reranker-4b-local" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/v1/rerank `
  -Headers $headers -ContentType "application/json" -Body $rerankBody | Select-Object id, model, usage

$ttsBody = @{ model = "hexgrad/Kokoro-82M"; voice = "zm_yunyang"; input = "这是本地中文语音验收。"; response_format = "wav" } | ConvertTo-Json
Invoke-WebRequest -Method Post -Uri http://127.0.0.1:8020/v1/audio/speech `
  -ContentType "application/json" -Body $ttsBody -OutFile .run\windows\tts-smoke.wav
```

不要只检查 `/health`：Qwen 和 Kokoro 都必须至少各执行一次真实请求，让懒加载模型实际载入。
验收最低要求：

- Qwen embedding 请求返回 1024 维向量；
- Qwen rerank 请求返回结果；
- TTS 请求生成非空 WAV；
- `GET /api/assets/stats` 的 `total_assets` 为 `63`；
- 素材库页面能看到图片、视频首帧和当前约束；
- `python scripts/verify_reproducibility.py --video-demo` 通过。

只迁移 63 份当前基线时，不要运行 `verify_reproducibility.py --external` 作为验收。该选项会按
旧 131 份清单检查完整私有语料，当前 63 份基线下预期会失败；63 份应以导入报告、bootstrap
报告和 `--video-demo` 结果为证据。

## 7. 旧 131 份全量语料

只有在找到完整的 `D:\AssetGraph\素材` 原始源后，才能按仓库旧清单创建 131 份包：

```powershell
python scripts\asset_corpus_bundle.py create `
  --inventory docs\asset-numbering\asset_inventory_20260709.json `
  --assets-root D:\AssetGraph\素材 `
  --output E:\private-transfer\assetgraph-corpus-131.tar
```

该包不得直接覆盖 `assets-current-63`。131 份是历史快照，和当前 63 份 catalog 的名称、路径及
约束修订不完全相同；迁移前需要先完成身份合并和数据库映射，再决定是否把两者合并到一个根目录。

## 8. 在线 API 不是模型下载步骤

以下内容不能由脚本自动生成，也不能填假值：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_PROCESSING_REGION=
OPENAI_API_KEY=
OPENAI_PROCESSING_REGION=
```

密钥必须由服务负责人提供，且不能出现在 Git、日志、截图、迁移包或浏览器任务参数中。当前
新数据库除了 API key 还需要已批准的外部处理方、处理区域、保留条款、secret-reference 凭据和
可写 evidence 存储；缺少任一项时在线生成和素材多模态分析会保持不可用，这是预期的 fail-closed
状态，不代表本地模型下载失败。

## 9. Windows 端回传证据

完成后只回传状态和路径，不回传密钥或原始素材：

```text
代码提交：
Qwen embedding/reranker：已下载，路径，实际请求结果
Kokoro 模型/配置/音色：已下载，SHA-256 校验结果，TTS 请求结果
FontConfig/Noto：fc-match 输出
StreamCap/douyinLive：版本、commit、verify-sidecars 输出
当前素材：63/63，dry-run 和正式导入报告
素材 bootstrap：63/63，约束/绑定报告
AssetGraph：/health、/api/assets/stats、前端页面截图
仍缺少的外部输入：只列名称，不写 secret 值
```
