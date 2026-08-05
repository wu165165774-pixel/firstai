# Sprint 07B.1：Agent Grounding Hardening

## 1. Sprint 信息

* 项目：NovelForge
* Sprint：07B.1
* 状态：Completed
* 完成日期：2026-08-05
* 发布版本：v0.14.0-alpha.2
* 前置版本：v0.14.0-alpha.1

## 2. 背景

在 Sprint 07B 的专业 Agent 端到端测试中，WorldAgent 和 PlotAgent 曾输出长期记忆中不存在的人名、地点、年代、势力和剧情事件。

SQLite 数据库审计确认这些内容并不存在，因此判定为模型自由补全导致的事实型幻觉。

## 3. Sprint 目标

* 事实查询不得依赖 LLM 自由生成
* 整理设定时不得遗漏低相似度的已有记忆
* 冲突检查不得在证据不足时构造虚假时间线
* Agent 返回结果必须携带可审计的记忆证据
* 创作任务和事实任务必须明确分离
* 避免 Qwen Thinking 消耗全部输出 Token

## 4. Agent Task Mode

新增三种 Agent 任务模式：

```text
auto
grounded
creative
```

### auto

根据指令内容自动判断执行模式。

专业 Agent 的非创作任务默认进入 Grounded 模式。

### grounded

* 不调用 LLM
* 只使用实际长期记忆
* 返回确定性答案
* 返回证据 ID、内容和检索策略

### creative

* 调用本地 Qwen
* 允许生成新的创作建议
* 不将创作建议自动写入长期记忆
* 在 Metadata 中标记 LLM 已被调用

## 5. AgentGroundingService

新增统一 Grounding 服务，并支持两种检索策略。

### 5.1 Hybrid Semantic Retrieval

用于具体事实查询，例如：

* 人物是什么性格
* 人物来自哪里
* 人物是什么身份
* 人物擅长什么

### 5.2 SQLite Type Scan

用于需要读取完整分类记忆的任务，例如：

* 整理全部世界观设定
* 汇总人物设定
* 列出剧情事件
* 剧情冲突检查
* 一致性检查

SQLite Type Scan 不受向量相似度阈值影响。

## 6. Memory ID 修复

Hybrid Retriever 返回结果使用：

```text
memory_id
```

SQLite MemoryItem 使用：

```text
id
```

AgentGroundingService 现已兼容这两种字段。

AgentResult 中的 `memory_ids` 可以正确返回真实记忆 ID。

## 7. 单一事实证据收缩

对于以下单一事实问题：

```text
林凡是什么性格？
```

只保留排名第一且直接支持回答的证据。

不会再把以下无关记忆放入结果：

* 人物的其他属性
* 其他人物
* 与当前问题无关的短期记忆

## 8. 专业 Agent Grounding 策略

### CharacterAgent

允许读取：

```text
character
short_term
```

具体人物事实使用 Hybrid Semantic Retrieval。

### WorldAgent

允许读取：

```text
world
```

整理世界观时使用 SQLite Type Scan。

### PlotAgent

允许读取：

```text
plot
```

剧情冲突检查不会再把普通 short-term 记忆当作完整剧情事件。

## 9. Grounded 端到端验证

### CharacterAgent

请求：

```text
林凡是什么性格？
```

返回：

```text
根据长期记忆，林凡性格谨慎。
```

检索策略：

```text
hybrid_semantic
```

证据数量：

```text
1
```

证据 ID：

```text
07c5ba3b-8872-4de2-84c3-7dbf7236e58f
```

### WorldAgent

请求：

```text
整理当前已经确认的世界观设定。
```

返回：

```text
根据长期记忆，当前已确认的世界观设定如下：
- 青云宗位于东荒大陆。
```

检索策略：

```text
sqlite_type_scan
```

证据 ID：

```text
045636e4-7eca-49c0-afa9-03e261601195
```

### PlotAgent

当前没有 `plot` 类型长期记忆，因此返回：

```text
当前长期记忆中暂无足够的剧情事件，无法判断是否存在明确冲突。
```

PlotAgent 没有生成虚构时间线、人物或剧情事件。

## 10. Creative 模式与 Qwen Thinking

Qwen3 默认 Thinking 模式可能将全部 `max_tokens` 消耗在思考阶段，导致：

```text
content = ""
finish_reason = "length"
```

Qwen Local Provider 现通过 OpenAI 兼容接口传递：

```python
extra_body={
    "reasoning_effort": "none",
}
```

关闭 Thinking 后，Creative 模式可以快速生成正文。

端到端验证结果：

```text
provider = qwen_local
model = qwen3:8b
finish_reason = stop
content = 非空
latency_ms ≈ 1542
task_mode = creative
llm_called = true
grounding_enforced = false
```

## 11. Agent Metadata

Grounded 结果包含：

* `task_mode`
* `grounding_enforced`
* `llm_called`
* `retrieval_strategy`
* `memory_used`
* `memory_count`
* `memory_ids`
* `memory_types`
* `evidence`
* `requested_provider`
* `requested_model`

## 12. 自动化测试

测试结果：

```text
Agent tests：22 passed
Memory/RAG tests：8 passed
Total：30 passed
```

全量测试：

```text
Ran 30 tests
OK
```

## 13. 验收结论

Sprint 07B.1 已完成：

* Agent Grounding Service
* Grounded 与 Creative 模式分离
* SQLite 类型全量扫描
* Hybrid Memory ID 修复
* 单一事实证据收缩
* Agent Evidence Metadata
* CharacterAgent 端到端验证
* WorldAgent 端到端验证
* PlotAgent 端到端验证
* Creative 模式端到端验证
* Qwen Thinking 关闭
* 30 条自动化测试通过

Sprint 状态：

```text
Completed
```
