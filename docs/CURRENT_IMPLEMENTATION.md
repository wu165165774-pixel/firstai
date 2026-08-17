# NovelForge 当前实现状态

## 1. 文档信息

* 项目名称：NovelForge
* 当前开发分支：master
* 当前代码版本：v1.0.0-rc.2
* 文档状态：当前实现快照
* 快照日期：2026-08-17
* 当前阶段：Sprint 10D 已完成，下一项为完整产品旅程与 v1.0 Go/No-Go

本文档记录 NovelForge 当前已经实现并完成基础验证的功能。

本文档不是最终架构文档，也不表示原规划中的所有 Sprint 均已按顺序完成。后续开发过程中，将继续补充缺失模块、自动化测试、Sprint 文档和正式版本验收。

---

## 2. 当前整体架构

当前系统主要由以下组件组成：

```text
用户请求
    ↓
FastAPI Chat API
    ↓
LLM Manager
    ↓
Provider Registry
    ├── Qwen Local Provider
    ├── DeepSeek Provider
    ├── OpenAI Provider
    ├── Claude Provider
    └── DashScope Provider
            ↓
        Ollama
            ↓
        qwen3:8b
```

长期记忆处理链路：

```text
用户聊天输入
    ↓
Qwen 生成聊天回复
    ↓
FastAPI BackgroundTasks
    ↓
LLM Memory Extractor
    ↓
结构化记忆分类
    ├── character
    ├── world
    ├── plot
    └── short_term
    ↓
Memory Manager
    ↓
SQLite 持久化
    ↓
去重、hit_count、importance、score 更新
    ↓
Embedding
    ↓
FAISS 持久化索引
```

---

## 3. 已实现功能

### 3.1 Backend 基础框架

已实现：

* FastAPI 应用
* Uvicorn 服务
* Docker 部署
* Docker Compose 编排
* 健康检查接口
* Swagger/OpenAPI 文档
* 请求中间件
* 请求 ID
* 请求耗时日志
* 统一项目配置
* 统一响应结构
* 基础异常处理

当前端口：

```text
宿主机端口：18080
容器端口：8000
```

---

### 3.2 LLM Provider 框架

已实现：

* Base LLM Provider
* Provider Registry
* LLM Manager
* ChatRequest
* ChatMessage
* Provider 动态选择
* Model 动态选择
* 统一聊天调用入口

当前已注册 Provider：

```text
deepseek
openai
claude
dashscope
qwen_local
```

DeepSeek 已配置但当前运行环境不可达；OpenAI、Claude 与 DashScope 未配置 key，因此不宣称云端付费生成验收通过。

---

### 3.3 本地 Qwen 部署

已实现：

* Ollama Docker 服务
* Backend 与 Ollama 容器通信
* qwen3:8b 本地模型
* OpenAI-compatible Chat API
* Qwen Local Provider
* GPU 推理
* 模型列表查询
* 聊天接口调用

硬件环境：

```text
GPU：NVIDIA GeForce RTX 4070 SUPER
显存：12 GB
CUDA：12.7
```

当前模型：

```text
qwen3:8b
qwen3-embedding:0.6b
```

---

### 3.4 长期记忆数据模型

已实现记忆字段：

```text
id
user_id
novel_id
memory_type
content
importance
hit_count
score
created_at
updated_at
last_accessed_at
metadata
```

记忆类型：

```text
character
world
plot
short_term
```

---

### 3.5 SQLite 记忆存储

已实现：

* SQLite 初始化
* memories 表自动创建
* 记忆新增
* 记忆查询
* 按用户和小说隔离
* metadata JSON 存储
* 时间字段维护
* 动态 score 计算
* 查询结果排序
* 容器重启后数据持久化

SQLite 数据文件：

```text
/app/data/memory.db
```

---

### 3.6 LLM 结构化记忆抽取

已实现：

* 后台异步记忆抽取
* 使用 Qwen 分析用户输入
* 只抽取用户明确提供的信息
* 返回结构化 JSON
* 自动判断 memory_type
* 自动计算 importance
* 一句话拆分为多条原子事实
* 无意义输入返回空数组
* JSON 清理与解析保护
* 非法 memory_type 过滤
* LLM 请求异常保护

验证示例：

输入：

```text
林凡性格谨慎，是青云宗的外门弟子。青云宗位于东荒大陆。
```

抽取结果：

```text
character：林凡性格谨慎。
character：林凡是青云宗的外门弟子。
world：青云宗位于东荒大陆。
```

输入：

```text
请继续。
```

抽取结果：

```json
[]
```

---

### 3.7 记忆去重与评分

已实现：

* 相同内容精确去重
* 重复记忆不产生新记录
* hit_count 自动增加
* updated_at 自动更新
* last_accessed_at 自动更新
* importance 合并
* score 动态计算
* 查询结果按 score 排序

已验证重复输入后：

```text
记录数量仍为 1
hit_count 从 1 增加到 2
score 重新计算
updated_at 更新
```

---

### 3.8 长期记忆上下文注入

已实现：

* 从用户请求提取 user_id
* 从用户请求提取 novel_id
* 提取最后一条用户消息
* 查询相关记忆
* 按 character、world、plot 和 other 分类
* 生成系统提示词
* 将长期记忆插入聊天 messages
* 要求模型禁止编造未记录设定

当前上下文注入仍主要依赖现有 Memory Retriever。

FAISS 语义检索尚未完全接入正式聊天链路。

---

### 3.9 Embedding

已实现：

* Ollama Embedding API
* qwen3-embedding:0.6b
* 批量文本 Embedding
* 1024 维向量
* float32 转换
* 向量归一化
* 空输入检查
* 维度检查
* NaN 和 Infinity 检查
* HTTP 异常处理

语义验证结果：

```text
林凡性格谨慎。
林凡做事小心，从不轻易冒险。
相似度：0.8963
```

与无关世界设定的相似度：

```text
青云宗位于东荒大陆。
相似度：0.2758
```

语义区分测试通过。

---

### 3.10 FAISS 向量存储

已实现：

* FAISS IndexFlatIP
* FAISS IndexIDMap2
* 余弦相似度搜索
* memory_id 到 vector_id 映射
* 稳定 vector_id 生成
* 向量新增
* 向量更新
* 向量删除基础能力
* 索引全量重建
* 索引搜索
* 索引统计
* 索引文件持久化
* JSON ID 映射持久化
* 容器重启后自动加载

持久化文件：

```text
/app/data/vector_db/memory.index
/app/data/vector_db/memory_ids.json
```

---

### 3.11 SQLite 与 FAISS 同步

已实现：

* 从 SQLite 全量重建 FAISS
* SQLite memory ID 与 FAISS vector ID 映射
* 新增记忆后自动生成 Embedding
* 新增记忆后自动写入 FAISS
* 去重更新后自动执行 FAISS upsert
* FAISS 失败不影响 SQLite 主存储
* 可通过 rebuild 恢复向量索引

当前已验证 SQLite 和 FAISS 记录数量一致。

---

### 3.12 FAISS 语义搜索

已实现独立语义搜索。

验证问题：

```text
谁做事很小心，不愿意轻易冒险？
```

第一名结果：

```text
林凡性格谨慎。
```

相似度：

```text
0.6419
```

说明语义搜索能够召回文本表述不同但含义相近的记忆。

---

## 4. 当前主要代码目录

```text
backend/app/
├── api/
│   └── v1/
├── config/
├── core/
├── llm/
│   ├── bootstrap.py
│   ├── base.py
│   ├── manager.py
│   ├── registry.py
│   ├── schemas.py
│   └── providers/
├── memory/
│   ├── context.py
│   ├── extractor.py
│   ├── manager.py
│   ├── retriever.py
│   ├── schemas.py
│   ├── score.py
│   └── storage/
└── rag/
    ├── embedding.py
    ├── faiss_store.py
    └── memory_indexer.py
```

---

## 5. 当前依赖

主要运行依赖：

```text
fastapi
uvicorn
pydantic
pydantic-settings
python-dotenv
loguru
httpx
openai
numpy
faiss-cpu
```

当前已验证：

```text
openai：2.53.0
httpx：0.28.1
numpy：2.5.1
faiss：1.15.0
```

依赖完整性检查：

```text
No broken requirements found.
```

---

## 6. 当前未完成功能

### 6.1 Vector RAG 正式检索链路

待实现：

* FAISS 搜索结果批量读取 SQLite
* user_id 隔离
* novel_id 隔离
* 无效 memory_id 清理
* similarity 过滤
* similarity 与 SQLite score 混合评分
* importance 权重
* hit_count 权重
* 时间衰减
* 最终 top-k 排序
* 接入 MemoryContextBuilder
* 接入正式 Chat API

---

### 6.2 索引一致性

待完善：

* 删除 SQLite 记忆时同步删除 FAISS
* 修改记忆内容时更新向量
* 应用启动时自动检查一致性
* SQLite 与 FAISS 数量不一致时自动重建
* 索引文件损坏恢复
* 模型或向量维度变化后的版本迁移

---

### 6.3 自动化测试

待补充：

* LLM Registry 测试
* Qwen Provider 测试
* SQLite Storage 测试
* Memory Manager 测试
* 记忆去重测试
* Memory Extractor 测试
* Embedding 测试
* FAISS Store 测试
* Memory Indexer 测试
* Chat API 集成测试
* 容器重启持久化测试

---

### 6.4 尚未完成的原规划模块

待后续继续实现：

* OpenAI Provider
* Claude Provider
* DashScope/Qwen API Provider
* DeepSeek API 正式验收
* Session Memory
* Working Memory
* Novel Agent
* LangGraph 工作流
* Prompt Manager
* Plot RAG
* External Knowledge RAG
* Temporal Graph RAG
* 世界观知识图谱
* 人物关系图谱
* Planner
* Consistency Engine
* Chapter Generator
* Rewrite Agent
* Review Agent
* Frontend
* 项目管理界面
* 插件机制
* 完整 v1.0 发布

---

## 7. 当前版本说明

当前版本：

```text
v0.13.0-alpha.1
```

该版本表示：

* 本地 Qwen 聊天能力已实现；
* 长期记忆核心链路已实现；
* LLM 结构化记忆提取已实现；
* SQLite 记忆持久化已实现；
* 精确去重和动态评分已实现；
* Ollama Embedding 已实现；
* FAISS 持久化向量索引已实现；
* SQLite 与 FAISS 自动同步已实现；
* 独立语义搜索已验证；
* 正式混合检索链路尚未完成。

该版本不是正式的 Sprint 13 完成版本，也不是生产版本。

---

## 8. 后续开发原则

从该快照之后继续开发时，应恢复以下工程要求：

1. 每个功能模块必须有明确范围。
2. 每个阶段必须有运行验证。
3. 每个阶段必须有自动化测试。
4. 每个正式 Sprint 必须有完整文档。
5. 每个稳定阶段必须提交 Git。
6. 每个正式里程碑必须打版本标签。
7. 不允许把数据库、日志、模型文件和向量索引提交到 Git。
8. 正式版本发布前必须确保工作区干净。
9. 任何架构调整必须同步更新文档。
10. 每个 Sprint 完成后必须提供验收清单。

---

## 9. 下一步

当前下一项开发任务：

```text
完成 FAISS 与 SQLite 混合检索
```

目标链路：

```text
用户问题
    ↓
Qwen Embedding
    ↓
FAISS 语义召回
    ↓
按 user_id 和 novel_id 过滤
    ↓
SQLite 获取完整记忆
    ↓
similarity + importance + hit_count + score 综合排序
    ↓
MemoryContextBuilder
    ↓
注入 Qwen Chat 上下文
```

完成该功能并补齐自动化测试后，再评估是否发布：

```text
v0.13.0
```
# NovelForge 当前实现状态

## 1. 文档信息

* 项目名称：NovelForge
* 当前开发分支：master
* 当前代码版本：v1.0.0-rc.2
* 文档状态：当前实现快照
* 快照日期：2026-08-17
* 当前阶段：Sprint 10D 已完成，下一项为完整产品旅程与 v1.0 Go/No-Go

本文档记录 NovelForge 当前已经实现并完成基础验证的功能。

本文档不是最终架构文档，也不表示原规划中的所有 Sprint 均已按顺序完成。后续开发过程中，将继续补充缺失模块、自动化测试、Sprint 文档和正式版本验收。

---

## 2. 当前整体架构

当前系统主要由以下组件组成：

```text
用户请求
    ↓
FastAPI Chat API
    ↓
LLM Manager
    ↓
Provider Registry
    ├── Qwen Local Provider
    ├── DeepSeek Provider
    ├── OpenAI Provider
    ├── Claude Provider
    └── DashScope Provider
            ↓
        Ollama
            ↓
        qwen3:8b
```

长期记忆处理链路：

```text
用户聊天输入
    ↓
Qwen 生成聊天回复
    ↓
FastAPI BackgroundTasks
    ↓
LLM Memory Extractor
    ↓
结构化记忆分类
    ├── character
    ├── world
    ├── plot
    └── short_term
    ↓
Memory Manager
    ↓
SQLite 持久化
    ↓
去重、hit_count、importance、score 更新
    ↓
Embedding
    ↓
FAISS 持久化索引
```

