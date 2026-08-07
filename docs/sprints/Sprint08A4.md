# Sprint 08A.4：Chapter Planning Foundation

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.15`
- 基线版本：`v0.15.0-alpha.14`
- 阶段：Sprint 08A — Novel Planning Foundation
- 核心目标：建立独立、结构化、可版本化并具备四层来源版本追踪的 Chapter Plan，为后续 Planner Agent、Writer Agent 与 Chapter Production Workflow 提供稳定章节规划输入。

## 2. Chapter Plan 领域边界

Chapter Plan 是独立领域实体，通过：

```text
arc_id
```

绑定 Story Arc。

全书章节顺序由：

```text
chapter_number
```

唯一确定。

一本小说中：

```text
UNIQUE(
    novel_id,
    chapter_number
)
```

因此不能同时存在两个相同章节号。

## 3. Chapter Plan 模型

核心字段：

```text
chapter_plan_id
novel_id
arc_id

volume_number
arc_number
chapter_number

revision

source_project_revision
source_story_bible_revision
source_novel_plan_revision
source_story_arc_revision

is_stale

title
objective
summary

pov_character_id
pov_character_name

opening_state
closing_state

conflict
reveal
hook

scene_beats
continuity_dependencies

target_word_count
metadata

created_at
updated_at
```

其中 `volume_number` / `arc_number` 是通过当前 Story Arc JOIN 派生的响应字段，不在 `chapter_plans` 中冗余存储。

## 4. Scene Beats

Chapter Plan 支持结构化 Scene Beat：

```text
beat_id
order
title
summary
purpose
character_ids
location_id
metadata
```

真实验收主 Chapter：

```text
3 Scene Beats
```

这为 Writer Agent 后续按场景生成正文提供稳定粒度。

## 5. 四层 Source Revision

每个 Chapter Plan revision 固定记录：

```text
source_project_revision
source_story_bible_revision
source_novel_plan_revision
source_story_arc_revision
```

Chapter Plan 当前是否 stale，由当前：

```text
Novel Project revision
Story Bible revision
Novel Plan revision
Story Arc revision
```

与 Chapter Plan 的四组 source revision 直接比较得出。

真实验收最终：

```text
Project revision = 2
Story Bible revision = 2
Novel Plan revision = 5
Story Arc revision = 5

Chapter Plan revision = 6

source_project_revision = 2
source_story_bible_revision = 2
source_novel_plan_revision = 5
source_story_arc_revision = 5

is_stale = false
```

## 6. 上游链式刷新

真实验收分别验证：

```text
Project change
    -> Chapter stale
    -> refresh Novel Plan
    -> refresh Story Arc
    -> refresh Chapter Plan

Story Bible change
    -> Chapter stale
    -> refresh Novel Plan
    -> refresh Story Arc
    -> refresh Chapter Plan

Novel Plan change
    -> Chapter stale
    -> refresh Story Arc
    -> refresh Chapter Plan

Story Arc change
    -> Chapter stale
    -> refresh Chapter Plan
```

最终整条：

```text
Project
  -> Story Bible
  -> Novel Plan
  -> Story Arc
  -> Chapter Plan
```

依赖链处于一致状态。

## 7. Optimistic Revision

Chapter Plan 更新支持：

```text
expected_revision
```

过期写入返回：

```text
HTTP 409 Conflict
```

真实验收：

```text
Chapter Plan revision conflict:
expected=1
actual=2
```

## 8. Chapter Number Conflict

重复章节号：

```text
POST Chapter 1
已有 Chapter 1
-> HTTP 409
```

把另一个章节移动到已占用章节号：

```text
PUT Chapter 2 -> Chapter 1
-> HTTP 409
```

真实验收：

```text
duplicate_chapter_status = 409
move_chapter_status = 409
```

## 9. Arc Rebind

Chapter Plan 可以重新绑定 Story Arc。

真实验收：

```text
原：
Volume 1 / Arc 1 / Chapter 2

