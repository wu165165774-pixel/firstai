# Sprint 08A.3：Story Arc Planning

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.14`
- 基线版本：`v0.15.0-alpha.13`
- 阶段：Sprint 08A — Novel Planning Foundation
- 核心目标：建立独立、可排序、可版本化并具备三层来源版本追踪的 Story Arc，为后续 Chapter Plan 提供稳定的中间规划层。

## 2. Story Arc 领域边界

Story Arc 是独立领域实体，不从 Novel Plan 的 `volume_plans` JSON 自动物化。

职责划分：

```text
Volume Plan
    -> 描述整卷的目标、冲突、主要事件和规模

Story Arc
    -> 描述卷内一个可独立演进、修改、排序和引用的故事弧
```

Story Arc 是 Arc 层唯一可编辑真源。

后续 Chapter Plan 将通过：

```text
arc_id
```

稳定引用 Story Arc。

## 3. Story Arc 模型

核心字段：

```text
arc_id
novel_id
volume_number
arc_number
revision

source_project_revision
source_story_bible_revision
source_novel_plan_revision
is_stale

title
objective
summary
opening_state
closing_state
core_conflict
stakes

turning_points
character_progression
plot_threads
dependencies

target_chapter_start
target_chapter_end
metadata

created_at
updated_at
```

## 4. Arc 排序与位置唯一性

一本小说内 Story Arc 固定按：

```text
volume_number ASC
arc_number ASC
```

排序。

位置唯一约束：

```text
UNIQUE(
    novel_id,
    volume_number,
    arc_number
)
```

因此不能同时存在两个：

```text
Volume 1 / Arc 1
```

真实验收：

```text
arc_positions = [(1, 1), (1, 2), (2, 1)]
volume_1_positions = [(1, 1), (1, 2)]

duplicate position -> HTTP 409
move to occupied position -> HTTP 409
```

## 5. 三层 Source Revision

每个 Story Arc revision 固定记录：

```text
source_project_revision
source_story_bible_revision
source_novel_plan_revision
```

Arc 当前是否 stale，由当前：

```text
Novel Project revision
Story Bible revision
Novel Plan revision
```

与 Arc 的三组 source revision 直接比较得出。

真实验收：

```text
Arc rev2
Project 1 / Bible 1 / Plan 2
is_stale = false

Project -> 2
Arc rev2 -> stale

Arc refresh -> rev3
Project 2 / Bible 1 / Plan 2

Story Bible -> 2
Arc rev3 -> stale

Arc refresh -> rev4
Project 2 / Bible 2 / Plan 2

Novel Plan -> 3
Arc rev4 -> stale

Arc refresh -> rev5
Project 2 / Bible 2 / Plan 3
is_stale = false
```

`is_stale` 不递归计算上游对象自身是否 stale；它只比较 Arc 记录的直接 source revisions 与当前 revisions。

## 6. Optimistic Revision

Story Arc 更新支持：

```text
expected_revision
```

过期写入返回：

```text
HTTP 409 Conflict
```

真实验收：

```text
Story Arc revision conflict:
expected=1
actual=2
```

## 7. Story Arc Revision History

新增不可变历史：

```text
story_arc_revisions
```

每次 Arc 更新：

```text
revision = revision + 1
```

并保存完整 snapshot。

真实验收：

```text
arc_revision_numbers = [5, 4, 3, 2, 1]
IMMUTABLE ARC HISTORY: PASS
```

历史 source revisions：

```text
rev1 -> Project 1 / Bible 1 / Plan 2
rev2 -> Project 1 / Bible 1 / Plan 2
rev3 -> Project 2 / Bible 1 / Plan 2
rev4 -> Project 2 / Bible 2 / Plan 2
rev5 -> Project 2 / Bible 2 / Plan 3
```

## 8. 结构化 Arc 内容

Turning Point 支持：

```text
turning_point_id
order
title
description
consequence
character_ids
```

Character Progression 支持：

```text
character_id
character_name
start_state
change
end_state
key_moments
```

同时支持：

```text
plot_threads
dependencies
target_chapter_start
target_chapter_end
```

真实验收主 Arc：

```text
2 Turning Points
1 Character Progression
target chapters = 1 -> 10
```

## 9. 数据库

继续使用：

```text
/app/data/novels.db
```

新增：

```text
story_arcs
story_arc_revisions
```

索引：

```text
idx_story_arcs_order
idx_story_arcs_volume
idx_story_arc_revisions_time
```

Story Arc 不写入：

```text
workflow_runs.db
```

真实验收：

```text
STORY ARC SQLITE PERSISTENCE: PASS
STORY ARC DOMAIN ISOLATION: PASS
```

迁移只创建 Arc 表和索引，不为已有 Novel 自动生成虚假 Arc。

## 10. REST API

新增：

```text
POST /api/v1/novels/{novel_id}/arcs
GET  /api/v1/novels/{novel_id}/arcs

