# NovelForge 产品与工程 Roadmap

## 1. 产品目标

NovelForge 的目标是在 Windows + Docker 环境中构建一个可以持续、可控地自动创作长篇小说的系统。

目标生产链路：

```text
创作意图
  -> Novel Project / Story Bible
  -> Novel Plan
  -> Story Arc
  -> Chapter Plan
  -> Chapter Draft
  -> Review / Rewrite / Re-review
  -> Accepted Manuscript
  -> Memory / Knowledge / Graph 回写
  -> 下一章
```

核心原则：

- 规划、正文、审核和知识状态使用明确的领域边界。
- LLM 生成结果先作为 candidate，必须经过校验和显式接受才能进入正式数据。
- SQLite 负责权威业务数据，FAISS 负责语义召回；后续图数据库负责时间与关系推理。
- 本地 `qwen3:8b` 是默认可离线运行模型，外部 Provider 是可选能力。
- 长篇生成必须可恢复、可审计、可重试，不能依赖单次超长 Prompt。

## 2. 当前基线

当前已发布基线：

```text
v0.15.0-alpha.19
```

已完成的主干能力：

- FastAPI、Docker Compose、本地 Ollama/Qwen、DeepSeek Provider 框架。
- 专业 Agent：Novel、Character、World、Plot、Chapter、Rewrite、Review、Planner。
- Chapter -> Review -> Rewrite -> Re-review 多轮质量工作流。
- 持久化工作流、独立 Worker、队列策略、DLQ、超时、背压、恢复与运维观测。
- SQLite 长期记忆、Qwen Embedding、FAISS、混合语义检索和一致性修复。
- Novel Project、Story Bible、Novel Plan、Story Arc、Chapter Plan 五层规划领域。
- Planner 三目标本地 Qwen 结构化候选生成、stale gate、fixed coordinates、Pydantic 强校验。
- target-aware compact context 和确定性 context budget；真实三阶段 Qwen 验收通过。
- Canonical Entity Registry、稳定 entity_id、确定性 Alias Resolver 和歧义候选返回。
- Story Bible 显式实体对齐、规划引用校验和 3600 字符 P0 Canon Context。

下一开发项：

```text
Sprint 08B.1 - Chapter Plan -> Chapter Workflow Bridge
状态：待开发
```

## 3. 交付路线

| 阶段 | 目标 | 状态 | 完成定义 |
| --- | --- | --- | --- |
| 08A.6 | Planner 候选审核与显式接受 | 已完成 | 生成不落库；接受独立触发；revision、stale、坐标和领域校验全部通过 |
| 08A.7 | Canonical Entity Foundation | 已完成 | 稳定 entity_id、Entity Registry、确定性 Alias Resolver、歧义不猜测和重启持久化通过 |
| 08A.8 | Story Bible Entity Alignment + Canon Context | 已完成 | 旧 Bible 兼容绑定实体；Planner/Writer 引用可校验；Canon Context 有优先级和预算 |
| 08B.1 | Chapter Plan -> Chapter Workflow 桥接 | 待开发 | Workflow 必须绑定 fresh Chapter Plan，并自动形成 grounded Chapter Agent 输入 |
| 08B.2 | Manuscript / Chapter Draft / Revision 领域 | 待开发 | 正文拥有稳定 ID、版本历史、审核状态、来源规划 revision 和恢复能力 |
| 08B.3 | 全小说 Orchestrator | 待开发 | 可按 Arc/Chapter 顺序持续生成，支持暂停、恢复、失败重试和人工门禁 |
| 08C.1 | 三层 Memory | 待开发 | Session、Working、Long-term 的职责、生命周期和提升/淘汰规则独立可验收 |
| 08C.2 | 外部知识库 | 待开发 | 小说内容库与外部知识库物理/逻辑隔离，引用来源可追踪 |
| 08C.3 | 双路并行检索 | 待开发 | Temporal/Graph 与 Vector RAG 并行，结果融合、去重、预算和降级可测 |
| 08D.1 | Temporal Graph 基础 | 待开发 | 角色、地点、事件、关系、时间有效区间与来源 revision 可持久化 |
| 08D.2 | Consistency Engine | 待开发 | 写作前约束、写作后事实抽取、冲突检测、审核修复形成闭环 |
| 08D.3 | Graph/Vector 融合与事实回写 | 待开发 | 新正文接受后原子/幂等地更新记忆、向量和图事实 |
| 08E | Vue 创作工作台 | 待开发 | Project/Bible/Plan/Arc/Chapter/Workflow/Review/Manuscript 可视化操作闭环 |
| 09 | Provider、Prompt、鉴权与发布工程 | 待开发 | OpenAI/Claude/DashScope、Prompt 版本、Auth、CI、迁移、备份与导出可验收 |
| 1.0 | 插件化与正式发布 | 待开发 | 插件边界、兼容策略、安装/禁用、升级和完整产品验收完成 |