---

## 3. 已实现功能

### 3.1 Backend 基础框架

已实现：

* FastAPI 应用
* Uvicorn 服务
* Docker 部署
* Docker Compose 编排
* 健康检查接口
* Swagger/OpenAPI 文档
* 请求中间件
* 请求 ID
* 请求耗时日志
* 统一项目配置
* 统一响应结构
* 基础异常处理

当前端口：

```text
宿主机端口：18080
容器端口：8000
```

---

### 3.2 LLM Provider 框架

已实现：

* Base LLM Provider
* Provider Registry
* LLM Manager
* ChatRequest
* ChatMessage
* Provider 动态选择
* Model 动态选择
* 统一聊天调用入口

当前已注册 Provider：

```text
deepseek
openai
claude
dashscope
qwen_local
```

DeepSeek 已配置但当前运行环境不可达；OpenAI、Claude 与 DashScope 未配置 key，因此不宣称云端付费生成验收通过。

---

### 3.3 本地 Qwen 部署

已实现：

* Ollama Docker 服务
* Backend 与 Ollama 容器通信
* qwen3:8b 本地模型
* OpenAI-compatible Chat API
* Qwen Local Provider
* GPU 推理
* 模型列表查询
* 聊天接口调用

硬件环境：

```text
GPU：NVIDIA GeForce RTX 4070 SUPER
显存：12 GB
CUDA：12.7
```

当前模型：

```text
qwen3:8b
qwen3-embedding:0.6b
```

---

### 3.4 长期记忆数据模型

已实现记忆字段：

```text
id
user_id
novel_id
memory_type
content
importance
hit_count
score
created_at
updated_at
last_accessed_at
metadata
```

记忆类型：

```text
character
world
plot
short_term
```

---

### 3.5 SQLite 记忆存储

已实现：

* SQLite 初始化
* memories 表自动创建
* 记忆新增
* 记忆查询
* 按用户和小说隔离
* metadata JSON 存储
* 时间字段维护
* 动态 score 计算
* 查询结果排序
* 容器重启后数据持久化

SQLite 数据文件：

```text
/app/data/memory.db
```

---

### 3.6 LLM 结构化记忆抽取

已实现：

* 后台异步记忆抽取
* 使用 Qwen 分析用户输入
* 只抽取用户明确提供的信息
* 返回结构化 JSON
* 自动判断 memory_type
* 自动计算 importance
* 一句话拆分为多条原子事实
* 无意义输入返回空数组
* JSON 清理与解析保护
* 非法 memory_type 过滤
* LLM 请求异常保护

验证示例：

输入：

```text
林凡性格谨慎，是青云宗的外门弟子。青云宗位于东荒大陆。
```

抽取结果：

```text
character：林凡性格谨慎。
character：林凡是青云宗的外门弟子。
world：青云宗位于东荒大陆。
```

输入：

```text
请继续。
```

抽取结果：

```json
[]
```

---

### 3.7 记忆去重与评分

已实现：

* 相同内容精确去重
* 重复记忆不产生新记录
* hit_count 自动增加
* updated_at 自动更新
* last_accessed_at 自动更新
* importance 合并
* score 动态计算
* 查询结果按 score 排序

已验证重复输入后：

```text
记录数量仍为 1
hit_count 从 1 增加到 2
score 重新计算
updated_at 更新
```

---

### 3.8 长期记忆上下文注入

已实现：

* 从用户请求提取 user_id
* 从用户请求提取 novel_id
* 提取最后一条用户消息
* 查询相关记忆
* 按 character、world、plot 和 other 分类
* 生成系统提示词
* 将长期记忆插入聊天 messages
* 要求模型禁止编造未记录设定

当前上下文注入仍主要依赖现有 Memory Retriever。

FAISS 语义检索尚未完全接入正式聊天链路。

---

### 3.9 Embedding

已实现：

* Ollama Embedding API
* qwen3-embedding:0.6b
* 批量文本 Embedding
* 1024 维向量
* float32 转换
* 向量归一化
* 空输入检查
* 维度检查
* NaN 和 Infinity 检查
* HTTP 异常处理

语义验证结果：

```text
林凡性格谨慎。
林凡做事小心，从不轻易冒险。
相似度：0.8963
```

与无关世界设定的相似度：

```text
青云宗位于东荒大陆。
相似度：0.2758
```

语义区分测试通过。

---

### 3.10 FAISS 向量存储

已实现：

* FAISS IndexFlatIP
* FAISS IndexIDMap2
* 余弦相似度搜索
* memory_id 到 vector_id 映射
* 稳定 vector_id 生成
* 向量新增
* 向量更新
* 向量删除基础能力
* 索引全量重建
* 索引搜索
* 索引统计
* 索引文件持久化
* JSON ID 映射持久化
* 容器重启后自动加载

持久化文件：

```text
/app/data/vector_db/memory.index
/app/data/vector_db/memory_ids.json
```

---

### 3.11 SQLite 与 FAISS 同步

已实现：

* 从 SQLite 全量重建 FAISS
* SQLite memory ID 与 FAISS vector ID 映射
* 新增记忆后自动生成 Embedding
* 新增记忆后自动写入 FAISS
* 去重更新后自动执行 FAISS upsert
* FAISS 失败不影响 SQLite 主存储
* 可通过 rebuild 恢复向量索引

当前已验证 SQLite 和 FAISS 记录数量一致。

---

### 3.12 FAISS 语义搜索

已实现独立语义搜索。

验证问题：

```text
谁做事很小心，不愿意轻易冒险？
```

第一名结果：

```text
林凡性格谨慎。
```

相似度：

```text
0.6419
```

说明语义搜索能够召回文本表述不同但含义相近的记忆。

---

## 4. 当前主要代码目录

```text
backend/app/
├── api/
│   └── v1/
├── config/
├── core/
├── llm/
│   ├── bootstrap.py
│   ├── base.py
│   ├── manager.py
│   ├── registry.py
│   ├── schemas.py
│   └── providers/
├── memory/
│   ├── context.py
│   ├── extractor.py
│   ├── manager.py
│   ├── retriever.py
│   ├── schemas.py
│   ├── score.py
│   └── storage/
└── rag/
    ├── embedding.py
    ├── faiss_store.py
    └── memory_indexer.py
```

---

## 5. 当前依赖

主要运行依赖：

```text
fastapi
uvicorn
pydantic
pydantic-settings
python-dotenv
loguru
httpx
openai
numpy
faiss-cpu
```

当前已验证：

```text
openai：2.53.0
httpx：0.28.1
numpy：2.5.1
faiss：1.15.0
```

依赖完整性检查：

```text
No broken requirements found.
```

---

## 6. 当前未完成功能

### 6.1 Vector RAG 正式检索链路

待实现：

* FAISS 搜索结果批量读取 SQLite
* user_id 隔离
* novel_id 隔离
* 无效 memory_id 清理
* similarity 过滤
* similarity 与 SQLite score 混合评分
* importance 权重
* hit_count 权重
* 时间衰减
* 最终 top-k 排序
* 接入 MemoryContextBuilder
* 接入正式 Chat API

---

### 6.2 索引一致性

待完善：

* 删除 SQLite 记忆时同步删除 FAISS
* 修改记忆内容时更新向量
* 应用启动时自动检查一致性
* SQLite 与 FAISS 数量不一致时自动重建
* 索引文件损坏恢复
* 模型或向量维度变化后的版本迁移

---

### 6.3 自动化测试

待补充：

* LLM Registry 测试
* Qwen Provider 测试
* SQLite Storage 测试
* Memory Manager 测试
* 记忆去重测试
* Memory Extractor 测试
* Embedding 测试
* FAISS Store 测试
* Memory Indexer 测试
* Chat API 集成测试
* 容器重启持久化测试

---

### 6.4 尚未完成的原规划模块

待后续继续实现：

* OpenAI Provider
* Claude Provider
* DashScope/Qwen API Provider
* DeepSeek API 正式验收
* Session Memory
* Working Memory
* Novel Agent
* LangGraph 工作流
* Prompt Manager
* Plot RAG
* External Knowledge RAG
* Temporal Graph RAG
* 世界观知识图谱
* 人物关系图谱
* Planner
* Consistency Engine
* Chapter Generator
* Rewrite Agent
* Review Agent
* Frontend
* 项目管理界面
* 插件机制
* 完整 v1.0 发布

---

## 7. 当前版本说明

当前版本：

```text
v0.13.0-alpha.1
```

该版本表示：

* 本地 Qwen 聊天能力已实现；
* 长期记忆核心链路已实现；
* LLM 结构化记忆提取已实现；
* SQLite 记忆持久化已实现；
* 精确去重和动态评分已实现；
* Ollama Embedding 已实现；
* FAISS 持久化向量索引已实现；
* SQLite 与 FAISS 自动同步已实现；
* 独立语义搜索已验证；
* 正式混合检索链路尚未完成。

该版本不是正式的 Sprint 13 完成版本，也不是生产版本。

---

## 8. 后续开发原则

从该快照之后继续开发时，应恢复以下工程要求：

1. 每个功能模块必须有明确范围。
2. 每个阶段必须有运行验证。
3. 每个阶段必须有自动化测试。
4. 每个正式 Sprint 必须有完整文档。
5. 每个稳定阶段必须提交 Git。
6. 每个正式里程碑必须打版本标签。
7. 不允许把数据库、日志、模型文件和向量索引提交到 Git。
8. 正式版本发布前必须确保工作区干净。
9. 任何架构调整必须同步更新文档。
10. 每个 Sprint 完成后必须提供验收清单。

---

## 9. 下一步

当前下一项开发任务：

```text
完成 FAISS 与 SQLite 混合检索
```

目标链路：

```text
用户问题
    ↓
Qwen Embedding
    ↓
FAISS 语义召回
    ↓
按 user_id 和 novel_id 过滤
    ↓
SQLite 获取完整记忆
    ↓
similarity + importance + hit_count + score 综合排序
    ↓
MemoryContextBuilder
    ↓
注入 Qwen Chat 上下文
```

完成该功能并补齐自动化测试后，再评估是否发布：

```text
v0.13.0
```

Sprint 07A：NovelAgent Core Framework completed
Sprint 07B：Agent API and specialized agents completed

Registered agents:
- novel
- character
- world
- plot

Agent API:
- GET /api/v1/agents
- POST /api/v1/agents/{agent_name}/execute

Test status:
- 24 tests passed



## Sprint 07B.1：Agent Grounding Hardening

状态：Completed

版本：v0.14.0-alpha.2

新增能力：

* Agent `auto / grounded / creative` 任务模式
* 专业 Agent 确定性事实回答
* Hybrid Semantic Retrieval
* SQLite 类型全量扫描
* HybridMemoryResult `memory_id` 兼容
* 单一事实证据收缩
* Agent Grounding Evidence
* 专业 Agent 事实型幻觉防护
* Grounded 模式不调用 LLM
* Creative 模式调用本地 Qwen
* Qwen Thinking 默认关闭，防止正文输出为空

当前专业 Agent：

* novel
* character
* world
* plot

测试状态：

* Agent tests：22 passed
* Memory/RAG tests：8 passed
* Total：30 passed

端到端状态：

* Character Grounded：Passed
* World Grounded：Passed
* Plot Grounded：Passed
* World Creative：Passed


## Sprint 07C.2：高级小说专业 Agent

状态：Completed

版本：v0.15.0-alpha.1

新增 Agent：

* ChapterAgent
* RewriteAgent
* ReviewAgent

当前 Agent Registry：

* chapter
* character
* novel
* plot
* review
* rewrite
* world

新增能力：

* 完整章节生成
* 小说文本改写、润色、扩写和缩写
* 人物一致性审查
* 世界观一致性审查
* 剧情因果和时间线审查
* 文本节奏、对话和表达质量审查
* 专业 Agent 执行 Metadata
* 专业 Agent 推荐 Reasoning 强度
* ReviewAgent 未确认设定防幻觉约束

推荐 Reasoning：

* ChapterAgent：low
* RewriteAgent：none
* ReviewAgent：medium

测试状态：

* Advanced Agent tests：7 passed
* Total：41 passed

端到端状态：

* ChapterAgent：Passed
* RewriteAgent：Passed
* ReviewAgent：Passed
* Seven Agent Registry：Passed
## Sprint 07C.2：高级小说专业 Agent

状态：Completed

版本：v0.15.0-alpha.1

新增 Agent：

* ChapterAgent
* RewriteAgent
* ReviewAgent

当前 Agent Registry：

* chapter
* character
* novel
* plot
* review
* rewrite
* world

新增能力：

* 完整章节生成
* 小说文本改写、润色、扩写和缩写
* 人物一致性审查
* 世界观一致性审查
* 剧情因果和时间线审查
* 文本节奏、对话和表达质量审查
* 专业 Agent 执行 Metadata
* 专业 Agent 推荐 Reasoning 强度
* ReviewAgent 未确认设定防幻觉约束

推荐 Reasoning：

* ChapterAgent：low
* RewriteAgent：none
* ReviewAgent：medium

测试状态：

* Advanced Agent tests：7 passed
* Total：41 passed

