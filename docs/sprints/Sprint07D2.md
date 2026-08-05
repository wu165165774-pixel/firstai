# Sprint 07D.2：多轮章节质量闭环

## 版本

- 发布版本：`v0.15.0-alpha.3`
- 基线：`v0.15.0-alpha.2`

## 目标

将章节工作流升级为：

```text
Chapter → Review → Rewrite → Re-Review
```

仅当最新正文经过 Review 且无需继续修订时，`quality_gate_passed=true`。

## 新增能力

- `max_revision_rounds`：默认 2，范围 0～5
- Rewrite 后自动复审
- `review_history`
- `review_raw_history`
- `revision_rounds`
- `WorkflowStep.round_index`
- `WorkflowStep.attempt_index`
- `max_revisions_reached`
- `stagnation_detected`
- 正文历史指纹和循环保护
- Rewrite 必须落实真实修改
- Review 空结果自动降级重试
- 重试时默认 `reasoning_effort=none`
- 重试输出预算至少 1200 Token

## Review 重试

```text
attempt 1:
  reasoning_effort = 请求值
  max_tokens = 请求值

空结果或失败后：

attempt 2:
  reasoning_effort = review_retry_reasoning_effort
  max_tokens = max(review_max_tokens, 1200)
```

所有尝试都会记录到 `workflow_steps`，Token 和延迟不会丢失。

## 停止条件

工作流在以下情况下结束：

- 质量门禁通过
- 达到最大修订轮次
- Rewrite 返回当前或历史正文
- Review 重试耗尽
- Review JSON 解析失败
- Draft、Review 或 Rewrite 执行失败
- 用户关闭自动改写

## 测试

定向工作流测试：

```text
Ran 15 tests
OK
```

全量回归：

```text
Ran 56 tests
OK
```

## 真实 Qwen 验收

模型：`qwen3:8b`

实际有效链路：

```text
draft   round=0 attempt=1
review  round=1 attempt=1
rewrite round=1 attempt=1
review  round=2 attempt=1
```

结果：

```text
workflow_status: max_revisions_reached
quality_gate_passed: false
revision_applied: true
revision_rounds: 1
review_history_count: 2
draft_equals_final: false
```

第二次 Review 仍要求修订，但验收请求只允许 1 轮 Rewrite，因此工作流按设计返回最新修订稿并保持 `quality_gate_passed=false`。

## 主要文件

```text
backend/app/workflows/schemas.py
backend/app/workflows/chapter_workflow.py
backend/tests/test_chapter_workflow.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D2.md
```

## 后续候选

- Review 分项评分
- 问题 ID 和修复状态
- 只传递未解决问题
- 修订差异摘要
- 动态停止阈值
- 工作流运行持久化
