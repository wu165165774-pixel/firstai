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
v0.15.0-alpha.28
```

当前已验收、待发布目标：

```text
v0.15.0-alpha.29 — Sprint 08E.1 Vue 创作工作台基础
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
- Chapter Workflow 显式绑定 fresh Chapter Plan，并在同步、恢复和外部 Worker 执行中注入有预算的 P0.3 Grounding。
- 全小说 Orchestrator 按冻结的 Chapter Plan revision 顺序逐章排队，并以 Manuscript 显式接受作为跨章推进门禁。
- Session / Working / Long-term Memory 作为独立生命周期层，具备稳定 revision、提升门、TTL 淘汰、事件审计和分层检索。
- External Knowledge 使用独立 SQLite/FAISS 命名空间、append-only source revisions、作用域隔离和可追踪 citation，并作为 P6 证据接入 Agent/Chat。
- Vector/Graph 检索通过可插拔双 lane 并行执行、RRF 融合、内容去重和确定性字符预算接入 Agent/Chat；Graph Provider 缺失时显式降级，不伪造图事实。
- Temporal Graph 使用独立 SQLite 权威库持久化事件、关系、章节有效区间和不可变来源 revision，并通过真实 Graph Provider 接入双路检索。
- Consistency Engine 从 Project/Bible/Canon/Temporal Graph 构建有预算的写作前约束，使用 Qwen 抽取候选事实，再以确定性规则阻断身份、关系、生死、地点、时间线、证据和知识范围冲突。
- Chapter Workflow 已形成约束注入、Review 候选事实、确定性冲突、Rewrite 修复和 Re-review 复检闭环；候选事实保持不写回。
- Approved Workflow 候选事实随 Manuscript revision 冻结，只有显式接受才在同一事务写入 outbox；Memory、FAISS 与 Temporal Graph 通过稳定 ID、逐 sink checkpoint、retry、启动恢复和旧 revision 撤回实现可审计的最终一致回写。

下一开发项：

```text
Sprint 08E.2 - 规划编辑与 Planner 候选审核
状态：待开发
```

## 3. 交付路线

| 阶段 | 目标 | 状态 | 完成定义 |
| --- | --- | --- | --- |
| 08A.6 | Planner 候选审核与显式接受 | 已完成 | 生成不落库；接受独立触发；revision、stale、坐标和领域校验全部通过 |
| 08A.7 | Canonical Entity Foundation | 已完成 | 稳定 entity_id、Entity Registry、确定性 Alias Resolver、歧义不猜测和重启持久化通过 |
| 08A.8 | Story Bible Entity Alignment + Canon Context | 已完成 | 旧 Bible 兼容绑定实体；Planner/Writer 引用可校验；Canon Context 有优先级和预算 |
| 08B.1 | Chapter Plan -> Chapter Workflow 桥接 | 已完成 | Workflow 必须绑定 fresh Chapter Plan，并自动形成 grounded Chapter Agent 输入 |
| 08B.2 | Manuscript / Chapter Draft / Revision 领域 | 已完成 | 正文拥有稳定 ID、版本历史、审核状态、来源规划 revision 和恢复能力 |
| 08B.3 | 全小说 Orchestrator | 已完成 | 按冻结 Chapter Plan 顺序逐章驱动 Workflow；暂停、恢复、重试、幂等和 Manuscript 人工门禁可恢复、可审计 |
| 08C.1 | 三层 Memory | 已完成 | 内容类型与生命周期正交；Session/Working/Long-term 的作用域、TTL、提升门、淘汰、索引和事件可独立验收 |
| 08C.2 | 外部知识库 | 已完成 | 小说内容库与外部知识库物理/逻辑隔离，引用来源可追踪 |
| 08C.3 | 双路并行检索 | 已完成 | Temporal/Graph 与 Vector RAG 并行，结果融合、去重、预算和降级可测 |
| 08D.1 | Temporal Graph 基础 | 已完成 | 角色、地点、事件、关系、时间有效区间与来源 revision 可持久化 |
| 08D.2 | Consistency Engine | 已完成 | 写作前约束、写作后事实抽取、冲突检测、审核修复形成闭环 |
| 08D.3 | Graph/Vector 融合与事实回写 | 已完成 | 新正文接受后原子入队，并幂等、可恢复地更新记忆、向量和图事实 |
| 08E.1 | Vue 创作工作台基础 | 已完成，待发布 | Project 总览、生产运行、正文审核/接受、事实投影与 Compose/Nginx 运行闭环 |
| 08E.2 | 规划编辑与候选审核 | 待开发 | Bible/Plan/Arc/Chapter 编辑、Planner candidate 审核接受和 Workflow 创建表单 |
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

当前已完成：

