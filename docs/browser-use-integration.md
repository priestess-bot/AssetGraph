# AssetGraph 与 Browser-use 同仓一体化布局

## 1. 目标

将 AssetGraph 后端、RAG ingestion、素材清单、麦兔 Browser-use worker 和部署脚本放在同一个项目根目录下，方便后续：

```text
部署
迁移
备份
版本追踪
worker/backend 协议同步演进
```

项目根目录：

```text
D:/AssetGraph
```

---

## 2. 推荐项目结构

```text
AssetGraph/
  backend/                  AssetGraph FastAPI 后端、数据库迁移、RAG API
  workers/
    browser-use/            麦兔 Browser-use worker
      src/browser_use_worker/
      tests/
      pyproject.toml
      README.md
  scripts/                  本地工具脚本，例如素材扫描、inventory 生成、导入器
  docs/                     架构、RAG、麦兔、worker 协议文档
  infra/                    PostgreSQL / MinIO / Neo4j / Milvus 等基础设施
  素材/                     本地麦兔素材目录；大文件不进 Git
```

---

## 3. 边界划分

### 3.1 AssetGraph backend

负责：

```text
RAG 数据摄取
素材元数据管理
AG-* 全局编号
MT-* / DH-* 本地编号映射
麦兔槽位建模
候选素材推荐
替换方案生成
Browser-use operation_plan 生成
重试队列、领取、释放、回收
执行结果回写
```

### 3.2 Browser-use worker

负责：

```text
领取 AssetGraph retry task
读取 operation_plan
打开/操作麦兔页面
执行素材替换、保存、截图
将成功/失败/人工介入结果写回 AssetGraph
```

worker 不应该直接拥有素材推荐逻辑，也不应该自行生成替换方案。worker 只执行 AssetGraph 给出的计划。

---

## 4. 为什么同仓而不是分仓

| 项目 | 同仓优势 |
|---|---|
| 协议同步 | backend API schema 和 worker 消费逻辑可以一次提交同步更新 |
| 部署迁移 | 拷贝/部署一个项目目录即可包含 API、worker、脚本和文档 |
| 测试闭环 | 后端测试和 worker 测试可以在同一 CI/本地命令里跑 |
| RAG 上下文 | worker 使用的 operation_plan 与 AssetGraph RAG 检索结果保持同版本 |
| 文档一致 | 麦兔协议、槽位规则、重试规则和执行器实现不会分散 |

---

## 5. 当前 worker 状态

当前 worker 已有可测试的 Maitu executor 抽象层，并已接入第一版只读 Browser-use CLI 探测会话；仍不执行上传、替换、保存等真实变更操作。

已支持：

```text
claim-next 请求 payload 组装
领取 retry task
AssetGraph asset metadata 读取
MaituBrowserUseExecutor 操作分发
MaituBrowserSession 抽象接口
BrowserUseCliSession 只读页面探测
--probe-maitu 登录态/页面状态检查
--observe-maitu 结构化读取当前直播间状态
--plan-code MT-PLAN-* --dry-run
--plan-code MT-PLAN-* --preflight
--build-plan-code MT-BUILD-* --dry-run
--build-plan-code MT-BUILD-* --preflight-build
BuildPlan operation safe dry-run renderer（不打开浏览器、不点击、不保存）
BuildPlan operation allowlist / save_live_room manual_review / 禁开播安全检查
BuildPlan 当前登录态 / liveRoomId / 场景 / 激活场景图层 / 直播脚本面板 preflight
retry_replace_layer_asset
retry_asset_upload_and_replace
retry_save_project
recover_login_then_retry
manual_required / resolve_missing_slot_asset 分流
recoverable failure 释放回队列
成功结果回写
dry-run 校验 operation_plan
单元测试
```

尚未接入：

```text
真实上传/替换/保存执行
页面 selector 操作
截图上传为 AssetGraph asset
```

---

## 6. 本地运行

后端：

```bash
cd backend
uvicorn app.main:app --reload
```

worker 配置检查 / 只读页面探测 / dry-run：

```bash
cd workers/browser-use
python -m browser_use_worker --check-config
python -m browser_use_worker --probe-maitu
python -m browser_use_worker --once --dry-run
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --dry-run
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build
python -m browser_use_worker --build-plan-code MT-BUILD-20260709-000001 --preflight-build --skip-browser-probe
```

`--build-plan-code ... --dry-run` fetches `/api/maitu/live-room-build-plans/{build_plan_code}/browser-use-operations` and prints a structured safe-action summary for each operation. It never opens Browser-use, clicks Maitu, uploads assets, writes scripts, saves drafts, or starts live streaming. Mutating operations such as `replace_layer_asset` and `add_script_block` are rendered as `planned_*_not_executed`; `save_live_room` must stay `manual_review`.

`--probe-maitu` 只读取当前 browser-use 页面状态，必要时打开麦兔首页，并输出：

```json
{
  "url": "https://live2.maituai.com/LiveManage",
  "logged_in": true,
  "login_required": false,
  "opened_home": false
}
```

它不会点击上传控件、替换素材或保存项目。

环境变量：

```text
ASSETGRAPH_API_BASE_URL=http://127.0.0.1:8000
BROWSER_USE_WORKER_ID=browser-use-worker-1
BROWSER_USE_LOCK_TTL_SECONDS=900
BROWSER_USE_POLL_INTERVAL_SECONDS=5
BROWSER_USE_MAX_ATTEMPTS=3
```

---

## 7. 后续接入真实 browser-use 的步骤

1. 在 `workers/browser-use` 中将 `BrowserUseCliSession` 从只读探测扩展为真实执行 session。
2. 使用 browser-use / Playwright 完成麦兔页面 selector 操作。
3. 明确浏览器 profile / cookies / 登录态保存位置。
4. 将本地素材路径从 `asset.local_relative_path` / `local_file_code` 解析为可上传文件。
5. 将截图保存并通过 AssetGraph 上传/入库，返回 `screenshot_asset_code`。
6. 将真实成功/失败结果回写 retry task。
7. 增加端到端测试：创建 retry task -> worker claim -> fake/real browser-use 执行 -> 回写 -> 状态变更。

---

## 8. 部署建议

后端、数据库、MinIO、Neo4j、Milvus 可以容器化部署；browser-use worker 需要能访问图形浏览器和麦兔网页，因此第一阶段建议部署在 Windows 桌面会话或支持浏览器自动化的工作机上。

部署时仍然以同一个项目目录为单位：

```text
AssetGraph/
  backend/
  workers/browser-use/
  scripts/
  infra/
  docs/
```