端到端状态：

* ChapterAgent：Passed
* RewriteAgent：Passed
* ReviewAgent：Passed
* Seven Agent Registry：Passed

## v0.15.0-alpha.2 — Sprint 07D.1 Chapter Production Workflow

已实现章节生产工作流：

```text
ChapterAgent → ReviewAgent → Quality Gate → RewriteAgent
```

新增：

- `POST /api/v1/workflows/chapter`
- 结构化 Review JSON
- 可配置严重等级门禁
- 自动改写开关
- 三个阶段独立推理等级、温度和 Token 上限
- 工作流步骤、Token 和延迟聚合
- 安全失败状态和原始正文保留
- 6 条工作流测试

验收状态：

```text
47/47 tests passed
OpenAPI workflow route passed
External port 18080 passed
Real Qwen two-stage branch passed
Real Qwen three-stage rewrite branch passed
```

说明：Sprint 07D.1 不在 Rewrite 后执行第二次 Review，因此改写分支的 `quality_gate_passed` 保持为 `false`。复审闭环将在 Sprint 07D.2 实现。

## v0.15.0-alpha.3 — Sprint 07D.2 Multi-Round Chapter Quality Loop

章节生产工作流已升级为：

```text
Chapter → Review → Rewrite → Re-Review
```

新增最大修订轮次、复审历史、步骤轮次和尝试编号、正文循环保护、Review 自动降级重试，以及严格的最终质量门禁语义。

验收：

```text
15/15 targeted workflow tests passed
56/56 full regression tests passed
OpenAPI multiround fields passed
OpenAPI review retry fields passed
Real Qwen draft-review-rewrite-review loop passed
Real Qwen max revision termination passed
```

真实验收最终状态为 `max_revisions_reached`：复审仍发现问题且请求只允许 1 轮修订。系统保留最新修订稿，并正确保持 `quality_gate_passed=false`。

## v0.15.0-alpha.4 — Sprint 07D.3 Structured Quality Tracking

章节生产闭环新增结构化质量评分与问题追踪：

```text
Chapter → Review + Scores + Issue IDs → Rewrite → Re-Review
```

新增：

- 六维质量评分与总分
- 0～10 分自动归一化
- 缺失评分安全推断
- `minimum_overall_score`
- `minimum_dimension_score`
- `require_all_issues_resolved`
- 稳定 `ISSUE-xxx` 标识
- `new / persisting / resolved / reopened` 状态迁移
- 只向 Rewrite 传递未解决问题
- 每轮修订差异摘要
- 完整质量门禁原因

验收：

```text
23/23 targeted workflow tests passed
64/64 full regression tests passed
Host-side API and OpenAPI validation passed
Real Qwen quality score history passed
Real Qwen issue tracking and transitions passed
Real Qwen revision diff summary passed
```

真实验收结果保留一个持续存在的 `ISSUE-001`，因此在一轮修订上限下返回 `max_revisions_reached`，并正确保持 `quality_gate_passed=false`。

## v0.15.0-alpha.5 — Sprint 07D.4 Workflow Run Persistence

章节生产工作流新增运行持久化和精确 Checkpoint 恢复。

新增 API：

```text
POST /api/v1/workflows/chapter/runs
GET  /api/v1/workflows/runs
GET  /api/v1/workflows/runs/{run_id}
POST /api/v1/workflows/runs/{run_id}/resume
```

新增能力：

- SQLite 保存运行请求、结果和状态
- 保存 Workflow Step 审计事件
- 保存 Draft、Rewrite 和 Checkpoint 章节版本
- `run_id / root_run_id / parent_run_id`
- Backend 重启后继续查询
- 未通过质量门禁的运行标记为 `resumable`
- 从最新正文精确恢复
- Resume 不重新调用 ChapterAgent
- Resume 参数白名单保护
- 成功运行禁止重复恢复
- 运行失败状态持久化

恢复时首个步骤为：

```text
stage: draft
agent: checkpoint
provider: workflow_checkpoint
```

验收：

```text
9/9 targeted workflow-run tests passed
73/73 full regression tests passed
Runtime Agent Manager compatibility passed
Parent run persistence passed
Backend restart persistence passed
Exact checkpoint content match passed
Parent-child lineage query passed
```

## v0.15.0-alpha.6 — Sprint 07D.5 Async Workflow Queue

章节生产工作流新增持久化异步队列和运行控制。

新增 API：

```text
POST /api/v1/workflows/chapter/runs/async
GET  /api/v1/workflows/runs/{run_id}/control
POST /api/v1/workflows/runs/{run_id}/cancel
```

新增能力：

- HTTP 202 立即返回 `run_id`
- SQLite 持久任务队列
- 进程内后台 Worker
- 原子任务领取
- 幂等提交和 `Idempotency-Key`
- 默认单任务并发控制
- queued 和 running 任务取消
- Worker 租约与心跳
- 租约过期任务自动回收
- Backend 重启后恢复 Worker
- Run、Queue、Event 状态同步持久化
- 保持同步 Run 和 Resume API 兼容

队列状态：

```text
queued
running
cancelling
cancelled
completed
failed
```

验收：

```text
8/8 async workflow tests passed
9/9 workflow persistence tests passed
81/81 full regression tests passed
HTTP 202 immediate submission passed
Idempotency match passed
Real Qwen background execution passed
Queued cancellation passed
Restart persistence passed
```

## v0.15.0-alpha.7 — Sprint 07D.6 Standalone Workflow Worker

Workflow 执行从 Backend API 进程解耦到独立 Worker 容器。

容器模式：

```text
novelforge-backend: external
novelforge-worker: worker
novelforge-ollama: Qwen inference
```

新增能力：

- 独立 Worker 进程入口
- SQLite Worker 注册表
- Worker 心跳、容量和活动任务数
- Worker 状态查询 API
- 多 Worker 原子任务领取
- API 与 Worker 跨进程取消
- SIGINT/SIGTERM 优雅停机
- 停机任务释放回 queued
- Worker 崩溃后的租约恢复
- 新 Worker 自动接管同一 Run
- 独立 Compose Worker 覆盖配置
- embedded 模式向后兼容

新增 API：

```text
GET /api/v1/workflows/workers
```

验收：

```text
9/9 standalone Worker tests passed
90/90 full regression tests passed
Backend external mode passed
Worker mode and registration passed
Real Worker container crash passed
lease_recovered count = 1
run_completed count = 1
chapter version count = 1
```

## v0.15.0-alpha.8 — Sprint 07D.7 Queue Policies and DLQ

独立 Workflow Worker 增加持久化队列策略和失败恢复能力。

新增能力：

- `-100 ～ 100` 任务优先级
- 优先级、可执行时间和 FIFO 调度
- 最大尝试次数与指数退避
- `retry_wait` 和 `retrying` 状态
- Dead Letter Queue
- 手动重新入队
- DLQ 查询 API
- 队列 Metrics API
- 旧 SQLite 数据库原地迁移
- 终态任务优先级统计

新增 API：

```text
POST /api/v1/workflows/runs/{run_id}/retry
GET  /api/v1/workflows/dead-letter
GET  /api/v1/workflows/queue/metrics
```

验收：

```text
103/103 full regression passed
priority_min = -50
priority_max = 95
priority_average = 22.5
dead_letter_count = 3
run_claimed = 4
retry_scheduled = 2
run_dead_lettered = 2
run_requeued = 1
```

## v0.15.0-alpha.9 — Sprint 07D.8 Backpressure, Timeout and Worker Control

Added production queue protection and Worker operations:

- global queue backpressure
- per-user active-run quota
- idempotency-before-backpressure
- per-attempt execution timeout
- timeout retry and DLQ integration
- Worker pause / resume / drain
- persistent rejection and timeout metrics
- SQLite in-place migration

Acceptance:
```text
113/113 tests passed
queue_full_rejections_delta = 1
user_quota_rejections_delta = 1
timeout_failures_delta = 2
real timed_out_count = 2
production policy restore passed
```

## v0.15.0-alpha.10 — Sprint 07D.9 Queue Operations and Observability

Workflow 队列补齐批量运维、历史归档和可观测性闭环。

新增能力：

- DLQ 批量重放
- 终态 queue job 归档
- 默认 DLQ 归档保护
- Run / Event / Version 历史保留
- 窗口吞吐 Metrics
- 排队延迟 Metrics
- 执行耗时 Metrics
- Worker 集群健康汇总
- stale Worker 独立观测而不误判健康集群

新增 API：

```text
POST /api/v1/workflows/dead-letter/replay
POST /api/v1/workflows/queue/archive
GET  /api/v1/workflows/queue/archive
GET  /api/v1/workflows/workers/health
```

验收：

```text
124/124 full regression passed
DLQ replayed = 2
archived_count = 7
run history preserved
default DLQ archive protection passed
health_status = healthy
running_workers = 1
accepting_workers = 1
stale_workers = 2
```

## v0.15.0-alpha.11 — Sprint 07D.10 Operations Dashboard and Infrastructure Finalization

07D Workflow Infrastructure 正式收尾。

新增：

- Worker 批量 pause / resume / drain
- Worker 历史安全清理与 dry-run
- 运维操作审计
- Queue/Worker 告警阈值
- Operations Dashboard 聚合 API
- Prometheus exposition endpoint

新增 API：

```text
POST /api/v1/workflows/workers/control/batch
POST /api/v1/workflows/workers/history/cleanup
GET  /api/v1/workflows/operations/audit
GET  /api/v1/workflows/operations/dashboard
GET  /api/v1/workflows/metrics/prometheus
```

验收：

```text
136/136 full regression passed
batch worker pause/resume passed
worker history cleanup passed
operations audit passed
dashboard aggregation passed
prometheus live metrics passed
worker health healthy
```

最终 Dashboard 可保持 `warning`，例如历史 DLQ backlog 达到阈值；这与 Worker 集群健康状态独立。

## v0.15.0-alpha.12 — Sprint 08A.1 Novel Project and Story Bible Foundation

08A Novel Planning Foundation 正式启动。

新增：

- Novel Project 领域模型
- 独立 `novels.db`
- Story Bible 结构化数据
- Story Bible 不可变 revision 历史
- Novel Project optimistic revision
- Story Bible optimistic revision
- user/status Project 查询
- Backend 重启持久化
- Novel / Workflow 数据库隔离

新增 API：

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

验收：

```text
151/151 full regression passed
Project revision conflict -> HTTP 409
Story Bible revision conflict -> HTTP 409
Story Bible revisions = [3, 2, 1]
novels.db domain isolation passed
Backend restart persistence passed
```

## v0.15.0-alpha.13 — Sprint 08A.2 Novel Planner Foundation

NovelForge 新增总体小说规划层。

新增：

- Novel Plan
- Main Plot Beats
- Character Arcs
- Volume Plans
- Novel Plan immutable revisions
- optimistic revision conflict
- Project revision source tracking
- Story Bible revision source tracking
- dynamic `is_stale`
- existing Novel Project Plan backfill
- Backend restart persistence

新增 API：

```text
GET /api/v1/novels/{novel_id}/plan
PUT /api/v1/novels/{novel_id}/plan
GET /api/v1/novels/{novel_id}/plan/revisions
GET /api/v1/novels/{novel_id}/plan/revisions/{revision}
```

验收：

```text
168/168 full regression passed
Plan revision conflict -> HTTP 409
Project change -> Plan stale
Story Bible change -> Plan stale
Plan refresh -> source revisions synchronized
Plan revisions = [4, 3, 2, 1]
Planner SQLite persistence passed
Backend restart persistence passed
```

## v0.15.0-alpha.14 — Sprint 08A.3 Story Arc Planning

NovelForge 新增独立 Story Arc 规划层。

新增：

- Story Arc 独立领域实体
- Volume / Arc 顺序和位置唯一约束
- Story Arc immutable revisions
- optimistic revision conflict
- Project source revision tracking
- Story Bible source revision tracking
- Novel Plan source revision tracking
- three-source dynamic `is_stale`
- Turning Points
- Character Progression
- Plot Threads / Dependencies
- target chapter range
- Backend restart persistence

新增 API：

```text
POST /api/v1/novels/{novel_id}/arcs
GET  /api/v1/novels/{novel_id}/arcs
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}
PUT  /api/v1/novels/{novel_id}/arcs/{arc_id}
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}/revisions
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}/revisions/{revision}
```

验收：

```text
186/186 full regression passed
Arc position conflicts -> HTTP 409
Arc revision conflict -> HTTP 409
Project change -> Arc stale
Story Bible change -> Arc stale
Novel Plan change -> Arc stale
Final Arc source revisions synchronized
Arc revisions = [5, 4, 3, 2, 1]
Story Arc SQLite persistence passed
Backend restart persistence passed
```

## v0.15.0-alpha.15 — Sprint 08A.4 Chapter Planning Foundation

NovelForge 新增独立 Chapter Plan 规划层。

新增：

- Chapter Plan 独立领域实体
- Story Arc binding
- full-novel chapter ordering
- chapter number uniqueness
- Arc rebind
- Scene Beats
- POV / conflict / reveal / hook
- continuity dependencies
- target word count
- Chapter Plan immutable revisions
- optimistic revision conflict
- Project source revision tracking
- Story Bible source revision tracking
- Novel Plan source revision tracking
- Story Arc source revision tracking
- four-source dynamic `is_stale`
- Backend restart persistence

