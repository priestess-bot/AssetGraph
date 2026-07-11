# 麦兔 Browser use 重试 Worker 执行协议

## 1. 目的

本文定义 Browser use worker 如何消费 AssetGraph 中的麦兔重试任务队列，并把执行结果回写给 AssetGraph。

AssetGraph 负责：

```text
生成重试任务
管理队列状态
领取/释放/回收任务锁
生成 Browser use 操作计划
接收执行结果回写
```

Browser use worker 负责：

```text
打开/操作麦兔软件
按 operation_plan 执行失败槽位的最小化重试
保存项目
截图留痕
把结果回写给 AssetGraph
```

重要边界：AssetGraph 不直接控制麦兔软件；Browser use 才是实际执行器。

---

## 2. Worker 主循环

推荐 worker 循环：

```text
while true:
  1. POST /api/maitu/retry-worker/next
  2. 如果返回 404：sleep 后继续
  3. 读取 response.retry_task 和 response.operation_plan，并保存 claim_token / lease_version
  4. 在任何麦兔变更前 POST heartbeat 验证租约，执行期间按间隔续租
  5. 对每个 operation：先 begin checkpoint；execute 才允许变更，skip 零副作用跳过，reconcile 转人工
  6. mutation 获得 verified readback evidence 后 complete checkpoint；complete 未确认时禁止下游 operation
  7. 成功：携带租约身份和稳定 retry_execution_id POST execution-results
  8. 可恢复失败：携带租约身份和稳定 retry_execution_id POST execution-results，状态 released
  9. 不可恢复/人工处理：携带租约身份和稳定 retry_execution_id POST execution-results
```

---

## 3. 取任务

### 请求

```http
POST /api/maitu/retry-worker/next
```

