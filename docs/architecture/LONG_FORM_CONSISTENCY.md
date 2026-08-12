# NovelForge 长篇小说一致性增量路线

## 1. 审计结论

审计基线：`v0.15.0-alpha.17`。

NovelForge 已经具备稳定的规划领域、可恢复章节工作流、本地 Qwen、SQLite Memory 和 FAISS 召回，但“人物身份、当前事实和角色认知”尚未形成权威闭环。当前最主要的风险不是缺少更多 Prompt，而是多个模块仍以自由文本名字连接，且检索结果没有经过 Canon、时态和知识范围仲裁。

因此采用增量路线：先建立稳定实体身份，再把实体接入 Story Bible 与 Writer Context，随后建设 Temporal State 和 Consistency Engine。现有 Planner、Workflow、Memory 和 RAG 不重写。

## 2. 当前已有能力

- `Novel Project -> Story Bible -> Novel Plan -> Story Arc -> Chapter Plan` 五层规划领域。
- Planner 三目标结构化 candidate、stale gate、fixed coordinates、Pydantic 强校验和显式接受。
- Chapter、Review、Rewrite、Re-review 工作流及队列、恢复、版本和运维能力。
- 稳定 Manuscript Chapter、不可变正文 revision、显式接受与 accepted-only 后续章节连续性。
- 持久化 Full Novel Orchestrator、逐章队列控制、人工门禁、暂停/恢复和失败重试。
- 正交的 Session/Working/Long-term Memory 生命周期、提升/淘汰事件与分层检索。
- SQLite Memory、Qwen Embedding、FAISS、关键词/向量混合评分和过滤。
- Agent 共享上下文与 metadata 扩展点。
- Story Bible 人物列表，以及规划结构中的 `character_id`、`character_ids`、`pov_character_id` 字段。

## 3. 名称与事实一致性风险

1. `StoryBible.characters` 当前是 `list[dict[str, Any]]`，没有统一的人物 schema、稳定 ID 强制或引用完整性校验。
2. 规划层虽然已有若干 character ID 字段，但没有权威实体源验证这些 ID 是否真实存在。
3. 别名没有确定性索引；同名、近名和别名只能由 LLM 自行理解。
4. 审计时 Memory 只有内容分类，不是严格的 Session / Working / Long-term 生命周期模型；该项已由 08C.1 解决。
5. Memory 和 FAISS 返回的是上下文证据，当前 Context Builder 尚未建立 Canon 优先级。
6. 审计时尚无 Temporal Graph；08D.1 已通过章节有效区间、current/historical 查询和来源 revision 解决这一基础能力。
7. 还没有 Knowledge Scope，POV Writer 无法可靠隔离世界真相、角色知识与角色信念。
8. Review Agent 以通用 LLM 审核为主，没有实体、关系、生死、地点等确定性检查器。
9. Chapter Workflow 还没有绑定正式 Chapter Plan，写作输入主要依赖自由文本 instruction。

## 4. 可直接扩展的现有模块

- `app.novels`：作为 Canonical Entity 的权威业务边界，复用现有 SQLite、service、API 和 revision 风格。
- `StoryBible`：后续保持旧 `characters` 兼容，同时增加实体引用校验和迁移入口。
- `AgentContext.metadata`：后续承载 active entities、POV entity 和 knowledge scope，不改变 Agent 基类。
- `MemoryContextBuilder`：后续升级为带优先级和预算的 Writer Context Builder。
- `ChapterWorkflow`：在 08B.1 接入 fresh Chapter Plan 和 Canon Context。
- `Review Agent`：后续接收结构化 consistency conflicts，不替换现有质量审核。

## 5. 需要小幅增加的数据结构

第一阶段只增加：

- `novel_entities`：稳定 `entity_id`、类型、正式名称、描述、metadata 和 revision。
- `novel_entity_aliases`：正式名称/别名的规范化索引。
- 实体 create/update/read/list/resolve schema。
- 显式的 `resolved / ambiguous / not_found` 解析结果。

后续阶段已增加或仍待增加：

- Story Bible 的兼容实体引用。
- 08D.1 已增加带 source、confidence、chapter range 的事件与关系动态状态。
- Active Scene Entities 和 Knowledge Scope。
- 统一 consistency conflict schema。

## 6. 暂时不要动的部分