## 4. 近期关键路径

### Sprint 08A.7 - 稳定实体身份

```text
Novel Project
  -> Entity Registry
  -> canonical entity_id + aliases
  -> deterministic resolution
```

本阶段先解决“这个人物究竟是谁”，不提前实现 Temporal Graph 或自动 Canon 回写。

### Sprint 08A.8 - Canon 上下文

在保持旧 Story Bible 数据兼容的同时，将人物条目与 Registry 对齐，并为 Planner/Writer 建立以下优先级：

```text
P0 Canon / Hard Constraints
P1 Current Scene State
P2 Active Character State
P3 Current Relationships
P4 Relevant Temporal Events
P5 Plot Vector RAG
P6 External Knowledge RAG
```

低优先级检索证据不得覆盖高优先级事实。

当前已完成：

- legacy `id` / `character_id` / `entity_id` 显式对齐。
- 歧义、重复绑定与 ID/名称冲突事务回滚。
- Entity 变更推进 Canon revision，并触发规划 stale。
- Planner 三目标 Canon 引用校验。
- Agent P0 Canon Context 在 Memory/RAG 之前注入。
- 3600 字符确定性预算和 active entity filter。

### Sprint 08A.6 - 显式接受

```text
Planner generate (persisted=false)
  -> 人工/客户端审核和可选编辑
  -> Planner accept
  -> source revision + stale + fixed coordinate 校验
  -> 既有领域服务写入
```

禁止事项：

- `/planner/generate` 自动落库。
- 新增 Planner candidate/run 数据表。
- 绕过 Novel Plan / Story Arc / Chapter Plan 的 Pydantic 和存储约束。
- 接受基于过期 Project、Bible、Plan 或 selected Arc 生成的候选。

### Sprint 08B.1 - 规划到写作桥接

Chapter Workflow 请求将显式引用 `chapter_plan_id` 和 revision。系统加载：

- Project 与 Story Bible 的精简约束。
- fresh Novel Plan、selected Story Arc、selected Chapter Plan。
- 相邻章节摘要与相关长期记忆。
- 明确的 POV、目标、scene beats、continuity dependencies 和字数预算。

08B.1 在 08A.8 完成后启动，避免把自由文本人物名称继续带入新的 Writer 桥接层。

### Sprint 08B.2 - 正文领域

正文不会继续只存在于 Workflow 运行结果中。需要新增正式 Manuscript 领域，区分：

- LLM draft。
- rewrite revision。
- reviewed candidate。
- accepted manuscript revision。

只有 accepted manuscript 才能成为后续章节的权威连续性来源。

## 5. Memory 与 RAG 目标架构

```text
Session Memory
  - 当前交互和临时意图

Working Memory
  - 当前卷、故事弧、章节任务、未解决问题和近期正文

Long-term Memory
  - 已接受的人物、世界、剧情事实

Retrieval
  ├── Vector RAG: 语义相关事实与文本片段
  └── Temporal Graph RAG: 指定时间点有效的关系与事件
          -> fusion / rerank / context budget
```

现有 `character/world/plot/short_term` 是内容分类，不等同于上述三层生命周期模型。08C.1 必须显式解决这一差异。

## 6. 每个 Sprint 的发布门禁

每个 Sprint 在 commit/tag 前必须满足：

1. focused tests 全部通过。
2. full regression 全部通过。
3. `docker-compose ... config --quiet` 通过。
4. `git diff --check` 通过。
5. OpenAPI 与外部端口行为通过。
6. 涉及 LLM 的功能完成真实目标模型验收。
7. 数据持久化、重启恢复、非持久化边界和数据库结构得到实际证明。
8. Sprint 文档与当前实现文档同步。
9. 未通过完整验收前不 commit、不创建版本 tag。

## 7. 非当前关键路径

以下工作有价值，但不能先于“规划 -> 写作 -> 正文 -> 连续性回写”主链：

- 为了框架而引入 LangGraph 或 LangChain。
- 同时铺开所有云 Provider。
- 先做插件市场再完成正文领域。
- 用增大模型上下文代替目标感知上下文和检索预算。

LangGraph 应在 08B.3 Orchestrator 的状态分支、持久恢复和人工门禁确实需要图状态机时引入；不是当前 08A.6 的前置条件。
