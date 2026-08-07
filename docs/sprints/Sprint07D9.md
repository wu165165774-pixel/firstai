# Sprint 07D.9：队列可观测性与运维闭环

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.10`
- 基线版本：`v0.15.0-alpha.9`
- 核心目标：在已有优先级、重试、DLQ、背压、超时和 Worker 控制基础上，补齐批量运维、归档和可观测性能力。

## 2. DLQ 批量重放

新增：

```text
POST /api/v1/workflows/dead-letter/replay
```

支持显式 `run_ids` 批量重放，并可覆盖：

```text
reset_attempts
priority
max_attempts
retry_base_seconds
timeout_seconds
```

批量重放继续遵守：

```text
全局队列上限
每用户活跃任务配额
```

真实验收：

```text
requested_count = 2
replayed_count = 2
skipped_count = 0
dlq_replayed_delta = 2
```

## 3. 队列归档

新增：

```text
POST /api/v1/workflows/queue/archive
GET  /api/v1/workflows/queue/archive
```

新增 SQLite 表：

```text
workflow_job_archive
```

默认归档终态：

```text
completed
cancelled
failed
```

默认不归档：

```text
dead_letter
```

必须显式 `include_dead_letter=true` 才会将 DLQ 队列记录归档。

支持：

```text
dry_run
older_than_seconds
limit
```

归档只移除 `workflow_run_jobs` 中的终态队列记录，不删除：

```text
workflow_runs
workflow_run_events
workflow_chapter_versions
```

真实验收确认：

```text
ARCHIVE DRY RUN: PASS
RUN HISTORY PRESERVED: PASS
DLQ DEFAULT ARCHIVE PROTECTION: PASS
```

验收归档：

```text
archived_count = 7
archived_jobs_total_delta = 7
archived_job_count_delta = 7
```

## 4. 队列可观测性

`GET /api/v1/workflows/queue/metrics` 增加窗口参数：

```text
window_seconds
```

新增指标：

```text
observation_window_seconds
terminal_in_window
completed_in_window
failed_in_window
dead_lettered_in_window
cancelled_in_window
throughput_per_minute
success_throughput_per_minute

queue_latency_samples
queue_latency_seconds_average
queue_latency_seconds_max

execution_duration_samples
execution_duration_seconds_average
execution_duration_seconds_max

oldest_ready_age_seconds

archived_job_count
dlq_replayed_total
archived_jobs_total
```

真实验收：

```text
observation_window_seconds = 3600.0
terminal_in_window = 2
dead_lettered_in_window = 2
throughput_per_minute = 0.03333333333333333
queue_latency_samples = 2
queue_latency_seconds_average = 1.9136655
execution_duration_samples = 2
execution_duration_seconds_average = 0.0953725
```

## 5. Worker 集群健康

新增：

```text
GET /api/v1/workflows/workers/health
```

返回：

```text
health_status
total_workers
running_workers
stale_workers
paused_workers
draining_workers
accepting_workers
total_capacity
active_count
available_slots
utilization
ready_count
```

健康语义：

```text
running_workers == 0
    -> unavailable

running_workers > 0
accepting_workers == 0
    -> degraded

running_workers > 0
accepting_workers > 0
    -> healthy
```

历史 `stale_workers` 保留为观测指标，但不会单独让一个可正常接单的集群降级。

最终真实验证：

```text
health_status = healthy
total_workers = 18
running_workers = 1
stale_workers = 2
accepting_workers = 1
available_slots = 1
```

## 6. 配置

新增默认配置：

```text
NOVELFORGE_WORKFLOW_DLQ_REPLAY_BATCH_MAX=100
NOVELFORGE_WORKFLOW_ARCHIVE_AFTER_SECONDS=604800
NOVELFORGE_WORKFLOW_ARCHIVE_BATCH_SIZE=500
```

其中：

```text
604800 秒 = 7 天
```

## 7. 自动化测试

新增：

```text
backend/tests/test_workflow_operations.py
```

最终增加 11 条 07D.9 测试，包括：

- 单任务 retry 覆盖 timeout
- DLQ 批量重放
- 非 DLQ / 非法项跳过
- 批量重放遵守队列上限
- Archive dry-run
- 真实 Archive
- Run 历史保留
- 默认 DLQ 归档保护
- Queue throughput / latency / duration Metrics
- Worker cluster health
- 历史 stale Worker 不误判健康集群

全量测试：

```text
Ran 124 tests
OK
```

## 8. 真实容器验收

DLQ Run：

```text
3b721ed9-3895-49eb-8ac0-2fc09cecc83d
e5e8f7da-468a-40fe-ae3d-27da5c1eb1e0
```

归档候选 Run：

```text
1fc9efd7-8612-4820-bbfb-2e536bfb92d9
```

验收结果：

```text
CONTROLLED DLQ CREATION: PASS
DLQ BULK REPLAY: PASS
REPLAY EXECUTION: PASS
ARCHIVE DRY RUN: PASS
RUN HISTORY PRESERVED: PASS
DLQ DEFAULT ARCHIVE PROTECTION: PASS
QUEUE OBSERVABILITY METRICS: PASS
WORKER CLUSTER HEALTH: PASS
REAL QUEUE OPERATIONS ACCEPTANCE: PASS
WORKER HEALTH SEMANTICS: PASS
```

## 9. 主要文件

```text
backend/app/api/v1/workflows.py
backend/app/workflows/async_executor.py
backend/app/workflows/async_queue.py
backend/app/workflows/run_schemas.py
backend/tests/test_workflow_operations.py
docker-compose.worker.yml
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D9.md
```

## 10. 验收结论

```text
124/124 full regression passed
DLQ bulk replay passed
Queue archive passed
Run history preservation passed
Default DLQ archive protection passed
Windowed queue metrics passed
Worker cluster health passed
Stale Worker health semantics passed
```

## 11. 后续计划

Sprint 07D.10 候选范围：

- Worker 历史记录清理
- Prometheus exposition endpoint
- 队列告警阈值
- 运维事件审计
- 批量 Worker 控制
- 队列管理 Dashboard API
