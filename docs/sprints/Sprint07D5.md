# Sprint 07D.5：异步任务队列与运行控制

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.6`
- 基线版本：`v0.15.0-alpha.5`
- 核心目标：在持久化 Workflow Run 之上增加异步提交、后台执行、幂等、防重复领取、任务取消、并发控制、Worker 租约、心跳和过期任务回收。

## 2. 异步执行模型

客户端提交：

```text
POST /api/v1/workflows/chapter/runs/async
```

接口立即返回：

```text
HTTP 202
run_id
queue_status
deduplicated
```

后台执行链路：

```text
queued
   ↓
Worker 原子领取
   ↓
running + lease + heartbeat
   ↓
Chapter → Review → Rewrite
   ↓
completed / failed
```

## 3. SQLite 持久队列

新增表：

```text
workflow_run_jobs
```

保存：

- `run_id`
- `idempotency_key`
- `queue_status`
- `cancel_requested`
- `lease_owner`
- `lease_expires_at`
- `heartbeat_at`
- `queued_at`
- `claimed_at`
- `updated_at`

队列与 `workflow_runs` 使用同一个 SQLite 数据库：

```text
/app/data/workflow_runs.db
```

## 4. 新增 API

```text
POST /api/v1/workflows/chapter/runs/async
GET  /api/v1/workflows/runs/{run_id}/control
POST /api/v1/workflows/runs/{run_id}/cancel
```

现有同步与恢复 API 保持兼容：

```text
POST /api/v1/workflows/chapter
POST /api/v1/workflows/chapter/runs
GET  /api/v1/workflows/runs
GET  /api/v1/workflows/runs/{run_id}
POST /api/v1/workflows/runs/{run_id}/resume
```

## 5. 队列状态

```text
queued
running
cancelling
cancelled
completed
failed
```

Run 执行状态扩展为：

```text
queued
running
cancelling
cancelled
succeeded
resumable
failed
```

## 6. 幂等提交

客户端可发送：

```text
Idempotency-Key
```

同一个幂等键重复提交时：

- 不创建新的 Run
- 返回原 `run_id`
- `deduplicated = true`

幂等键最大长度：

```text
128
```

## 7. Worker 并发控制

默认并发数：

```text
NOVELFORGE_WORKFLOW_CONCURRENCY=1
```

当一个任务正在运行时，后续任务保持 `queued`，直到 Worker 有空闲容量。

## 8. 租约和心跳

Worker 原子领取任务后写入：

```text
lease_owner
lease_expires_at
heartbeat_at
```

运行期间定期续租。

配置：

```text
NOVELFORGE_WORKFLOW_LEASE_SECONDS
NOVELFORGE_WORKFLOW_HEARTBEAT_SECONDS
```

## 9. 崩溃恢复

当任务状态为：

```text
running
cancelling
```

且租约已经过期时：

- 普通 `running` 任务重新回到 `queued`
- 已请求取消的任务变为 `cancelled`
- 写入 `lease_recovered` 或 `run_cancelled` 审计事件

Backend 重启后，异步接口或控制接口会重新启动 Worker。

## 10. 任务取消

### queued 任务

立即转换：

```text
queued → cancelled
```

### running 任务

先转换：

```text
running → cancelling
```

随后取消进程内 Task，并最终写入：

```text
cancelled
```

取消同时更新：

- Queue 状态
- Run 执行状态
- 完成时间
- 审计事件

## 11. 审计事件

异步执行新增：

```text
run_queued
run_claimed
cancel_requested
run_cancelled
lease_recovered
```

原工作流事件继续保留：

```text
workflow_step
run_completed
run_stopped
run_failed
```

## 12. 自动化测试

新增 8 条测试：

1. 异步路由和 OpenAPI Schema
2. 并发上限为 1
3. 幂等键长度保护
4. queued 任务取消
5. running 任务取消
6. 过期租约回收
7. 重复提交幂等
8. Worker 执行并持久化

全量回归：

```text
Ran 81 tests
OK
```

## 13. 真实 Qwen 验收

主任务：

```text
run_id: c99a497b-cbb0-4d13-808f-2d82d36121f4
submission_elapsed_seconds: 0.156
queue_status: completed
execution_status: succeeded
successful_stages: [draft, review]
```

幂等重复提交：

```text
duplicate_run_id: c99a497b-cbb0-4d13-808f-2d82d36121f4
idempotency_match: true
```

取消任务：

```text
run_id: a0c8be7b-141e-4399-b071-c7fafbdad612
queue_status: cancelled
execution_status: cancelled
events: [run_queued, run_cancelled]
```

Backend 重启后，主任务和取消任务都可以通过 Control API 查询。

## 14. 主要文件

```text
backend/app/api/v1/workflows.py
backend/app/workflows/async_queue.py
backend/app/workflows/async_executor.py
backend/app/workflows/run_schemas.py
backend/app/workflows/storage.py
backend/tests/test_workflow_async.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D5.md
```

## 15. 验收结果

```text
8/8 async workflow tests passed
9/9 workflow persistence tests passed
81/81 full regression tests passed
HTTP 202 immediate submission passed
Idempotency passed
Background Qwen execution passed
Queued cancellation passed
Restart persistence passed
```

## 16. 后续计划

Sprint 07D.6 候选范围：

- 独立 Worker 容器
- Backend 与 Worker 进程解耦
- 多 Worker 横向扩展
- 优先级队列
- 最大排队长度
- 每用户并发和配额
- Dead Letter Queue
- 自动重试策略
