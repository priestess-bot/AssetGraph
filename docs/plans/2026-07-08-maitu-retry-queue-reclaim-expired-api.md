# 麦兔重试队列过期领取回收 API

## 背景

上一轮已经增加 retry queue 的领取/释放机制：

```text
pending -> claim-next -> in_progress
release -> pending
```

但如果 Browser use worker 崩溃、断网、进程被杀，可能无法主动调用 release，导致任务永久停留在 `in_progress`。

本轮新增过期领取回收 API，让系统可以把超时锁自动放回队列。

## API

```http
POST /api/maitu/retry-queue/reclaim-expired
```

行为：

```text
status = in_progress
claim_expires_at < now()
  -> status = pending
  -> claimed_by = null
  -> claimed_at = null
  -> claim_expires_at = null
```

返回示例：

```json
{
  "reclaimed_count": 1,
  "retry_task_codes": ["MT-RETRY-20260708-000001"]
}
```

## 使用场景

- 定时任务周期性调用。
- Browser use worker 启动前调用一次。
- Agent 发现 retry queue 长时间无进展时调用。
- 管理后台提供“回收过期任务”按钮。

## 与 claim-next 的关系

`claim-next` 负责领取任务：

```text
pending -> in_progress
```

`reclaim-expired` 负责回收过期锁：

```text
in_progress + expired -> pending
```

两者配合后，即使 worker 异常退出，retry task 也不会永久卡死。

## 验收标准

- 调用 API 后能返回回收数量和任务编号列表。
- 被回收任务状态变为 `pending`。
- 被回收任务清空 `claimed_by`、`claimed_at`、`claim_expires_at`。
- 已验证 API 合约测试通过。
- 全量测试、编译检查和 SQL migration 解析通过。
