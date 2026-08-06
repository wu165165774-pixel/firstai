# Sprint 07D.6：独立 Worker 容器与故障接管

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.7`
- 基线版本：`v0.15.0-alpha.6`
- 核心目标：把 Workflow 执行从 Backend API 进程中解耦到独立 Worker 容器，并实现多进程领取、Worker 注册、跨进程取消、优雅停机、租约过期恢复和真实容器故障接管。

## 2. 容器架构

```text
novelforge-backend
  execution_mode = external
  负责：提交、查询、取消、OpenAPI

novelforge-worker
  execution_mode = worker
  负责：领取、心跳、执行、恢复

novelforge-ollama
  负责：Qwen 推理
```

部署使用：

```text
docker-compose.yml
docker-compose.worker.yml
```

Worker 覆盖配置不会直接改写原有 Compose 文件。

## 3. 执行模式

```text
embedded
external
worker
```

### embedded

保持 Sprint 07D.5 的兼容行为，由 API 进程内 Worker 执行任务。

### external

API 只写入 SQLite 队列，不启动进程内 Worker。

### worker

独立进程启动 Worker 循环，原子领取任务并执行工作流。

独立入口：

```text
python -m app.workers.workflow_worker
```

## 4. Worker 注册表

新增 SQLite 表：

```text
workflow_workers
```

字段：

- `worker_id`
- `worker_status`
- `capacity`
- `active_count`
- `started_at`
- `heartbeat_at`
- `stopped_at`
- `metadata_json`

Worker 状态：

```text
running
stopping
stopped
stale
```

查询 API：

```text
GET /api/v1/workflows/workers
```

## 5. 多 Worker 原子领取

所有 Worker 使用同一个 SQLite 队列。

任务领取在 `BEGIN IMMEDIATE` 事务中完成：

```text
queued
  ↓
单个 Worker 原子更新
  ↓
running + lease_owner
```

两个 Worker 不会领取同一个 queued 任务。

## 6. 跨进程取消

API 进程只写入：

```text
cancel_requested = true
queue_status = cancelling
```

独立 Worker 的心跳协程检测取消请求，并取消对应执行 Task，最终持久化：

```text
cancelled
```

## 7. 优雅停机

Worker 收到 SIGINT 或 SIGTERM 后：

1. 标记 Worker 为 `stopping`
2. 取消活动 Task
3. 未收到用户取消的 Run 通过 `release_claim()` 回到 `queued`
4. 写入 `worker_released`
5. Worker 标记为 `stopped`

其他 Worker 可以重新领取被释放任务。

## 8. 崩溃与租约恢复

非优雅退出时，旧 Worker 无法续租。

新 Worker 启动后：

```text
发现 lease_expires_at 已过期
  ↓
写入 lease_recovered
  ↓
running → queued
  ↓
新 Worker 重新领取
  ↓
继续执行同一个 run_id
```

## 9. Docker 配置

Backend：

```text
NOVELFORGE_WORKFLOW_EXECUTION_MODE=external
NOVELFORGE_WORKFLOW_DB_PATH=/app/data/workflow_runs.db
```

Worker：

```text
NOVELFORGE_WORKFLOW_EXECUTION_MODE=worker
NOVELFORGE_WORKFLOW_CONCURRENCY=1
NOVELFORGE_WORKFLOW_LEASE_SECONDS=12
NOVELFORGE_WORKFLOW_HEARTBEAT_SECONDS=3
```

Worker 与 Backend 共享：

```text
./backend:/app
./data:/app/data
```

## 10. 自动化测试

新增 9 条测试：

1. external 模式只入队
2. 独立 Worker 执行外部任务
3. 跨进程取消
4. 优雅停机重新排队
5. 两个 Worker 领取不同任务
6. Worker 注册生命周期
7. 非法执行模式拒绝
8. Worker API 注册
9. Worker 入口可导入

全量回归：

```text
Ran 90 tests
OK
```

## 11. 容器集成验收

验证：

```text
backend_running: true
worker_running: true
backend_mode: external
worker_mode: worker
worker_status: running
worker_capacity: 1
worker_execution_mode: worker
```

## 12. 真实故障接管验收

Run：

```text
e9b2328c-5460-4cae-96c0-d6b34bc30b09
```

旧 Worker：

```text
worker-e85dbe69-cc77-4475-9505-48ef762ad5e1
```

新 Worker：

```text
worker-2aedb90c-ab1b-480e-b441-48d9380de29f
```

真实操作：

1. 提交长篇 Qwen 任务
2. 等待旧 Worker 领取
3. 暂停并强制删除旧 Worker 容器
4. 等待租约过期
5. 创建新 Worker 容器
6. 新 Worker 恢复并完成同一 Run

最终事件：

```text
run_queued
run_claimed
lease_recovered
run_claimed
workflow_step
workflow_step
run_completed
```

精确计数：

```text
claim_count: 2
recovery_count: 1
completed_count: 1
version_count: 1
successful_stages: [draft, review]
```

Worker 注册状态：

```text
old_worker_registry_status: stale
new_worker_registry_status: running
```

这证明：

- 同一个 Run 被旧、新 Worker 分别领取
- 租约只恢复一次
- Run 只完成一次
- 只生成一份最终章节版本
- 没有重复完成或重复版本

## 13. 主要文件

```text
backend/app/api/v1/workflows.py
backend/app/workflows/async_executor.py
backend/app/workflows/async_queue.py
backend/app/workflows/run_schemas.py
backend/app/workers/workflow_worker.py
backend/tests/test_workflow_worker.py
docker-compose.worker.yml
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D6.md
```

## 14. 验收结果

```text
9/9 standalone Worker tests passed
8/8 async queue regression passed
9/9 persistence regression passed
90/90 full regression passed
Compose configuration passed
External Backend mode passed
Standalone Worker registration passed
Real Worker crash failover passed
Exactly-once final persistence checks passed
```

## 15. 后续计划

Sprint 07D.7 候选范围：

- 任务优先级
- 每用户并发限制
- 最大排队长度
- 自动重试与指数退避
- Dead Letter Queue
- Worker 管理 API
- 任务重试和重新入队 API
- 队列运行指标与运维面板
