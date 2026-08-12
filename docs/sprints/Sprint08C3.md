# Sprint 08C.3 - Dual-path Retrieval

## 状态

```text
已完成
发布版本：v0.15.0-alpha.25
基线版本：v0.15.0-alpha.24
```

## 目标与边界

本 Sprint 建立 Vector/Graph 双路并发执行、融合、去重、预算和可观测降级，但不提前实现 08D.1 的 Temporal Graph 存储。

```text
Vector lane: existing Working/Long-term Hybrid Memory
Graph lane: pluggable provider protocol
             -> concurrent execution
             -> deterministic RRF fusion
             -> provenance + context budget
```

默认 Graph Provider 明确报告 `unavailable`。因此 08D.1 之前真实生产请求会诚实返回 `vector_only` 与 `degraded=true`，不会新增占位 Graph 表或伪造图事实。

## 双路执行与降级

- Vector 与 Graph lane 通过 `asyncio.gather` 同时启动。
- 每条 lane 独立应用 `timeout_ms`，状态为 `success/unavailable/failed/timed_out`。
- 单 lane 失败、超时或未配置时，另一 lane 结果仍然返回。
- 对外错误经过清理，不包含原始异常信息、路径或 secret。
- 两条 lane 都成功时 mode 为 `dual`；只有一条成功时分别为 `vector_only` 或 `graph_only`；均失败时为 `unavailable`。

## 融合、去重与预算

- 使用 reciprocal rank fusion，固定 `RRF_K=60`。
- 内容先执行 NFKC、空白归一化和 case-fold，再以 SHA-256 指纹去重。
- 同内容跨 lane 合并后保留全部 source path、source ID、rank、score 和 metadata。
- 排序以 fusion score、最佳原始 score 和内容指纹稳定打破平局。
- `top_k` 和 `char_budget` 同时生效，响应报告 `chars_used`、`truncated` 和 `deduplicated_count`。

## 既有系统接入

- Session Memory 不进入向量 lane，仍按 `session_id` 从 SQLite 精确加载。
- Working/Long-term Memory 复用既有 Hybrid Retriever 和 Qwen Embedding/FAISS。
- Memory Context 保留 Session、Working、Long-term 分层，并为未来 Graph-only 证据增加 Temporal Graph 分区。
- Novel Agent/Chat 返回 `memory_retrieval_*` metadata。
- 专业 Agent 语义检索返回 `dual_path_fusion`、lane 诊断、来源 path 和融合分数，并保留原始 Vector memory ID。
- 类型枚举和冲突扫描继续使用 SQLite 精确查询。

## API

```text
POST /api/v1/retrieval/fused
```

请求提供 scope、query、`top_k`、字符预算、相似度门槛、timeout、Memory 类型过滤以及未来 Graph Provider 可消费的 entity/time 坐标。响应包含 mode、degraded、融合证据、来源和 lane 诊断。

## 自动化验证

```text
13/13 Dual Retrieval focused tests passed
23/23 Agent related tests passed
23/23 Memory related tests passed
14/14 Workflow Grounding tests passed
373/373 full regression passed
Python compileall: PASS
Docker Compose base + worker overlay config: PASS
git diff --check: PASS
```

13 项专项测试覆盖真实并发启动、RRF 跨 lane 去重与 provenance、同 lane 重复项不重复加权、确定性预算、Graph unavailable 降级、Vector failure 降级、lane timeout 取消、Vector scope/tier/type adapter、Agent memory ID 兼容、专业 Agent/Chat 诊断、Context 分区和 API/OpenAPI；Novel Agent 接入另有独立回归锁定。

## 真实运行态验收

使用 08C.1 保留的 Long-term Memory，仅执行读取和生成，没有删除或重建验收数据库：

```text
user_id = sprint08c1-acceptance
novel_id = memory-lifecycle-20260811
memory_id = 0783f006-efba-424d-ba14-b245f7827ffb
marker = 08C1-AMBER-20260811
```

- `/api/v1/retrieval/fused` 经真实 `qwen3-embedding:0.6b` 返回正确 Long-term Memory 与原始 ID。
- Vector lane 为 `success`，Graph lane 为 `unavailable`；总体 `vector_only/degraded=true`，没有 Graph 证据。
- 后端重启后仍命中相同 Memory ID，在线 OpenAPI 版本为 `0.15.0-alpha.25`。
- grounded Plot Agent 返回 `dual_path_fusion`、两条 lane 诊断、原始 memory ID、`source_paths=[vector]` 和融合分数。
- 真实 `qwen3:8b`、medium reasoning 返回“潮钟坐标仍待本章复核”，`finish_reason=stop`。
- Qwen 调用 token 用量为 prompt 549、completion 284、total 833。
- OpenAPI 包含 `/api/v1/retrieval/fused`。

详细验收记录：`data/sprint08c3_acceptance.json`。验收数据被保留。

## 后续

下一项 Sprint 08D.1：实现角色、地点、事件、关系、时间有效区间和来源 revision 的真正 Temporal Graph 权威存储，并将 Provider 接入现有 Graph lane。
