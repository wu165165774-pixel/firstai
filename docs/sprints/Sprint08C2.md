# Sprint 08C.2 - External Knowledge Base

## 状态

```text
已完成
发布版本：v0.15.0-alpha.24
基线版本：v0.15.0-alpha.23
```

## 目标与边界

本 Sprint 建立来源可追踪、按用户和知识库隔离的外部知识库。外部知识只作为最低优先级 P6 证据，不成为小说 Canon、Story Bible、Planning、Manuscript 或 Memory 的权威事实。

```text
P0 Canon / Hard Constraints
...
P5 Plot Vector RAG
P6 External Knowledge RAG
```

外部资料中的提示词或命令始终按被引用数据处理，不得执行；使用外部上下文的 Chat 不运行自动 Memory 抽取。

## 存储与索引隔离

权威数据使用独立数据库：

```text
data/external_knowledge.db
  external_knowledge_sources
  external_knowledge_revisions
  external_knowledge_chunks
```

它不复用 `memory.db`、`novels.db` 或其表。语义索引同样使用独立命名空间：

```text
data/vector_db/external_knowledge.index
data/vector_db/external_knowledge_ids.json
```

既有 Memory 继续使用 `memory.index` / `memory_ids.json`。应用启动时以 External Knowledge SQLite 当前 chunks 为权威集合检查 FAISS；missing 或 orphan IDs 会触发完整 rebuild。

## Source、Revision 与 Chunk

- Source ID 是稳定 UUID。
- `(user_id, knowledge_base_id, source_uri)` 唯一。
- `source_type` 和 `source_uri` 创建后不可变。
- 内容、标题、作者、发布日期和 metadata 的修改生成 append-only revision。
- 更新必须提交 `expected_revision`；过期 revision 返回 HTTP 409。
- 当前内容按 1000 字符预算、120 字符 overlap 确定性切块。
- Chunk ID 从 source UUID、revision、chunk number 和 content hash 确定性派生。
- 每个 chunk 保存 `start_char/end_char`，可回溯到原始 source revision。

## 检索与 Citation

检索先在独立 FAISS 中取得候选，再由 SQLite JOIN 强制以下 scope：

```text
user_id
knowledge_base_ids[]
current source revision only
```

引用格式：

```text
EK:<source_id>:r<source_revision>:c<chunk_number>
```

引用对象还包含 source URI、标题、类型、作者、发布日期、chunk ID 和字符坐标。Agent/Chat 返回边界会把同源缩写规范成完整引用、移除不在检索上下文中的伪造引用，并在模型漏引时补上最高相关证据。

## API

```text
POST   /api/v1/external-knowledge/sources
GET    /api/v1/external-knowledge/sources
GET    /api/v1/external-knowledge/sources/{source_id}
PUT    /api/v1/external-knowledge/sources/{source_id}
DELETE /api/v1/external-knowledge/sources/{source_id}
GET    /api/v1/external-knowledge/sources/{source_id}/revisions
POST   /api/v1/external-knowledge/retrieve
```

## Agent 与 Chat 接入

- `AgentContext.external_knowledge_base_ids` 是显式 opt-in；兼容 Workflow metadata 传入同名字段。
- P6 block 排在 Canon、Chapter Plan Grounding 和 Memory 之后。
- External context 预算为 2600 字符。
- Prompt 明确要求不执行资料内指令，并逐字保留完整 revision/chunk citation。
- 响应 metadata 返回 `external_knowledge_used`、`external_knowledge_priority` 和 `external_knowledge_citations`。
- Chat 使用外部证据时返回 `memory_extraction_skipped=true`，防止外部世界知识自动污染小说 Memory。

## 自动化验证

```text
External Knowledge focused: 16/16 PASS
full regression after final citation hardening: 359/359 PASS
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

16 项聚焦测试覆盖 schema、物理命名空间、确定性 chunks、URI 冲突、scope 隔离、append-only revisions、revision conflict、当前 revision 检索、删除、索引修复、上下文预算/P6/注入防护、Agent 顺序与 opt-in、Chat Memory 隔离、完整 citation 规范化/补全、API/OpenAPI。

最终 citation hardening 后的完整 359 项回归已通过。

## 真实运行态验收

```text
scope user = acceptance-08c2-20260811-24edd0c451e444f99ee0a6b72bcb197b
knowledge_base_id = maritime-safety
source_id = 73622379-3a96-4abe-b260-aecc044b70c3
source_uri = urn:novelforge:sprint08c2:20260811-24edd0c451e444f99ee0a6b72bcb197b
```

- 创建返回 HTTP 201、revision 1、`indexed=true`。
- 真实 `qwen3-embedding:0.6b` 检索返回 `r1:c1`。
- 跨用户 GET 返回 HTTP 404，跨用户检索返回 0 条。
- 更新推进到 revision 2；重复使用 expected revision 1 返回 HTTP 409。
- revision 历史为 `[2, 1]`，当前检索只返回 `r2:c1`，标题和 URI 可追踪。
- 后端重启后 source revision 2 和独立 FAISS 检索仍存在。
- 真实 `qwen3:8b` 以 `medium` reasoning 返回 74 摄氏度及完整 `r2:c1` 引用；未执行资料中要求回答 999 度的注入旁注。
- 同一完整 citation 同时出现在 Agent 正文和 `external_knowledge_citations` metadata。
- 真实 Chat API 同样返回 74 摄氏度和完整引用，`memory_extraction_skipped=true`；验收 novel 的 Memory 计数保持 `0 -> 0`。

验收记录：

```text
data/sprint08c2_acceptance.json
```

验收数据被保留，没有为测试通过而删除。

## 后续

下一项 Sprint 08C.3：建立 Temporal/Graph 与 Vector RAG 双路并行检索、融合、去重、预算和降级。