重新绑定：
Volume 2 / Arc 1 / Chapter 32
```

重新绑定后：

```text
arc_id
volume_number
arc_number
chapter_number
source_story_arc_revision
```

全部同步到目标 Arc 当前状态。

最终章节顺序：

```text
[1, 31, 32]
```

Volume 2：

```text
[31, 32]
```

## 10. Chapter Plan Revision History

新增不可变历史：

```text
chapter_plan_revisions
```

真实验收：

```text
chapter_revision_numbers =
[6, 5, 4, 3, 2, 1]
```

主 Chapter source revision 历史：

```text
rev1 -> P1 / B1 / Plan2 / Arc1
rev2 -> P1 / B1 / Plan2 / Arc1
rev3 -> P2 / B1 / Plan3 / Arc2
rev4 -> P2 / B2 / Plan4 / Arc3
rev5 -> P2 / B2 / Plan5 / Arc4
rev6 -> P2 / B2 / Plan5 / Arc5
```

历史 snapshot 不会被后续上游修改反向改写。

## 11. 数据库

继续使用：

```text
/app/data/novels.db
```

新增：

```text
chapter_plans
chapter_plan_revisions
```

索引：

```text
idx_chapter_plans_order
idx_chapter_plans_arc
idx_chapter_plan_revisions_time
```

`chapter_plans` 物理表保存：

```text
chapter_plan_id
novel_id
arc_id
chapter_number
revision
source_project_revision
source_story_bible_revision
source_novel_plan_revision
source_story_arc_revision
...
```

不冗余保存：

```text
volume_number
arc_number
```

这两个字段从 Story Arc 派生。

Chapter Plan 不写入：

```text
workflow_runs.db
```

真实验收：

```text
CHAPTER PLAN SQLITE PERSISTENCE: PASS
CHAPTER PLAN DOMAIN ISOLATION: PASS
```

## 12. REST API

新增：

```text
POST /api/v1/novels/{novel_id}/chapter-plans
GET  /api/v1/novels/{novel_id}/chapter-plans

GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}
PUT  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}

GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}/revisions
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}/revisions/{revision}
```

列表支持：

```text
arc_id
volume_number
limit
offset
```

固定按照：

```text
chapter_number ASC
```

排序。

## 13. 真实验收

验收 Novel：

```text
novel_id = 9e219fcb-a6cd-45d7-aaa3-aef13183a0e0
```

主 Story Arc：

```text
arc_id = 41ab5f96-2e85-4661-b8b7-495e04190045
```

主 Chapter Plan：

```text
chapter_plan_id = 981a77a1-b98a-4469-97a0-90b6f4125f8d
```

最终：

```text
Project revision = 2
Story Bible revision = 2
Novel Plan revision = 5
Story Arc revision = 5
Chapter Plan revision = 6

Chapter source:
Project = 2
Bible = 2
Plan = 5
Arc = 5

is_stale = false

Chapter numbers:
[1, 31, 32]

Chapter revisions:
[6, 5, 4, 3, 2, 1]
```

验收结果：

```text
CHAPTER PLAN OPENAPI LIVE: PASS
NOVEL + PLAN + ARC SEED: PASS
STRUCTURED CHAPTER PLAN: PASS
CHAPTER ORDER + FILTERS: PASS
CHAPTER NUMBER CONFLICT: PASS
CHAPTER ARC REBIND: PASS
CHAPTER REVISION + CONFLICT: PASS
PROJECT -> CHAPTER STALE: PASS
PROJECT CHAIN REFRESH: PASS
STORY BIBLE -> CHAPTER STALE: PASS
STORY BIBLE CHAIN REFRESH: PASS
NOVEL PLAN -> CHAPTER STALE: PASS
NOVEL PLAN CHAIN REFRESH: PASS
STORY ARC -> CHAPTER STALE: PASS
FOUR-SOURCE CHAPTER REFRESH: PASS
IMMUTABLE CHAPTER HISTORY: PASS
FINAL CHAPTER LIST + REBIND: PASS
CHAPTER PLAN SQLITE PERSISTENCE: PASS
CHAPTER PLAN DOMAIN ISOLATION: PASS
CHAPTER PLAN LIVE ACCEPTANCE: PASS
CHAPTER PLAN RESTART PERSISTENCE: PASS
GIT DIFF CHECK: PASS
```

验收文件：

```text
data/sprint08a4_acceptance.json
```

## 14. 自动化测试

新增：

```text
backend/tests/test_chapter_plan.py
```

新增 20 条测试。

全量：

```text
Ran 206 tests
OK
```

## 15. 主要文件

```text
backend/app/api/v1/novels.py
backend/app/novels/schemas.py
backend/app/novels/service.py
backend/app/novels/storage.py
backend/tests/test_chapter_plan.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint08A4.md
```

## 16. 下一步

Sprint 08A.5：

```text
Planner Agent + Local Qwen Planning
```

目标是在已经稳定的：

```text
Novel Project
Story Bible
Novel Plan
Story Arc
Chapter Plan
```

领域层之上接入本地 `qwen3:8b`。

LLM 只负责生成候选规划内容；revision、stale、并发控制、持久化和历史仍由后端领域层负责。
