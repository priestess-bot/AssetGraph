# 2026-07-07 Browser use 执行结果回写 API

## 背景

上一轮已经把麦兔替换方案转换为 Browser use 可理解的操作步骤：

```text
AssetGraph -> browser-use-operations -> Browser use -> 麦兔软件
```

但如果 Browser use 只执行、不回写，AssetGraph 无法知道：

- 是否真的完成替换；
- 哪个槽位成功、哪个槽位失败；
- 麦兔页面是否保存成功；
- 是否出现登录过期、找不到图层、素材上传失败等问题；
- 是否有截图素材可以用于复盘。

因此本轮增加 Browser use 执行结果回写 API，让自动化链路可追踪、可复盘。

## 分工

```text
AssetGraph：生成替换方案、生成 Browser use 操作计划、接收执行结果、沉淀状态
Browser use：打开麦兔软件，执行页面操作，回写执行结果
麦兔软件：直播间搭建与素材替换的实际操作环境
```

## 新增编号

执行记录使用独立编号：

```text
MT-EXEC-{YYYYMMDD}-{SEQ}
```

示例：

```text
MT-EXEC-20260707-000001
```

## 新增数据库表

新增 migration：

```text
backend/migrations/005_maitu_execution_results.sql
```

包含：

- `maitu_replacement_plan_executions`
- `maitu_replacement_plan_operation_results`

### maitu_replacement_plan_executions

记录一次 Browser use 执行的总体状态：

- `execution_code`
- `plan_code`
- `executor`
- `execution_status`
- `started_at`
- `finished_at`
- `error_message`
- `screenshot_asset_code`
- `result_summary`

### maitu_replacement_plan_operation_results

记录每个槽位/操作的执行结果：

- `execution_code`
- `plan_code`
- `slot_code`
- `operation_type`
- `asset_code`
- `status`
- `error_message`
- `screenshot_asset_code`
- `details`
- `sort_order`

## 新增 API

### 创建执行结果

```http
POST /api/maitu/replacement-plans/{plan_code}/execution-results
```

请求示例：

```json
{
  "executor": "browser_use",
  "execution_status": "succeeded",
  "started_at": "2026-07-07T09:00:00Z",
  "finished_at": "2026-07-07T09:02:00Z",
  "screenshot_asset_code": "AG-IMG-20260707-000099",
  "result_summary": "Browser use 已在麦兔中完成商品主图替换并保存项目。",
  "operation_results": [
    {
      "slot_code": "MT-SLOT-20260707-000001",
      "operation_type": "replace_layer_asset",
      "asset_code": "AG-IMG-20260707-000001",
      "status": "succeeded",
      "screenshot_asset_code": "AG-IMG-20260707-000099",
      "details": {
        "layer_name": "layer_8",
        "saved": true
      }
    }
  ]
}
```

返回示例：

```json
{
  "id": "uuid",
  "execution_code": "MT-EXEC-20260707-000001",
  "plan_code": "MT-PLAN-20260707-000001",
  "executor": "browser_use",
  "execution_status": "succeeded",
  "result_summary": "Browser use 已在麦兔中完成商品主图替换并保存项目。",
  "operation_results": [
    {
      "slot_code": "MT-SLOT-20260707-000001",
      "operation_type": "replace_layer_asset",
      "asset_code": "AG-IMG-20260707-000001",
      "status": "succeeded",
      "details": {
        "layer_name": "layer_8",
        "saved": true
      }
    }
  ]
}
```

### 列出执行结果

```http
GET /api/maitu/replacement-plans/{plan_code}/execution-results
```

支持过滤：

```http
?executor=browser_use&execution_status=succeeded
```

### 获取单次执行结果

```http
GET /api/maitu/replacement-plans/{plan_code}/execution-results/{execution_code}
```

## 状态同步

当 Browser use 回写执行结果后，AssetGraph 会同步更新替换方案状态：

| execution_status | plan status |
| --- | --- |
| `succeeded` | `executed` |
| `partial_failed` | `partial_failed` |
| `failed` | `execution_failed` |
| 其他 | `execution_reported` |

## 验收标准

- 可以为已有 replacement plan 创建 Browser use 执行结果。
- 返回自动生成的 `MT-EXEC-*` 编号。
- 可以记录每个槽位的执行状态、错误信息、截图素材和 details。
- 可以按 plan 查询执行历史。
- 可以按 execution_code 查询单次执行详情。
- 不存在的 plan 返回 404。
- 测试、编译和 migration SQL 解析全部通过。
