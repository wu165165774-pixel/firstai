# Sprint 08A.5：Planner Agent + Local Qwen Structured Planning

## 1. 版本信息

- 发布版本：`v0.15.0-alpha.16`
- 基线版本：`v0.15.0-alpha.15`
- 阶段：Sprint 08A — Novel Planning Foundation
- 核心目标：在稳定的 Novel Project、Story Bible、Novel Plan、Story Arc、Chapter Plan 领域链之上，接入本地 `qwen3:8b`，生成经过强校验但不自动持久化的规划候选。

## 2. Planner Candidate-Only 边界

新增端点：

```text
POST /api/v1/novels/{novel_id}/planner/generate
```

端点只负责：

```text
读取权威领域上下文
构造 target-aware prompt
调用本地 Qwen
解析 JSON
执行 Pydantic 最终校验
返回 candidate
```

端点绝不执行：

```text
Novel Plan 持久化
Story Arc 持久化
Chapter Plan 持久化
```

所有响应保持：

```text
persisted = false
```

候选接受继续通过既有领域 API：

```text
PUT  /api/v1/novels/{novel_id}/plan
POST /api/v1/novels/{novel_id}/arcs
POST /api/v1/novels/{novel_id}/chapter-plans
```

## 3. Planner Targets

支持三个目标：

```text
novel_plan
story_arc
chapter_plan
```

默认推理配置：

```text
provider = qwen_local
model = qwen3:8b
reasoning_effort = medium
temperature = 0.2
max_tokens = 2600
```

## 4. Structured Candidate Validation

三个候选分别由以下 Pydantic 模型强校验：

```text
NovelPlanCandidate
StoryArcCandidate
ChapterPlanCandidate
```

模型统一使用：

```text
extra = forbid
```

Planner 输出允许纯 JSON、JSON code fence 或带少量外围文本的 JSON object，但最终必须：

```text
可提取为单个 JSON object
通过目标 Candidate Pydantic schema
不包含未声明字段
```

解析或校验失败返回：

```text
HTTP 502
```

## 5. Stale Gates

Novel Plan candidate 可以在当前 Novel Plan stale 时生成，用于刷新总体规划。

Story Arc candidate 要求：

```text
Novel Plan is_stale = false
```

Chapter Plan candidate 要求：

```text
Novel Plan is_stale = false
selected Story Arc is_stale = false
```

违反 gate 返回：

```text
HTTP 409 Conflict
```

## 6. Fixed Coordinates

Story Arc 的固定坐标：

```text
volume_number
arc_number
```

Chapter Plan 的固定坐标：

```text
arc_id
chapter_number
```

Qwen 返回后由服务层再次检查这些坐标。模型改变固定坐标时，候选会被拒绝。

## 7. Target-Aware Compact Context

Planner 不再对所有目标发送相同的完整领域快照。

Novel Plan context：

```text
compact Project
compact Story Bible
current Novel Plan
```

Story Arc context：

```text
compact Project
compact Story Bible
current Novel Plan
existing Story Arc index/summary
```

Chapter Plan context：

```text
compact Project
compact Story Bible
current Novel Plan
single selected Story Arc
nearby Chapter Plan summaries
```

Chapter target 不会同时携带完整 `story_arcs` collection 和 `selected_story_arc`，也不会携带完整 Chapter Plan collection。

## 8. Deterministic Context Budget

权威上下文硬预算：

```text
CONTEXT_CHAR_BUDGET = 3600
```

压缩过程：

1. 移除 metadata、时间戳和动态 stale 噪声。
2. 优先保留 ID、固定坐标和 source revision。
3. 对文本、列表和字典执行确定性多档压缩。
4. 极端输入仍超限时，按 target context section 分配硬预算。
5. 最终 authoritative context 始终是有效 JSON，且字符数不超过 3600。

回归复现：

```text
修复前：20827 / 3600 chars
修复后： 3600 / 3600 chars
```

## 9. Compact Candidate Schema

发送给 Qwen 的 JSON Schema 会移除 prompt 中的文档噪声：

```text
title
description
default
examples
min/max documentation
```

仍保留生成所需结构：

```text
type
properties
required
items
enum
const
anyOf
```

Schema 压缩只服务于生成；Pydantic 模型继续作为最终权威校验。