新增 API：

```text
POST /api/v1/novels/{novel_id}/chapter-plans
GET  /api/v1/novels/{novel_id}/chapter-plans
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}
PUT  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}/revisions
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}/revisions/{revision}
```

验收：

```text
206/206 full regression passed
Chapter number conflicts -> HTTP 409
Chapter revision conflict -> HTTP 409
Arc rebind passed
Project change -> Chapter stale
Story Bible change -> Chapter stale
Novel Plan change -> Chapter stale
Story Arc change -> Chapter stale
Final four-source revisions synchronized
Chapter revisions = [6, 5, 4, 3, 2, 1]
Chapter SQLite persistence passed
Backend restart persistence passed
```

## v0.15.0-alpha.16 — Sprint 08A.5 Planner Agent + Local Qwen Structured Planning

NovelForge 在稳定的五层规划领域链之上新增 Planner Agent，并接入本地 `qwen3:8b` 生成结构化规划候选。

新增：

- Planner Agent 与独立 Planner API
- Novel Plan / Story Arc / Chapter Plan 三类候选
- `qwen_local` + `qwen3:8b` 默认推理配置
- Pydantic candidate 最终强校验
- Story Arc / Chapter Plan fixed coordinate 校验
- Novel Plan / Story Arc / Chapter Plan stale gates
- target-aware compact context
- 3600 字符 deterministic context hard budget
- compact prompt JSON Schema
- context / prompt size metadata
- provider、model、usage、latency、source revision metadata

新增 API：

```text
POST /api/v1/novels/{novel_id}/planner/generate
```

架构边界：

```text
/planner/generate returns validated candidate only
persisted = false
no Planner persistence tables
accepted candidates persist through existing domain APIs
```

Chapter target context：

```text
Project
Story Bible
Novel Plan
single selected Story Arc
nearby Chapter Plan summaries
```

不会重复携带完整 Story Arc collection 与 selected Story Arc。

真实 `qwen3:8b` 验收：

```text
Novel Plan Candidate: PASS
prompt_tokens = 1711
planner_context_chars = 2131

Story Arc Candidate: PASS
prompt_tokens = 1961
planner_context_chars = 2758

Chapter Plan Candidate: PASS
prompt_tokens = 2067
planner_context_chars = 3104

Ollama runtime n_ctx = 4096
input prompt truncation = false
```

验收同时证明：

```text
candidate non-persistence passed
explicit domain persistence passed
fixed coordinates passed
Plan stale gates returned HTTP 409
selected Arc stale gate returned HTTP 409
Planner database tables absent
Backend restart persistence passed
```

自动化验证：

```text
22/22 Planner focused tests passed
228/228 full regression passed
Docker Compose config passed
git diff --check passed
```

## v0.15.0-alpha.17 — Sprint 08A.6 Planner Candidate Review + Explicit Acceptance

Planner candidate-only 架构新增显式审核接受能力。

新增 API：

```text
POST /api/v1/novels/{novel_id}/planner/accept
```

正式边界：

```text
/planner/generate -> validated candidate, persisted=false
client review/edit -> explicit user action
/planner/accept -> existing domain persistence, persisted=true
```

新增能力：

- Novel Plan / Story Arc / Chapter Plan 三类候选显式接受。
- target 与 candidate 类型强绑定。
- Story Arc / Chapter Plan fixed coordinates 二次校验。
- 接受前重新执行 target-specific stale gate。
- 接受前比较完整 source revision snapshot。
- SQLite 写事务内再次核对 expected source revisions，防止检查与落库之间的竞态。
- 冲突统一返回 HTTP 409，且不产生部分写入。
- 接受继续复用既有规划领域服务和数据表。
- `/planner/generate` 行为保持不变，继续绝不自动落库。
- Planner 数据库表继续不存在。

真实 `qwen3:8b` 三阶段生成与接受：

```text
Novel Plan: prompt 1351, completion 2207, accept revision 2
Story Arc: prompt 1568, completion 1688, accept revision 1
Chapter Plan: prompt 1672, completion 1445, accept revision 1
persisted on all generation responses = false
persisted on all acceptance responses = true
Ollama truncated = 0, 0, 0
```

冲突与持久化验收：

```text
old candidate acceptance -> HTTP 409
persisted revision unchanged after conflict
planner tables = []
Backend restart persistence passed
Chapter Plan Arc binding preserved
```

自动化验证：

```text
33/33 Planner focused tests passed
239/239 full regression passed
Docker Compose config passed
git diff --check passed
```

项目后续主线统一记录于：

```text
docs/ROADMAP.md
```

## v0.15.0-alpha.18 — Sprint 08A.7 Canonical Entity Foundation

NovelForge 在既有 Novel Project 领域内新增稳定实体身份基础，开始解决长篇生成中的同名、近名和别名串角色问题。

新增数据表：

```text
novel_entities
novel_entity_aliases
```

新增 API：

```text
POST  /api/v1/novels/{novel_id}/entities
GET   /api/v1/novels/{novel_id}/entities
GET   /api/v1/novels/{novel_id}/entities/{entity_id}
PATCH /api/v1/novels/{novel_id}/entities/{entity_id}
POST  /api/v1/novels/{novel_id}/entities/resolve
```

正式语义：

- `(novel_id, entity_id)` 是稳定身份，名字只用于显示和解析。
- 支持 character、organization、location、item、creature、concept；当前重点为 character。
- entity update 保留 ID，并使用 `expected_revision` 乐观并发。
- alias 索引在同一 SQLite 事务中重建。
- 解析优先级固定为 exact canonical、exact alias、normalized canonical、normalized alias。
- 规范化使用空白清理、Unicode NFKC 和 casefold。
- 同一优先级命中多个实体时返回 ambiguous candidates，不默认选择任一实体。

保持不变：

```text
Story Bible legacy character dictionaries remain compatible
Planner generate remains candidate-only and persisted=false
Planner accept remains explicit
Novel Plan / Story Arc / Chapter Plan schemas and stale semantics remain unchanged
Memory / FAISS remain retrieval evidence, not Canon authority
```

自动化验证：

```text
15/15 Entity Registry focused tests passed
15/15 Novel Project focused tests passed
17/17 Novel Planner focused tests passed
33/33 Planner Agent focused tests passed
254/254 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 API 与重启验收：

```text
exact canonical resolution passed
normalized alias resolution passed
shared alias returned 2 ambiguous candidates without guessing
stable entity ID and revision conflict passed
alias index replacement passed
Backend restart persistence passed
existing Novel Plan revision remained 1
Planner database tables remained absent
```

详细一致性审计与后续 P0/P1/P2 路线：

```text
docs/architecture/LONG_FORM_CONSISTENCY.md
docs/ROADMAP.md
```

## v0.15.0-alpha.19 — Sprint 08A.8 Story Bible Entity Alignment + Canon Context

NovelForge 完成一致性 P0.2，将 legacy Story Bible、Entity Registry、Planner 和 Agent Context 串成可验收的 Canon 身份链。

新增 API：

```text
POST /api/v1/novels/{novel_id}/story-bible/entities/align
```

新增能力：

- legacy `id`、`character_id`、`entity_id` 兼容识别。
- Story Bible 人物显式绑定 stable entity ID。
- 缺失实体可在显式操作中创建。
- 同名/别名歧义不猜测。
- 重复实体绑定、ID/名称冲突、类型冲突整体回滚。
- `expected_revision` 乐观并发。
- 第二次无变化对齐不增加 revision。
- Entity create/update 推进 Canon revision，使旧规划进入 stale。
- Novel Plan、Story Arc、Chapter Plan 人物/地点引用校验。
- Planner candidate 输出未知 Canon ID 时拒绝。
- 显式接受被编辑成未知 ID 时返回 HTTP 409。
- `CanonContextBuilder` 以 P0 system message 注入 Agent。
- 3600 字符确定性 Canon budget。
- active entity / POV entity 定向选择。
- Memory/RAG 明确为低优先级 evidence。
- Planner target-aware context 内携带 compact canonical entities，且不重复注入通用 Canon block。

保持不变：

```text
/planner/generate remains candidate-only and persisted=false
/planner/accept remains an explicit action
no Planner persistence tables
fixed coordinates and stale gates remain enforced
legacy Story Bible free-form fields remain readable and writable
unmigrated entity types remain compatible
```

自动化验证：

```text
22/22 Canon/Alignment focused tests passed
35/35 Planner focused tests passed
15/15 Entity Registry focused tests passed
278/278 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 `qwen3:8b` 验收：

```text
Novel Plan: prompt 1412, completion 2171, context chars 1593
Story Arc: prompt 1607, completion 1649, context chars 2193
Chapter Plan: prompt 1691, completion 1529, context chars 2518
all candidates persisted=false
all candidate character references used canonical Registry IDs
invalid canonical acceptance -> HTTP 409 and no persistence
Ollama n_ctx=4096, truncated=0/0/0
Backend restart persistence passed
Planner tables=[]
```

## v0.15.0-alpha.20 — Sprint 08B.1 Chapter Plan -> Chapter Workflow Bridge

NovelForge 完成一致性 P0.3，将已接受的 Chapter Plan revision 正式接入 Chapter Production Workflow。

新增能力：

- 新 Chapter Workflow HTTP 执行强制携带 `chapter_plan_id` 和 `chapter_plan_revision`。
- 在任何 Agent 调用前加载并验证 Project、Story Bible、fresh Novel Plan、selected Story Arc 和 selected Chapter Plan。
- revision mismatch、stale Plan/Arc/Chapter 统一在生成前返回 HTTP 409。
- selected Project/Bible/Plan/Arc/Chapter 与紧邻章节形成 3600 字符确定性 Grounding Context。
- 自动派生 POV、active character/location IDs、continuity dependencies 和 Memory query。
- Chapter、Review、Rewrite 全阶段共享 P0.3 权威规划 system message。
- Canon 与规划上下文位于 Memory/RAG 证据之前。
- Workflow result 与 persisted Run 记录 binding、source revisions、context chars、active entities 和 adjacent chapters。
- sync Run、resume、async submission 和外部 Worker 均重新校验相同绑定。
- 入队后规划变 stale 的 Job 在 LLM 调用前进入 dead-letter。
- Qwen Review 返回 `finish_reason=length` 时自动使用无推理 fallback 重试，不解析半截 JSON。

HTTP 语义：

```text
missing Chapter Plan binding -> 422
unknown Chapter Plan -> 404
revision conflict -> 409
stale Novel Plan / Story Arc / Chapter Plan -> 409
```

保持不变：

```text
Planner generate remains candidate-only and persisted=false
Planner accept remains explicit
Novel Plan / Story Arc / Chapter Plan remain independent persisted domains
chapter_plans still do not physically store volume_number or arc_number
Memory/RAG remains supporting evidence, not Canon or accepted planning authority
no new Workflow Grounding persistence table
```

自动化验证：

```text
24/24 Chapter Workflow focused tests passed
14/14 Workflow Grounding focused tests passed
293/293 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 `qwen3:8b` 验收：

```text
grounding_context_chars = 3595 / 3600
sync resume Review total tokens = 3997 / 4096
external Worker Draft total tokens = 3127 / 4096
external Worker Review total tokens = 4001 / 4096
sync resume quality gate = passed
external Worker queue/run = completed/succeeded
all real Chapter/Review steps grounding_enforced=true
```

竞态与重启验收：

```text
fresh Job submitted while Worker stopped
Story Bible revision advanced 5 -> 6
Worker revalidation rejected stale Novel Plan
Job dead_lettered with latest_content_length=0
sync and async stale gates returned HTTP 409
Backend/Worker restart persistence passed
OpenAPI binding requirement persisted
```

## v0.15.0-alpha.21 — Sprint 08B.2 Manuscript / Chapter Draft / Revision Domain

NovelForge 新增正式 Manuscript 领域，将 Workflow 正文输出与权威接受稿分离。

新增数据表：

```text
manuscript_chapters
manuscript_revisions
```

新增能力：

- `(novel_id, chapter_number)` 对应稳定 Manuscript Chapter ID。
- 正文 revision append-only，并保存 content hash、Workflow Run/Version 和规划来源 revision。
- 只允许导入 succeeded、completed、quality-gated 的持久化 Workflow Run。
- Workflow draft/rewrite/checkpoint 版本被复制为 immutable Manuscript revisions。
- 最终 Workflow 正文成为 reviewed candidate，但导入不自动接受。
- 显式接受使用 Manuscript 聚合 revision 乐观并发。
- 导入和接受都在事务内重验 Project/Bible/Plan/Arc/Chapter freshness。
- 同一 Run 重复导入和同一 revision 重复接受均幂等。
- 后续 Chapter Workflow 只加载最多两个 accepted prior Manuscript revisions。
- candidate-only 内容不会进入 Agent Grounding，也不会替换既有 accepted revision。

新增 API：

```text
POST /api/v1/novels/{novel_id}/manuscript/chapters/import-workflow
GET  /api/v1/novels/{novel_id}/manuscript/chapters
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}
POST /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}/accept
```

自动化验证：

```text
16/16 Manuscript focused tests passed
14/14 Workflow Grounding focused tests passed
24/24 Chapter Workflow focused tests passed
309/309 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 `qwen3:8b` 验收：