```json
{
  "claimed_by": "browser-use-worker-1",
  "lock_ttl_seconds": 900,
  "failure_type": "missing_layer",
  "maitu_project_code": "MT-PROJ-20260708-000001",
  "scene_name": "京东空白直播间",
  "max_attempts": 3
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `claimed_by` | 是 | worker 唯一标识，建议包含机器名/进程号/实例编号 |
| `lock_ttl_seconds` | 否 | 任务锁过期秒数，默认 900 |
| `failure_type` | 否 | 只领取指定失败类型 |
| `maitu_project_code` | 否 | 只领取指定麦兔项目任务 |
| `scene_name` | 否 | 只领取指定场景任务 |
| `max_attempts` | 否 | 只领取 `retry_attempt_count < max_attempts` 的任务 |

### 成功响应

```json
{
  "reclaimed_count": 0,
  "reclaimed_retry_task_codes": [],
  "retry_task": {
    "retry_task_code": "MT-RETRY-20260708-000001",
    "plan_code": "MT-PLAN-20260708-000001",
    "execution_code": "MT-EXEC-20260708-000001",
    "slot_code": "MT-SLOT-20260708-000001",
    "asset_code": "AG-IMG-20260708-000001",
    "executor": "browser_use",
    "failure_type": "missing_layer",
    "retryable": true,
    "status": "in_progress",
    "retry_attempt_count": 0,
    "claimed_by": "browser-use-worker-1",
    "claimed_at": "2026-07-08T09:00:00Z",
    "claim_expires_at": "2026-07-08T09:15:00Z",
    "claim_token": "[REDACTED]",
    "lease_version": 1,
    "maitu_project_code": "MT-PROJ-20260708-000001",
    "scene_name": "京东空白直播间",
    "slot_name": "商品主图",
    "layer_name": "layer_8",
    "next_operation_type": "retry_replace_layer_asset",
    "browser_use_operations_url": "/api/maitu/retry-tasks/MT-RETRY-20260708-000001/browser-use-operations"
  },
  "operation_plan": {
    "retry_task_code": "MT-RETRY-20260708-000001",
    "plan_code": "MT-PLAN-20260708-000001",
    "execution_code": "MT-EXEC-20260708-000001",
    "executor": "browser_use",
    "target_app": "maitu",
    "maitu_project_code": "MT-PROJ-20260708-000001",
    "scene_name": "京东空白直播间",
    "operations": [
      {
        "operation_type": "retry_replace_layer_asset",
        "retry_task_code": "MT-RETRY-20260708-000001",
        "slot_code": "MT-SLOT-20260708-000001",
        "slot_name": "商品主图",
        "scene_name": "京东空白直播间",
        "layer_name": "layer_8",
        "asset_code": "AG-IMG-20260708-000001",
        "asset_title": "胶原蛋白商品主图-白底款",
        "replacement_policy": "keep_layout",
        "failure_type": "missing_layer",
        "status": "ready",
        "instruction": "执行重试任务...只重试槽位...保持原图层位置和尺寸不变..."
      }
    ]
  }
}
```

### 无任务响应

```http
404 No claimable Maitu retry task found
```

worker 应 sleep 后重试，不要把 404 视为异常报警。

`claim_token` 是当前领取的不可猜测租约凭据，只在 claim-next 和 retry-worker/next 的成功响应中返回；普通 retry task 列表和 GET 不返回它。worker 不得记录或跨任务复用该值。每次重新领取都会生成新 token 并递增 `lease_version`。

### 租约续租

真实执行前、执行期间以及 release / execution-results 获得确定响应前调用：

```http
POST /api/maitu/retry-tasks/{retry_task_code}/heartbeat
```

```json
{
  "claimed_by": "browser-use-worker-1",
  "claim_token": "[REDACTED]",
  "lease_version": 1,
  "lock_ttl_seconds": 900
}
```

heartbeat、release 和 execution-results 都要求任务仍为 `in_progress`、租约未过期，且 `claimed_by`、`claim_token`、`lease_version` 全部匹配。旧 token、旧 version、过期租约或其他 worker 的回写返回 `409 Conflict`。

浏览器操作结束后，worker 必须先停止并回收执行期 heartbeat 线程，再同步 heartbeat 一次以获得完整的新 TTL，随后启动新的 callback heartbeat，直到 execution-results 获得确定响应。三次 execution-results 尝试的请求 timeout 与退避总预算必须低于该 TTL；所有尝试继续复用完全相同的 `retry_execution_id` 和 payload。成功、人工介入和可恢复释放都通过该幂等 receipt 通道确认；可恢复释放使用 `retry_execution_status=released`，原子回到 `pending` 且不消耗 retry attempt。这样，慢 HTTP 重试或服务端已提交但响应丢失都不会造成重复计数或 Worker 崩溃。

每个 non-dry-run 队列任务只允许内置的 exact `MaituBrowserUseExecutor`，其 session 也必须是 exact `BrowserUseCliSession`；structural Protocol、子类或第三方 executor/session 即使自报 guard/timeout 支持也会在 claim、heartbeat 或浏览器调用前被拒绝。所有关键 executor/session 方法必须仍绑定到原始类实现，实例级 `MethodType` 覆盖、注入 command runner 以及与 Worker 不同的 asset client 同样在 claim 前拒绝。`BrowserUseWorker.run_once()` 在 dry-run 下会在 claim 前直接拒绝，保证公开 Worker API 也不会修改队列；只读 dry-run 必须走不领取任务的 plan/build-plan 路径。受信任的 concrete executor 必须实现执行 guard，并从受信任 session 读取单次外部副作用的最大 timeout。Worker 只在该 timeout 小于租约 TTL 的 80% 时执行。具体麦兔 CLI session 在每条 browser-use 命令前同步 heartbeat；因此单条阻塞命令即使无法在进程内强制取消，也会从 timeout 起被限制在当前 TTL 内，下一条副作用前仍需重新通过 lease guard。

通用 `PATCH /retry-tasks/{code}` 只允许修改 `result_summary` / `retry_instruction`，且任务为 `in_progress` 时返回 409。`status`、`retry_attempt_count` 和执行编号只能通过带租约身份及 receipt 的 execution-results/release 协议改变。

---

## 4. 执行前预检（只读）

在真实 Browser use 改动麦兔项目之前，建议先对指定替换方案运行只读预检：

```bash
cd workers/browser-use
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight
```

预检会调用：

```http
GET /api/maitu/replacement-plans/{plan_code}/browser-use-operations
GET /api/assets/{asset_code}
```

并检查：

1. `operation_plan.operations` 非空。
2. `operation_type` 被当前 worker 支持，且不是 `manual_retry_required` / `resolve_missing_slot_asset`。
3. operation plan 含 `maitu_project_code` 与 `scene_name`。
4. 每个替换操作都能查到 AssetGraph 素材。
5. operation 包含 Browser-use 友好字段：`asset_display_code`、`asset_local_file_code`、`asset_original_filename`、`asset_browser_use_hint`。
6. 本地素材文件存在于 `--assets-root` 下，且大小与 AssetGraph 元数据一致或给出 warning。
7. Browser-use 当前会话可看到麦兔页面，并且不是登录页。
8. 当前麦兔页面文本中可见目标 `layer_name` 或 `slot_name`；否则拒绝无人值守替换，避免把素材替换到错误图层。

预检不领取 retry queue，不上传素材，不替换图层，不保存项目。返回 JSON 中：

```json
{
  "status": "passed|warning|failed",
  "ready_to_execute": true,
  "failure_count": 0,
  "warning_count": 0,
  "skipped_count": 0,
  "checks": []
}
```

`ready_to_execute=true` 只表示预检无失败、无 warning、无 skipped；它不是实际替换成功证明。

如只做 API/文件 smoke test，可跳过浏览器探测：

```bash
python -m browser_use_worker --plan-code MT-PLAN-20260709-000001 --preflight --skip-browser-probe
```

这会返回 `status=warning` 且 `ready_to_execute=false`，因为麦兔登录态未验证。

---

## 5. 执行 operation_plan

worker 必须按 `operation_plan.operations` 执行。

Phase 6C-A 将每个 retry task 展开为显式副作用 operation：通常是 `primary` 与 `save_project`；`save_failed` 只返回一个 `save_project`，避免双重保存。每个 operation 必须携带稳定的 `operation_key`、64 位小写十六进制 `operation_fingerprint` 和 `status=ready`。

执行原则：

1. 只重试 `operation.slot_code` 指定的失败槽位。
2. 不重新构图。
3. 不改变原场景结构。
4. 保持原 `layer_name`、位置、尺寸、层级。
5. 只替换目标素材资源。
6. 替换后保存麦兔项目。
7. 如有截图能力，保存截图并回写 `screenshot_asset_code`。

---

## 6. operation_type 处理

| operation_type | worker 行为 |
|---|---|
| `retry_replace_layer_asset` | 重新定位场景/图层/槽位，替换素材，保持布局 |
| `retry_asset_upload_and_replace` | 重新上传素材，再替换到目标槽位 |
| `retry_save_project` | 重新保存项目，必要时截图确认 |
| `recover_login_then_retry` | 先恢复登录，再重新执行替换 |
| `resolve_missing_slot_asset` | 素材缺失，通常需要重新查询或人工确认 |
| `manual_retry_required` | 不自动操作，回写 manual_required |
| `retry_browser_use_operation` | 当前不执行通用 instruction；fail closed 并回写 `manual_required`，必须重新生成明确支持的 operation type |

---

## 7. 操作级 checkpoint barrier

租约只能阻止 stale worker 的下一次写入，不能判断上一条麦兔命令是“未执行”还是“已执行但响应丢失”。因此每个副作用 operation 都必须使用 checkpoint：

### Begin

```http
POST /api/maitu/retry-tasks/{retry_task_code}/operations/{operation_key}/begin
```

```json
{
  "claimed_by": "browser-use-worker-1",
  "claim_token": "[REDACTED]",
  "lease_version": 1,
  "attempt_id": "87715675-af7c-4b75-9d4c-14f9c45e20f4",
  "operation_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

决策：

- `execute`：begin 已确定持久化，允许执行当前 operation。
- `skip`：相同 authoritative fingerprint 已完成，禁止重放 mutation。
- `reconcile`：旧 lease 已开始但未确定完成；禁止 mutation，转人工核对。

Begin 请求结果不确定时，最多重试 3 次，必须复用同一 `attempt_id` 和完全相同的 payload；在获得确定 `execute` 前不得调用任何麦兔 mutation。

### Complete

mutation 返回 authoritative readback evidence 且 `verified=true` 后调用：

```http
POST /api/maitu/retry-tasks/{retry_task_code}/operations/{operation_key}/complete
```

```json
{
  "claimed_by": "browser-use-worker-1",
  "claim_token": "[REDACTED]",
  "lease_version": 1,
  "attempt_id": "87715675-af7c-4b75-9d4c-14f9c45e20f4",
  "operation_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "completion_id": "f8e2ad75-270d-4190-8255-7334399f7c8d",
  "result_summary": "authoritative readback verified",
  "evidence": {"verified": true, "material_id": 41043}
}
```

Complete 未获得确定响应时，最多重试 3 次并复用同一 `completion_id`、`attempt_id` 和 payload；全部失败后回写 `released`，禁止执行下游 operation。Backend 会将未完成 checkpoint 转为 `reconcile_required`，新 lease 只能 reconcile，不能无脑重放。

Checkpoint 表不保存 `claim_token`。completion evidence 必须是 `verified=true` 的权威 readback；Backend、Worker 与数据库约束共同拒绝未验证 evidence。Evidence 递归拒绝大小写/分隔符变体的 credential key（例如 authorization、各类 token、cookie、password、secret），并拒绝任意字符串位置包含当前 claim token。Execution-result 的摘要、错误、重试说明及其他持久字段同样不得包含当前 claim token，receipt 写入前会再次递归检查。终态 `succeeded` 只有在当前 authoritative operation keys/fingerprints 全部存在安全、已验证的 `completed` checkpoint 时才允许写入。活动 retry lease 期间，关联 slot 的 PATCH/DELETE 会返回 409，以冻结跨外部副作用窗口的 authoritative intent。

### 人工 Reconciliation（Phase 6C-B）

`reconcile_required` 不能靠普通重试清除。操作员必须先确保 retry task 没有活动 worker lease，再使用同一 operator credential 读取：

```http
GET /api/maitu/retry-tasks/{retry_task_code}/operation-checkpoints
```

从响应取得当前 `reconcile_required` 项的 exact `operation_key`、`operation_fingerprint` 和 `attempt_id`，随后根据麦兔权威读回提交：

```http
POST /api/maitu/retry-tasks/{retry_task_code}/operations/{operation_key}/reconcile
```

```json
{
  "reconciliation_id": "d8f7a0e1-6c2e-4fd0-86e0-9999d0010001",
  "expected_attempt_id": "87715675-af7c-4b75-9d4c-14f9c45e20f4",
  "operation_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "resolution": "confirmed_not_applied",
  "resolution_summary": "麦兔权威读回确认目标图层仍为旧素材",
  "evidence": {
    "verified": true,
    "operation_applied": false,
    "observed_material_id": 41042
  }
}
```

- `/reconcile` 必须携带后端配置的 operator Bearer credential；`resolved_by` 由服务端认证配置生成，客户端不能自报身份。后端通过 `MAITU_RECONCILIATION_OPERATOR_TOKEN` 和 `MAITU_RECONCILIATION_OPERATOR_ID` 配置；未配置 token 时接口返回 503。
- `expected_attempt_id` 必须与当前 `reconcile_required` checkpoint 的 attempt 完全一致；旧人工页面不能解析后续同 fingerprint 的新 attempt。
- `confirmed_completed` 必须带 `operation_applied=true`，checkpoint 进入 `completed`；下一 claim 的 begin 返回 `skip`。
- `confirmed_not_applied` 必须带 `operation_applied=false`，checkpoint 进入一次性的 `retry_authorized`；下一 claim 的 begin 在同一事务中把它消费为 `begun` 并返回 `execute`。
- 两种结果都把 task 恢复为 `pending`，让 Worker 继续其余显式 operation。
- reconciliation 只接受当前 authoritative fingerprint，活动 lease、错误状态、未验证或含 credential 的 evidence 均返回冲突或校验失败。`resolution_summary` 与 evidence 的所有嵌套键和值同样禁止配置中的 operator secret、Bearer、常见及现代 provider token（含 `sk-proj-*`、`github_pat_*`、`hf_*`），以及 canonical/compact UUID 形态的 claim token（即使与其他字符拼接仍按子串拒绝）；敏感语义键名仍递归拒绝。请求校验失败的 422 响应只保留错误类型、顶层来源（如 `body/query/path`）和固定消息；Pydantic 的原始 `input`/`ctx`、用户控制的字段路径与消息都不会回显。
- 重试请求必须复用同一 `reconciliation_id` 和完全相同 payload；同 ID 同内容幂等返回，同 ID 异内容冲突。
- reconciliation receipt 与 checkpoint 都不保存 `claim_token`。

---

## 8. 成功回写

### 请求

```http
POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
```

```json
{
  "retry_execution_id": "7be4e98f-dd31-4c50-97d6-604d46ec7869",
  "retry_execution_status": "succeeded",
  "claimed_by": "browser-use-worker-1",
  "claim_token": "[REDACTED]",
  "lease_version": 1,
  "last_retry_execution_code": "MT-EXEC-20260708-000002",
  "result_summary": "Browser use 重新定位 layer_8 后已完成商品主图替换并保存项目。",
  "screenshot_asset_code": "AG-IMG-20260708-000199"
}
```

结果：

```text
status = succeeded
retry_attempt_count += 1
last_retry_execution_code = 请求值
result_summary = 请求值
screenshot_asset_code = 请求值
```

`retry_execution_id` 是本次执行的幂等键。网络结果不确定时，worker 必须用同一个 ID 和完全相同的 payload 重试：相同内容只增加一次 `retry_attempt_count`；同一 ID 被不同 payload 或不同任务复用时返回 `409 Conflict`。

---

## 9. 可恢复失败：幂等 receipt 回队列

当 worker 认为失败可能通过后续重试恢复，例如：

- 麦兔临时卡顿
- 网络抖动
- 保存按钮短暂不可用
- worker 自身浏览器异常
- worker 需要重启

Worker 不调用一次性、无法确认响应丢失的 release callback，而是复用幂等 execution-results 通道：

```http
POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
```

```json
{
  "retry_execution_id": "4413b514-bdf1-4319-ac39-efabc6b16f76",
  "retry_execution_status": "released",
  "result_summary": "worker browser crashed; release back to queue",
  "claimed_by": "browser-use-worker-1",
  "claim_token": "[REDACTED]",
  "lease_version": 1
}
```

结果：

```text
status = pending
retry_attempt_count 不增加
last_retry_execution_id = retry_execution_id
claimed_by = null
claimed_at = null
claim_expires_at = null
claim_token = null
lease_version 保留，下一次领取时递增
```

同一 `retry_execution_id` 和完全相同 payload 可安全重试；服务端已提交但响应丢失时不会重复消费 attempt。`POST .../release` 仍保留给显式人工/管理操作，但队列 Worker 的自动回调必须使用上述 receipt 协议。

---

## 10. 不可恢复失败 / 人工处理

当 worker 确认自动化无法继续，例如：

- 麦兔模板被改动，目标图层确实不存在
- 登录需要人工验证码
- 素材文件缺失且无法自动获取
- 替换规则不明确

调用：

```http
POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
```

```json
{
  "retry_execution_id": "4413b514-bdf1-4319-ac39-efabc6b16f76",
  "retry_execution_status": "manual_required",
  "claimed_by": "browser-use-worker-1",
  "claim_token": "[REDACTED]",
  "lease_version": 1,
  "last_retry_execution_code": "MT-EXEC-20260708-000003",
  "error_message": "重新扫描后仍未找到 layer_8。",
  "result_summary": "需要人工确认麦兔模板图层是否被改名。",
  "retry_instruction": "人工确认模板图层名称后再重试。",
  "screenshot_asset_code": "AG-IMG-20260708-000200"
}
```

结果：

```text
status = manual_required
retry_attempt_count += 1
```

---

## 11. 锁与超时

`POST /api/maitu/retry-worker/next` 会自动先执行过期回收：

```text
status = in_progress
claim_expires_at < now()
  -> status = pending
  -> clear claimed_by / claimed_at / claim_expires_at / claim_token
  -> keep lease_version; the next claim increments it
```

因此 worker 启动时无需单独调用 `reclaim-expired`。

如果不用 worker-next，而是手动编排，则推荐流程：

```text
POST /api/maitu/retry-queue/reclaim-expired
POST /api/maitu/retry-queue/claim-next
GET  /api/maitu/retry-tasks/{retry_task_code}/browser-use-operations
```

---

## 12. Worker 错误处理策略

| 情况 | 处理 |
|---|---|
| `/retry-worker/next` 返回 404 | sleep 后继续轮询 |
| 初始 heartbeat 返回 409/失败 | 不启动 Browser use；等待当前租约过期或由新领取者处理 |
| 执行中 heartbeat 失败 | 在 concrete executor 的下一个副作用边界停止；最终重验失败则禁止 execution-results 回写 |
| execution-results 响应缓慢/丢失 | 最终同步续租后保持 callback heartbeat；复用同一 ID/payload，并将三次请求 timeout/退避预算限制在 TTL 内 |
| Browser use 启动失败 | 以 `retry_execution_status=released` 幂等回写，或让锁过期后回收 |
| 麦兔登录过期 | 若可自动登录，执行；否则回写 `manual_required` |
| 找不到图层 | 重新扫描一次；仍失败则按 `failure_type` 决定 `released` 或 `manual_required` |
| 保存失败 | 可回写 `released`，或回写 `failed` 并附截图 |
| worker 进程崩溃 | 无需处理，锁过期后 reclaim |

---

## 13. 最小 Python 伪代码

```python
import time
import uuid
import requests

BASE_URL = "http://localhost:8000/api/maitu"
WORKER_ID = "browser-use-worker-1"

while True:
    response = requests.post(
        f"{BASE_URL}/retry-worker/next",
        json={"claimed_by": WORKER_ID, "lock_ttl_seconds": 900, "max_attempts": 3},
        timeout=30,
    )
    if response.status_code == 404:
        time.sleep(10)
        continue
    response.raise_for_status()

    payload = response.json()
    task = payload["retry_task"]
    task_code = task["retry_task_code"]
    lease = {
        "claimed_by": WORKER_ID,
        "claim_token": task["claim_token"],
        "lease_version": task["lease_version"],
    }

    # 真实变更前同步验证；执行期间另启循环，每隔 TTL/3 调用同一 heartbeat。
    requests.post(
        f"{BASE_URL}/retry-tasks/{task_code}/heartbeat",
        json={**lease, "lock_ttl_seconds": 900},
        timeout=30,
    ).raise_for_status()
    heartbeat = start_heartbeat(task_code, lease, interval_seconds=300)
    try:
        for operation in payload["operation_plan"]["operations"]:
            attempt_id = str(uuid.uuid4())
            begin_payload = {
                **lease,
                "attempt_id": attempt_id,
                "operation_fingerprint": operation["operation_fingerprint"],
            }
            checkpoint = post_idempotently(
                f"{BASE_URL}/retry-tasks/{task_code}/operations/{operation['operation_key']}/begin",
                begin_payload,
                max_attempts=3,
            )
            if checkpoint["decision"] == "skip":
                continue
            if checkpoint["decision"] == "reconcile":
                raise ManualReconciliationRequired(operation["operation_key"])
            evidence = run_browser_use_operation(operation)
            if evidence.get("verified") is not True:
                raise ManualReconciliationRequired(operation["operation_key"])
            complete_payload = {
                **begin_payload,
                "completion_id": str(uuid.uuid4()),
                "result_summary": "authoritative readback verified",
                "evidence": evidence,
            }
            post_idempotently(
                f"{BASE_URL}/retry-tasks/{task_code}/operations/{operation['operation_key']}/complete",
                complete_payload,
                max_attempts=3,
            )
        result = succeeded_result()
    finally:
        heartbeat.stop_and_join()

    # 回写前必须重新取得完整 TTL；失败则禁止旧 worker 回写。
    requests.post(
        f"{BASE_URL}/retry-tasks/{task_code}/heartbeat",
        json={**lease, "lock_ttl_seconds": 900},
        timeout=30,
    ).raise_for_status()

    retry_execution_id = str(uuid.uuid4())
    result_payload = {
        **lease,
        "retry_execution_id": retry_execution_id,
        "retry_execution_status": result.status,
        "result_summary": result.summary,
        "screenshot_asset_code": result.screenshot_asset_code,
    }
    callback_heartbeat = start_heartbeat(task_code, lease, interval_seconds=300)
    try:
        # 所有尝试复用相同 ID/payload，且 3 次 timeout + 退避总和必须小于 TTL。
        post_idempotently(
            f"{BASE_URL}/retry-tasks/{task_code}/execution-results",
            result_payload,
            max_attempts=3,
            timeout_seconds=240,
        )
    finally:
        callback_heartbeat.stop_and_join()
```

---

## 14. 验收检查清单

worker 接入前应确认：

- [ ] worker 有唯一 `claimed_by`。
- [ ] worker 使用 `/api/maitu/retry-worker/next` 取任务。
- [ ] worker 将 `claim_token` 视为短期秘密，不记录、不跨领取复用。
- [ ] worker 在首个外部写前验证 heartbeat，并在执行期间续租。
- [ ] 每条 browser-use 命令前同步续租，单次外部调用 timeout 小于 TTL 的 80%。
- [ ] worker 在 callback 前最终续租，并保持 heartbeat 到 execution-results 确认完成。
- [ ] execution-results 重试的 timeout 与退避总预算小于租约 TTL。
- [ ] heartbeat/execution-results 都携带当前 `claimed_by + claim_token + lease_version`。
- [ ] worker 只执行 `operation_plan.operations` 中的失败槽位。
- [ ] 每个 retry operation 都有 canonical `operation_key`、authoritative fingerprint 和 `status=ready`。
- [ ] begin 返回确定 `execute` 前零 mutation；`skip` 零 mutation；`reconcile` 转人工。
- [ ] mutation 只有拿到 `verified=true` readback evidence 后才 complete checkpoint。
- [ ] begin/complete 重试分别复用稳定 `attempt_id` / `completion_id` 与完全相同 payload。
- [ ] complete 未确认时禁止执行下游 operation。
- [ ] worker 不改变麦兔原布局。
- [ ] 成功、可恢复释放和人工结果都使用 UUID `retry_execution_id`，传输重试复用相同 ID 和 payload。
- [ ] 成功时回写 `succeeded`。
- [ ] 可恢复失败时通过 execution-results 回写 `released`，不消费 retry attempt。
- [ ] 不可恢复失败时回写 `manual_required`。
- [ ] worker 崩溃后任务能通过 reclaim-expired 回到队列。
