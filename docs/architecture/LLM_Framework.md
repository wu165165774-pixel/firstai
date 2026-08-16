# LLM Framework Architecture

业务层只依赖 LLMManager、ChatRequest、ChatResponse 和 ChatMessage。

具体 SDK 只存在于 Provider 层。

新增 Provider 时：

1. 实现 BaseChatProvider
2. 注册 Provider
3. 声明 capability 与无网络 configuration check
4. 使用显式、有超时的 health probe
5. 不修改业务层

当前 Provider：

- `qwen_local`：Ollama OpenAI-compatible，本地默认能力。
- `deepseek`：DeepSeek OpenAI-compatible。
- `openai`：OpenAI Chat Completions。
- `claude`：Anthropic Messages API。
- `dashscope`：阿里云百炼 OpenAI-compatible。

可选云 Provider 只从环境读取 key、endpoint 与默认 model。Catalog 默认不访问网络；只有显式 `probe=true` 才调用厂商 Models API，并由统一超时与稳定错误码收敛。业务请求和 Catalog 均不得返回 key 或 endpoint。
