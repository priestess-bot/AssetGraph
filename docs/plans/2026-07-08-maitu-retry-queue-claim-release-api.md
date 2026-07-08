# 麦兔重试队列领取与释放 API

## 背景

`GET /api/maitu/retry-queue` 已能批量返回可重试任务，但多 worker 并发处理时会出现同一个 `MT-RETRY-*` 被多个 Browser use worker 同时拿走的问题。

本轮新增领取/锁定机制：

```text
pending -> in_progress
```

并记录：

```text
claimed_by
claimed_at
claim_expires_at
```

这样 Browser use 可以多实例并行拉取任务，避免重复执行同一个重试任务。

## API

### 1. 领取下一个任务

```http
POST /api/maitu/retry-queue/claim-next
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

行为：

```text
选择一个 pending、retryable、retry_attempt_count < max_attempts 的任务
  -> status = in_progress
  -> claimed_by = 请求方
  -> claimed_at = now()
  -> claim_expires_at = now() + lock_ttl_seconds
```

返回被领取的 retry queue item，包含：

```text
retry_task_code
status = in_progress
claimed_by
claimed_at
claim_expires_at
next_operation_type
browser_use_operations_url
```

无可领取任务时返回 404。

### 2. 释放任务

```http
POST /api/maitu/retry-tasks/{retry_task_code}/release
```

请求示例：

```json
{
  "status": "pending",
  "result_summary": "worker heartbeat lost; release back to queue"
}
```

行为：

```text
status = 请求状态，默认 pending
claimed_by = null
claimed_at = null
claim_expires_at = null
```

可用于 worker 崩溃、心跳丢失、人工撤销执行等场景。

## 数据库字段

在 `maitu_execution_retry_tasks` 中新增：

```text
claimed_by VARCHAR(128)
claimed_at TIMESTAMPTZ
claim_expires_at TIMESTAMPTZ
```

新增索引：

```text
idx_maitu_retry_tasks_claimed_by
idx_maitu_retry_tasks_claim_expires_at
```

## 并发说明

真实 PostgreSQL repository 使用：

```sql
FOR UPDATE SKIP LOCKED
```

领取任务，避免多个 worker 同时 claim 到同一条 retry task。

## 验收标准

- 可以 claim 下一个 pending/retryable/未超过最大尝试次数的任务。
- claim 后任务状态变为 `in_progress`。
- claim 后写入 `claimed_by`、`claimed_at`、`claim_expires_at`。
- claim 后默认 retry queue 不再返回该任务。
- 可以 release 已领取任务。
- release 后清空 claim 字段，状态回到 `pending`。
- release 不存在的 retry task 返回 404。
- 全量测试、编译检查和 SQL migration 解析通过。
