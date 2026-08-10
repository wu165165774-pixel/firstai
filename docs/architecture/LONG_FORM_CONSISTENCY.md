# NovelForge 长篇小说一致性增量路线

## 1. 审计结论

审计基线：`v0.15.0-alpha.17`。

NovelForge 已经具备稳定的规划领域、可恢复章节工作流、本地 Qwen、SQLite Memory 和 FAISS 召回，但“人物身份、当前事实和角色认知”尚未形成权威闭环。当前最主要的风险不是缺少更多 Prompt，而是多个模块仍以自由文本名字连接，且检索结果没有经过 Canon、时态和知识范围仲裁。

因此采用增量路线：先建立稳定实体身份，再把实体接入 Story Bible 与 Writer Context，随后建设 Temporal State 和 Consistency Engine。现有 Planner、Workflow、Memory 和 RAG 不重写。

## 2. 当前已有能力

- `Novel Project -> Story Bible -> Novel Plan -> Story Arc -> Chapter Plan` 五层规划领域。
- Planner 三目标结构化 candidate、stale gate、fixed coordinates、Pydantic 强校验和显式接受。
- Chapter、Review、Rewrite、Re-review 工作流及队列、恢复、版本和运维能力。
- SQLite Memory、Qwen Embedding、FAISS、关键词/向量混合评分和过滤。
- Agent 共享上下文与 metadata 扩展点。
- Story Bible 人物列表，以及规划结构中的 `character_id`、`character_ids`、`pov_character_id` 字段。

## 3. 名称与事实一致性风险

1. `StoryBible.characters` 当前是 `list[dict[str, Any]]`，没有统一的人物 schema、稳定 ID 强制或引用完整性校验。
2. 规划层虽然已有若干 character ID 字段，但没有权威实体源验证这些 ID 是否真实存在。
3. 别名没有确定性索引；同名、近名和别名只能由 LLM 自行理解。
4. 当前 Memory 是内容分类，不是严格的 Session / Working / Long-term 生命周期模型。
5. Memory 和 FAISS 返回的是上下文证据，当前 Context Builder 尚未建立 Canon 优先级。
6. 还没有 Temporal Graph，无法区分当前关系与历史关系、当前地点与历史地点。
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

后续阶段再增加：

- Story Bible 的兼容实体引用。
- 带 source、confidence、chapter range 的动态状态。
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

### P0.2：Story Bible Entity Alignment + Canon Context

- 为旧 `characters` 提供兼容导入/绑定，不直接删除自由结构字段。
- 校验 Planner/Chapter Plan 中的 character ID 引用。
- 构建带确定性预算的 Writer Context，明确 P0 Canon 不可被 Memory/RAG 覆盖。
- 把 external knowledge 限制为世界知识证据，不允许决定小说内部人物事实。

### P0.3：Workflow Grounding

- Chapter Workflow 显式绑定 fresh Chapter Plan revision。
- 建立 `active_character_ids`、`active_location_ids` 和 `pov_character_id`。
- 只为活跃实体加载 Canon、当前状态、关系与相关检索证据。

## 8. P1 / P2 路线

### P1：Temporal State

- 动态人物状态和关系有效区间。
- current / historical 查询。
- source、confidence、source chapter 和来源 revision。
- Active Scene Entities 驱动的 entity-aware retrieval。
- Graph/Vector 结果融合、去重、冲突仲裁和 context budget。

### P2：Consistency Engine

- 统一冲突类型与 severity/evidence/expected/generated 结构。
- 先做确定性的 alias、关系、生死、地点、身份检查。
- 增加 WORLD_TRUTH、CHARACTER_KNOWLEDGE、CHARACTER_BELIEF、READER_KNOWLEDGE。
- LLM 只解释和修复明确冲突，不独自决定 Canon。
- accepted manuscript 后再幂等回写 Memory、Vector 和 Temporal Graph。

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

`MemoryExtractor` 当前对同一抽取结果存在重复调用 `memory_manager.add_memory(...)` 的路径，可能造成已有记录 hit count 异常增加。它不属于 P0.1 实体身份切片，本阶段不混入修复；应在 Memory 生命周期改造前以独立回归测试修复。