```text
Chapter 1 Workflow succeeded/completed and passed quality gate
first import created one approved candidate; second import deduplicated
candidate accepted_revision remained null before explicit accept
Chapter 2 pre-accept grounding contained no candidate Manuscript IDs
explicit accept advanced aggregate revision; repeated accept changed=false
Chapter 2 post-accept grounding contained Chapter 1 Manuscript revision 1
Story Bible revision 5 -> 6 caused accept to return HTTP 409
stale rejection left Chapter 2 accepted_revision=null
```

## v0.15.0-alpha.22 — Sprint 08B.3 Full Novel Orchestrator

NovelForge 新增持久化全小说 Orchestrator，在既有 Workflow Queue 与 Manuscript 领域之间提供可恢复的跨章节控制流。

新增数据表：

```text
novel_orchestrations
novel_orchestration_steps
novel_orchestration_events
```

核心边界：

- 创建时冻结选择范围、Chapter Plan ID/revision、章节顺序、Workflow 和 Queue 策略。
- 每次只排入当前章节的一个 Workflow Run，不并发生成后续章节。
- `advance` 显式协调 succeeded/completed/quality-gated Run，并复用 Manuscript 导入服务形成 candidate。
- candidate 的 `accepted_revision` 保持 `null`；接受仍只能调用既有 Manuscript API。
- 只有当前 step 对应的精确 candidate revision 被接受后，Orchestrator 才排入下一章。
- 后续章节继续由既有 Grounding 读取 accepted-only prior Manuscript revisions。
- Orchestrator 聚合使用 revision 乐观并发；每个状态变化写入 append-only event。
- pause 不取消在途 Workflow，而是阻断候选导入和跨章推进；resume 会恢复原状态并 reconcile。
- Queue/DLQ failure 可重试同一 Run；质量门失败或人工拒绝候选可创建新的 Workflow attempt。
- 创建支持 `Idempotency-Key`，进程重启后聚合、steps、events 和关联 Run 仍可恢复。

新增 API：

```text
POST /api/v1/novels/{novel_id}/orchestrations
GET  /api/v1/novels/{novel_id}/orchestrations
GET  /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/advance
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/pause
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/resume
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/retry
```

自动化验证：

```text
19/19 Orchestrator focused tests passed
16/16 Manuscript focused tests passed
14/14 Workflow Grounding focused tests passed
8/8 Workflow Async focused tests passed
328/328 full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实外部 Worker `qwen3:8b` 验收：

```text
orchestration_id = 8eb289fe-1aaa-4a95-8f2a-24ef107f234f
Chapter 1 Run succeeded/completed and passed quality gate
pause blocked candidate import and Chapter 2 queueing after Run completion
resume imported Chapter 1 candidate without accepting it
explicit Manuscript accept then queued exactly one Chapter 2 Run
Chapter 2 Grounding contained Chapter 1 accepted Manuscript revision 1
Chapter 2 candidate remained gated until explicit Manuscript accept
final orchestration revision = 9, status = completed, accepted = 2/2
same Idempotency-Key returned deduplicated=true
Story Bible revision 2 -> 3 made new orchestration creation return HTTP 409
```

控制流目前是线性的，SQLite 聚合状态与既有 Queue/DLQ 已足够表达持久恢复、人工门禁和重试，因此本 Sprint 未引入 LangGraph，避免形成第二套执行/checkpoint 权威源。

## v0.15.0-alpha.23 — Sprint 08C.1 Three-tier Memory

NovelForge 将 Memory 内容分类与生命周期正式拆开：

```text
memory_type = character / world / plot / short_term
memory_tier = session / working / long_term
```

新增 `memories` 列：

```text
memory_tier
session_id
expires_at
revision
```

新增表：

```text
memory_lifecycle_events
```

生命周期规则：

- 旧 rows 自动迁移为 `long_term`，不改变稳定 ID、内容类型或旧 API 默认行为。
- Session 必须绑定 `session_id`，默认 24 小时 TTL，不写入 FAISS；同内容只在同 session 内去重。
- Working 为小说级当前创作窗口，默认 30 天 TTL，写入 FAISS。
- Long-term 为跨会话检索证据，无自动 TTL，写入 FAISS，但不是 Canon。
- 只允许 `session -> working -> long_term` 相邻提升，保持同一 memory ID。
- Session 的 frequency 提升要求 `hit_count >= 2`；user-confirmed 提升要求 `importance >= 0.5`。
- Working -> Long-term 要求权威 basis 与 `importance >= 0.7`；accepted Manuscript / Story Bible basis 必须有 `metadata.source_reference`。
- promote 使用 `expected_revision`，冲突返回 HTTP 409；创建、强化、提升、淘汰和显式删除写 append-only events。
- sweep 只淘汰已过期 Session/Working；Long-term 永不被自动 sweep。
- FAISS consistency 只以 Working/Long-term 为权威集合，Session 误入索引会被 rebuild 清理。
- Agent tiered Memory block 内按 Session、Working、Long-term 排列，整体仍位于 Canon 与 Chapter Plan Grounding 之后。

扩展/新增 API：

```text
POST /api/v1/memory
GET  /api/v1/memory/{user_id}/{novel_id}?memory_tier=&session_id=
POST /api/v1/memory/{memory_id}/promote
GET  /api/v1/memory/{memory_id}/lifecycle/events
POST /api/v1/memory/lifecycle/sweep
POST /api/v1/memory/sessions/{session_id}/close
```

同时修复 `MemoryExtractor` 对单个抽取事实重复保存两次的问题。

自动化验证：

```text
15/15 Memory Lifecycle focused tests passed
8/8 existing Memory/RAG tests passed
48/48 Agent/Canon/Workflow Grounding related tests passed
343/343 full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实 HTTP + Qwen Embedding 验收：

```text
acceptance memory_id = 0783f006-efba-424d-ba14-b245f7827ffb
Session revision 1 did not appear in /retrieve
stale expected_revision returned HTTP 409
Session -> Working kept ID, produced revision 2 and entered /retrieve
Working -> Long-term kept ID, produced revision 3 and removed TTL
events = memory_created, memory_promoted, memory_promoted
expired Session dry-run/execute each selected exactly one ID
session close evicted only the selected session
final scope contains no Session and preserves one Long-term row
```

## v0.15.0-alpha.24 — Sprint 08C.2 External Knowledge Base

NovelForge 新增与小说内部 Memory/Canon 分离的外部知识库：

```text
external_knowledge.db
  -> external_knowledge_sources
  -> external_knowledge_revisions
  -> external_knowledge_chunks

vector_db/external_knowledge.index
vector_db/external_knowledge_ids.json
```

核心边界：

- 外部知识不进入 `memory.db`、Canon、Story Bible 或已接受正文。
- Source 使用稳定 UUID；`source_uri` 在 `(user_id, knowledge_base_id)` 内唯一。
- 内容变更形成 append-only revision，并通过 `expected_revision` 乐观并发；冲突返回 HTTP 409。
- 当前 revision 按 1000 字符、120 字符 overlap 确定性切块；chunk 保存字符坐标和内容 hash。
- SQLite 是权威源，独立 FAISS namespace 负责语义召回；启动时检查并修复 missing/orphan vectors。
- 读取和检索都强制 `user_id + knowledge_base_id` scope，跨作用域 GET 返回 404，检索返回空集。
- Citation 格式为 `EK:<source_id>:r<revision>:c<chunk>`，同时包含 URI、标题、来源类型和字符坐标。
- Novel Agent/Chat 仅在显式给出 `external_knowledge_base_ids` 时加载 P6 External Knowledge。
- 外部证据中的命令只视为数据；不能覆盖 P0-P5 权威上下文，也不触发自动 Memory 抽取。
- 返回边界只保留本轮检索上下文中的 citation；同源缩写会规范成完整 revision/chunk 引用，漏引会补入最高相关证据。

新增 API：

```text
POST   /api/v1/external-knowledge/sources
GET    /api/v1/external-knowledge/sources
GET    /api/v1/external-knowledge/sources/{source_id}
PUT    /api/v1/external-knowledge/sources/{source_id}
DELETE /api/v1/external-knowledge/sources/{source_id}
GET    /api/v1/external-knowledge/sources/{source_id}/revisions
POST   /api/v1/external-knowledge/retrieve
```

自动化验证：

```text
16/16 External Knowledge focused tests passed
359/359 full regression passed after final citation hardening
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实本地 Qwen 验收：

```text
source_id = 73622379-3a96-4abe-b260-aecc044b70c3
create revision 1 returned 201 and indexed=true
cross-user GET returned 404; cross-user retrieval returned zero hits
update advanced revision 1 -> 2; stale update returned HTTP 409
retrieval citation advanced from r1:c1 to r2:c1
backend restart preserved source revision 2 and independent FAISS retrieval
qwen3:8b answered 74 degrees with the complete r2:c1 citation
embedded instruction requesting 999 degrees was not executed
Chat marked memory_extraction_skipped=true; acceptance Memory count stayed 0
```

## v0.15.0-alpha.25 — Sprint 08C.3 Dual-path Retrieval

NovelForge 新增可插拔的 Vector/Graph 双路检索执行与确定性融合层：

```text
Vector Memory Provider ─┐
                        ├─ concurrent lanes -> RRF -> dedup -> budget
Temporal Graph Provider ┘                    -> provenance + diagnostics
```

核心边界：

- Vector lane 复用现有 Hybrid Memory，只检索 Working/Long-term；Session Memory 继续由 SQLite 按 `session_id` 精确加载。
- 两条 lane 使用 `asyncio` 并发执行，并分别应用超时；不可用、异常或超时只降级对应 lane。
- 默认 Graph Provider 明确返回 `unavailable`，直到 08D.1 提供真正的 Temporal Graph 存储；本 Sprint 不新增 Graph/Planner 表，也不伪造 Graph 结果。
- 融合使用 `RRF_K=60`，以 NFKC、空白归一化和 case-fold 后的 SHA-256 内容指纹去重。
- 排序、来源顺序、`top_k` 和字符预算均为确定性；每条证据保留 path、source ID、rank、原始 score 与 metadata。
- lane 错误对外只返回清理后的诊断，不泄露内部异常正文、路径或 secret。

新增 API：

```text
POST /api/v1/retrieval/fused
```

请求支持 `top_k`、`char_budget`、Vector 相似度门槛、lane timeout、Memory 类型过滤，以及供未来 Graph Provider 使用的 active entity/time 坐标。响应返回 `dual/vector_only/graph_only/unavailable`、`degraded`、融合证据和两条 lane 诊断。

接入行为：

- Memory Context 保持 Session -> Working -> Long-term -> Temporal Graph 分区顺序，并携带检索诊断。
- Novel Agent 与 Chat metadata 返回 `memory_retrieval_mode`、`memory_retrieval_degraded`、`memory_retrieval_lanes`。
- 专业 Agent 的语义检索策略变为 `dual_path_fusion`，证据保留原 Vector memory ID、`source_paths` 和 `fusion_score`。
- 类型枚举/冲突扫描仍走精确 SQLite 查询，不错误地包装成语义双路检索。

自动化验证：

```text
13/13 Dual Retrieval focused tests passed
23/23 Agent related tests passed
23/23 Memory related tests passed
14/14 Workflow Grounding tests passed
373/373 full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收：

```text
scope user = sprint08c1-acceptance
scope novel = memory-lifecycle-20260811
memory_id = 0783f006-efba-424d-ba14-b245f7827ffb
marker = 08C1-AMBER-20260811

qwen3-embedding:0.6b Vector lane returned the exact Long-term memory
Graph lane reported unavailable with no fabricated Graph evidence
HTTP mode = vector_only, degraded = true
backend restart preserved the same source memory ID and retrieval result
online OpenAPI version after restart = 0.15.0-alpha.25
grounded Plot Agent exposed provenance and both lane diagnostics
qwen3:8b medium returned the correct memory-backed sentence
prompt/completion/total tokens = 549/284/833
finish_reason = stop
```

验收记录保存在 `data/sprint08c3_acceptance.json`；既有验收数据未删除。下一项为 Sprint 08D.1 Temporal Graph Foundation。

## v0.15.0-alpha.26 — Sprint 08D.1 Temporal Graph Foundation

NovelForge 新增独立 Temporal Graph 权威库，并将真实 Graph Provider 接入既有双路检索：

```text
novel_entities (canonical identity)
          │
          v
temporal_graph.db
  ├── temporal_events
  ├── temporal_event_participants
  ├── temporal_event_revisions
  ├── temporal_relations
  └── temporal_relation_revisions
          │
          v
Graph Provider + Vector Provider -> RRF / dedup / budget
```

核心边界：

