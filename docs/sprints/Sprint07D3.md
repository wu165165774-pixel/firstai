# Sprint 07D.3：结构化质量评分与问题追踪

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.4`
- 基线版本：`v0.15.0-alpha.3`
- 核心目标：为多轮章节质量闭环增加结构化评分、稳定问题标识、跨轮问题状态和修订差异摘要。

## 2. 工作流能力

```text
Chapter
   ↓
Review + Quality Scores + Issue IDs
   ↓
Quality Gate
   ↓
Rewrite unresolved issues only
   ↓
Re-Review + Issue Transitions
```

工作流不仅判断是否通过，还会解释为什么未通过、哪些问题仍未解决，以及每轮修订实际改变了什么。

## 3. 六维质量评分

Review 支持以下评分维度：

- `continuity`
- `character_consistency`
- `world_consistency`
- `plot_logic`
- `prose_quality`
- `pacing`
- `overall`

所有评分统一规范为 `0～100`。

当模型返回 `0～10` 评分时自动放大为 `0～100`。当模型未返回评分时，系统会根据 Review 结论和问题严重程度安全推断评分，并标记：

- `scores_inferred`
- `scores_normalized`

## 4. 质量门禁参数

新增请求参数：

- `minimum_overall_score`，默认 `80`
- `minimum_dimension_score`，默认 `70`
- `require_all_issues_resolved`，默认 `true`

质量门禁会综合判断：

- Review 是否批准
- 是否存在触发改写的严重等级
- 是否存在未解决问题
- 总分是否低于阈值
- 任一维度是否低于阈值

具体原因写入：

```text
quality_gate_reasons
```

## 5. 稳定问题 ID

每个 Review 问题会被分配稳定 ID：

```text
ISSUE-001
ISSUE-002
```

跨轮次通过规范化类别、问题描述和建议进行匹配，从而识别同一问题。

## 6. 问题状态追踪

问题状态：

- `open`
- `resolved`

状态迁移：

- `new`
- `persisting`
- `resolved`
- `reopened`

结果包含：

- `issue_tracker`
- `issue_transitions`
- `unresolved_issue_ids`

示例：

```text
ISSUE-001 round 1 new
ISSUE-001 round 2 persisting
ISSUE-001 round 3 resolved
```

## 7. 只传递未解决问题

下一轮 Rewrite 只接收当前仍未解决的问题，避免重复修改已经修复的内容。

```text
Review round 1:
ISSUE-001
ISSUE-002

Review round 2:
ISSUE-002

Rewrite round 2:
仅处理 ISSUE-002
```

## 8. 修订差异摘要

每轮 Rewrite 后记录：

- `before_length`
- `after_length`
- `added_characters`
- `removed_characters`
- `replaced_characters`
- `similarity_ratio`
- `changed`
- `summary`

差异记录保存在：

```text
revision_diffs
```

## 9. 新增响应字段

- `quality_scores`
- `quality_score_history`
- `issue_tracker`
- `issue_transitions`
- `unresolved_issue_ids`
- `quality_gate_reasons`
- `revision_diffs`

## 10. 自动化测试

章节工作流测试增加到 23 条，覆盖：

1. 审查通过时跳过改写
2. 关闭自动改写
3. 维度评分失败原因
4. Review 空结果重试
5. Review JSON 解析失败
6. 问题 ID 分配与解决
7. 代码围栏 JSON
8. 无问题但低分触发改写
9. 最大修订轮次
10. 缺失评分推断
11. 持续问题复用 ID
12. 历史正文循环
13. 相同正文停滞
14. Review 重试耗尽
15. 修订差异摘要
16. 改写后复审
17. Rewrite 必须真实修改
18. 第二次 Review 解析失败
19. 第二轮 Rewrite 只接收未解决问题
20. 十分制评分归一化
21. 两轮修订后通过
22. 零修订轮次
23. OpenAPI 质量追踪字段

全量回归：

```text
Ran 64 tests
OK
```

## 11. 真实 Qwen 验收

模型：

```text
qwen3:8b
```

真实链路：

```text
draft → review → rewrite → review
```

结果：

```text
workflow_status: max_revisions_reached
quality_gate_passed: false
revision_rounds: 1
review_history_count: 2
quality_score_history_count: 2
issue_tracker_count: 1
issue_transition_count: 2
transition_rounds: [1, 2]
```

问题追踪：

```text
ISSUE-001 round 1 new
ISSUE-001 round 2 persisting
```

差异摘要：

```text
before_length: 506
after_length: 499
removed_characters: 7
similarity_ratio: 0.9930348258706467
changed: true
```

门禁未通过原因：

```text
severity:ISSUE-001:minor
unresolved_issues
dimension_score_below_threshold:prose_quality
dimension_score_below_threshold:pacing
```

## 12. 主要文件

```text
backend/app/workflows/schemas.py
backend/app/workflows/quality.py
backend/app/workflows/chapter_workflow.py
backend/tests/test_chapter_workflow.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint07D3.md
```

## 13. 后续计划

Sprint 07D.4 候选范围：

- 工作流运行记录持久化
- 可恢复的 Workflow Run
- 章节版本历史
- Review 和 Rewrite 审计记录
- 运行查询 API
- 失败步骤重试和断点续跑