- 不改 Planner candidate-only 和显式接受边界。
- 不改 Novel Plan、Story Arc、Chapter Plan 已发布表结构和 stale 语义。
- 不为本阶段引入 LangGraph、Neo4j 或新的向量数据库。
- 不重写现有 Memory/FAISS；在 Canon Context 可用后再做分层与融合。
- 不一次性把全部旧 Story Bible 数据强迁移成新实体，避免破坏兼容性。
- 不在 Entity Registry 尚未稳定前实现 Temporal Graph。

## 7. 最小改造方案

### P0.1：Canonical Entity Foundation

- 在 novels 领域增加稳定 Entity Registry。
- 第一类重点支持 character，同时保留 organization、location、item、creature、concept 类型。
- 内部逻辑使用 `(novel_id, entity_id)` 定位，名字只用于展示和解析。
- Alias Resolver 采用固定优先级：exact canonical、exact alias、normalized canonical、normalized alias。
- 多个实体同级命中时返回 ambiguous candidates，绝不默认选择第一个。
- 更新使用 revision 乐观并发；实体 ID 不可修改。

### P0.2：Story Bible Entity Alignment + Canon Context（已完成）

- 为旧 `characters` 提供兼容导入/绑定，不直接删除自由结构字段。
- 校验 Planner/Chapter Plan 中的 character ID 引用。
- 构建带确定性预算的 Writer Context，明确 P0 Canon 不可被 Memory/RAG 覆盖。
- 把 external knowledge 限制为世界知识证据，不允许决定小说内部人物事实。

当前实现补充：

- 旧 Story Bible 通过显式 API 对齐，不在普通 update 时静默创建实体。
- 对齐在单一 SQLite 事务中完成，歧义、重复和 ID/名称冲突整体回滚。
- Entity create/update 推进 Story Bible Canon revision，使既有规划正确 stale。
- Planner 与领域写入均验证 canonical character/location references。
- Agent Canon Context 位于 Memory/RAG 之前，最大 3600 字符。
- `secret` 暂不进入人物 Canon profile；完整 POV Knowledge Scope 留到 P2。

### P0.3：Workflow Grounding（已完成）

- Chapter Workflow 显式绑定 fresh Chapter Plan revision。
- 建立 `active_character_ids`、`active_location_ids` 和 `pov_character_id`。
- 使用 3600 字符确定性预算加载 selected Plan/Arc/Chapter、活跃实体和相邻章节摘要。
- Chapter、Review、Rewrite 共享权威规划上下文，并确保 Memory/RAG 只作为低优先级检索证据。
- 同步、resume、异步队列和外部 Worker 均保存绑定并在执行点重新校验 freshness。

### P0.4：Accepted Manuscript Continuity（已完成）

- succeeded、completed 且 quality-gated 的 Workflow Run 可显式导入为 reviewed candidate。
- Manuscript Chapter 使用稳定 ID，正文 revisions append-only 并保存完整规划来源快照。
- candidate 导入不会自动接受；接受是带聚合 revision 并发检查的独立事务。
- 导入与接受都重新验证 Project、Bible、Plan、Arc、Chapter freshness。
- 后续 Chapter Workflow 只使用 accepted prior revisions，未接受候选不会成为 Canon 或连续性事实。
- 事实抽取、Memory/Vector/Temporal Graph 回写仍留在后续 Sprint，不由 08B.2 隐式执行。

### P0.5：Full Novel Orchestration（已完成）

- 创建时冻结 Chapter Plan ID/revision 顺序，避免运行中选择集合漂移。
- 一次只允许一个章节进入 Workflow Queue；下一章只在上一章精确候选 revision 被显式接受后排队。
- Orchestrator 只显式导入质量门通过的 Workflow candidate，不拥有 Manuscript 接受权限。
- 聚合 revision、append-only events 和 SQLite 状态支持幂等控制、暂停、恢复、重试与重启恢复。
- 暂停保留在途 Workflow，避免浪费本地模型推理；恢复后显式 reconcile 终态。
- Queue/DLQ 继续作为执行与重试权威来源，Orchestrator 不复制 Worker 调度状态。
- 当前控制流是确定性的线性状态机，因此未引入 LangGraph 或第二套 checkpoint；未来出现并行分支、人工任务图或补偿事务时再评估。

### P0.6：Three-tier Memory Lifecycle（已完成）

