# Sprint 08A.8 - Story Bible Entity Alignment + Canon Context

## 状态

```text
已完成
发布版本：v0.15.0-alpha.19
基线版本：v0.15.0-alpha.18
```

## 目标

在稳定 Entity Registry 之上完成 P0.2：让旧 Story Bible 人物显式绑定 `entity_id`，并让 Planner 与通用 Agent 使用有优先级、有预算的 Canon Context。

```text
Legacy Story Bible characters
  -> explicit alignment action
  -> canonical entity_id
  -> planning reference validation
  -> P0 Canon Context
  -> lower-priority Memory/RAG evidence
```

## Story Bible 显式对齐

新增 API：

```text
POST /api/v1/novels/{novel_id}/story-bible/entities/align
```

请求必须携带 `expected_revision`，并可用 `create_missing` 控制是否为未绑定人物创建实体。

兼容识别：

```text
entity_id
character_id
id
```

名称兼容识别 `canonical_name` 与 `name`。对齐行为：

- 已存在 ID：校验实体类型及 ID/名称一致性。
- 无 ID：使用确定性 Alias Resolver 解析。
- 无匹配且 `create_missing=true`：创建 character entity。
- 同级多候选、重复绑定、ID/名称冲突：HTTP 409，整个事务回滚。
- 成功后只增量写入 `entity_id`，保留原有自由结构字段。
- 第二次对齐没有变化时不增加 revision。

## Canon revision

Entity create/update 现在推进 Story Bible revision。该 revision 作为当前规划链的 Canon 变更门禁，因此人物正式名称、别名或描述变化会使旧 Novel Plan/Arc/Chapter 正确进入 stale 状态。

## Planning reference validation

当某一实体类型已经进入 Registry 后，以下字段必须引用存在且类型正确的实体：

```text
Novel Plan:
  main_plot.character_ids
  character_arcs.character_id + character_name

Story Arc:
  turning_points.character_ids
  character_progression.character_id + character_name

Chapter Plan:
  pov_character_id + pov_character_name
  scene_beats.character_ids
  scene_beats.location_id
```

未迁移的实体类型继续使用 legacy 兼容模式；但一个已知 ID 被当成错误类型时始终拒绝。

Planner generation 在 Pydantic candidate 校验和 fixed coordinates 后执行 Canon 引用校验。模型返回未知 ID 时 generation 返回 output error；客户端编辑 candidate 写入未知 ID 时 acceptance 返回 HTTP 409。

## Canon Context Builder

新增 `CanonContextBuilder`：

- P0 `[CANON FACTS - MUST NOT VIOLATE]` system message。
- 最大 3600 字符确定性预算。
- 支持 active entity IDs 和 POV entity。
- 包含 project constraints、style、world rules、themes 和 canonical entity profiles。
- 人物 `secret` 不进入当前 Canon profile，避免在 Knowledge Scope 完成前扩大泄露面。
- Canon message 位于 Memory/RAG message 之前。
- Memory 明确降级为 retrieval evidence，不得覆盖 Canon。

Planner 已在自己的 3600 字符 target-aware context 内携带 compact canonical entities，并关闭通用 Agent 的二次 Canon 注入，避免重复 Prompt。

## 自动化验证

```text
Canon/Alignment focused tests: 22/22 PASS
Planner focused tests: 35/35 PASS
Entity Registry focused tests: 15/15 PASS
Full regression: 278/278 PASS
Python compileall: PASS
Docker Compose config: PASS
git diff --check: PASS
```

## 真实 qwen3:8b 验收

验收实体：

```text
novel_id = 225ef127-d966-47d5-893f-e32512e6cea7
entity_ids = char_su_lan, char_luo_zhou
arc_id = 5205adfa-c3b1-4755-b3cf-2f6a38e0123a
chapter_plan_id = 86e4f2c9-ad1a-4a6c-bae4-f4b29e8fa156
```

真实结果：

```text
Novel Plan:
prompt_tokens = 1412
completion_tokens = 2171
planner_context_chars = 1593

Story Arc:
prompt_tokens = 1607
completion_tokens = 1649
planner_context_chars = 2193

Chapter Plan:
prompt_tokens = 1691
completion_tokens = 1529
planner_context_chars = 2518
```

三阶段结果：

- candidate response 全部 `persisted=false`。
- 全部人物引用只使用 Registry 中的两个 ID。
- `canonical_references_validated=true`。
- 无效 `char_missing` candidate acceptance 返回 HTTP 409，Plan revision 保持不变。
- 有效 candidate 通过显式 acceptance 进入既有领域表。
- Ollama `n_ctx=4096`，三次 `truncated=0`。
- Backend 重启后 Bible bindings、Entity、Plan、Arc、Chapter 全部恢复。
- Planner 数据库表仍为 `[]`。

验收记录：

```text
data/sprint08a8_acceptance.json
```

## 后续

下一项为 Sprint 08B.1 / P0.3 Workflow Grounding：Chapter Workflow 显式绑定 fresh Chapter Plan，并从 Chapter Plan 自动形成 active entities、POV 和 grounded Chapter Agent 输入。
