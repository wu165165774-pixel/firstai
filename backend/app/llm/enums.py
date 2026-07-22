from enum import StrEnum

class ProviderType(StrEnum):
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    CLAUDE = "claude"
    QWEN = "qwen"
    OLLAMA = "ollama"