- 新 Workflow HTTP 请求强制携带 `chapter_plan_id` 和 `chapter_plan_revision`。
- 在任何 Agent 调用前校验 Project、Bible、Novel Plan、selected Arc 和 selected Chapter Plan freshness。
- 3600 字符确定性 P0.3 Grounding 包含 selected Chapter Plan、Arc、总体规划摘要、活跃实体和相邻章节摘要。
- Chapter、Review、Rewrite 全阶段共享同一权威规划上下文，且位于 Memory/RAG 证据之前。
- 持久化 Run、resume、异步队列和外部 Worker 保存并重新验证相同绑定。
- 入队后规划变 stale 的 Job 在生成前进入 dead-letter。
- Review 输出以 `finish_reason=length` 截断时使用无推理回退重试。

### Sprint 08B.2 - 正文领域

正文不会继续只存在于 Workflow 运行结果中。需要新增正式 Manuscript 领域，区分：

- LLM draft。
- rewrite revision。
- reviewed candidate。
- accepted manuscript revision。

只有 accepted manuscript 才能成为后续章节的权威连续性来源。

当前已完成：

- 每章使用稳定 `manuscript_chapter_id`，正文 revision append-only。
- 只允许导入 succeeded、completed 且 quality-gated 的持久化 Workflow Run。
- 导入为 reviewed candidate，不自动接受；重复 Run 导入幂等。
- 显式接受使用 Manuscript 聚合 revision 乐观并发，并在事务内重验全部规划来源。
- 只有 accepted revision 进入后续 Chapter Workflow Grounding，未接受候选保持隔离。
- Grounding metadata 记录 accepted Manuscript ID/revision，并继续遵守 3600 字符预算。
- 自动化 309 项回归和真实两章 `qwen3:8b` 候选/接受/stale gate 验收通过。

### Sprint 08B.3 - 全小说 Orchestrator

Orchestrator 负责跨章节控制流，不取代 Workflow 或 Manuscript 领域：

```text
frozen Chapter Plan revisions
  -> queue one Chapter Workflow
  -> explicit advance imports reviewed candidate
  -> human accepts through Manuscript API
  -> explicit advance queues the next chapter
```

当前已完成：

- 创建时冻结 Arc/Chapter 选择、章节顺序、Chapter Plan ID/revision 和运行策略。
- 同一时间只排入一个章节；只有精确候选 revision 被显式接受后才推进下一章。
- `advance` 只协调既有 Workflow 与 Manuscript API 边界，不自动接受正文。
- 聚合 revision 乐观并发、append-only 事件、创建幂等、暂停、恢复和失败重试完整持久化。
- 暂停不取消正在运行的昂贵推理，但阻止候选导入和跨章节推进。
- stale Plan 在创建时返回 HTTP 409；入队后的规划 freshness 继续由既有 Workflow Grounding 重验。
- 未引入 LangGraph：当前线性状态机由 SQLite 事务和既有 Queue/DLQ 完整表达，避免增加双重持久化源。
- 自动化 328 项回归和真实外部 Worker 两章 `qwen3:8b` 顺序编排验收通过。

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

`character/world/plot/short_term` 继续表示内容分类；独立 `memory_tier=session/working/long_term` 表示生命周期。08C.1 已显式解决这一差异：

- Session：必须绑定 `session_id`，默认 24 小时 TTL，不进入 FAISS，可按 session close。
- Working：小说作用域，默认 30 天 TTL，进入 FAISS，用于当前卷/弧/章节任务。
- Long-term：跨会话证据，无自动 TTL，进入 FAISS，但仍低于 Canon 与 Chapter Plan Grounding。
- 提升只能相邻执行，保持稳定 memory ID，并以 revision 和 append-only lifecycle event 审计。
- Long-term 不自动淘汰；Working -> Long-term 要求权威 basis、足够 importance，并在来源型提升时保存 `source_reference`。
- 旧记录自动迁移为 Long-term，不改变现有 `memory_type` 或旧 API 默认行为。

08C.3 已完成双路检索执行与融合边界：

- Vector lane 复用现有 Working/Long-term Hybrid Memory；Session 继续按精确 SQLite scope 加载。
- Vector 与 Graph lane 使用独立超时并发执行，单 lane 不可用、失败或超时不会拖垮另一 lane。
- 结果使用确定性 RRF、规范化内容指纹去重、`top_k` 与字符预算，并保留每条来源的 path、ID、rank、score 和 metadata。
- API、Memory Context、Novel Agent、Chat 和专业 Agent 返回显式 lane 诊断与降级状态。
- 08D.1 已将独立 Temporal Graph 权威库接入 Graph Provider；无图数据时 lane 健康返回空集，小说不存在或用户 scope 不匹配时显式降级为 unavailable。

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
