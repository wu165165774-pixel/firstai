# NovelForge 当前实现状态

## 1. 文档信息

* 项目名称：NovelForge
* 当前开发分支：master
* 当前代码版本：v0.13.0-alpha.1
* 文档状态：当前实现快照
* 快照日期：2026-08-05
* 当前阶段：长期记忆与 Vector RAG 基础能力已实现，混合检索整合进行中

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
    ├── DeepSeek Provider
    └── Qwen Local Provider
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
qwen_local
```

DeepSeek Provider 框架已经存在，但尚未使用真实 DeepSeek API Key 完成正式验收。

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
* 当前代码版本：v0.13.0-alpha.1
* 文档状态：当前实现快照
* 快照日期：2026-08-05
* 当前阶段：长期记忆与 Vector RAG 基础能力已实现，混合检索整合进行中

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
    ├── DeepSeek Provider
    └── Qwen Local Provider
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
qwen_local
```

DeepSeek Provider 框架已经存在，但尚未使用真实 DeepSeek API Key 完成正式验收。

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