- `novel_entities` 仍是实体身份的唯一权威；Graph 只保存对稳定 entity ID 的引用。
- Event 与 Relation 使用当前聚合加 append-only revision snapshot，更新受 `expected_revision` 与 `BEGIN IMMEDIATE` 保护。
- Event participants 物理规范化，地点必须引用 `location` 实体；不存在或跨小说的实体不能写入。
- 时间范围使用闭合 chapter interval，支持指定章节的 current 查询和显式 historical 查询。
- 来源仅允许精确 Story Bible revision 或 accepted Manuscript revision；后者必须匹配正文 chapter。
- 本 Sprint 不自动抽取、不回写、不修改 Canon/Memory/Manuscript，保留 08D.3 的事实写入边界。

Temporal Graph API 提供 Event/Relation 创建、读取、更新、列表、revision 历史与统一 query。查询支持 active entity、chapter、context、event type、predicate 和 historical 过滤，并返回有效区间、confidence、来源 revision 与 Graph revision。

检索与 Agent 接入：

- 默认 Graph lane 已替换为真实 `TemporalGraphRetrievalProvider`；数据库查询在线程中执行，不阻塞异步 lane 调度。
- Graph Provider 消费 `active_entity_ids`、`allowed_memory_types` 和 `as_of=chapter:N`，输出完整 provenance。
- Memory Context、Chat、Novel Agent、Character/World/Plot 等 grounded Agent 自动从 metadata 转发 active character/location/entity IDs 与 chapter number。
- 正确 scope 下 Graph 与 Vector 可同时成功并按规范化内容去重；错误用户 scope 返回零证据并安全降级。

自动化验证：

```text
16/16 Temporal Graph focused tests passed
14/14 Dual Retrieval focused tests passed
390/390 first full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收：

```text
scope user = acceptance-08d1-15468ee84ff2
scope novel = 6bb1eaa5-d175-4a93-892e-3ec7271ddd95
marker = 08D1-AZURE-15468ee84ff2

event revision advanced 1 -> 2; stale update returned HTTP 409
chapter 2 current = historical hostile relation only
chapter 3 current = oath event + current ally relation
chapter 3 historical = current facts + ended hostile relation
fused evidence preserved Vector memory ID and Graph event ID
grounded Character Agent answered the chapter-valid ally relation without LLM
qwen3:8b answered the exact oath event; retrieval mode = dual, degraded = false
wrong-user retrieval returned zero evidence
```

验收记录保存在 `data/sprint08d1_acceptance.json`；既有数据库与验收数据未删除。下一项为 Sprint 08D.2 Consistency Engine。

## v0.15.0-alpha.27 — Sprint 08D.2 Consistency Engine

NovelForge 在 Temporal Graph 之上增加 candidate-only 的一致性分析与 Chapter Workflow 硬门禁：

```text
Project / Bible / Canon / current Graph
                 │
                 v
       bounded P0.4 constraints
                 │
                 v
Draft -> Review fact candidates -> deterministic conflicts
                 │                         │
                 └──── Rewrite <───────────┘
                           │
                           v
                       Re-review
```

写作前约束：

- Project constraints、Story Bible rules、Canonical Entity 和指定章节有效的 Temporal Event/Relation 统一为带精确来源 revision 的结构化约束。
- 约束使用确定性 severity/category/ID 排序与字符预算；完整 API 默认 3600 字符，Workflow P0.4 最多 1400 字符。
- Workflow 已由 P0 Canon Context 提供身份信息，因此 P0.4 文本过滤重复 identity，但结果仍保留完整 constraint 列表。
- Novel Agent 将 Chapter Plan Grounding 与 Consistency Constraints 作为权威 system messages，顺序高于 Session/Working/Long-term Memory 和双路 RAG。

写作后检查：

- 候选事实覆盖 relationship、life_state、location、identity 与 event。
- 知识范围统一为 WORLD_TRUTH、CHARACTER_KNOWLEDGE、CHARACTER_BELIEF、READER_KNOWLEDGE。
- 确定性规则检查 unknown/ambiguous entity、ID/name mismatch、relationship、life state、location、timeline、unsupported evidence 与 knowledge scope。
- alias 歧义不会猜测；关系同义词使用受控词表；对称盟友/敌对关系检查反向边。
- transition 必须同时具有明确 evidence，不能仅靠模型标签绕过冲突门禁。
- Qwen 抽取和 grounded Review 的章节号强制绑定请求/Chapter Plan；外部 `/check` 提交错误坐标仍返回 `timeline_conflict`。

API：

```text
POST /api/v1/novels/{novel_id}/consistency/constraints
POST /api/v1/novels/{novel_id}/consistency/check
POST /api/v1/novels/{novel_id}/consistency/analyze
```

`/analyze` 默认使用本地 `qwen3:8b` medium reasoning 抽取候选事实，再交给确定性检查器。三个端点均执行 user/novel scope 门禁，并保持 `persisted=false`。一致性实现没有 Graph/Memory/Vector/Canon/Manuscript 写路径；事实接受与回写留给 08D.3。

Workflow Review 输出新增 `candidate_facts`。确认的 blocking conflict 会强制审核失败、生成一致性 Review issue 并携带完整冲突数据进入 Rewrite；下一次 Review 对修订正文重新抽取和检查。结果暴露 constraints、当前 conflicts、逐轮 conflict history、上下文字符数和 `consistency_fact_persisted=false`。

自动化验证：

```text
16/16 Consistency Engine focused tests passed
25/25 Chapter Workflow focused tests passed
15/15 Workflow Grounding focused tests passed
408/408 full regression passed in 103.532s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收复用并保留 08D.1 小说 `6bb1eaa5-d175-4a93-892e-3ec7271ddd95`。第 3 章当前 Graph 记录岚与祁为盟友；输入“岚对祁拔剑，宣称两人一直是敌人”后，在线确定性 API 与修复后的真实 `qwen3:8b` 抽取路径均返回 blocking `relationship_conflict`。真实调用 token 为 258/440/698，章节固定为 3，`persisted=false`；调用前后 Temporal Graph revision 行数保持 Event 2、Relation 2。

验收记录保存在 `data/sprint08d2_acceptance.json`；既有数据库与验收数据未删除。下一项为 Sprint 08D.3 accepted Manuscript 后的原子、幂等事实回写。

## v0.15.0-alpha.28 — Sprint 08D.3 Accepted Fact Projection

NovelForge 已把 Review 候选事实接入显式 Manuscript 接受边界：

```text
Qwen Review candidate_facts
          │ frozen into approved Manuscript revision
          v
explicit Manuscript accept + transactional outbox
          │
          ├── Long-term Memory SQLite
          ├── FAISS Vector
          └── Temporal Event / Relation
```

一致性边界：

- 只有最终 approved Workflow version 保存候选事实；未批准版本和未接受 Manuscript 不会回写。
- Manuscript 接受指针与 outbox 在 `novels.db` 的同一个 `BEGIN IMMEDIATE` 事务内提交。
- Memory、FAISS 与 Temporal Graph 不伪装成跨库原子事务，而是使用稳定 SHA-256 projection ID、逐 sink checkpoint、幂等 upsert、失败状态、显式 retry 和 startup recovery 达成最终一致。
- 每条 Memory/Graph 记录保留 `manuscript:<chapter_id>:r<revision>:fact:<index>`，Graph source 还保存 accepted Manuscript ID、revision 与 chapter coordinate。
- 接受替代 revision 时，旧事实先撤回再投影新事实；旧向量和 Memory 被移除，Graph 事实标记 retracted。transition 关闭的旧关系/状态区间会在撤回时恢复。
- `CHARACTER_BELIEF` 不进入世界状态冲突；`CHARACTER_KNOWLEDGE` 保留 knowledge holder/knower metadata，并继续作为角色知识约束。

API 新增：

```text
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{chapter_id}/revisions/{revision}/fact-projection
POST /api/v1/novels/{novel_id}/manuscript/chapters/{chapter_id}/revisions/{revision}/fact-projection/retry
```

接受响应同时返回 projection summary。失败的跨存储投影不回滚已提交的 Manuscript 接受；客户端可查询精确 sink checkpoint 并安全重试。retry 在执行前校验完整 novel/chapter/revision scope。

自动化验证：

```text
19/19 Fact Projection focused tests passed
19/19 Manuscript focused tests passed
18/18 Consistency Engine focused tests passed
18/18 Temporal Graph focused tests passed
434/434 full regression passed in 118.183s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收创建并保留独立小说 `c561bb57-d151-4032-8a61-3abd8a144536`。真实 `qwen3:8b` Chapter Workflow 运行约 29.4 秒，使用 6768 tokens，Review 输出 2 个无冲突候选事实。正式 import/accept 后，2 个 outbox item 均在首次尝试完成 Memory、Vector 与 Graph checkpoint；融合检索为 `dual`，Vector/Graph lane 均为 `success`，并返回同一 accepted Manuscript provenance。

显式 retry 与后端重启后 attempts 仍为 1、Event/Relation revision rows 仍为 1，证明 completed 投影没有重复写入。错误 novel scope 的 retry 返回 HTTP 404。验收记录保存在 `data/sprint08d3_acceptance.json`；既有数据库与历史验收数据均未删除。下一项为 Sprint 08E Vue 创作工作台。

## v0.15.0-alpha.29 — Sprint 08E.1 Vue 创作工作台基础

NovelForge 已增加 Vue 3 创作工作台，将既有权威领域以只通过正式 API 的方式组成首个浏览器操作闭环：

```text
项目库 / 创作总览
  -> Chapter Plan / Workflow / Orchestration
  -> Manuscript candidate review + explicit accept
  -> Fact Projection checkpoint + retry
```

工作台按 `user_id` 加载项目，展示 Project/Bible/Plan/Arc/Chapter/Manuscript 六段生产链及 revision/stale 状态。章节生产页展示规划地图、质量门通过的 Workflow 导入和全书任务控制；重复导入会读取 Run 的 Chapter Plan 绑定并携带当前 Manuscript optimistic revision。正文审核页选择不可变 revision，显式接受时携带聚合 revision；事实面板展示冻结事实和 Memory/Vector/Graph checkpoint，只允许查询或重试后端 outbox。

生产部署新增 `novelforge-frontend`：Node 22 使用 lockfile 和 `npm ci` 构建，Nginx 1.27 在宿主 `18081` 提供 SPA、静态资源缓存、`/healthz` 和同源 `/api` Backend 代理。开发态 Vite 代理到宿主 `18080`。界面不依赖 CDN 或远程字体，也未放宽 Backend CORS。

自动化与运行验证：

```text
8/8 frontend pure/API tests passed
Vue SFC compile passed
Rollup bundle verification passed (330654 bytes)
CSS parse passed (210 top-level rules)
Frontend Docker/Vite production build passed
Frontend 18081 root/assets/healthz/SPA/API proxy passed
434/434 backend full regression passed in 198.522s
Docker Compose base + worker overlay config passed
```

真实只读联调复用并保留 08D.3 小说 `c561bb57-d151-4032-8a61-3abd8a144536`。Project、Bible、Plan、Arc、Chapter Plan、Workflow、Manuscript/revision 和 completed Fact Projection 全部通过工作台依赖的 API 返回；经 `18081` Nginx 代理按保留 user scope 查询精确 1 个项目。验收记录保存在 `data/sprint08e1_acceptance.json`。下一项为 08E.2 规划编辑、Planner candidate 审核接受与 Workflow 创建表单。

## v0.15.0-alpha.30 — Sprint 08E.2 规划编辑与 Planner 候选审核

Planning Studio 已把 Story Bible、Novel Plan、Story Arc 与 Chapter Plan 的编辑接到正式领域 API。常用字段使用表单，复杂嵌套结构使用经过数组/对象形状校验的 JSON 区域；更新携带 `expected_revision`，新 Arc/Chapter 使用 POST，既有实体保持稳定 ID 并使用 PUT 产生新 revision。

Planner 三目标在浏览器中形成 `generate -> review/edit -> explicit accept` 闭环。生成结果明确显示 `persisted=false`、模型、token、latency 与 compact context；accept 保留 source revisions，并固定使用生成时的 Story Arc/Chapter coordinates，因此审核 JSON 不能通过同时篡改请求坐标来绕过后端校验。Story Arc 生成要求 fresh Novel Plan，Chapter Plan 生成要求 fresh Plan 与所选 Arc；Novel Plan stale 时仍允许重新生成。

章节生产页新增单章 Workflow 表单。它只列出 fresh Chapter Plan，提交精确 `chapter_plan_id + revision` 到持久化 async queue，并携带 idempotency key 与优先级；Workflow 成功后仍需在既有 Manuscript 页面手工导入、审核和接受。

真实 `qwen3:8b` 验收在保留小说 `85c4dff6-7530-459f-a3f7-1eaf34fc5c76` 上完成 Novel Plan、V1/A1 Story Arc 和 chapter 1 三段 candidate-only/explicit-accept。三次生成分别使用 2499、2565、3502 tokens；Arc revision 更新使 Chapter stale，Chapter 新 revision 又恢复 fresh。异步 Workflow 重复提交返回同一 Run 且 `deduplicated=true`。该 Run 最终为 `resumable/review_parse_failed`，因此没有自动 import/accept；本次验收确认的是队列、精确 revision 绑定和幂等边界，而不是成功正文产物。

自动化与运行验证：

```text
14/14 frontend pure/API tests passed
Vue bundle verification passed (375344 bytes)
CSS parse passed (255 top-level rules)
Frontend Docker/Vite production build passed
Frontend 18081 root/assets/healthz/API proxy passed
434/434 backend full regression passed in 193.326s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

