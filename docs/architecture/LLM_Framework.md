# LLM Framework Architecture

业务层只依赖 LLMManager、ChatRequest、ChatResponse 和 ChatMessage。

具体 SDK 只存在于 Provider 层。

新增 Provider 时：
1. 实现 BaseChatProvider
2. 注册 Provider
3. 不修改业务层

下一阶段：DeepSeek Provider、环境变量配置、API Key 安全加载和 Chat API。
