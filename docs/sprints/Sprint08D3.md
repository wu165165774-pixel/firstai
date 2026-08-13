# Sprint 08D.3 - Accepted Fact Projection

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.28
基线版本：v0.15.0-alpha.27
```

## 目标与边界

本 Sprint 只投影已经通过 Review 且被显式接受的 Manuscript 事实：

```text
Review candidate_facts
  -> approved Workflow version
  -> immutable Manuscript revision
  -> explicit accept + transactional outbox
  -> Memory / FAISS / Temporal Graph
```

候选事实不会在生成、Review、Workflow 完成或 Manuscript import 时提前写入。接受与 outbox 入队在 `novels.db` 内原子提交；三个下游存储使用 checkpoint 和稳定 ID 实现可恢复的最终一致，而不是依赖不存在的分布式事务。

## 冻结与接受门禁

- Workflow import 只接受 succeeded、completed、quality-gated Run。
- 最终 approved version 冻结 Review `candidate_facts`，其他 version 保存空事实列表。
- import 拒绝仍含 confirmed blocking consistency conflict 的 Run。
- candidate fact 的 chapter coordinate 必须等于 grounded Chapter Plan coordinate。
- 只有显式 Manuscript accept 才创建 outbox；接受指针与 outbox 同事务提交。
- 重复接受相同 revision 返回 `changed=false`，不会创建重复任务。

## 可恢复投影

每个事实使用稳定 `fp_<sha256>` projection ID，并记录：

```text
memory_projected
vector_projected
graph_projected
attempts / status / last_error
```

Memory 使用稳定 `mem_<projection_id>`，进入 Long-term tier；FAISS 复用同一 Memory ID；Graph 使用稳定 Event/Relation ID。重试会检查已完成 checkpoint 对应的真实 sink 是否仍存在，缺失时只修复必要阶段。启动时 processing 项转为可重试状态，并按旧事实撤回优先、同章失败阻断后续事实的顺序恢复。

## Revision 替换与时态语义

- 新 accepted revision 会把旧 revision 的任务切换为 retract，再处理新事实。
- retract 顺序为 Vector、Graph、Memory，避免 Memory 先消失而向量仍可召回。
- Graph 记录保留 revision history，但 retracted 事实从 current 与 historical list/query 隐藏；detail/revision API 仍可审计。
- WORLD_TRUTH transition 可关闭上一段冲突关系、位置或生死状态；撤回 transition 会恢复先前有效区间。
- 接受旧 revision 可重新激活其稳定事实；多次替换会把未完成撤回重新绑定到最新 accepted revision。
- `CHARACTER_BELIEF` 不污染世界状态；`CHARACTER_KNOWLEDGE` 保存 holder/knower metadata。

## API 与来源

```text
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{chapter_id}/revisions/{revision}/fact-projection
POST /api/v1/novels/{novel_id}/manuscript/chapters/{chapter_id}/revisions/{revision}/fact-projection/retry
```

每条投影保留：

```text
source_type = accepted_manuscript
source_id = manuscript_chapter_id
source_revision = accepted revision
source_chapter_number = grounded chapter
source_reference = manuscript:<chapter_id>:r<revision>:fact:<index>
```

retry 在执行任何任务前校验 novel/chapter/revision 三元 scope。投影失败不会回滚已经提交的 Manuscript 接受，状态和错误保持可查、可重试。

## 自动化验证

```text
19/19 Fact Projection focused tests passed
19/19 Manuscript focused tests passed
18/18 Consistency Engine focused tests passed
18/18 Temporal Graph focused tests passed
434/434 full regression passed in 118.183s
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

覆盖接受事务、稳定 ID、重复执行、单 sink 故障与修复、processing 启动恢复、API/OpenAPI、错误 scope、旧 revision 撤回/重新激活、多次替换、时态区间关闭/恢复、belief 隔离和 knowledge holder provenance。

## 真实运行态验收

```text
user_id = acceptance-08d3-d85958a2019f
novel_id = c561bb57-d151-4032-8a61-3abd8a144536
marker = 08D3-EMBER-4072ab792dd0
chapter_number = 1
workflow_run_id = 707bc1a1-1e92-4c79-bf4f-2d86fa6e2c34
manuscript_chapter_id = 369abad3-2dec-4b2a-bd18-7615eefa8a79
```

- 真实 `qwen3:8b` 完成 Draft + Review，运行约 29.4 秒，prompt/completion/total tokens 为 5089/1679/6768。
- Workflow `succeeded/completed`、quality gate 通过，生成 2 个无冲突 candidate facts；Workflow 阶段保持 `consistency_fact_persisted=false`。
- 正式 Manuscript import/accept 后生成 1 个 Relation 和 1 个 Event 投影；两个任务首次 attempts=1 即完成三个 sink checkpoint。
- Memory、Graph 都保留同一 accepted Manuscript source reference；融合检索返回 2 个 Vector 与 2 个 Graph candidate，模式 `dual`、无降级。
- completed retry 返回 HTTP 200，但 attempts 和 Graph revision rows 不增加；后端优雅重启后结果仍相同，双 lane 继续成功。
- 错误 novel scope retry 返回 HTTP 404；旧验收数据库和历史记录未删除。

完整记录保存在 `data/sprint08d3_acceptance.json`。

## 后续

Sprint 08E：构建 Vue 创作工作台，把 Project/Bible/Plan/Arc/Chapter/Workflow/Review/Manuscript 与事实投影状态形成可视化操作闭环。
