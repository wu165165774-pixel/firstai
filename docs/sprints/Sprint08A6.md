# Sprint 08A.6 - Planner Candidate Review + Explicit Acceptance

## 状态

```text
已完成
发布版本：v0.15.0-alpha.17
基线版本：v0.15.0-alpha.16
```

本 Sprint 在 Planner candidate-only 架构上增加显式接受动作。自动化、真实 Qwen、冲突控制、数据库边界和重启持久化均已通过验收。

## 目标

新增 API：

```text
POST /api/v1/novels/{novel_id}/planner/accept
```

完整链路：

```text
POST /planner/generate
  -> validated candidate
  -> persisted=false
  -> 客户端审核或编辑 candidate
  -> POST /planner/accept
  -> accepted domain entity
  -> persisted=true
```

## 架构边界

- `/planner/generate` 继续只生成候选，绝不落库。
- `/planner/accept` 是独立且显式的用户动作。
- 不新增 Planner 数据库表。
- Novel Plan 接受复用既有 revision update。
- Story Arc 和 Chapter Plan 接受复用既有 create 领域写入。
- 所有 candidate 继续由 Pydantic 最终强校验。
- Story Arc 和 Chapter Plan 的固定坐标必须同时匹配请求与 candidate。

## 接受冲突控制

接受请求必须回传生成结果中的 `source_revisions`：

```text
project_revision
story_bible_revision
novel_plan_revision
story_arc_revision (Chapter Plan only)
```

服务在接受前重新加载权威数据并执行：

1. target-specific stale gate。
2. 完整 source revision snapshot 比较。
3. fixed-coordinate 比较。
4. 领域 Pydantic 校验。
5. SQLite 写事务内再次校验 expected source revisions。

任一来源在生成后发生变化，接受返回 HTTP 409，不产生部分写入。

## 当前测试

新增覆盖：

- target 与 candidate 类型不匹配。
- Story Arc / Chapter Plan 坐标不匹配。
- Chapter Plan 缺少 selected Arc revision。
- 三种 candidate 的显式领域持久化。
- Project/Bible/Plan/Arc source revision 变化冲突。
- Story Arc / Chapter Plan stale gate。
- SQLite 写事务内 source race guard。
- Planner acceptance conflict -> HTTP 409。
- Planner 数据库表继续不存在。

自动化验证：

```text
Planner focused tests: 33/33 PASS
Full regression: 239/239 PASS
```

## 真实 Qwen 验收

验收使用新建小说，依次执行：

1. 生成 Novel Plan candidate，证明 `persisted=false`。
2. 通过 `/planner/accept` 接受 Novel Plan，证明 revision 写入。
3. 生成 Story Arc candidate，证明 `persisted=false`。
4. 通过 `/planner/accept` 接受 Story Arc，证明固定坐标和 source revisions。
5. 生成 Chapter Plan candidate，证明 `persisted=false` 且无输入截断。
6. 通过 `/planner/accept` 接受 Chapter Plan，证明 Arc binding 与派生卷/弧坐标。
7. 修改上游数据后，旧 candidate 接受必须返回 HTTP 409。
8. 验证 `/planner/generate` 在整个流程中从未写入领域数据。
9. 验证没有 Planner 数据库表。
10. 重启 Backend，验证接受后的领域数据仍存在。

验收实体：

```text
novel_id = 942f7864-a234-4ebb-bc65-3b80b534f5a0
arc_id = 9e66ff7d-fe53-4bdc-843d-7519600952cc
chapter_plan_id = 46070f4d-fb51-44ca-bce2-bd30a4bcd597
```

真实 `qwen3:8b` 结果：

```text
Novel Plan:
prompt_tokens = 1351
completion_tokens = 2207
planner_context_chars = 1331
persisted = false
accept -> revision 2

Story Arc:
prompt_tokens = 1568
completion_tokens = 1688
planner_context_chars = 1961
persisted = false
accept -> revision 1, coordinates 1/1

Chapter Plan:
prompt_tokens = 1672
completion_tokens = 1445
planner_context_chars = 2298
persisted = false
accept -> revision 1, Arc binding preserved
```

Ollama 运行证据：

```text
runtime n_ctx = 4096
truncated = 0, 0, 0
GPU layers offloaded = 37/37
```

旧 Novel Plan candidate 再次接受：

```text
HTTP 409
expected novel_plan_revision = 1
actual novel_plan_revision = 2
current persisted revision remains 2
```

数据库与重启：

```text
planner tables = []
Novel Plan revision after restart = 2
Story Arc revision after restart = 1
Chapter Plan revision after restart = 1
Chapter -> Arc binding preserved
```

验收文件：

```text
data/sprint08a6_acceptance.json
```

## 发布门禁

```text
focused tests PASS
full regression PASS
Compose config PASS
git diff --check PASS
live OpenAPI PASS
real qwen3:8b three-stage generate/accept PASS
stale candidate acceptance conflict PASS
restart persistence PASS
Planner database non-persistence PASS
```

全部门禁均已通过，发布版本为 `v0.15.0-alpha.17`。