验收记录保存在 `data/sprint08e2_acceptance.json`；既有数据库和验收数据未删除。完整发布验收见 `docs/sprints/Sprint08E2.md`。下一项为 Sprint 09 工程化与安全边界。

## v0.15.0-alpha.31 — Sprint 09A 鉴权与多用户安全边界

NovelForge 已加入可选的 Bearer 身份层。运维通过 `AUTH_TOKENS_JSON` 将高熵 token 映射到固定 `user_id` 和 roles；启用鉴权时，无 token/错误 token 分别返回 401，配置为空、JSON 无效、token 过短或 principal 不完整时拒绝安全运行。默认 `AUTH_ENABLED=false` 保留本地单机开发兼容。

统一授权依赖递归检查 path、query、JSON body 与 metadata 中的用户/小说声明。普通用户只能声明令牌绑定的 `user_id`；已存在的 Novel、Workflow Run 与 Memory 会反查所有者，跨用户资源统一隐藏为 404。普通用户不能无用户过滤列出全部项目/Run，也不能访问 Queue、Worker、DLQ、Operations 与 Prometheus；`admin` role 保留跨用户运维权限。

`/api/v1/health` 保持匿名，其他业务 operation 在 OpenAPI 中声明 `BearerAuth`；`GET /api/v1/auth/me` 返回当前身份但绝不返回 token。Vue 工作台增加会话令牌输入，令牌只进入 `sessionStorage` 和 Authorization header，认证身份会校正创作者 ID。Compose 与 `.env.example` 只提供无 secret 的配置入口。

当前自动化验证：

