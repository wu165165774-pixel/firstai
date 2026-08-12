# Sprint 08D.2 - Consistency Engine

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.27
基线版本：v0.15.0-alpha.26
```

## 目标与边界

本 Sprint 在 08D.1 Temporal Graph 之上建立写作前、写作后和审核修复的一致性闭环：

```text
Project / Story Bible / Canon / chapter-valid Graph
                         │
                         v
              bounded P0.4 constraints
                         │
                         v
Chapter Draft -> Review candidate facts -> deterministic check
                         │                         │
                         │ confirmed conflict      │ no conflict
                         v                         v
                      Rewrite ----------------> Re-review
```

LLM 只负责从正文或 Review 输出中生成结构化候选事实。实体解析、证据验证和冲突结论由确定性引擎负责。所有结果均为 candidate，`persisted=false`；本 Sprint 不写 Temporal Graph、Memory、Vector、Canonical Entity 或 Manuscript，接受后事实回写仍属于 08D.3。

## 写作前约束

- 读取 Project constraints、Story Bible rules、Canonical Entity，以及目标章节当前有效的 Temporal Event/Relation。
- 每条约束携带 source type、source ID、精确 revision、有效章节区间、实体 ID 和 knowledge scope。
- 约束按 severity、类别和稳定 ID 确定性排序，并受字符预算限制；超长首条约束会安全截断而不是得到空上下文。
- Chapter Workflow 使用 1400 字符 P0.4 上下文。Canon 身份已由 P0 注入，因此 Workflow 的 P0.4 文本不重复身份块，但完整 API 响应保留身份约束。
- Novel Agent 将 Chapter Plan Grounding、Consistency Constraints 排在 Memory/RAG 之前，低优先级召回不能覆盖权威约束。

## 候选事实与冲突模型

候选事实支持：

```text
relationship | life_state | location | identity | event
```

知识范围统一为：

```text
WORLD_TRUTH
CHARACTER_KNOWLEDGE
CHARACTER_BELIEF
READER_KNOWLEDGE
```

冲突统一携带 `conflict_id`、type、severity、status、blocking、expected、generated、recommendation、entity IDs、candidate fact ID 和来源证据。当前确定性检查覆盖：

- 未知实体、歧义 alias 和 ID/名称不一致。
- 关系冲突，包括盟友/敌对的受控同义词与对称反向边。
- 生死状态、当前位置和错误地点实体类型。
- 请求章节坐标与显式候选事实章节不一致。
- 候选 evidence 不存在于正文。
- CHARACTER_KNOWLEDGE 缺少 holder、holder 不是 Canonical Character，或没有知识证据/显式获知过程。

`change_type=transition` 不能单独绕过门禁；evidence 必须同时包含受控的决裂、结盟、死亡、复活、移动、揭示或获知语义。Qwen 抽取和 grounded Review 的章节号由请求/Chapter Plan 强制覆盖，模型无权改变固定坐标。

## API

```text
POST /api/v1/novels/{novel_id}/consistency/constraints
POST /api/v1/novels/{novel_id}/consistency/check
POST /api/v1/novels/{novel_id}/consistency/analyze
```

- `/constraints` 返回写作前约束和有预算文本。
- `/check` 接收调用方提供的候选事实并执行确定性检查。
- `/analyze` 默认使用 `qwen_local`、`qwen3:8b`、medium reasoning 抽取候选事实，再调用同一确定性检查器。
- 用户与小说 scope 不匹配返回 HTTP 404，不泄露小说存在性。
- 无法解析、校验失败或截断的模型输出返回 HTTP 502。

## Chapter Workflow 闭环

- Draft、Review 和 Rewrite 均接收同一份 P0.4 Consistency Context。
- Review JSON 增加 `candidate_facts`；旧 Review 输出省略该字段时保持兼容并默认为空列表。
- 确定性阻断冲突强制 `approved=false`，并转换为可追踪 Review issue。
- Rewrite 同时接收 unresolved issues 和完整 deterministic conflict JSON。
- Re-review 对新正文重新抽取和检查；旧冲突不会被盲目沿用。
- Workflow 结果暴露 constraint、当前 conflicts、每轮 conflict history 和 `consistency_fact_persisted=false`。

## 自动化验证

```text
16/16 Consistency Engine focused tests passed
25/25 Chapter Workflow focused tests passed
15/15 Workflow Grounding focused tests passed
408/408 full regression passed in 103.532s
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

覆盖范围包括约束预算与 provenance、scope 404、关系/生死/地点/身份/时间线/证据/knowledge scope、歧义不猜测、伪 transition 不绕过、模型错误章节固定、API/OpenAPI、Graph 不持久化，以及“冲突阻断 -> Rewrite -> Re-review 清除”的 Workflow 闭环。

## 真实运行态验收

复用并保留 08D.1 的真实 Canon 与 Temporal Graph 数据：

```text
user_id = acceptance-08d1-15468ee84ff2
novel_id = 6bb1eaa5-d175-4a93-892e-3ec7271ddd95
marker = 08D2-CRIMSON-20260812
chapter_number = 3
current Graph relation = 岚 —盟友→ 祁
generated assertion = 岚与祁一直是敌人
```

- 在线 `/constraints` 返回 4 条 identity/relationship/timeline 约束，文本 680 字符，`persisted=false`。
- 在线 `/check` 返回一个 confirmed、blocking 的 `relationship_conflict`，expected 为“盟友”；错误用户返回 HTTP 404。
- 真实 `qwen3:8b` 抽取一个 relationship candidate；模型曾把 marker 错放入 `chapter_number`，回归修复后权威坐标固定为 3。
- 修复后的最终在线模型调用返回 `finish_reason=stop`，token 为 prompt 258 / completion 440 / total 698，延迟约 11.0 秒。
- 确定性复检返回一个 blocking `relationship_conflict`，结果 `persisted=false`。
- 调用前后 Temporal Graph revision 行数保持 Event 2、Relation 2；在线 Event revision 仍为 2，Relation revision 仍为 1。

验收记录保存在 `data/sprint08d2_acceptance.json`，已有数据库与历史验收数据均未删除。

## 后续

Sprint 08D.3 将只在 Manuscript 明确接受后，把已审核事实原子、幂等地写入 Memory、Vector 与 Temporal Graph，并补齐跨存储失败恢复和 provenance。
