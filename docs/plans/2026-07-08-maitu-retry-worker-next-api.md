# 麦兔 retry worker next API

## 背景

Browser use worker 执行一次任务前，原本需要按顺序调用：

```text
POST /api/maitu/retry-queue/reclaim-expired
POST /api/maitu/retry-queue/claim-next
GET  /api/maitu/retry-tasks/{retry_task_code}/browser-use-operations
```

这对 worker 来说调用步骤偏多，也容易漏掉回收过期任务。

本轮新增 worker 一站式入口：

```http
POST /api/maitu/retry-worker/next
```

它会自动完成：

```text
reclaim expired locks
  -> claim next retry task
  -> return Browser use operation plan
```

## API

```http
POST /api/maitu/retry-worker/next
```

请求示例：

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

返回示例：

```json
{
  "reclaimed_count": 0,
  "reclaimed_retry_task_codes": [],
  "retry_task": {
    "retry_task_code": "MT-RETRY-20260708-000001",
    "status": "in_progress",
    "claimed_by": "browser-use-worker-1",
    "claimed_at": "2026-07-08T09:00:00Z",
    "claim_expires_at": "2026-07-08T09:15:00Z",
    "next_operation_type": "retry_replace_layer_asset",
    "browser_use_operations_url": "/api/maitu/retry-tasks/MT-RETRY-20260708-000001/browser-use-operations"
  },
  "operation_plan": {
    "retry_task_code": "MT-RETRY-20260708-000001",
    "executor": "browser_use",
    "target_app": "maitu",
    "operations": [
      {
        "operation_type": "retry_replace_layer_asset",
        "status": "ready",
        "instruction": "只重试槽位...保持原图层位置和尺寸不变..."
      }
    ]
  }
}
```

无可领取任务时返回 404。

## 推荐 worker 循环

```text
while true:
  POST /api/maitu/retry-worker/next
  if 404:
    sleep
    continue

  执行 response.operation_plan.operations

  成功:
    POST /api/maitu/retry-tasks/{retry_task_code}/execution-results

  可重试失败:
    POST /api/maitu/retry-tasks/{retry_task_code}/release

  不可重试/人工处理:
    POST /api/maitu/retry-tasks/{retry_task_code}/execution-results retry_execution_status=manual_required
```

## 验收标准

- worker-next 会先回收过期 claim。
- worker-next 会 claim 下一条可执行 retry task。
- worker-next 返回被 claim 的 retry task。
- worker-next 同时返回 Browser use operation plan。
- 无可领取任务时返回 404。
- 全量测试、编译检查和 SQL migration 解析通过。
