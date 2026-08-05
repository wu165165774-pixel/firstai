# Sprint 07D.1：章节生产工作流

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.2`
- 基线版本：`v0.15.0-alpha.1`
- 核心目标：将 ChapterAgent、ReviewAgent 和 RewriteAgent 串联成可调用的章节生产工作流。

## 2. 功能范围

新增接口：

```text
POST /api/v1/workflows/chapter
```

执行链路：

```text
ChapterAgent 生成章节初稿
        ↓
ReviewAgent 输出结构化审查报告
        ↓
质量门禁判断
        ├── 无需修订：直接返回初稿
        └── 需要修订：RewriteAgent 生成修订稿
```

## 3. 请求能力

工作流请求支持：

- 用户与小说标识
- 模型供应商和模型名称
- 长期记忆开关
- 自动改写开关
- 三个 Agent 独立的 `reasoning_effort`
- 三个 Agent 独立的温度和最大 Token
- 自定义触发改写的严重等级
- 工作流元数据

默认改写门禁：

```text
critical
major
```

## 4. 结构化审查

ReviewAgent 被要求返回一个 JSON 对象，包含：

- `approved`
- `summary`
- `issues`

每个问题包含：

- `severity`
- `category`
- `issue`
- `evidence`
- `impact`
- `recommendation`

工作流可以从普通 JSON 或 Markdown 代码围栏中的 JSON 提取并验证审查报告。解析失败时不会误改写正文，而是返回 `review_parse_failed` 和原始初稿。

## 5. 工作流状态

支持以下状态：

- `completed`
- `draft_failed`
- `review_failed`
- `review_parse_failed`
- `rewrite_failed`

失败时保留已经成功完成的步骤、可用正文、Token 使用量和错误阶段信息。

## 6. 返回结果

响应包含：

- `draft`
- `review_report`
- `review_raw`
- `final_content`
- `revision_applied`
- `quality_gate_passed`
- `workflow_steps`
- 聚合 Token 与延迟
- 工作流元数据

`quality_gate_passed` 的语义是“当前返回内容已经通过 Review 门禁”。Sprint 07D.1 在 Rewrite 后不执行第二次 Review，因此改写分支返回 `quality_gate_passed=false`，避免把未经复审的修订稿错误标记为已通过。

## 7. 自动化测试

新增 `tests/test_chapter_workflow.py`，覆盖：

1. Review 通过时跳过 Rewrite
2. Major 问题触发 Rewrite
3. 可以关闭自动改写
4. 非法 Review JSON 安全降级
5. Markdown 代码围栏 JSON 解析
6. OpenAPI 中注册 Workflow 路由

全量测试结果：

```text
Ran 47 tests
OK
```

## 8. 真实模型验收

### 默认质量门禁

真实调用 `qwen3:8b`：

```text
workflow_status: completed
revision_applied: False
quality_gate_passed: True
workflow_steps: draft, review
total_tokens: 3522
```

ReviewAgent 返回 2 个未命中默认 `critical/major` 门禁的问题，因此未触发改写。

### 强制 Rewrite 分支

将触发等级扩展为全部严重等级后：

```text
workflow_status: completed
revision_applied: True
quality_gate_passed: False
review_approved: True
review_severities: moderate
workflow_steps: draft, review, rewrite
total_tokens: 4595
```

最终文本与初稿不同，真实三阶段链路通过。

## 9. 主要文件

```text
backend/app/workflows/__init__.py
backend/app/workflows/schemas.py
backend/app/workflows/chapter_workflow.py
backend/app/api/v1/workflows.py
backend/app/main.py
backend/tests/test_chapter_workflow.py
```

## 10. 后续计划

Sprint 07D.2：

- Rewrite 后自动再次 Review
- 最大修订轮次
- 质量分数和停止条件
- 防止循环改写
- 最终稿质量门禁认证
