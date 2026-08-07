# Sprint 08A.2：Novel Planner Foundation

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.13`
- 基线版本：`v0.15.0-alpha.12`
- 阶段：Sprint 08A — Novel Planning Foundation
- 核心目标：建立可持久化、可版本化、可检测过期状态的 Novel Plan，为后续 Story Arc / Chapter Plan / Planner Agent 提供统一总体规划基础。

## 2. Novel Plan

Novel Plan 结构包括：

```text
story_premise
core_conflict
central_question
ending_direction
themes
main_plot
character_arcs
volume_plans
metadata
```

核心版本字段：

```text
revision
source_project_revision
source_story_bible_revision
is_stale
created_at
updated_at
```

## 3. Main Plot

总体剧情节点支持结构化保存：

```text
beat_id
order
title
summary
purpose
character_ids
```

真实验收写入 2 个主线 Plot Beat。

## 4. Character Arc

角色弧光支持：

```text
character_id
character_name
role
start_state
desire
need
internal_conflict
external_conflict
midpoint_shift
end_state
key_turning_points
```

真实验收写入 1 个 Character Arc。

## 5. Volume Plan

分卷规划支持：

```text
volume_number
title
purpose
start_state
end_state
core_conflict
climax
target_word_count
major_events
character_focus
```

真实验收写入 1 个 Volume Plan。

## 6. Novel Plan Revision

新增不可变历史：

```text
novel_plan_revisions
```

每次更新 Novel Plan：

```text
revision = revision + 1
```

并保存完整 snapshot。

真实验收：

```text
plan_revision_numbers = [4, 3, 2, 1]
IMMUTABLE PLAN HISTORY: PASS
```

## 7. Optimistic Revision

Novel Plan 更新支持：

```text
expected_revision
```

过期写入：

```text
HTTP 409 Conflict
```

真实验收：

```text
Novel Plan revision conflict:
expected=1
actual=2
```

## 8. Source Revision / Stale Detection

每个 Plan revision 固定记录：

```text
source_project_revision
source_story_bible_revision
```

当前 Plan 是否过期由：

```text
current Project revision
current Story Bible revision
```

与 source revisions 比较得出。

真实验收链：

```text
Plan rev2
source Project = 1
source Bible = 1
is_stale = false

Project -> revision 2
Plan rev2 -> is_stale = true

Plan refresh -> revision 3
source Project = 2
source Bible = 1
is_stale = false

Story Bible -> revision 2
Plan rev3 -> is_stale = true

Plan refresh -> revision 4
source Project = 2
source Bible = 2
is_stale = false
```

这使后续 Agent 可以明确拒绝在过期规划上继续生成内容。

## 9. 自动初始化与迁移

创建 Novel Project 时自动创建：

```text
Novel Plan revision 1
```

已有 Novel Project 在存储层初始化时进行幂等 backfill。

真实数据库 migration：

```text
novel_project_count = 1
novel_plan_count = 1
missing_plan_count = 0
NOVEL PLAN MIGRATION: PASS
```

## 10. 数据库

继续使用：

```text
/app/data/novels.db
```

新增：

```text
novel_plans
novel_plan_revisions
```

索引：

```text
idx_novel_plan_revisions_time
```

Planner 表不会写入：

```text
workflow_runs.db
```

真实验收：

```text
NOVEL PLANNER SQLITE PERSISTENCE: PASS
NOVEL/WORKFLOW DOMAIN ISOLATION: PASS
```

## 11. REST API

新增：

```text
GET /api/v1/novels/{novel_id}/plan
PUT /api/v1/novels/{novel_id}/plan

GET /api/v1/novels/{novel_id}/plan/revisions
GET /api/v1/novels/{novel_id}/plan/revisions/{revision}
```

OpenAPI 中：

```text
is_stale
```

是带默认值 `false` 的响应属性，不属于客户端 required 输入字段。

## 12. 真实验收

验收 Novel：

```text
novel_id = 19fc3345-5af9-40f2-8ac3-06d1c638aeab
```

最终：

```text
Project revision = 2
Story Bible revision = 2
Plan revision = 4

Plan source Project revision = 2
Plan source Story Bible revision = 2
Plan is_stale = false

Plan revisions = [4, 3, 2, 1]
```

验收结果：

```text
NOVEL PLANNER OPENAPI LIVE: PASS
SEEDED NOVEL PLAN: PASS
STRUCTURED NOVEL PLAN: PASS
NOVEL PLAN CONFLICT: PASS
PROJECT STALE DETECTION: PASS
PROJECT STALE REFRESH: PASS
STORY BIBLE STALE DETECTION: PASS
PLAN SOURCE REVISION REFRESH: PASS
IMMUTABLE PLAN HISTORY: PASS
NOVEL PLANNER SQLITE PERSISTENCE: PASS
NOVEL/WORKFLOW DOMAIN ISOLATION: PASS
NOVEL PLANNER LIVE ACCEPTANCE: PASS
NOVEL PLANNER RESTART PERSISTENCE: PASS
GIT DIFF CHECK: PASS
```

验收文件：

```text
data/sprint08a2_acceptance.json
```

## 13. 自动化测试

新增：

```text
backend/tests/test_novel_planner.py
```

新增 17 条测试。

全量：

```text
Ran 168 tests
OK
```

## 14. 主要文件

```text
backend/app/api/v1/novels.py
backend/app/novels/schemas.py
backend/app/novels/service.py
backend/app/novels/storage.py
backend/tests/test_novel_planner.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint08A2.md
```

## 15. 下一步

Sprint 08A.3：

```text
Story Arc Planning
```

重点建立：

```text
Story Arc
Arc revision
Arc -> Volume binding
Arc objectives
Arc conflicts
Arc turning points
Arc character progression
Arc stale/source revision tracking
```

并继续沿用 08A.2 的 source revision 与 stale 语义。
