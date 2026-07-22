# Sprint 03A：LLM Core

## 目标
建立与具体模型厂商无关的 LLM 核心抽象层。

## 交付内容
- ChatMessage
- ChatRequest
- ChatResponse
- TokenUsage
- BaseChatProvider
- ProviderRegistry
- LLMManager
- LLM 异常类型
- 单元测试

## 调用链
Application / Service -> LLMManager -> ProviderRegistry -> BaseChatProvider -> Provider

## 当前限制
本 Sprint 不调用真实模型。下一阶段接入 DeepSeek。
