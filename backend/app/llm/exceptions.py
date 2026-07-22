class LLMError(Exception):
    """Base exception for the LLM subsystem."""

class ProviderNotFoundError(LLMError):
    pass

class ProviderAlreadyRegisteredError(LLMError):
    pass

class ProviderConfigurationError(LLMError):
    pass

class ProviderRequestError(LLMError):
    pass