- `memory_type=character/world/plot/short_term` 保持内容分类，新增正交 `memory_tier=session/working/long_term`。
- 旧 SQLite rows 增量迁移为 Long-term，稳定 ID、既有 API 与 FAISS 数据不丢失。
- Session 必须绑定 session ID，24 小时 TTL 且不进入 FAISS；session close 可作用域淘汰。
- Working 使用 30 天 TTL并进入混合检索；Long-term 无自动 TTL，只有显式删除。
- Session -> Working 与 Working -> Long-term 只能相邻提升，使用 memory revision 乐观并发并保存 append-only lifecycle events。
- Working -> Long-term 需要权威 promotion basis 和 `importance >= 0.7`；accepted Manuscript / Story Bible 来源还必须携带 `metadata.source_reference`。
- Agent 上下文按 Session -> Working -> Long-term 排列，但整个 Memory block 仍位于 Canon 与 Chapter Plan Grounding 之后。
- FAISS consistency rebuild 只覆盖 Working/Long-term，能够清理误入索引的 Session ID。

## 8. P1 / P2 路线

### P1：Temporal State（08D.1 基础已完成）

- 动态人物状态和关系有效区间。
- current / historical 查询。
- source、confidence、source chapter 和来源 revision。
- Active Scene Entities 驱动的 entity-aware retrieval。
- Graph/Vector 结果融合、去重、冲突仲裁和 context budget。

08D.1 以独立 `temporal_graph.db` 保存当前聚合和 append-only revision snapshot；实体身份仍由 `novel_entities` 唯一授权。Graph Provider 已接入 08C.3 双 lane，并消费 active entity 与 chapter 坐标。08D.2 已增加候选事实抽取与确定性冲突仲裁；accepted Manuscript 后的原子/幂等回写仍属于 08D.3。

### P2：Consistency Engine（08D.2 已完成）

- 统一冲突类型与 severity/evidence/expected/generated 结构。
- 先做确定性的 alias、关系、生死、地点、身份检查。
- 增加 WORLD_TRUTH、CHARACTER_KNOWLEDGE、CHARACTER_BELIEF、READER_KNOWLEDGE。
- LLM 只解释和修复明确冲突，不独自决定 Canon。
- accepted manuscript 后再幂等回写 Memory、Vector 和 Temporal Graph。

08D.2 将 Project/Bible world rules、Canonical Entity 和指定章节有效的 Temporal Event/Relation 统一为带来源 revision 的 P0.4 约束。独立 API 与 Chapter Review 均可产生结构化候选事实，但冲突结论由确定性检查器给出；LLM 不能凭空新增 Canon，也不能仅把 `change_type` 标成 transition 绕过门禁。确认的阻断冲突进入 Rewrite，下一轮 Review 重新抽取并复检。

本阶段保持 candidate-only：`persisted=false`，不写 Temporal Graph、Memory、Vector、Canon 或 Manuscript。模型抽取与 grounded Review 的章节号强制绑定请求/Chapter Plan 固定坐标；显式 `/check` 仍会对调用方提交的错误章节报告 `timeline_conflict`。事实接受、原子写入、幂等键和跨存储补偿仍归 08D.3。

## 9. 文件影响范围

P0.1 新增或修改：

```text
backend/app/novels/schemas.py
backend/app/novels/storage.py
backend/app/novels/service.py
backend/app/api/v1/novels.py
backend/tests/test_entity_registry.py
docs/architecture/LONG_FORM_CONSISTENCY.md
docs/sprints/Sprint08A7.md
docs/ROADMAP.md
docs/CURRENT_IMPLEMENTATION.md
docs/CHANGELOG.md
```

P0.2 预计重点修改：

```text
backend/app/novels/schemas.py
backend/app/novels/service.py
backend/app/agents/memory_context.py
backend/app/agents/chapter_agent.py
backend/app/planner/service.py
backend/tests/test_novel_project.py
backend/tests/test_chapter_agent.py
backend/tests/test_planner_agent.py
```

## 10. 已识别技术债

08C.1 已修复 `MemoryExtractor` 重复保存路径；08C.2 外部知识隔离、08C.3 Graph/Vector 双路融合、08D.1 Temporal Graph 基础和 08D.2 Consistency Engine 均已完成。当前技术债集中在候选抽取召回率评估，以及 accepted Manuscript 后跨 Memory、Vector、Temporal Graph 的原子、幂等事实回写。