```text
6/6 Authentication focused tests passed
15/15 Novel Project focused tests passed
9/9 Workflow Run focused tests passed
15/15 Memory Lifecycle focused tests passed
15/15 frontend tests passed
Vue bundle verification passed (377316 bytes)
440/440 backend full regression passed in 112.999s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

生产前端镜像以 16/16 steps 构建完成，root、healthz 与 Nginx API proxy 均返回 HTTP 200。隔离 Uvicorn 在 `AUTH_ENABLED=true` 下实际验证匿名 401、正确 token 200、身份不匹配 403、跨用户 Novel 404、普通用户运维 403 与管理员运维 200；验收脚本随后关闭隔离进程，主 Backend 保持默认开发模式。验收记录保存在 `data/sprint09a_acceptance.json`；完整状态见 `docs/sprints/Sprint09A.md`。下一项为 Sprint 09B Provider 配置与 Prompt 版本。

## v0.15.0-alpha.32 — Sprint 09B.1 Provider 能力与配置状态

LLM Registry 在保持 `providers: ["deepseek", "qwen_local"]` 兼容字段的同时，增加不可变能力描述：Provider 类型、默认/支持模型、streaming、reasoning effort 与 key 要求。Catalog 明确区分 `registered`、`configured` 与 `available`；普通查询不实例化 Provider 或访问网络，只有显式 `probe=true` 才并行执行健康检查，单路超时由 `timeout_ms` 限制，错误统一收敛为不含异常详情的稳定代码。

Qwen OpenAI-compatible base URL 与模型改由 Settings/Compose 提供，并确定性补全 `/v1`。DeepSeek 修复了错误的大写 Settings 属性访问，支持配置默认模型、保留 `temperature=0`，空 key 会以明确配置异常失败。配置示例只提供空 key，占位文件与 Catalog 均不输出 secret 或 base URL。

Vue 工作台的单章 Workflow 表单已接入 Catalog，按配置与探测状态展示 Provider，并根据能力选择模型；目录不可访问时保留手工输入兼容路径。生产前端镜像、root、healthz 与 Nginx API proxy 已验证。真实 Catalog 探测中本地 `qwen_local/qwen3:8b` 可用；已配置但当前不可达的 DeepSeek 独立报告 `health_check_failed`，不会被错误标记为未注册或未配置。

自动化与运行验证：

```text
7/7 Provider focused tests passed
4/4 Qwen reasoning tests passed
16/16 frontend tests passed
447/447 backend full regression passed in 98.357s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
Frontend Docker/Vite production build passed (16 BuildKit steps)
Frontend root / healthz / API proxy returned HTTP 200
Real Qwen Provider probe passed
```

验收记录保存在 `data/sprint09b1_acceptance.json`；既有业务与验收数据库未删除。下一项为 Sprint 09B.2 Prompt revision 与可审计选择，OpenAI/Claude/DashScope 的新增适配在后续独立子 Sprint 实施。

## v0.15.0-alpha.33 — Sprint 09B.2 Prompt revision 与可审计选择

代码内 Prompt Registry 为 Novel、Character、World、Plot、Chapter、Review、Rewrite、Planner、Consistency fact extraction 和 Memory extraction 注册 20 个稳定 Prompt identity。每个 identity 支持多个不可变 revision、显式 revision 解析和确定性的 current revision；`GET /api/v1/prompts` 只返回 ID、分类、描述与 revision 列表，不返回 Prompt 正文。

每次 Agent LLM 调用记录两条 provenance：实际 system prompt 的 revision/SHA-256，以及包含 Canon、Grounding、Memory、External Knowledge、用户指令等最终 provider-visible messages 的 canonical request revision/SHA-256。Agent 边界会丢弃请求 metadata 和 Provider 响应中同名的伪造 provenance，再写入服务端计算结果。Planner response 与 Workflow step metadata 继承该记录；Workflow 原有 JSON 持久化路径因此无需新表或 schema migration 即可跨重启保留。

Consistency fact extraction 与 Memory extraction 不经过 Agent，已分别直接接入相同 provenance。Consistency analysis response 返回记录；LLM 提取出的 Memory 在 metadata 中持久保存对应 system/request revision 与摘要。摘要不包含 Prompt、正文、key 或 endpoint 原文。

Vue Planner candidate 区与 Workflow Inspector 聚合显示 `prompt_id@revision`，用于作者核对实际选择；界面不能编辑或伪造 revision。在线 Prompt 编辑、数据库 Prompt 表和运行中热替换均不属于本 Sprint。

自动化与运行验证：

```text
6/6 Prompt Catalog focused tests passed
18/18 Consistency tests passed
15/15 Memory Lifecycle tests passed
35/35 Planner tests passed
25/25 Chapter Workflow tests passed
7/7 Agent tests passed
6/6 Authentication tests passed
18/18 frontend tests passed
453/453 backend full regression passed in 92.618s
Python compileall passed
Frontend Docker/Vite production build passed (16 BuildKit steps)
```

真实 `qwen3:8b` 验收复用保留小说 `85c4dff6-7530-459f-a3f7-1eaf34fc5c76`，生成 Novel Plan candidate 使用 3747 tokens、约 33.0 秒并以 `finish_reason=stop` 完成。响应包含 `agent.planner.system@r1` 与 `agent.planner.request@r1` 两条 64 位摘要，最终组装 request 为 6509 字符；`persisted=false`，生成前后 Novel Plan revision 均为 2。验收没有接受 candidate、没有删除既有数据。

验收记录保存在 `data/sprint09b2_acceptance.json`。下一项为 Sprint 09B.3 OpenAI、Claude 与 DashScope Provider 适配。

## v0.15.0-alpha.34 — Sprint 09B.3 OpenAI / Claude / DashScope Provider 适配

Provider Registry 新增 `openai`、`claude` 与 `dashscope`，与既有 `deepseek`、`qwen_local` 一起复用同一 `ChatRequest`、`ChatResponse`、streaming、Catalog 和 Prompt provenance 边界。云 key、base URL 与默认 model 只从 Settings/环境读取；Catalog 与日志均不输出 secret 或 endpoint。

OpenAI adapter 使用异步 Chat Completions，并映射现代 `max_completion_tokens` 与 reasoning effort。DashScope 使用阿里云百炼官方支持的 OpenAI-compatible API，把 thinking 映射为 `enable_thinking`。Claude 使用官方异步 Messages SDK，确定性拆分 system 与对话消息、归一化 usage/finish reason，并拒绝缺少原生 content-block 语义的普通文本 tool message。三者均支持 SSE streaming，并通过非计费 Models API 接入既有有界健康探测。

新增云 Provider 未配置 key 时保持 `registered=true`、`configured=false`，`probe=true` 返回 `available=false/not_configured` 且不实例化 client。当前运行探测确认本地 `qwen_local/qwen3:8b` 可用；DeepSeek 已配置但当前不可达；OpenAI、Claude、DashScope 均未配置，因此本 Sprint 不宣称付费云生成在线验收通过。

自动化与运行验证：

```text
14/14 Provider focused tests passed
4/4 Qwen reasoning tests passed
7/7 Agent tests passed
35/35 Planner tests passed
18/18 frontend tests passed
460/460 backend full regression passed in 111.535s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
Backend image with Anthropic SDK built successfully
```

完整状态见 `docs/sprints/Sprint09B3.md`，验收记录保存在 `data/sprint09b3_acceptance.json`。Sprint 09B 已完成，下一项为 Sprint 09C 迁移、备份与导出。

## v0.15.0-alpha.35 — Sprint 09C.1 离线一致备份与安全恢复基础

新增固定 authority allowlist 的离线备份 CLI，覆盖 `novels.db`、`workflow_runs.db`、`memory.db`、`external_knowledge.db`、`temporal_graph.db` 与两组 FAISS index/mapping。五个 SQLite 没有跨库事务锁，因此创建备份要求 Backend 与 Worker 同时停写，并在 Manifest 明确记录 `offline_required`，不宣称在线原子快照。

SQLite 使用 Backup API 复制并执行 integrity check；FAISS 实际加载并校验 dimension、`ntotal` 与 ID mapping 数量。严格 Manifest 记录 SHA-256、文件大小与非敏感结构元数据，拒绝未知/缺失文件、路径穿越、符号链接、部分 FAISS 对和非法重建状态。

恢复默认 dry-run，只允许 staging 后写入不存在的新目录，拒绝覆盖生产数据或已有目标。运维人员必须先恢复到隔离目录并验证，再通过受控部署切换。完整操作步骤和安全边界见 `docs/operations/BACKUP_RESTORE.md`。

当前自动化专项 `12/12`、Backend 全量回归 `472/472` 与 Frontend `18/18` 均通过；Python compileall、两套 Compose config 和 Frontend Docker/Vite 生产构建通过。专项包含 Windows bind mount 不支持目录原子重命名时的安全降级验证。

真实演练 `sprint09c1-20260816T234604` 在 Backend/Worker 停写窗口创建并验证 9 文件快照，无 FAISS 重建项；dry-run 写入 0 文件，隔离恢复写入 9 文件。恢复文件哈希零差异，SQLite integrity 与 FAISS/mapping 数量一致性通过；服务恢复后 Backend/Frontend HTTP 200，Worker running 且 accepting。既有数据未删除或覆盖。验收记录保存在 `data/sprint09c1_acceptance.json`。下一项为 Sprint 09C.2 Schema migration。

## v0.15.0-alpha.36 — Sprint 09C.2 显式 Schema Migration

五个 SQLite authority 现在拥有显式 schema version 1、完整业务表/列/命名索引契约，以及逐库 `novelforge_schema_migrations` ledger。管理 CLI 提供只读 status、需要已验证 09C.1 备份与停写确认的 upgrade，以及包含 integrity、foreign key、schema 和 ledger checksum 的严格 verify。

升级会先调用已发布 Storage 的兼容初始化补齐历史列/索引，再对全部五库预检；无法补齐的缺列不会被盖章。每库在独立事务中写 ledger 与 `PRAGMA user_version=1`，失败回滚，重复执行幂等。由于 SQLite 没有跨库事务，中断后通过 ledger 续跑或从完整维护前备份恢复，不虚构跨库原子性。

Backend/Worker 在加载业务模块前拒绝高于程序支持版本的数据库，并在启动阶段验证 v0/v1 契约；v0 在本次兼容窗口仍可运行。标准脚本先从同一备份恢复隔离副本并完成 upgrade/verify，成功后才迁移生产五库。

专项 `10/10`、Authentication `6/6`、Worker `9/9`、Frontend `18/18` 通过；Backend 全量在迁移前与生产 v1 迁移后分别 `482/482` 通过。Backend、Frontend、Worker 生产镜像构建成功。

真实维护窗口使用备份 `sprint09c2-20260817T002047`，完整快照 9 个文件；隔离副本和生产五库均由 v0 升级到 v1 并严格 verify。所有库 ledger/checksum 有效、integrity 为 `ok`、foreign-key error 为 0。迁移前后业务表摘要一致，只有 Worker 重启按设计新增一条运行时注册记录；既有数据未删除或覆盖。服务恢复后 Backend/Frontend HTTP 200、OpenAPI `0.15.0-alpha.36` 且 Worker 正常注册。完整状态见 `docs/sprints/Sprint09C2.md`，验收记录保存在 `data/sprint09c2_acceptance.json`。下一项为 Sprint 09C.3 小说导出。

## v0.15.0-alpha.37 — Sprint 09C.3 小说导出

新增 `GET /api/v1/novels/{novel_id}/export`，在内存中生成确定性 ZIP，不在服务端落地导出文件。包内包含当前 Project、Story Bible、Canonical Entity Registry、Novel Plan、Story Arc、Chapter Plan，以及仅显式接受的 Manuscript 正文和来源 revision 元数据；草稿、superseded revision 与未接受候选不会进入导出。

`manifest.json` 声明格式版本、应用版本、小说/规划 revision、内容选择规则和计数，并为 manifest 之外每个成员记录字节数与 SHA-256；响应头提供 manifest 自身 SHA-256。固定 ZIP 时间戳、排序和 JSON 序列化使相同 authority 快照产生完全相同的 archive bytes。导出前后重新采集所有相关聚合 revision 指纹，并发修改返回 HTTP 409；接受正文内容与冻结 hash 不一致时 fail closed。

鉴权继续由既有 Bearer 中间件按 `novel_id` 执行，其他用户看到 HTTP 404；所有领域读取都显式限定同一 novel。Vue 工作台提供“导出小说”下载按钮并复用会话 Bearer token。Export 专项 `7/7`、Authentication `7/7`、Backend 全量 `490/490`、Frontend `19/19` 通过，Backend/Frontend/Worker 生产镜像构建成功。

真实生产 drill 对已有 2 章 accepted manuscript 的小说执行两次 HTTP 导出，每包 11 个成员；逐成员长度/hash、响应 manifest hash 和两次 archive bytes 全部一致，临时 ZIP 已自动清理。Backend HTTP 200、OpenAPI `0.15.0-alpha.37` 且导出路由存在；Frontend `.37` 镜像重建后 HTTP 200，生产 bundle 包含“导出小说”入口；生产数据未修改。完整状态见 `docs/sprints/Sprint09C3.md`，验收记录保存在 `data/sprint09c3_acceptance.json`。Sprint 09C 已完成，下一项为 Sprint 09D CI 与发布工程。

## v0.15.0-alpha.38 — Sprint 09D CI 与发布工程

新增 PR/master CI 与 `v*` tag Release workflow，把 Backend 全量回归、Frontend test/build/bundle、两套 Compose config、Backend/Frontend/Worker 镜像构建和版本封板变为自动门禁。原先写死的 Windows Backend build context 已改为 `./backend`，可在不同安装目录和 Linux runner 使用；Backend `.dockerignore` 排除测试、字节码、缓存、数据、日志与本地环境文件，避免污染发布上下文。

`app.release_engineering` 校验 Backend、Frontend 与 package-lock 四处版本、目标 tag、同版本 PASS acceptance 和 Compose 可移植性。源码 release ZIP 使用固定成员顺序/时间戳/压缩，内置逐文件长度与 SHA-256 manifest；manifest 只记录 acceptance path/sprint/PASS 摘要，不打包可能含生产标识的原始验收 JSON。独立 verify 拒绝篡改、重复/额外成员和不安全路径。tag workflow 同时导出三镜像 gzip、生成 `SHA256SUMS`、上传 Actions artifact 并创建或更新 GitHub Release，不假设未配置的镜像 registry。

升级流程要求先完成 09C.1 离线一致备份；回滚必须先验证目标旧版本 schema 上限，数据库版本不兼容时禁止直接启动旧 Backend，只能从隔离验证过的升级前完整备份恢复。Release 专项 `8/8`、Backend 全量 `498/498`、Frontend `19/19`、两套 Compose config 与三镜像生产构建通过；`.38` release drill 生成 237 文件确定性源码包，并通过独立复验与逐字节重建对比，最终哈希记录在 acceptance 与制品 `SHA256SUMS`。完整状态见 `docs/sprints/Sprint09D.md`；Sprint 09D 已完成，下一项为 Sprint 1.0。

## v0.16.0-alpha.1 — Sprint 10A 插件契约与只读目录

新增 `app.plugins` 边界和 Manifest v1。插件必须声明稳定 ID、自身 SemVer、entry point、capability、permission、Plugin API 版本以及 Core 最低/最高兼容范围；未知字段、重复声明、非法坐标和不成立的版本窗口由 Pydantic fail closed。Core 自有 SemVer 比较器支持 prerelease，兼容窗口采用 `min inclusive / max exclusive`，Plugin API 必须精确匹配。

Backend 只扫描 `PLUGIN_ROOT` 一级 package 的 `novelforge-plugin.json`，单文件读取严格限制 64 KiB、package 数限制 100，并拒绝 package/manifest 符号链接。`PLUGIN_ENABLED_JSON` 是无通配符精确 allow-list；启用项缺失、重复、损坏或不兼容会阻止启动。Catalog 返回稳定错误码、manifest SHA-256 和声明，但不返回绝对路径、文件正文或异常详情。

`GET /api/v1/plugins` 受既有 Bearer 保护并要求 `admin` role。Backend/Worker 通过 Compose 只读挂载 `./plugins`，本地插件默认不进入 Git 或源码发行包。本阶段明确保持 `execution_enabled=false` 与 `loaded=false`：发现过程不会导入 entry point，也没有上传/远程安装 API；permission 只是审计声明，不代表授权。

Plugin 专项 `9/9`、Release `8/8`、Authentication `7/7`、Schema Migration `10/10`、Backend 全量 `507/507`、Frontend `19/19` 和两套 Compose config 已通过。Backend/Frontend/Worker 三镜像生产构建与 live Plugin drill 通过：OpenAPI `0.16.0-alpha.1`、Plugin API `1`、插件根可用、空目录、配置有效，Backend/Frontend HTTP 200、Worker running，且执行仍为关闭。完整状态见 `docs/sprints/Sprint10A.md`；Sprint 10A 已完成，下一项为 Sprint 10B 受控运行时激活。

## v0.16.0-alpha.2 — Sprint 10B 受控插件运行时

Manifest v2 在 10A 契约上增加 entry point SHA-256。运行时在激活前重新核对已发现 Manifest 的哈希，只接受插件一级目录中的单文件 Python entry point，限制源码为 1 MiB，拒绝符号链接，并直接编译一次读取且已验证的字节。Manifest v1 继续用于只读 Catalog，但不能执行；执行总开关默认关闭。

`PLUGIN_PERMISSION_GRANTS_JSON` 为每个插件提供显式权限准入。插件上下文只公开版本、声明能力、已授予权限、扩展注册与 cleanup 注册；扩展必须属于已声明 capability 且使用插件 ID 命名空间。激活成功后上下文封存，所有扩展一次性提交；任一插件失败时，候选和本轮已激活插件按逆序卸载并回滚扩展。同步/异步 activate、deactivate 和 cleanup 均受支持，Catalog 暴露 active order、runtime generation 和稳定错误码而不返回异常详情。

Backend 与独立 Worker 都在启动时激活，在正常退出、Worker 异常或 Backend 启动取消时保证清理。本运行时面向本地可信、已审计且哈希固定的插件，不是恶意代码沙箱；permission 是准入边界而非 Python/OS 权限隔离。系统仍不提供上传、远程安装、在线升级或热重载 API，具体 capability 连接 Core 业务注册表需要后续 Core-owned adapter。

Plugin Runtime 专项 `12/12`、Plugin Catalog `9/9`、Worker `9/9`、Authentication `7/7`、Release Engineering `8/8`、Schema Migration `10/10`、Backend 全量 `519/519` 与 Frontend `19/19` 均通过；Python compileall、PowerShell drill 语法、两套 Compose config、`git diff --check` 和 Frontend Docker/Vite 生产构建通过。

真实 live drill 使用不进入 Git 的临时 Manifest v2 fixture，在 Backend 和 Worker 两个容器内完成完整性固定、权限准入和实际激活；Backend Catalog `loaded=true`，Worker 激活标记存在，三服务健康。演练随后重建 Backend/Worker 恢复 `PLUGIN_EXECUTION_ENABLED=false`，精确删除 fixture，业务数据未修改。Backend/Frontend/Worker 镜像分别为 `45d48255...d4ad`、`e9e0d379...c869`、`22d6dc67...c575`。完整状态见 `docs/sprints/Sprint10B.md` 和 `docs/operations/PLUGINS.md`；Sprint 10B 已完成，下一项为 1.0 Release Candidate 收口。

## v1.0.0-rc.1 — Sprint 10C 1.0 RC 本地部署硬化

标准 Compose 将 Frontend `18081` 与 Backend `18080` 默认绑定到 `127.0.0.1`，Ollama `11434` 固定为 loopback；Backend Settings 和 Compose 同时改为 `DEBUG=false`。新启动门在插件加载与索引恢复之前校验部署暴露：绑定只接受 IPv4 字面量，非 loopback 必须启用鉴权并关闭 Debug，否则以稳定 `unsafe_network_exposure` 拒绝启动；显式风险 override 会记录到启动状态。

Nginx 关闭版本暴露，并为 SPA、静态资源、healthz 与代理 API 增加 nosniff、frame deny、no-referrer 和同源 CSP。Release Engineering 现在同时校验应用版本、Backend Python 包 `pyproject.toml`、Frontend 和 lockfile 五处身份，避免 RC 制品内部版本分裂。

Deployment Security 专项 `6/6`、Release Engineering `9/9`、Plugin Catalog `9/9`、Plugin Runtime `12/12`、Authentication `7/7`、Frontend `21/21` 与 Backend 全量 `526/526` 均通过；Python compileall、两套 Compose config 和 `git diff --check` 通过，三镜像生产构建完成。

真实 RC 安全演练确认 Backend、Frontend 与 Ollama 分别只绑定 `127.0.0.1:18080`、`127.0.0.1:18081` 与 `127.0.0.1:11434`；不安全的非 loopback 暴露 fail closed，鉴权启用且 Debug 关闭的配置可准入。运行态 Debug、风险 override 和插件执行均关闭，安全响应头存在，Backend/Frontend/Ollama HTTP 200，Worker 正常运行。三镜像分别为 `dcd952e4...a0ee`、`0b62f0cc...62bc`、`b006f3e3...41c9`。完整边界见 `docs/operations/DEPLOYMENT_SECURITY.md`，验收记录保存在 `data/sprint10c_acceptance.json`；Sprint 10C 已完成，下一项为 Sprint 10D RC 依赖锁定与升级/回滚矩阵。

## v1.0.0-rc.2 — Sprint 10D RC 依赖锁定与升级/回滚矩阵

Backend 的声明性依赖范围继续保存在 `pyproject.toml`，生产解析则固定为 `requirements.lock` 中从已验收 RC1 镜像采集的 34 个 Linux/Python 3.12 分发包。Backend 与 Worker 镜像、CI 和 Release workflow 都只从 lock 安装并执行 `pip check`，不再升级 pip 或重新解析宽范围项目依赖；旧 `requirements.txt` 只保留为指向 lock 的兼容入口。Frontend 继续由 lockfile v3、80 个带 resolved/integrity 的包和 `npm ci` 管理。

Python、Node、Nginx 与 Ollama 镜像均固定到 SHA-256 digest，9 个 GitHub Action 使用完整 40 位 commit。Release Engineering 会验证精确且排序的 Backend lock、Frontend integrity、Dockerfile/Compose digest、Action commit、lock 安装命令和源码制品收录，任何范围依赖、缺失直接依赖、可变 image tag 或 Action tag 都 fail closed。Dependabot 只提出候选更新，不能绕过专项、全量和 live 门禁。

`release-compatibility.json` 将 schema v1、允许的 RC1/Alpha2 升级来源、RC1 回滚上限与未知路径阻断变成机器可读契约。`release_engineering.cli assess` 对已声明同 schema 路径返回 `direct`，对未知路径返回 `blocked`，对高于旧版本上限的 schema 返回 `restore_backup`；所有已知升级/回滚仍要求先完成离线备份。生产演练脚本会把备份恢复到隔离目录，再用保留的 RC1 镜像验证旧 Backend 能打开 schema v1，不让旧版本接触生产数据目录。

真实 lock contract 已确认 Backend 34 包、Frontend 80 包、4 个 digest-pinned image 和 9 个 commit-pinned Action。Release Engineering `12/12`、Dependency Runtime Lock `3/3`、Schema Migration `10/10`、Frontend `21/21` 与 Backend 全量 `532/532` 均通过；Python compileall、两套 Compose config、`git diff --check`、三镜像构建和 Backend/Worker 镜像内 lock 精确对照均通过。

离线备份 `sprint10d-20260817T160013` 与 9 文件隔离恢复通过。RC1 Backend 只挂载隔离恢复目录，在 schema v1 上启动并返回 HTTP 200；RC2 Backend/Frontend 均返回 HTTP 200，Worker 正常运行，清理复验确认回滚探针已删除。三镜像分别为 `43ee7fb5...53fa`、`0b62f0cc...62bc`、`f801cc6c...2b29`。完整边界见 `docs/operations/DEPENDENCY_LOCKS.md`、`docs/sprints/Sprint10D.md` 与 `data/sprint10d_acceptance.json`；Sprint 10D 已完成，下一项为完整产品旅程、RC 缺陷清零和正式 `v1.0.0` Go/No-Go。
