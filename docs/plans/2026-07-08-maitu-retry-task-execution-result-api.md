# 麦兔重试任务执行结果回写 API

## 背景

AssetGraph 已经支持：

```text
Browser use 执行失败
  -> AssetGraph 生成 MT-RETRY-* 重试任务
  -> AssetGraph 生成 Browser use 最小化重试操作计划
```

但重试执行完成后，还需要 Browser use 把结果回写给 AssetGraph，否则 retry task 无法自动关闭或进入下一轮处理。

本轮目标是补齐：

```text
执行重试 -> 回写结果 -> 更新 retry task 状态
```

## API

```http
POST /api/maitu/retry-tasks/{retry_task_code}/execution-results
```

请求示例：

```json
{
  "retry_execution_status": "succeeded",
  "last_retry_execution_code": "MT-EXEC-20260708-000002",
  "result_summary": "Browser use 重新定位 layer_8 后已完成商品主图替换并保存项目。",
  "screenshot_asset_code": "AG-IMG-20260708-000199"
}
```

失败示例：

```json
{
  "retry_execution_status": "failed",
  "last_retry_execution_code": "MT-EXEC-20260708-000003",
  "error_message": "重新扫描后仍未找到 layer_8。",
  "result_summary": "重试失败，需要人工确认麦兔模板图层是否被改名。",
  "retry_instruction": "人工确认模板图层名称后再重试。"
}
```

## 字段

```text
retry_execution_status      重试执行状态：succeeded / failed / manual_required / ...
last_retry_execution_code   最近一次重试对应的执行编号
result_summary              重试结果摘要
error_message               重试失败错误信息
screenshot_asset_code       重试截图素材编号
retry_instruction           下一轮重试或人工处理指令
```

## 状态映射

```text
succeeded        -> retry task status = succeeded
failed           -> retry task status = failed
manual_required  -> retry task status = manual_required
其他             -> 原样写入 retry task status
```

每次回写都会：

```text
retry_attempt_count += 1
updated_at = now()
```

同时按请求内容更新：

```text
last_retry_execution_code
result_summary
error_message
screenshot_asset_code
retry_instruction
```

## 验收标准

- 存在的 retry task 可以接收执行结果回写。
- 回写 succeeded 后 retry task 状态变为 `succeeded`。
- `retry_attempt_count` 自动加 1。
- `last_retry_execution_code`、`result_summary`、`screenshot_asset_code` 被保存。
- 再次 GET retry task 可以看到更新后的状态。
- 不存在的 retry task 返回 404。
- 全量测试、编译检查和 PostgreSQL migration 解析通过。
