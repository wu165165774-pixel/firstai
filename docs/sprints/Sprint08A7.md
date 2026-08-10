# Sprint 08A.7 - Canonical Entity Foundation

## 状态

```text
已完成
发布版本：v0.15.0-alpha.18
基线版本：v0.15.0-alpha.17
```

## 目标

在不重写现有 Story Bible、Planner、Workflow、Memory 或 RAG 的前提下，建立长篇小说一致性所需的稳定实体身份基础：

```text
Novel Project
  -> Entity Registry
  -> Canonical entity_id
  -> deterministic Alias Resolver
```

## 数据模型

新增兼容表：

```text
novel_entities
novel_entity_aliases
```

实体主键为 `(novel_id, entity_id)`。`entity_id` 在小说内稳定且更新时不可变；相同 ID 可在不同小说中独立存在。

支持类型：

```text
character
organization
location
item
creature
concept
```

第一阶段重点是 `character`。

## API

```text
POST  /api/v1/novels/{novel_id}/entities
GET   /api/v1/novels/{novel_id}/entities
GET   /api/v1/novels/{novel_id}/entities/{entity_id}
PATCH /api/v1/novels/{novel_id}/entities/{entity_id}
POST  /api/v1/novels/{novel_id}/entities/resolve
```

## Alias Resolver

固定解析优先级：

```text
1. exact canonical name
2. exact alias
3. normalized canonical name
4. normalized alias
```

规范化使用空白清理、Unicode NFKC 和 casefold。若同一优先级命中多个实体，返回：

```text
status = ambiguous
entity = null
candidates = [...]
```

Resolver 不使用向量相似度，也不会盲选第一个候选。

## 并发与兼容边界

- 实体更新支持 `expected_revision` 乐观并发。
- 实体 ID 不可通过 update 修改。
- 新表由现有 SQLite 初始化流程增量创建，不删除或重写旧表。
- Story Bible 的自由结构 `characters` 本 Sprint 保持兼容。
- 不改变任何已发布规划 API。
- 不改变 Planner candidate-only、stale gate、fixed coordinates 或 Pydantic 最终校验。
- 不接管 Memory/FAISS 的事实权威。

## 测试范围

- 表结构与存储重启。
- 自动 ID 与显式 ID。
- 小说间 ID 隔离。
- 名称/别名清洗和去重。
- 四级固定解析优先级。
- 同名/同别名歧义不猜测。
- entity type 辅助消歧。
- revision 和 ID 冲突。
- alias 更新后索引原子重建。
- API、HTTP 409 和 OpenAPI 路由。

自动化验证：

```text
Entity Registry focused tests: 15/15 PASS
Novel Project focused tests: 15/15 PASS
Novel Planner focused tests: 17/17 PASS
Planner Agent focused tests: 33/33 PASS
Full regression: 254/254 PASS
Python compileall: PASS
Docker Compose config: PASS
git diff --check: PASS
```

## 真实服务验收

验收实体：

```text
novel_id = ed4b374c-79e5-481b-a5fa-42a18f215932
entity_ids = char_lin_xue, char_su_xue
```

实际结果：

```text
OpenAPI version = 0.15.0-alpha.18
exact canonical -> resolved
Unicode NFKC/casefold alias -> resolved
shared alias -> ambiguous, 2 candidates, no guessed entity
entity ID after update -> unchanged
entity revision after update -> 2
stale expected_revision -> HTTP 409
removed alias after update -> not_found
Backend restart persistence -> PASS
entity rows after restart -> 2
existing Novel Plan revision before/after -> 1 / 1
Planner database tables -> []
```

验收记录：

```text
data/sprint08a7_acceptance.json
```

## 后续

Sprint 08A.8 将进行 Story Bible Entity Alignment 和 Canon Context Builder：让 Planner/Writer 的人物引用绑定 Registry，并明确 Canon > Current State > Memory/RAG 的上下文优先级。
