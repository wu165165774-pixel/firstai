# Sprint 08D.1 - Temporal Graph Foundation

## 状态

```text
已完成
发布版本：v0.15.0-alpha.26
基线版本：v0.15.0-alpha.25
```

## 目标与边界

本 Sprint 建立 Temporal Graph 权威存储，并把真实 Graph Provider 接入 08C.3 已发布的双路检索层：

```text
Canonical Entity Registry
          │ stable entity_id
          v
temporal_graph.db
  ├── current Event / Relation aggregates
  ├── normalized Event participants
  └── immutable revision snapshots
          │ active entities + chapter coordinate
          v
Temporal Graph Provider ─┐
                         ├─ RRF fusion -> Agent / Chat context
Vector Memory Provider ──┘
```

实体身份仍由 `novel_entities` 唯一授权。Temporal Graph 不复制 Canonical Entity，不自动抽取或回写事实，也不改变 Planner candidate-only、Manuscript 人工接受或既有规划 stale 语义。自动事实抽取与接受后原子/幂等回写留给 08D.3。

## 数据模型与一致性

- 独立 `data/temporal_graph.db`，不把 Graph 动态状态混入 `novels.db` 或 `memory.db`。
- Event 保存类型、上下文类型、标题/摘要、参与实体、地点、起止章节、confidence、metadata 和来源。
- Relation 保存 subject/predicate/object、描述、有效起止章节、confidence、metadata 和来源。
- Event participants 使用规范化表，按精确 entity ID 查询，避免 JSON/文本误命中。
- 当前聚合使用稳定 ID 和 revision；每次创建/更新都写入不可变 JSON snapshot。
- 更新使用 `BEGIN IMMEDIATE` 和 `expected_revision`，并发写入只有一个 revision 胜出；陈旧写入返回 HTTP 409。
- 时间区间为闭区间；指定章节时查询在该章有效的事实，`include_historical=true` 可同时返回已结束事实。

## 来源与实体门禁

Temporal Graph 只接受两类权威来源：

- `story_bible`：`source_id` 必须等于 novel ID，且指定 revision 必须真实存在。
- `accepted_manuscript`：必须引用已接受的精确 Manuscript revision，且 source chapter 与正文 chapter 一致。

所有参与实体、关系两端和地点都必须存在于同一小说的 Canonical Entity Registry；地点引用还必须是 `location` 类型。来源 revision 与 Graph revision 均保留在检索 provenance 中。

## API

```text
POST /api/v1/novels/{novel_id}/temporal-graph/events
GET  /api/v1/novels/{novel_id}/temporal-graph/events
GET  /api/v1/novels/{novel_id}/temporal-graph/events/{event_id}
PUT  /api/v1/novels/{novel_id}/temporal-graph/events/{event_id}
GET  /api/v1/novels/{novel_id}/temporal-graph/events/{event_id}/revisions

POST /api/v1/novels/{novel_id}/temporal-graph/relations
GET  /api/v1/novels/{novel_id}/temporal-graph/relations
GET  /api/v1/novels/{novel_id}/temporal-graph/relations/{relation_id}
PUT  /api/v1/novels/{novel_id}/temporal-graph/relations/{relation_id}
GET  /api/v1/novels/{novel_id}/temporal-graph/relations/{relation_id}/revisions

POST /api/v1/novels/{novel_id}/temporal-graph/query
```

列表与查询支持 active entities、章节坐标、current/historical、context/event/predicate 过滤。Graph 查询使用确定性的实体重合度、词法匹配、confidence 和稳定排序生成证据。

## 双路检索与 Agent 接入

- 默认 Graph lane 由真实 `TemporalGraphRetrievalProvider` 提供，不再使用占位 Provider。
- SQLite Graph 查询放到工作线程，保持 Vector/Graph lane 的并发与独立 timeout 语义。
- `allowed_memory_types` 映射为 Graph context 类型；`as_of=chapter:N` 映射为章节坐标。
- Graph evidence 保留 graph kind、entity IDs、有效区间、来源类型/ID/revision 和 Graph revision。
- Memory Context、Chat、Novel Agent 与 grounded 专业 Agent 均传递 active entity IDs 和 chapter number。
- 用户 scope 不匹配时不泄露小说存在性：Vector 返回空集，Graph 报 unavailable，融合层安全降级。

## 自动化验证

```text
16/16 Temporal Graph focused tests passed
14/14 Dual Retrieval focused tests passed
390/390 first full regression passed
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

专项测试覆盖独立/规范化表结构、current/historical 查询、精确参与实体过滤、Event/Relation revision snapshot、关系 reopen、真实并发更新单胜者、Canonical Entity/地点类型校验、Story Bible/accepted Manuscript 来源门禁、scope 隔离、Provider 坐标映射、API/OpenAPI 与 HTTP 404/409。

## 真实运行态验收

使用全新并保留的验收小说与 Graph 数据：

```text
user_id = acceptance-08d1-15468ee84ff2
novel_id = 6bb1eaa5-d175-4a93-892e-3ec7271ddd95
marker = 08D1-AZURE-15468ee84ff2
event_id = evt_oath_15468ee84ff2
current_relation_id = rel_allies_15468ee84ff2
historical_relation_id = rel_hostile_15468ee84ff2
```

- Event 更新至 revision 2，revision 列表为 `[2, 1]`，陈旧更新返回 HTTP 409。
- 第 2 章 current 查询只返回“敌对”；第 3 章 current 查询返回“北塔盟约”和“盟友”，不返回已结束的“敌对”；historical 查询可恢复历史关系。
- 真实 `qwen3-embedding:0.6b` Vector 证据与 Graph Event 内容去重为一条融合证据，同时保留 Vector/Graph 两个来源。
- grounded Character Agent 仅使用第 3 章有效的 Graph 关系，确定性回答“岚与祁是盟友”，没有调用 LLM。
- Novel Agent 使用真实 `qwen3:8b`、medium reasoning 准确回答北塔盟约事实；Vector/Graph 均成功且未降级。
- 错误 user scope 返回零证据，没有跨用户泄露。

完整运行态验收保存在 `data/sprint08d1_acceptance.json`；验收数据未删除。

## 后续

下一项 Sprint 08D.2：增加确定性 Consistency Engine、统一 conflict schema 和写作前/后门禁。08D.3 再实现 accepted Manuscript 后 Memory、Vector、Temporal Graph 的原子、幂等事实回写。