## 10. Planner Metadata

候选响应新增可观测 metadata：

```text
planner_context_mode = target_aware_compact
planner_context_chars
planner_prompt_chars
planner_target
candidate_validated
persisted = false
```

响应同时记录：

```text
provider
model
finish_reason
token usage
latency_ms
source revision snapshot
```

## 11. 数据库边界

Sprint 08A.5 不新增 Planner 数据库表。

实际 `novels.db` 验证：

```text
planner_tables = []
planning_tables = [
  chapter_plans,
  novel_plans,
  story_arcs
]
```

Planner candidate 不写入：

```text
novels.db
workflow_runs.db
```

## 12. Real Qwen Context-Truncation Fix

修复前真实 Chapter Plan 请求：

```text
Ollama runtime n_ctx = 4096
input prompt = 4253 tokens
input prompt truncation
HTTP 502
Planner output does not contain a JSON object
```

修复后真实三阶段：

```text
Novel Plan:
prompt_tokens = 1711
completion_tokens = 2063
planner_context_chars = 2131
planner_prompt_chars = 4356

Story Arc:
prompt_tokens = 1961
completion_tokens = 1695
planner_context_chars = 2758
planner_prompt_chars = 4735

Chapter Plan:
prompt_tokens = 2067
completion_tokens = 1460
planner_context_chars = 3104
planner_prompt_chars = 4676
```

Ollama 日志：

```text
n_ctx = 4096
truncated = 0
GPU layers offloaded = 37/37
```

三个 candidate 均为：

```text
provider = qwen_local
model = qwen3:8b
persisted = false
Pydantic candidate validation = PASS
```

## 13. 真实验收

验收 Novel：

```text
novel_id = f4cec24d-93c4-4d60-8bbb-c943aaad1359
```

显式接受的 Story Arc：

```text
arc_id = e9420162-1861-4ae7-a1f3-8a8ac345a99b
```

显式接受的 Chapter Plan：

```text
chapter_plan_id = 46e53250-984c-4a68-a906-d6511f1adf88
```

验收结果：

```text
NOVEL PLAN CANDIDATE: PASS
NOVEL PLAN CANDIDATE NON-PERSISTENCE: PASS
NOVEL PLAN EXPLICIT PERSISTENCE: PASS

STORY ARC CANDIDATE: PASS
STORY ARC FIXED COORDINATES: PASS
STORY ARC CANDIDATE NON-PERSISTENCE: PASS
STORY ARC EXPLICIT PERSISTENCE: PASS

CHAPTER PLAN CANDIDATE: PASS
CHAPTER PLAN FIXED COORDINATES: PASS
CHAPTER PLAN CANDIDATE NON-PERSISTENCE: PASS
CHAPTER PLAN EXPLICIT PERSISTENCE: PASS
OLLAMA INPUT PROMPT TRUNCATION: ABSENT

PLAN STALE -> STORY ARC GENERATION 409: PASS
PLAN STALE -> CHAPTER PLAN GENERATION 409: PASS
SELECTED ARC STALE -> CHAPTER PLAN GENERATION 409: PASS

PLANNER DATABASE NON-PERSISTENCE: PASS
BACKEND RESTART PERSISTENCE: PASS
```

验收文件：

```text
data/sprint08a5_acceptance.json
```

## 14. 自动化测试

Planner focused：

```text
Ran 22 tests
OK
```

全量回归：

```text
Ran 228 tests
OK
```

同时通过：

```text
python compileall
Docker Compose config
git diff --check
```

## 15. 主要文件

```text
backend/app/agents/planner_agent.py
backend/app/api/v1/planner.py
backend/app/planner/bootstrap.py
backend/app/planner/parser.py
backend/app/planner/schemas.py
backend/app/planner/service.py
backend/tests/test_planner_agent.py
backend/app/main.py
docs/CURRENT_IMPLEMENTATION.md
docs/sprints/Sprint08A5.md
```

## 16. 下一步

Sprint 08A.6 可以在 candidate-only 边界上继续建设人工审核与显式接受工作流，或为 Writer Agent 接入已持久化的 Chapter Plan。

Planner 的持久化边界继续保持：

```text
Qwen generates candidates
Pydantic validates candidates
Domain APIs persist accepted plans
```
