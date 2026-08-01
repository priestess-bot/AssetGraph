# Windows 原生开发

Windows 开发链路直接使用本机桌面、Edge/Chrome、PostgreSQL 和 MinIO，不需要 VNC、
Xvfb、WSL 或 Linux 虚拟桌面。Neo4j、Milvus、Qwen、本地 TTS 和直播录制 sidecar 是
按需能力，不阻塞工作台、核心 API 和 Browser-use dry-run 的日常开发。

## 一次性初始化

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Setup-AssetGraph.ps1
```

脚本会执行以下工作：

1. 检查 Git、Python 和 Node.js，缺少时通过 winget 安装 uv、PostgreSQL 16 与 FFmpeg；
2. 创建本机 `assetgraph` PostgreSQL 角色和数据库；
3. 安装 backend、worker、固定 commit 的 Browser-use 和前端依赖；
4. 下载并校验与 Compose 配置相同版本的 Windows MinIO；
5. 把 `.env` 中尚未自定义的 Linux 默认目录替换为仓库内 Windows 绝对路径；
6. 构建前端并应用全部数据库 migration。

初始化命令可以重复执行。已有的非默认 `.env` 路径与密钥不会被覆盖。若机器已有
PostgreSQL 且 `postgres` 密码不同，请显式传入：

```powershell
.\scripts\windows\Setup-AssetGraph.ps1 -PostgresSuperPassword "your-password"
```

## 启动与停止

启动开发模式：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Start-AssetGraph.ps1
```

该命令在后台启动 MinIO、支持热重载的 FastAPI 和 Vite，并使用默认浏览器打开：

- 工作台：`http://127.0.0.1:5173/console/`
- 后端 API：`http://127.0.0.1:8000/docs`
- MinIO 控制台：`http://127.0.0.1:9001`

进程记录和日志位于 `.run/windows/`。停止本次启动的进程：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Stop-AssetGraph.ps1
```

验证生产构建由后端直接托管时，使用：

```powershell
.\scripts\windows\Start-AssetGraph.ps1 -Production
```

## 可见麦兔浏览器

启动使用独立用户目录、仅监听本机 CDP 端口的可见 Edge/Chrome：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\Start-MaituBrowser.ps1
```

首次启动后在打开的浏览器中人工完成麦兔登录。登录态保存在
`data/maitu-browser-profile/`，该目录不进入 Git。随后可运行只读探针：

```powershell
$env:BROWSER_USE_REPO = (Resolve-Path .\.external\browser-use).Path
$env:BROWSER_USE_CDP_URL = "http://127.0.0.1:9223"
$env:BROWSER_USE_SESSION_NAME = "assetgraph-maitu-windows"
uv run --project workers/browser-use python -m browser_use_worker --probe-maitu
```

默认配置使用 `http://127.0.0.1:9223` 和会话名
`assetgraph-maitu-windows`。Worker 直接附着到这个 Windows 可见浏览器，不创建虚拟
桌面，也不会在只读探针中上传、保存或开播。

真实在线生成和素材分析仍需要在 `.env` 中配置相应 API key、处理区域和授权策略。
私有素材需要单独设置 `ASSETGRAPH_ASSETS_ROOT`，不属于核心应用启动前置条件。

模型、字体、录制 sidecar、当前 63 份产品素材以及旧 131 份历史语料的分阶段下载和迁移步骤，
见 [Windows 模型与素材部署指南](windows-model-and-material-provisioning.md)。
