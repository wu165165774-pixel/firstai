# Sprint 07D.7：任务优先级、自动重试与 Dead Letter Queue

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.8`
- 基线版本：`v0.15.0-alpha.7`
- 核心目标：为独立 Workflow Worker 增加持久化优先级调度、失败自动重试、指数退避、Dead Letter Queue、手动重新入队和队列运行指标。

## 2. 优先级调度

异步提交接口支持请求头：

```text
X-Workflow-Priority
```

范围：

```text
-100 ～ 100
```

默认值：

```text
0
```

调度顺序：

```text
priority DESC
available_at ASC
queued_at ASC
```

## 3. 自动重试

新增请求头：

```text
X-Workflow-Max-Attempts
X-Workflow-Retry-Base-Seconds
```

默认策略：

```text
max_attempts = 3
retry_base_seconds = 2.0
```

`max_attempts` 包含第一次执行。失败后使用指数退避，最大退避时间由：

```text
NOVELFORGE_WORKFLOW_MAX_RETRY_DELAY_SECONDS
```

限制，默认 300 秒。

新增状态：

```text
retry_wait
retrying
```

新增事件：

```text
retry_scheduled
```

用户取消不会进入自动重试。

## 4. Dead Letter Queue

达到最大尝试次数后：

```text
running
  ↓
dead_letter
```

Run 执行状态同步变为 `dead_letter`。

持久化字段：

```text
priority
attempt_count
max_attempts
retry_base_seconds
available_at
last_error
dead_lettered_at
```

事件：

```text
run_dead_lettered
```

## 5. 手动重新入队

新增 API：

```text
POST /api/v1/workflows/runs/{run_id}/retry
```

允许重新入队：

```text
failed
dead_letter
```

事件：

```text
run_requeued
```

## 6. 查询和指标 API

新增：

```text
GET /api/v1/workflows/dead-letter
GET /api/v1/workflows/queue/metrics
```

Metrics：

```text
total_jobs
status_counts
ready_count
delayed_retry_count
dead_letter_count
priority_min
priority_max
priority_average
worker_status_counts
```

优先级统计覆盖全部持久化任务，即使所有任务都进入终态，统计值仍有效。

## 7. SQLite 迁移

旧版 `workflow_run_jobs` 表原地增加策略字段。迁移顺序：

```text
确认旧表
  ↓
PRAGMA table_info
  ↓
ALTER TABLE 补齐字段
  ↓
初始化 available_at
  ↓
创建 idx_workflow_jobs_schedule
```

避免旧数据库还没有 `available_at` 时提前创建索引。

## 8. 自动化测试

新增 13 条队列策略测试，包括优先级、FIFO、指数退避、DLQ、手动重入队、取消、Metrics、参数边界、执行器重试、旧数据库迁移和终态优先级统计。

全量测试：

```text
Ran 103 tests
OK
```

## 9. 真实容器验收

高优先级 Run：

```text
06e7dd89-0c13-4a6b-8653-2a66d596b29b
```

低优先级 Run：

```text
48099d1c-84bd-47b1-8532-1b869c06d518
```

领取时间：

```text
high: 2026-08-06T10:05:23.188250+00:00
low:  2026-08-06T10:05:23.887287+00:00
```

自动重试与手动重入队 Run：

```text
9cb84374-9e8f-4614-a86a-80745201fe3a
```

最终事件计数：

```text
run_claimed = 4
retry_scheduled = 2
run_dead_lettered = 2
run_requeued = 1
```

Metrics：

```text
priority_min = -50
priority_max = 95
priority_average = 22.5
dead_letter_count = 3
```

## 10. 验收结果

```text
103/103 full regression passed
Priority scheduling passed
Automatic retry passed
Dead Letter Queue passed
Manual requeue passed
Queue Metrics passed
Legacy SQLite migration passed
Standalone Worker deployment passed
```

## 11. 后续计划

Sprint 07D.8 候选范围：

- 每用户并发配额
- 全局最大排队长度
- 队列背压与 429 响应
- 任务超时
- Worker 管理 API
- DLQ 批量重放
- 队列清理和归档
