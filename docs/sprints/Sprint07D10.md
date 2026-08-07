# Sprint 07D.10：Workflow Infrastructure 收尾与运维面板基础

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.11`
- 基线版本：`v0.15.0-alpha.10`
- 核心目标：完成 07D Workflow Infrastructure 收尾，补齐 Worker 批量控制、历史清理、运维审计、Dashboard 聚合与 Prometheus 指标输出。

## 2. 批量 Worker 控制

新增：

```text
POST /api/v1/workflows/workers/control/batch
```

支持：

```text
pause
resume
drain
```

特性：

- 显式 Worker ID 列表
- 单批上限保护
- 单个 Worker 失败不会中断整批
- 不存在 Worker 进入 skipped
- 每个子操作以及批量操作均写入审计日志

真实验收：

```text
pause_requested_count = 2
pause_succeeded_count = 1
pause_skipped_count = 1
BATCH WORKER PAUSE: PASS

BATCH WORKER RESUME: PASS
```

## 3. Worker 历史清理

新增：

```text
POST /api/v1/workflows/workers/history/cleanup
```

支持：

```text
older_than_seconds
stale_after_seconds
include_stale_running
limit
dry_run
```

安全规则：

- 当前正常 running Worker 不会因为 `older_than_seconds=0` 被删除
- 默认只清理已停止历史记录
- stale running Worker 必须显式允许
- dry-run 可预览候选项
- 清理过程写入运维审计

真实验收创建专用 stopped Worker：

```text
acceptance-stopped-8ed7cf7e0bd9417c93a124cdbbcdefb6
```

结果：

```text
cleanup_preview_candidates = 18
cleanup_deleted_count = 18
WORKER CLEANUP DRY RUN: PASS
WORKER HISTORY CLEANUP: PASS
```

当前正常 Worker 保留。

## 4. 运维审计

新增 SQLite 表：

```text
workflow_operations_audit
```

新增查询：

```text
GET /api/v1/workflows/operations/audit
```

审计覆盖：

```text
worker_control
worker_control_batch
worker_history_cleanup
dead_letter_replay
queue_archive
```

真实验收：

```text
batch_audit_count = 2
cleanup_audit_count = 2
worker_control_audit_count = 3
final_audit_metric = 7.0
OPERATIONS AUDIT: PASS
```

## 5. Dashboard 聚合 API

新增：

```text
GET /api/v1/workflows/operations/dashboard
```

聚合：

```text
queue metrics
worker health
alerts
thresholds
recent audit
```

默认阈值：

```text
ready_jobs = 100
oldest_ready_seconds = 60.0
dead_letters = 10
worker_utilization = 0.9
```

真实验收：

```text
paused_alert_status = critical
paused_alert_codes =
    dead_letter_backlog
    worker_not_accepting

恢复 Worker 后：
worker health = healthy
accepting_workers = 1
worker_not_accepting 告警消失
```

最终 Dashboard 仍为 `warning` 是因为历史 DLQ backlog 已达到告警阈值，不代表 Worker 不健康。

## 6. Prometheus 输出

新增：

```text
GET /api/v1/workflows/metrics/prometheus
```

Content-Type：

```text
text/plain; version=0.0.4; charset=utf-8
```

主要指标：

```text
novelforge_workflow_queue_jobs{status="..."}
novelforge_workflow_queue_ready_jobs
novelforge_workflow_worker_running
novelforge_workflow_worker_stale
novelforge_workflow_worker_accepting
novelforge_workflow_worker_utilization
novelforge_workflow_queue_throughput_per_minute
novelforge_workflow_queue_backpressure_active
novelforge_workflow_dlq_replayed_total
novelforge_workflow_archived_jobs_total
novelforge_workflow_operations_audit_total
novelforge_workflow_operational_alerts{severity="..."}
```

真实验收：

```text
PROMETHEUS EXPOSITION: PASS
critical_alert_metric = 1.0
final_audit_metric = 7.0
worker_running_metric = 1.0
worker_accepting_metric = 1.0
PROMETHEUS LIVE METRICS: PASS
```

## 7. 自动化测试

新增：

```text
backend/tests/test_workflow_operations_dashboard.py
```

新增 12 条测试。

全量：

```text
Ran 136 tests
OK
```

## 8. 真实容器验收

最终：

```text
PROMETHEUS EXPOSITION: PASS
BATCH WORKER PAUSE: PASS
BATCH WORKER RESUME: PASS
WORKER CLEANUP DRY RUN: PASS
WORKER HISTORY CLEANUP: PASS
OPERATIONS AUDIT: PASS
DASHBOARD AGGREGATION: PASS
PROMETHEUS LIVE METRICS: PASS
REAL OPERATIONS DASHBOARD ACCEPTANCE: PASS
GIT DIFF CHECK: PASS
```

验收结果：

```text
data/sprint07d10_acceptance.json
```

## 9. 主要文件

```text
backend/app/api/v1/workflows.py
backend/app/workflows/async_queue.py
backend/app/workflows/run_schemas.py
backend/tests/test_workflow_operations_dashboard.py
docker-compose.worker.yml
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D10.md
```

## 10. 07D 阶段完成状态

07D 系列已经形成完整的生产级异步 Workflow Infrastructure：

```text
07D.5  Async Workflow Queue
07D.6  Standalone Worker
07D.7  Priority / Retry / DLQ
07D.8  Backpressure / Timeout / Worker Control
07D.9  Replay / Archive / Observability / Cluster Health
07D.10 Batch Ops / Audit / Dashboard / Prometheus
```

下一阶段开发重心转向 Planner / Agent 编排与长篇小说生产流程。
