# Sprint 08B.2 - Manuscript / Chapter Draft / Revision Domain

## 状态

```text
已完成
发布版本：v0.15.0-alpha.21
基线版本：v0.15.0-alpha.20
```

## 目标

让正文不再只存在于 Workflow Run 结果中，并建立明确的候选与正式稿边界：

```text
succeeded + quality-gated Workflow Run
  -> explicit import
  -> immutable Manuscript revisions
  -> reviewed candidate
  -> explicit accept
  -> authoritative accepted manuscript
  -> later Chapter Workflow continuity
```

Workflow 不会自动写入或接受 Manuscript。只有显式导入后形成候选，只有显式接受的修订才能成为后续章节的权威连续性来源。

## 正文领域

新增表：

```text
manuscript_chapters
manuscript_revisions
```

`manuscript_chapters` 在 `(novel_id, chapter_number)` 上唯一，并为每章提供稳定 `manuscript_chapter_id`、聚合 revision、latest revision 和 accepted revision 指针。

`manuscript_revisions` 为 append-only 正文版本，保存：

- 正文、SHA-256 content hash 和不可变 revision。
- 来源 Workflow Run / Workflow Version、draft/rewrite/checkpoint 阶段和轮次。
- reviewed candidate 状态、质量分数和审核摘要。
- Project、Story Bible、Novel Plan、Story Arc、Chapter Plan 来源 revision。
- selected Arc / Chapter Plan 稳定 ID。

同一 Workflow Run / Version 只能导入一次。重复导入同一 Run 返回现有结果，不重复追加正文 revision。

## 导入与接受边界

导入只接受满足以下条件的持久化 Workflow Run：

```text
execution_status = succeeded
workflow_status = completed
quality_gate_passed = true
planning_freshness_validated = true
```

导入复制 Run 中的持久化正文版本；最终正文对应版本标记为 `approved`，更早版本标记为 `superseded`。导入不会更新 accepted revision。

接受是独立操作：

- 只允许接受 `approved` candidate。
- 使用 Manuscript 聚合 `expected_manuscript_revision` 做乐观并发。
- 在单一 `BEGIN IMMEDIATE` 事务中重新验证 Project/Bible/Plan/Arc/Chapter 来源 revision 和 freshness。
- stale 或 revision mismatch 返回 HTTP 409，接受指针不改变。
- 重复接受当前 revision 幂等返回 `changed=false`。

## API

```text
POST /api/v1/novels/{novel_id}/manuscript/chapters/import-workflow
GET  /api/v1/novels/{novel_id}/manuscript/chapters
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}
POST /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}/accept
```

不存在的 Novel、Workflow、Manuscript Chapter 或 revision 返回 HTTP 404。无效 Run 状态、并发冲突、来源 stale 和不允许接受的 revision 返回 HTTP 409。

## 后续章节连续性

Chapter Workflow Grounding 只读取目标章节之前最多两个已接受 Manuscript revision：

```text
accepted manuscript > candidate-only manuscript
```

未接受候选不会进入 Agent 输入。后续导入的新候选也不会替换已有 accepted revision，直到显式接受。

接受稿连续性位于 3600 字符 P0.3 Grounding 预算内，并在紧缩路径中优先保留。Workflow metadata 记录：

```text
accepted_manuscript_chapter_ids
accepted_manuscript_revisions
manuscript_continuity_mode = accepted_only
```

## 自动化验证

```text
Manuscript focused tests: 16/16 PASS
Workflow Grounding focused tests: 14/14 PASS
Chapter Workflow focused tests: 24/24 PASS
Full regression: 309/309 PASS
Python compileall: PASS
Docker Compose config: PASS
git diff --check: PASS
```

覆盖内容包括 schema/index、稳定 ID、不可变 revision、Run 幂等导入、乐观并发、接受幂等、stale import/accept、重启存储、候选隔离、接受稿 Grounding、3600 字符预算和全部 OpenAPI 路由。

## 真实 qwen3:8b 验收

验收规划链：

```text
novel_id = 87e614d3-6c90-4cfd-81b1-f7c0222120dd
arc_id = f2b85432-b4ce-4e78-ae0b-ac5f8c543100
chapter_1_plan_id = 6faffad8-7ce0-4b92-a36d-e4e1ee41f884
chapter_2_plan_id = e11b8a15-5a48-4edd-b963-e6d9d5db9404
```

第一章真实 Run：

```text
run_id = 7d3517d3-f8dc-4d58-adce-453bc5377345
execution/workflow = succeeded/completed
quality_gate_passed = true
provider/model = qwen_local/qwen3:8b
draft/review = success/success
final_content_chars = 685
```

导入第一章后：

```text
manuscript_chapter_id = 586a1ac7-cbec-4a02-a371-7183a7bca267
first import = HTTP 201, deduplicated=false
second import = HTTP 201, deduplicated=true
latest_revision = 1
review_status = approved
accepted_revision = null
```

接受前第二章真实 Run 的 `accepted_manuscript_chapter_ids=[]`。第一章显式接受后，重复接受返回 `changed=false`；接受后的第二章真实 Run：

```text
run_id = 759bea22-9198-4d2d-811c-51c49450b528
execution/workflow = succeeded/completed
quality_gate_passed = true
accepted_manuscript_chapter_ids = [586a1ac7-cbec-4a02-a371-7183a7bca267]
accepted_manuscript_revisions = [1]
manuscript_continuity_mode = accepted_only
```

stale gate 验收：第二章候选导入后将 Story Bible revision 从 5 推进到 6，接受返回 HTTP 409；第二章 Manuscript 聚合 revision 保持 1，`accepted_revision` 保持 `null`。

Backend 重启后，在线 OpenAPI 版本为 `0.15.0-alpha.21`、6 条 Manuscript 路由完整；第一章接受指针、正文 hash、第二章未接受候选和第二章 Workflow 的 accepted-only Grounding metadata 全部恢复。

验收记录：

```text
data/sprint08b2_acceptance.json
```

## 后续

下一项为 Sprint 08B.3：建立全小说 Orchestrator，按 Arc / Chapter 顺序驱动 Workflow、Manuscript 显式门禁、暂停、恢复和失败重试。
