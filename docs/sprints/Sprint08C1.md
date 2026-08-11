# Sprint 08C.1 - Three-tier Memory

## 状态

```text
已完成
发布版本：v0.15.0-alpha.23
基线版本：v0.15.0-alpha.22
```

## 目标

把 Memory 的“内容是什么”与“活多久、在哪个作用域有效”分离：

```text
content taxonomy: character / world / plot / short_term
lifecycle tier:  session / working / long_term
```

`short_term` 不再被误用为 Session 的同义词。任何内容类型都可以按明确规则进入任一生命周期层。

## 数据模型与兼容迁移

`memories` 新增：

```text
memory_tier TEXT NOT NULL DEFAULT 'long_term'
session_id TEXT NULL
expires_at TEXT NULL
revision INTEGER NOT NULL DEFAULT 1
```

新增 append-only `memory_lifecycle_events`，记录 created、reinforced、promoted、evicted、deleted 的来源层、目标层、reason、policy payload 和时间。

旧 rows 通过 SQLite 增量升级自动成为 Long-term；稳定 memory ID、`memory_type`、内容、分数、metadata 与 FAISS 关系不变。

## 三层职责

### Session

- 当前交互、临时意图与会话内状态。
- 必须绑定 `session_id`，默认 TTL 24 小时。
- 相同内容只在同一 session 内去重；不同 session 互相隔离。
- 不写入 FAISS；可按 TTL sweep 或 session close 淘汰。

### Working

- 当前卷、Story Arc、章节任务、未解决问题与近期创作状态。
- 小说作用域，默认 TTL 30 天；重复强化会刷新 TTL。
- 写入 FAISS，参与混合语义检索。

### Long-term

- 可跨会话召回的用户确认或权威来源证据。
- 无自动 TTL，参与 FAISS/混合检索。
- 仍然不是 Canon，不能覆盖 Entity/Story Bible/Planning/accepted Manuscript 权威事实。
- 不被 lifecycle sweep 自动删除，只能显式删除。

## 提升门

只允许：

```text
session -> working -> long_term
```

所有提升保持 memory ID，要求 `expected_revision` 并推进 revision：

- Session frequency basis：`hit_count >= 2`。
- Session user-confirmed basis：`importance >= 0.5`。
- Working -> Long-term：basis 必须为 `user_confirmed`、`accepted_manuscript` 或 `story_bible`，且 `importance >= 0.7`。
- accepted Manuscript / Story Bible basis 还要求 `metadata.source_reference`。
- 跨层、错误 basis、低 importance 或 revision mismatch 返回 HTTP 409。

## 检索与上下文

- Session 不进 FAISS，通过 `(user_id, novel_id, session_id)` 精确读取。
- Working/Long-term 进入 FAISS，Hybrid Retriever 返回 tier metadata 并支持 tier filter。
- consistency rebuild 的 SQLite 权威集合只包含 Working/Long-term，因此可清理误入 FAISS 的 Session ID。
- Agent Memory block 内顺序为 Session -> Working -> Long-term。
- 整个 Memory block 继续保留已发布 `source=long_term_memory` 下游契约，并位于 Canon 与 Chapter Plan Grounding 之后；新增 `memory_mode=tiered` 表达新模式。

## API

```text
POST /api/v1/memory
GET  /api/v1/memory/{user_id}/{novel_id}
POST /api/v1/memory/{memory_id}/promote
GET  /api/v1/memory/{memory_id}/lifecycle/events
POST /api/v1/memory/lifecycle/sweep
POST /api/v1/memory/sessions/{session_id}/close
```

既有 create/query/delete/retrieve API 保持兼容。Create 默认 `long_term`；query 新增 `memory_tier`、`session_id`、`include_expired` filter。

## 已知缺陷修复

`MemoryExtractor` 原来对每个解析事实连续调用两次 `memory_manager.add_memory(...)`，会让 hit count 虚增并返回重复结果。08C.1 删除重复路径，并用独立回归证明每条事实只保存一次。

## 自动化验证

```text
Memory Lifecycle focused: 15/15 PASS
existing Memory/RAG: 8/8 PASS
Agent/Canon/Workflow Grounding related: 48/48 PASS
full regression: 343/343 PASS
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

覆盖旧表迁移、schema validation、session-scoped duplicate、FAISS exclusion、相邻提升、频次/权威门、revision conflict、稳定 ID、事件重启、TTL dry-run/execute、session close、Long-term 保留、tiered context 顺序、Extractor 单次保存、API 409 和 OpenAPI。

## 真实运行态验收

```text
scope user = sprint08c1-acceptance
scope novel = memory-lifecycle-20260811
memory_id = 0783f006-efba-424d-ba14-b245f7827ffb
```

- 两个相同 Session 内容在不同 session 下获得不同 ID。
- Session revision 1 在真实 `/retrieve` 中返回 0，证明没有写入 FAISS。
- 错误 expected revision 返回 HTTP 409。
- Session -> Working 保持 ID，revision 2，生成 30 天 TTL，并通过本地 `qwen3-embedding:0.6b` 进入 `/retrieve`。
- Working -> Long-term 保持 ID，revision 3，TTL 变为 null。
- 主记录 lifecycle events 为 created/promoted/promoted。
- 过期 Session `9ef09770-8c2a-4e30-a92f-a2fb808ab95c` 的 dry-run 与执行均只命中该 ID，事件为 created/evicted。
- session close 只淘汰 `08c1-other` 的记录；最终 scope 无 Session，Long-term 主记录保留。
- 使用 base + worker overlay 联合重启 Backend/Worker 后，在线版本为 `0.15.0-alpha.23`，OpenAPI 保持 7 个 Memory 路径（4 个 lifecycle 路径）。
- 重启后验收 scope 仍只有 Long-term 主记录，revision 3、TTL 为 null、三条 lifecycle events 完整，Session 数为 0。
- 启动一致性检查为 SQLite 9 / FAISS 9、无需 rebuild；重启后的真实 `/retrieve` 仍通过本地 embedding 唯一召回主记录，证明 Long-term row 与 FAISS 索引均已持久化。
- 容器内只读复核确认生产 `memories` 已有四个 lifecycle columns，事件表存在，主记录位于 FAISS，两条已淘汰 Session ID 均不在 FAISS。

验收记录：

```text
data/sprint08c1_acceptance.json
```

## 后续

下一项 Sprint 08C.2：建立与小说内部 Memory/Canon 物理或逻辑隔离、来源可追踪的外部知识库。
