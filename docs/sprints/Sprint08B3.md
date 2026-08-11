# Sprint 08B.3 - Full Novel Orchestrator

## 状态

```text
已完成
发布版本：v0.15.0-alpha.22
基线版本：v0.15.0-alpha.21
```

## 目标与边界

建立可恢复、可审计的全小说章节控制循环：

```text
freeze Chapter Plan revisions
  -> queue current Chapter Workflow
  -> explicit advance imports candidate
  -> human accepts through Manuscript API
  -> explicit advance queues next chapter
  -> completed
```

Orchestrator 不生成正文、不复制 Workflow 执行器，也不接受 Manuscript。它只协调已发布领域，并把“上一章已明确接受”设为下一章排队的硬门禁。

## 持久化模型

新增表：

```text
novel_orchestrations
novel_orchestration_steps
novel_orchestration_events
```

聚合保存 novel/user、状态、乐观并发 revision、当前 step、选择快照、Workflow/Queue 策略、暂停来源和错误。Step 冻结：

- `chapter_plan_id` / `chapter_plan_revision`
- `chapter_number` / `chapter_title`
- `arc_id` / `arc_revision`
- Workflow Run/attempt、Manuscript candidate/accepted revision

Event 使用聚合内递增 sequence，记录创建、排队、候选导入、接受、暂停、恢复、失败、重试和完成。

## 状态与推进规则

```text
ready
  -> waiting_for_workflow
  -> waiting_for_acceptance
  -> waiting_for_workflow (next chapter)
  -> completed

any active state -> paused -> resume previous state
queue/quality/import failure -> failed -> retry
```

- 创建时验证 fresh Novel Plan 和所有 selected Chapter Plan Grounding，然后按 chapter number 冻结顺序。
- 已有精确匹配当前 Chapter Plan revision 的 accepted Manuscript 会被跳过。
- active Queue 状态下重复 `advance` 不创建第二个 Run。
- succeeded/completed/quality-gated Run 只有在显式 `advance` 时才导入 candidate。
- candidate 导入不自动接受；只有既有 Manuscript API 能改变 accepted revision。
- 下一章只在 step 中记录的精确 candidate revision 已接受后排队。
- pause 不取消在途本地推理；暂停期间 `advance` 不导入、不排下一章。
- Queue/DLQ failure 重试复用同一 Run；质量门失败或人工拒绝 candidate 时创建新 attempt。
- 所有控制操作要求 `expected_revision`，冲突返回 HTTP 409。

## API

```text
POST /api/v1/novels/{novel_id}/orchestrations
GET  /api/v1/novels/{novel_id}/orchestrations
GET  /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/advance
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/pause
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/resume
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/retry
```

创建支持 `Idempotency-Key`。不存在资源返回 HTTP 404，revision/stale/状态冲突返回 HTTP 409，Queue 背压返回 HTTP 429，非法 schema 返回 HTTP 422。

## LangGraph 决策

本 Sprint 不引入 LangGraph。当前流程是一条确定性的线性状态机；SQLite 聚合事务负责业务 checkpoint，Workflow Queue/DLQ 负责执行状态。再增加图 checkpoint 会制造双重权威源。未来只有在出现并行章节分支、多种人工任务节点、补偿事务或动态子图后才重新评估。

## 自动化验证

```text
Orchestrator focused tests: 19/19 PASS
Manuscript focused tests: 16/16 PASS
Workflow Grounding focused tests: 14/14 PASS
Workflow Async focused tests: 8/8 PASS
Full regression: 328/328 PASS
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

覆盖 schema/index、重启存储、冻结顺序、逐章排队、幂等创建/推进、错误 owner、stale gates、候选隔离、精确 accepted gate、暂停/恢复、Queue failure retry、quality failure retry、人工拒绝 retry、预接受跳过、两章完成、乐观并发、API/OpenAPI 和 404/409。

## 真实 qwen3:8b 验收

```text
novel_id = e872414f-8e9b-48fb-95a1-1da63dc8a0e6
orchestration_id = 8eb289fe-1aaa-4a95-8f2a-24ef107f234f
chapter_1_run_id = 02009cae-e2e0-443f-aae6-38a39cb573f0
chapter_2_run_id = ffe7d4ea-e03d-4516-a97b-f83b51573695
provider/model = qwen_local/qwen3:8b
```

两个 Run 都由外部 Worker 实际执行并达到 `succeeded/completed`、`quality_gate_passed=true`。验收证明：

- 第 1 章运行完成后暂停，`advance` 保持 revision 3，未导入 candidate、未排第 2 章。
- resume 后第 1 章成为 candidate revision 1，`accepted_revision=null`。
- 通过 Manuscript API 显式接受后，编排才排入第 2 章。
- 第 2 章 Grounding 记录第 1 章 Manuscript ID 和 accepted revision 1。
- 第 2 章同样经过 candidate 与显式接受门，最终 revision 9、2/2 accepted、status completed。
- 重复创建命中相同 ID，`deduplicated=true`。
- Story Bible revision 2 推进至 3 后，新建编排返回 HTTP 409，编排总数不变，已完成聚合不受影响。
- Backend/Worker 重启后在线版本为 `0.15.0-alpha.22`；聚合 revision 9、10 条 events、两章 accepted revision 和 6 条 OpenAPI path / 7 个操作全部恢复。

验收记录：

```text
data/sprint08b3_acceptance.json
```

## 后续

下一项 Sprint 08C.1：建立 Session / Working / Long-term 三层 Memory 的职责、生命周期、提升与淘汰规则。
