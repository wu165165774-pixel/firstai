# Sprint 08A.1：Novel Project + Story Bible 数据模型与持久化层

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.12`
- 基线版本：`v0.15.0-alpha.11`
- 阶段：Sprint 08A — Novel Planning Foundation
- 核心目标：建立小说项目与 Story Bible 的稳定领域模型、SQLite 持久化、Revision 历史以及 REST API，为后续 Novel Planner / Agent / RAG / Chapter Workflow 提供统一数据基础。

## 2. Novel Project

新增小说项目领域对象：

```text
novel_id
user_id
title
genre
premise
language
target_word_count
status
style_guide
constraints
metadata
revision
story_bible_revision
created_at
updated_at
```

支持状态：

```text
planning
writing
paused
completed
archived
```

支持：

- 创建 Novel Project
- 查询单个 Project
- 按 user/status 分页查询
- Project partial update
- Project optimistic revision
- Story Bible 当前 revision 同步

## 3. Story Bible

Story Bible 结构：

```text
world
characters
factions
locations
rules
themes
timeline
metadata
```

创建 Novel Project 时自动创建：

```text
Story Bible revision 1
```

因此后续 Planner / Agent / RAG 可以假设 Story Bible 始终存在。

## 4. Story Bible Revision

新增不可变历史：

```text
story_bible_revisions
```

每次 Story Bible 更新：

```text
revision = revision + 1
```

并保存完整 snapshot。

支持：

- 当前 Story Bible 查询
- partial merge update
- revision 列表
- 指定 revision 查询
- 历史 snapshot 不受当前版本修改影响

真实验收：

```text
revision_numbers = [3, 2, 1]
IMMUTABLE BIBLE HISTORY: PASS
```

## 5. Optimistic Revision

Novel Project 与 Story Bible 均支持：

```text
expected_revision
```

过期版本写入返回：

```text
HTTP 409 Conflict
```

真实验收：

```text
Project:
expected=1
actual=2
HTTP 409

Story Bible:
expected=2
actual=3
HTTP 409
```

这为后续 Frontend / Planner Agent / Writer Agent / Background Worker 并发修改提供基础保护。

## 6. 独立领域数据库

新增：

```text
/app/data/novels.db
```

表：

```text
novel_projects
story_bibles
story_bible_revisions
```

Novel 数据不写入：

```text
workflow_runs.db
```

真实验收：

```text
NOVEL SQLITE DOMAIN ISOLATION: PASS
```

这样 Workflow Queue 生命周期、Worker 历史清理、Queue Archive 不会影响 Novel Project / Story Bible。

## 7. REST API

新增：

```text
POST  /api/v1/novels
GET   /api/v1/novels

GET   /api/v1/novels/{novel_id}
PATCH /api/v1/novels/{novel_id}

GET   /api/v1/novels/{novel_id}/story-bible
PUT   /api/v1/novels/{novel_id}/story-bible

GET   /api/v1/novels/{novel_id}/story-bible/revisions
GET   /api/v1/novels/{novel_id}/story-bible/revisions/{revision}
```

## 8. 真实验收数据

验收 Novel：

```text
novel_id = 1bb46fc4-34ec-4aef-b23c-83582e75eae1
```

最终状态：

```text
project_revision = 2
project_status = writing
story_bible_revision = 3
story_bible_revision_count = 3
```

验收结果：

```text
NOVEL OPENAPI LIVE: PASS
PROJECT CREATE + INITIAL BIBLE: PASS
PROJECT REVISION + FILTERS: PASS
STORY BIBLE REVISION 2: PASS
STORY BIBLE PARTIAL MERGE: PASS
STORY BIBLE CONFLICT: PASS
IMMUTABLE BIBLE HISTORY: PASS
PROJECT/BIBLE REVISION SYNC: PASS
NOVEL SQLITE DOMAIN ISOLATION: PASS
NOVEL PROJECT LIVE ACCEPTANCE: PASS
BACKEND RESTART PERSISTENCE: PASS
GIT DIFF CHECK: PASS
```

验收文件：

```text
data/sprint08a1_acceptance.json
```

## 9. 自动化测试

新增：

```text
backend/tests/test_novel_project.py
```

新增 15 条测试。

全量：

```text
Ran 151 tests
OK
```

## 10. 主要文件

```text
backend/app/api/v1/novels.py
backend/app/novels/__init__.py
backend/app/novels/schemas.py
backend/app/novels/service.py
backend/app/novels/storage.py
backend/tests/test_novel_project.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint08A1.md
```

## 11. 下一步

Sprint 08A.2：

```text
Novel Planner 数据模型与规划骨架
```

目标：

```text
Story Premise
Core Conflict
Ending Direction
Character Arcs
Main Plot
Volume Plan
Story Arc
Chapter Planning 基础
```

并让 Planner 直接绑定：

```text
Novel Project
Story Bible revision
```
