from enum import IntEnum



class ErrorCode(IntEnum):

    SUCCESS = 0


    # API
    INVALID_REQUEST = 10001


    # LLM
    LLM_TIMEOUT = 20001
    MODEL_NOT_FOUND = 20002
    PROVIDER_ERROR = 20003


    # Memory
    MEMORY_NOT_FOUND = 30001


    # RAG
    VECTOR_NOT_FOUND = 40001


    # Graph
    GRAPH_ERROR = 50001


    # Agent
    AGENT_ERROR = 60001