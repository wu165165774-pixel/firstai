# Sprint 08E.2 - 规划编辑与 Planner 候选审核

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.30
基线版本：v0.15.0-alpha.29
```

## 目标与边界

08E.2 补齐浏览器中的规划写入闭环，同时严格复用已经发布的领域 API：

```text
Story Bible manual edit -> PUT with expected_revision
Novel Plan manual edit  -> PUT with expected_revision
Story Arc create/edit    -> POST or stable arc_id PUT
Chapter Plan create/edit -> POST or stable chapter_plan_id PUT

Planner generate -> validated candidate, persisted=false
Planner review   -> editable candidate JSON
Planner accept   -> explicit /planner/accept, persisted=true

fresh Chapter Plan -> async Workflow queue
```

- 不新增 Planner persistence table。
- 不在 `/planner/generate` 后自动保存。
- Story Arc 和 Chapter Plan 的生成坐标保持固定；即使审核人修改 candidate JSON，accept 请求仍携带原始生成坐标，让后端检测坐标篡改。
- 所有更新携带当前 optimistic revision；HTTP 409 原样反馈，不静默覆盖其他编辑者的 revision。
- Story Arc 接受后使用稳定 `arc_id`；Chapter Plan 继续只保存 `arc_id`，卷号/弧号由后端 JOIN 派生。
- 单章 Workflow 绑定精确、fresh 的 `chapter_plan_id + revision`，并使用异步队列而非浏览器同步长连接。

## 工作台能力

- 四个规划域在同一 Planning Studio 中切换，展示 revision 与 stale 状态。
- 常用叙事字段使用表单；嵌套 beats、角色推进、分卷与 metadata 使用带结构校验的 JSON 编辑区。
- 支持新建 Story Arc / Chapter Plan 和编辑既有稳定实体。
- Planner 使用本地 `qwen3:8b`、medium reasoning；候选区展示 `persisted=false`、token、latency 与 compact context 信息。
- 接受前允许人工修改候选，但 source revisions 与原始 fixed coordinates 不可被 UI 绕过。
- 章节生产页新增单章 Workflow 表单，包含 fresh Chapter Plan、指令、Provider/Model、质量阈值、修订轮数、自动 Rewrite 与队列优先级。

## 前端验证

```text
14/14 frontend pure/API tests passed
App.vue + PlanningStudio.vue SFC compile passed
Vue bundle verification passed (375344 bytes)
CSS parse passed (255 top-level rules)
Docker/Vite build passed: 14 modules
Production assets: JS 116.96 KB, CSS 24.50 KB
18081 root + Nginx API proxy passed
```

## 真实 Qwen/API 验收

保留独立验收项目：

```text
user_id = acceptance-08e2-6c744aa142
novel_id = 85c4dff6-7530-459f-a3f7-1eaf34fc5c76
marker = 6c744aa142
```

- Story Bible 通过正式 PUT 从 r1 更新为 r2。
- Novel Plan：候选 `persisted=false`，2499 tokens、约 21.0 秒、compact context 977 chars；显式接受后为 fresh r2。
- Story Arc：固定 V1/A1，候选 `persisted=false`，2565 tokens、约 11.9 秒；接受后创建稳定 Arc r1。
- Chapter Plan：固定上述 `arc_id` 与 chapter 1，候选 `persisted=false`，3502 tokens、约 19.3 秒；接受后创建 Chapter Plan r1。
- Arc 通过 PUT 更新到 r2 后 Chapter 正确变 stale；Chapter 通过 PUT 更新到 r2 后恢复 fresh，并记录 `source_story_arc_revision=2`。
- 单章 Workflow 首次提交返回 queued；相同 idempotency key 再次提交返回同一 Run 且 `deduplicated=true`。
- 该 Run 最终为 `execution_status=resumable`、`workflow_status=review_parse_failed`，正文长度 1287、修订 1 轮、总计 15386 tokens；队列、精确 Chapter Plan revision 绑定和幂等提交得到验证，但这次真实模型产物没有通过 Review 解析，也没有自动 import/accept。

验收记录保存在 `data/sprint08e2_acceptance.json`；既有数据库和验收项目均保留。

## 发布前验证

```text
14/14 frontend pure/API tests passed
Vue bundle verification passed (375344 bytes)
App.vue + PlanningStudio.vue SFC compile passed
CSS parse passed (255 top-level rules)
Docker/Vite production build passed: 14 modules
Production assets: JS 116.96 KB, CSS 24.50 KB
434/434 backend full regression passed in 193.326s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

## 后续

Sprint 09：Provider 配置、鉴权、多用户安全边界、Prompt 版本、CI、数据库迁移、备份与导出。
