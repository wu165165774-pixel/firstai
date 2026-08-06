# Sprint 07D.4：工作流运行持久化与断点恢复

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.5`
- 基线版本：`v0.15.0-alpha.4`
- 核心目标：为章节生产工作流增加运行持久化、审计记录、章节版本历史、运行查询与精确 Checkpoint 恢复。

## 2. 持久化运行模型

每次持久化执行都会生成唯一：

```text
run_id
```

恢复运行同时维护：

```text
root_run_id
parent_run_id
```

从而形成可查询的运行链：

```text
Root Run
   ↓
Resume Run
   ↓
Next Resume Run
```

## 3. SQLite 数据结构

新增三个持久化实体：

### workflow_runs

保存：

- 运行 ID 与父子关系
- 用户与小说 ID
- 工作流执行状态
- 工作流业务状态
- 请求与完整结果
- 最新有效正文
- 是否可以恢复
- 创建、更新和完成时间
- 异常信息

### workflow_run_events

保存：

- Run 启动事件
- 每个 Workflow Step
- Stage、Round 和 Attempt
- Step 的完整 Payload
- Run 完成、停止或失败事件

### workflow_chapter_versions

保存：

- Draft 版本
- Rewrite 版本
- Checkpoint 版本
- 版本序号
- 内容哈希
- 来源阶段和轮次

默认数据库：

```text
/app/data/workflow_runs.db
```

宿主机持久化位置：

```text
D:\AI\novel-ai\data\workflow_runs.db
```

## 4. 新增 API

```text
POST /api/v1/workflows/chapter/runs
GET  /api/v1/workflows/runs
GET  /api/v1/workflows/runs/{run_id}
POST /api/v1/workflows/runs/{run_id}/resume
```

原有非持久化 API 保留：

```text
POST /api/v1/workflows/chapter
```

## 5. 运行状态

外层执行状态：

- `running`
- `succeeded`
- `resumable`
- `failed`

只有满足以下条件的运行才可以恢复：

- 质量门禁尚未通过
- 已存在非空 `latest_content`
- 运行被标记为 `resumable`

已成功通过质量门禁的运行禁止重复恢复。

## 6. 精确 Checkpoint 恢复

恢复时不会重新运行 ChapterAgent。

系统通过 `CheckpointAgentManager` 将父运行的 `latest_content` 精确注入为新的 Draft Step：

```text
stage: draft
agent: checkpoint
provider: workflow_checkpoint
model: stored-content
```

然后继续执行：

```text
Review → Rewrite → Re-Review
```

Checkpoint 内容必须与父运行持久化正文逐字一致。

## 7. 恢复参数保护

Resume 只允许覆盖工作流运行参数，例如：

- Provider 和 Model
- 修订轮次
- Review 重试
- Reasoning Effort
- Temperature
- Token 上限
- 质量门禁阈值
- Metadata

禁止通过 Resume 修改：

- `user_id`
- `novel_id`
- 原始指令等身份或归属字段

未知覆盖字段返回冲突错误。

## 8. Agent Manager 兼容修复

项目现有运行时使用：

```text
app.agents.bootstrap.agent_manager
```

07D.4 初始实现曾错误读取：

```text
request.app.state.agent_manager
```

导致 Run API 返回：

```text
503 Agent manager is not available
```

最终实现恢复使用现有全局 Agent Manager 单例，并增加测试防止再次回归。

## 9. 自动化测试

新增 9 条定向测试：

1. Run API 和 OpenAPI 注册
2. 用户与小说过滤查询
3. 未通过运行标记为 resumable
4. 精确 Checkpoint 与父子关系
5. Event 和章节版本持久化
6. Storage 重开后仍可读取
7. 成功运行禁止恢复
8. 未知 Resume 参数拒绝
9. 工作流失败状态持久化

全量回归：

```text
Ran 73 tests
OK
```

## 10. 真实 Qwen 验收

父运行：

```text
run_id: 90ea0b26-b364-448a-824c-617ed385062e
execution_status: resumable
workflow_status: max_revisions_reached
event_count: 4
version_count: 1
latest_content_length: 1003
```

Backend 重启后仍能查询父运行。

恢复运行：

```text
run_id: 509da7bf-bb68-46dc-889b-7cd9950a33d6
parent_run_id: 90ea0b26-b364-448a-824c-617ed385062e
root_run_id: 90ea0b26-b364-448a-824c-617ed385062e
checkpoint_exact_match: true
checkpoint_agent: checkpoint
event_count: 6
version_count: 2
lineage_run_count: 2
```

恢复运行仍未通过严格质量门禁，因此正确保持：

```text
execution_status: resumable
workflow_status: max_revisions_reached
quality_gate_passed: false
```

这不影响恢复能力验收；关键目标是精确加载 Checkpoint、继续执行工作流并保存新的父子运行。

## 11. 主要文件

```text
backend/app/api/v1/workflows.py
backend/app/workflows/run_schemas.py
backend/app/workflows/run_service.py
backend/app/workflows/storage.py
backend/tests/test_workflow_runs.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D4.md
```

## 12. 验收结果

```text
9/9 targeted tests passed
73/73 full regression tests passed
Runtime Agent Manager check passed
Parent run persistence passed
Backend restart persistence passed
Exact checkpoint resume passed
Run lineage query passed
```

## 13. 后续计划

Sprint 07D.5 候选范围：

- 异步工作流执行
- Run 排队和后台 Worker
- 运行取消
- 运行状态轮询
- 并发控制
- 幂等请求键
- 超时和租约
- 崩溃后自动恢复 running 状态
