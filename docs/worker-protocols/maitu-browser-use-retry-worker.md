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
  3. 读取 response.retry_task 和 response.operation_plan
  4. 执行 operation_plan.operations
  5. 成功：POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
  6. 可恢复失败：POST /api/maitu/retry-tasks/{retry_task_code}/release
  7. 不可恢复/人工处理：POST /api/maitu/retry-tasks/{retry_task_code}/execution-results，状态 manual_required
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

---

## 4. 执行 operation_plan

worker 必须按 `operation_plan.operations` 执行。

第一版约定一个 retry task 返回一个 operation；未来可以扩展为多个 operation。

执行原则：

1. 只重试 `operation.slot_code` 指定的失败槽位。
2. 不重新构图。
3. 不改变原场景结构。
4. 保持原 `layer_name`、位置、尺寸、层级。
5. 只替换目标素材资源。
6. 替换后保存麦兔项目。
7. 如有截图能力，保存截图并回写 `screenshot_asset_code`。

---

## 5. operation_type 处理

| operation_type | worker 行为 |
|---|---|
| `retry_replace_layer_asset` | 重新定位场景/图层/槽位，替换素材，保持布局 |
| `retry_asset_upload_and_replace` | 重新上传素材，再替换到目标槽位 |
| `retry_save_project` | 重新保存项目，必要时截图确认 |
| `recover_login_then_retry` | 先恢复登录，再重新执行替换 |
| `resolve_missing_slot_asset` | 素材缺失，通常需要重新查询或人工确认 |
| `manual_retry_required` | 不自动操作，回写 manual_required |
| `retry_browser_use_operation` | 通用重试，按 instruction 执行 |

---

## 6. 成功回写

### 请求

```http
POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
```

```json
{
  "retry_execution_status": "succeeded",
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

---

## 7. 可恢复失败：release 回队列

当 worker 认为失败可能通过后续重试恢复，例如：

- 麦兔临时卡顿
- 网络抖动
- 保存按钮短暂不可用
- worker 自身浏览器异常
- worker 需要重启

调用：

```http
POST /api/maitu/retry-tasks/{retry_task_code}/release
```

```json
{
  "status": "pending",
  "result_summary": "worker browser crashed; release back to queue"
}
```

结果：

```text
status = pending
claimed_by = null
claimed_at = null
claim_expires_at = null
```

---

## 8. 不可恢复失败 / 人工处理

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
  "retry_execution_status": "manual_required",
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

## 9. 锁与超时

`POST /api/maitu/retry-worker/next` 会自动先执行过期回收：

```text
status = in_progress
claim_expires_at < now()
  -> status = pending
  -> clear claimed_by / claimed_at / claim_expires_at
```

因此 worker 启动时无需单独调用 `reclaim-expired`。

如果不用 worker-next，而是手动编排，则推荐流程：

```text
POST /api/maitu/retry-queue/reclaim-expired
POST /api/maitu/retry-queue/claim-next
GET  /api/maitu/retry-tasks/{retry_task_code}/browser-use-operations
```

---

## 10. Worker 错误处理策略

| 情况 | 处理 |
|---|---|
| `/retry-worker/next` 返回 404 | sleep 后继续轮询 |
| Browser use 启动失败 | release 当前任务，或让锁过期后回收 |
| 麦兔登录过期 | 若可自动登录，执行；否则回写 `manual_required` |
| 找不到图层 | 重新扫描一次；仍失败则按 `failure_type` 决定 release 或 manual_required |
| 保存失败 | 可 release，或回写 failed 并附截图 |
| worker 进程崩溃 | 无需处理，锁过期后 reclaim |

---

## 11. 最小 Python 伪代码

```python
import time
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
    retry_task = payload["retry_task"]
    operation_plan = payload["operation_plan"]
    retry_task_code = retry_task["retry_task_code"]

    try:
        result = run_browser_use(operation_plan)
    except RecoverableWorkerError as exc:
        requests.post(
            f"{BASE_URL}/retry-tasks/{retry_task_code}/release",
            json={"status": "pending", "result_summary": str(exc)},
            timeout=30,
        )
        continue
    except ManualRequiredError as exc:
        requests.post(
            f"{BASE_URL}/retry-tasks/{retry_task_code}/execution-results",
            json={
                "retry_execution_status": "manual_required",
                "error_message": str(exc),
                "result_summary": "需要人工介入。",
            },
            timeout=30,
        )
        continue

    requests.post(
        f"{BASE_URL}/retry-tasks/{retry_task_code}/execution-results",
        json={
            "retry_execution_status": "succeeded",
            "last_retry_execution_code": result.execution_code,
            "result_summary": result.summary,
            "screenshot_asset_code": result.screenshot_asset_code,
        },
        timeout=30,
    )
```

---

## 12. 验收检查清单

worker 接入前应确认：

- [ ] worker 有唯一 `claimed_by`。
- [ ] worker 使用 `/api/maitu/retry-worker/next` 取任务。
- [ ] worker 只执行 `operation_plan.operations` 中的失败槽位。
- [ ] worker 不改变麦兔原布局。
- [ ] 成功时回写 `succeeded`。
- [ ] 可恢复失败时调用 `release`。
- [ ] 不可恢复失败时回写 `manual_required`。
- [ ] worker 崩溃后任务能通过 reclaim-expired 回到队列。