GET  /api/v1/novels/{novel_id}/arcs/{arc_id}
PUT  /api/v1/novels/{novel_id}/arcs/{arc_id}

GET  /api/v1/novels/{novel_id}/arcs/{arc_id}/revisions
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}/revisions/{revision}
```

列表支持：

```text
volume_number
limit
offset
```

OpenAPI 中：

```text
is_stale
```

是默认值为 `false` 的响应属性，不属于客户端 required 输入字段。

## 11. 真实验收

验收 Novel：

```text
novel_id = 81fcd68d-f468-4dfc-a70d-bdae7476df9e
```

主 Arc：

```text
arc_id = 6802bfb2-8e4d-42d9-85e7-8cd24e83cf47
```

最终状态：

```text
Project revision = 2
Story Bible revision = 2
Novel Plan revision = 3

Story Arc revision = 5

source_project_revision = 2
source_story_bible_revision = 2
source_novel_plan_revision = 3
is_stale = false

Arc positions:
[(1, 1), (1, 2), (2, 1)]

Arc revisions:
[5, 4, 3, 2, 1]
```

验收结果：

```text
STORY ARC OPENAPI LIVE: PASS
NOVEL + PLAN SEED: PASS
STORY ARC CREATE + SOURCE CAPTURE: PASS
ARC SORT + VOLUME FILTER: PASS
ARC POSITION CONFLICT: PASS
ARC REVISION + CONFLICT: PASS
PROJECT -> ARC STALE: PASS
PROJECT SOURCE REFRESH: PASS
STORY BIBLE -> ARC STALE: PASS
STORY BIBLE SOURCE REFRESH: PASS
NOVEL PLAN -> ARC STALE: PASS
THREE-SOURCE ARC REFRESH: PASS
IMMUTABLE ARC HISTORY: PASS
STORY ARC SQLITE PERSISTENCE: PASS
STORY ARC DOMAIN ISOLATION: PASS
STORY ARC LIVE ACCEPTANCE: PASS
STORY ARC RESTART PERSISTENCE: PASS
GIT DIFF CHECK: PASS
```

验收文件：

```text
data/sprint08a3_acceptance.json
```

## 12. 自动化测试

新增：

```text
backend/tests/test_story_arc.py
```

新增 18 条测试。

全量：

```text
Ran 186 tests
OK
```

## 13. 主要文件

```text
backend/app/api/v1/novels.py
backend/app/novels/schemas.py
backend/app/novels/service.py
backend/app/novels/storage.py
backend/tests/test_story_arc.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint08A3.md
```

## 14. 下一步

Sprint 08A.4：

```text
Chapter Planning Foundation
```

重点建立：

```text
Chapter Plan
Chapter Plan revision
Chapter order
Story Arc binding
Chapter objective
POV
scene beats
conflict / reveal / hook
continuity dependencies
target word count

source Project revision
source Story Bible revision
source Novel Plan revision
source Story Arc revision
stale tracking
```

Chapter Plan 将通过 `arc_id` 绑定 Story Arc，并继续沿用 08A 系列的 immutable revision、optimistic concurrency 与 source revision 语义。
