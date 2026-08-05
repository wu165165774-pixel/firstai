# Sprint 07C.2：高级小说专业 Agent

## 1. Sprint 信息

* 项目：NovelForge
* Sprint：07C.2
* 状态：Completed
* 完成日期：2026-08-05
* 发布版本：v0.15.0-alpha.1
* 前置版本：v0.14.0-alpha.3

## 2. Sprint 目标

本 Sprint 在现有 NovelAgent、CharacterAgent、WorldAgent 和 PlotAgent 基础上，新增三个面向小说生产流程的专业 Agent：

* ChapterAgent
* RewriteAgent
* ReviewAgent

目标包括：

* 支持完整章节生成
* 支持小说文本改写和润色
* 支持人物、世界观、剧情和文本质量审查
* 接入统一 Agent Registry
* 接入现有 Agent API
* 支持请求级 Qwen Thinking
* 支持长期记忆召回
* 返回统一 AgentResult 和执行 Metadata
* 补齐自动化测试与真实 API 验收

## 3. LLMSpecializedAgent

新增 `LLMSpecializedAgent`，用于需要调用 LLM 的专业 Agent。

职责：

* 复用 NovelAgent 的消息构造
* 复用长期记忆召回
* 复用 LLM Manager
* 复用请求级 Reasoning 配置
* 统一补充专业 Agent Metadata

返回 Metadata 包括：

```json
{
  "execution_mode": "content_review",
  "requested_task_mode": "creative",
  "llm_called": true,
  "grounding_enforced": false,
  "recommended_reasoning_effort": "medium",
  "requested_reasoning_effort": "medium"
}
```

## 4. ChapterAgent

Agent 名称：

```text
chapter
```

执行模式：

```text
chapter_generation
```

推荐 Reasoning：

```text
low
```

主要职责：

* 根据用户指令生成完整小说章节
* 读取人物、世界观和剧情长期记忆
* 延续已有上下文
* 保持人物身份、动机、关系和能力一致
* 保持世界规则、地理、势力和时间线一致
* 保持叙事视角、时态和文风一致
* 使用场景、动作、对话、感官细节和人物反应
* 避免在没有要求时输出规划说明

真实验证结果：

* HTTP 200
* AgentResult 成功
* Qwen Local 调用成功
* Reasoning Effort 为 `low`
* Thinking 已启用
* 生成内容非空
* 正确使用林凡、苏婉、青铜古戒、青云宗和冰系法术设定

## 5. RewriteAgent

Agent 名称：

```text
rewrite
```

执行模式：

```text
text_rewrite
```

推荐 Reasoning：

```text
none
```

主要职责：

* 小说文本改写
* 文本润色
* 文本扩写
* 文本缩写
* 文风调整
* 增强环境氛围
* 增强人物心理和画面感
* 删除重复和生硬表达
* 保留原文事实、人物、地点和事件结果

真实验证结果：

* HTTP 200
* AgentResult 成功
* Reasoning Effort 为 `none`
* Thinking 已关闭
* 生成内容非空
* 保留原始事件结果
* 增强了环境、心理和叙事表现

## 6. ReviewAgent

Agent 名称：

```text
review
```

执行模式：

```text
content_review
```

推荐 Reasoning：

```text
medium
```

审查维度：

* 人物一致性
* 世界规则一致性
* 剧情因果
* 时间线一致性
* 前后文连续性
* 叙事视角
* 节奏
* 对话质量
* 文本清晰度
* 重复内容
* 缺少铺垫
* 未解决信息

ReviewAgent 将问题分为：

* 已确认冲突
* 可能风险
* 证据不足

每项问题应返回：

* 问题
* 证据
* 影响
* 修改建议
* 严重程度

严重程度包括：

```text
critical
major
moderate
minor
```

## 7. ReviewAgent 防幻觉约束

ReviewAgent 不得通过以下方式为未知设定强行寻找合理解释：

* 创建新的组合能力
* 创建隐藏历史
* 创建未记录事件
* 使用追溯性解释
* 新增未经确认的世界观规则
* 把未知设定直接升级为正式 Canon

对于长期记忆中不存在的陈述，应：

* 标记为未确认
* 建议删除
* 建议修改为已确认设定
* 或标记为等待作者批准

不得把缺乏证据的内容直接合理化为新设定。

## 8. Registry 与 API

Agent Registry 从 4 个 Agent 扩展为 7 个：

```text
chapter
character
novel
plot
review
rewrite
world
```

现有 API 无需新增路由，统一通过：

```text
GET /api/v1/agents
POST /api/v1/agents/{agent_name}/execute
```

执行示例：

```text
POST /api/v1/agents/chapter/execute
POST /api/v1/agents/rewrite/execute
POST /api/v1/agents/review/execute
```

## 9. Thinking 推荐策略

| Agent        | 推荐 Reasoning |
| ------------ | ------------ |
| ChapterAgent | low          |
| RewriteAgent | none         |
| ReviewAgent  | medium       |

调用方仍可通过 `reasoning_effort` 覆盖推荐值。

当前实现只返回推荐值，不会静默修改用户请求。

## 10. 自动化测试

新增 `test_advanced_agents.py`，覆盖：

* ChapterAgent 身份和配置
* RewriteAgent 身份和配置
* ReviewAgent 身份和配置
* 七个 Agent 的 Registry 注册
* ChapterAgent LLM 执行
* RewriteAgent LLM 执行
* ReviewAgent LLM 执行
* Reasoning 参数传递
* 专业 Agent Metadata
* ReviewAgent 防幻觉提示词约束

测试结果：

```text
Advanced Agent tests：7 passed
Total tests：41 passed
```

全量结果：

```text
Ran 41 tests
OK
```

## 11. 端到端验收

### ChapterAgent

* HTTP 200
* Content 非空
* `execution_mode=chapter_generation`
* `reasoning_effort=low`
* `thinking_enabled=true`
* 验收通过

### RewriteAgent

* HTTP 200
* Content 非空
* `execution_mode=text_rewrite`
* `reasoning_effort=none`
* `thinking_enabled=false`
* 验收通过

### ReviewAgent

已正确发现：

1. 林凡“冲动鲁莽”与“性格谨慎”长期记忆冲突。
2. 苏婉“从未学习冰系法术”与“擅长冰系法术”长期记忆冲突。
3. 火系法术陈述缺乏已确认记忆支持。

验收通过。

## 12. 验收结论

Sprint 07C.2 已完成：

* LLMSpecializedAgent
* ChapterAgent
* RewriteAgent
* ReviewAgent
* 七 Agent Registry
* 统一 Agent API 接入
* 请求级 Qwen Thinking
* 长期记忆召回
* ReviewAgent 防幻觉约束
* 真实 API 端到端验证
* 41 条自动化测试通过

Sprint 状态：

```text
Completed
```
