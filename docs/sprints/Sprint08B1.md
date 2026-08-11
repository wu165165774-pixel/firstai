# Sprint 08B.1 - Chapter Plan -> Chapter Workflow Bridge

## 状态

```text
已完成
发布版本：v0.15.0-alpha.20
基线版本：v0.15.0-alpha.19
```

## 目标

完成 P0.3 Workflow Grounding，让章节生产不再只依赖自由文本 instruction，而是显式绑定已接受且 fresh 的 Chapter Plan revision。

```text
Novel Project / Story Bible / Canon
  -> fresh Novel Plan
  -> fresh selected Story Arc
  -> fresh selected Chapter Plan revision
  -> bounded authoritative grounding
  -> Chapter / Review / Rewrite
  -> persisted sync or async Workflow Run
```

## 显式规划绑定

所有新 Chapter Workflow HTTP 执行入口必须携带：

```text
chapter_plan_id
chapter_plan_revision
```

绑定适用于：

```text
POST /api/v1/workflows/chapter
POST /api/v1/workflows/chapter/runs
POST /api/v1/workflows/chapter/runs/async
```

Python schema 保留字段可空，仅用于读取 08B.1 之前已经持久化的历史 Run；OpenAPI 和所有新 HTTP 执行入口均将两字段标记为必填并再次显式验证。

错误语义：

- 未提供绑定：HTTP 422。
- Chapter Plan 不存在：HTTP 404。
- revision 不匹配：HTTP 409。
- Novel Plan、selected Story Arc 或 selected Chapter Plan stale：HTTP 409。

## P0.3 Grounding Context

`ChapterWorkflowGroundingService` 在任何 Agent 调用前加载并验证：

- Project 与 Story Bible 精简约束。
- fresh Novel Plan 及当前 volume 摘要。
- 单一 selected Story Arc。
- 单一 selected Chapter Plan。
- 最多两个前置章节和一个后续章节的紧邻摘要。
- active character/location IDs 与 POV character ID。
- 基于章节目标、摘要、POV 和 continuity dependencies 构建的 Memory query。

上下文使用 3600 字符确定性硬预算，保留绑定坐标、source revisions、POV、scene beats、continuity dependencies、target word count 和活跃实体。

优先级保持：

```text
P0 Canon / Hard Constraints
P0.3 Accepted Chapter Plan Grounding
Memory / RAG retrieval evidence
free-form instruction
```

Grounding system message 在 Memory/RAG 之前注入 Chapter、Review 和 Rewrite 三个阶段。专业 Agent 返回 `grounding_enforced=true`，Workflow result 同时记录 source revision、active entities、相邻章节和 context 字符数。

## 持久化、恢复与外部 Worker

- 持久化 Run 保存 `chapter_plan_id` 和 revision。
- resume 使用原始绑定并在执行前重新解析 fresh 规划链。
- 异步提交在 API admission 时校验一次。
- 外部 Worker claim Job 后再次校验，防止排队期间规划被修改。
- 排队后变 stale 的 Job 不调用 LLM，按既有队列策略进入 dead-letter。
- 不新增 Workflow Grounding 或 Planner 数据库表；继续复用既有 planning 与 workflow run/queue 存储。

## Qwen 审核截断回退

真实 `qwen3:8b` 验收发现：审核 prompt 接近 Ollama 4096 context 时，模型可能在输出完整 JSON 前以 `finish_reason=length` 停止。此前非空截断输出会直接进入解析并产生 `review_parse_failed`。

当前行为：

- `finish_reason=length` 明确标记 `review_output_truncated=true`。
- 截断结果不会进入 JSON parser。
- 在 `review_retry_attempts` 范围内使用既有 fallback 配置重试。
- 默认 fallback `reasoning_effort=none`，为结构化 JSON 留出 completion budget。
- 重试耗尽时保持安全停止，不接受不完整审核。

## 自动化验证

```text
Chapter Workflow focused tests: 24/24 PASS
Workflow Grounding focused tests: 14/14 PASS
Full regression: 293/293 PASS
Python compileall: PASS
Docker Compose config: PASS
git diff --check: PASS
```

## 真实 qwen3:8b 验收

验收数据：

```text
novel_id = e758d70f-4a34-4311-abae-a8045c96c41e
arc_id = 0e5c4813-215d-4025-9138-fa9f2913939e
chapter_plan_id = 78d32bff-2147-43d9-a940-64a5ad9645f5
chapter_plan_revision = 1
grounding_context_chars = 3595 / 3600
Ollama qwen3:8b context_length = 4096
```

持久化 resume Run：

```text
run_id = 28c4851c-0cde-49af-a938-b428df4f8db8
execution_status = succeeded
workflow_status = completed
quality_gate_passed = true
Review: prompt 3269, completion 728, total 3997, finish_reason=stop
```

真实外部 Worker Run：

```text
run_id = daccb8e4-224d-4713-944a-87da4ed7168d
queue_status = completed
execution_status = succeeded
workflow_status = completed
quality_gate_passed = true
Draft: prompt 2185, completion 942, total 3127
Review: prompt 3081, completion 920, total 4001
```

两次成功结果均证明：

- provider/model 为 `qwen_local` / `qwen3:8b`。
- Chapter 与 Review 均 `grounding_enforced=true`。
- selected Chapter Plan ID/revision 被持久化。
- active entities、POV、selected Arc 和相邻章节 IDs 正确。
- successful Review token total 小于 Ollama 4096 context。

门禁验收：

```text
missing binding -> HTTP 422
unknown Chapter Plan -> HTTP 404
revision conflict -> HTTP 409
stale synchronous execution -> HTTP 409
stale asynchronous submission -> HTTP 409
fresh-at-submit / stale-at-worker -> dead_letter before generation
latest_content_length after stale worker rejection = 0
```

Backend/Worker 重启后，规划数据、成功 Run、Grounding metadata、dead-letter Job 和 OpenAPI 必填绑定全部恢复。

验收记录：

```text
data/sprint08b1_acceptance.json
```

## 后续

下一项为 Sprint 08B.2：建立 Manuscript / Chapter Draft / Revision 正文领域，让 Workflow 输出经过显式审核接受后成为可版本化、可恢复、可作为后续章节连续性来源的正式正文。
