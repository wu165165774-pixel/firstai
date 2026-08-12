from fastapi import APIRouter, BackgroundTasks

from app.llm.bootstrap import registry
from app.llm.manager import LLMManager
from app.llm.schemas import (
    ChatRequest,
    ChatMessage,
)

from app.memory.context import memory_context_builder
from app.memory.extractor import memory_extractor
from app.knowledge.context import (
    enforce_external_knowledge_citations,
    external_knowledge_context_builder,
)


router = APIRouter()


llm_manager = LLMManager(
    registry
)


@router.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
):

    # metadata 可能为空，先做保护
    metadata = request.metadata or {}

    user_id = metadata.get(
        "user_id",
        "default_user",
    )

    novel_id = metadata.get(
        "novel_id",
        "default_novel",
    )

    # 提取本轮最后一条用户消息
    query = ""

    for message in reversed(request.messages):

        role = (
            message.role
            if hasattr(message, "role")
            else message.get("role")
        )

        if role != "user":
            continue

        content = (
            message.content
            if hasattr(message, "content")
            else message.get("content")
        )

        query = (content or "").strip()
        break

    # 根据当前问题检索长期记忆
    memory_context_args = {
        "user_id": user_id,
        "novel_id": novel_id,
        "query": query,
    }
    session_id = metadata.get("session_id")
    if session_id:
        memory_context_args["session_id"] = str(session_id)

    memory_context = await memory_context_builder.build(
        **memory_context_args
    )

    if memory_context:

        request.messages.insert(
            0,
            ChatMessage(
                role="system",
                content=memory_context,
            ),
        )

    knowledge_base_ids = metadata.get(
        "external_knowledge_base_ids",
        [],
    )
    external_context = ""
    if isinstance(knowledge_base_ids, list) and knowledge_base_ids and query:
        external_context = await external_knowledge_context_builder.build(
            user_id=str(user_id),
            knowledge_base_ids=[str(item) for item in knowledge_base_ids],
            query=str(
                metadata.get("external_knowledge_query", query)
            ),
            top_k=4,
        )
        if external_context:
            request.messages.insert(
                1 if memory_context else 0,
                ChatMessage(
                    role="system",
                    content=external_context,
                    metadata={
                        "source": "external_knowledge",
                        "priority": "P6",
                        "citation_required": True,
                        "knowledge_base_ids": knowledge_base_ids,
                    },
                ),
            )

    # 调用当前选择的模型
    result = await llm_manager.chat(
        request.provider,
        request,
    )

    if external_context:
        if isinstance(result, dict):
            raw_content = str(result.get("content", "") or "")
        else:
            raw_content = str(getattr(result, "content", "") or "")
        normalized_content, external_citations = (
            enforce_external_knowledge_citations(
                raw_content,
                external_context,
            )
        )

        external_metadata = {
            "external_knowledge_used": True,
            "external_knowledge_priority": "P6",
            "external_knowledge_citations": external_citations,
            "memory_extraction_skipped": True,
            "memory_extraction_skip_reason": (
                "external_knowledge_isolation"
            ),
        }
        if isinstance(result, dict):
            result["content"] = normalized_content
            result_metadata = result.get("metadata")
            if not isinstance(result_metadata, dict):
                result_metadata = {}
                result["metadata"] = result_metadata
            result_metadata.update(external_metadata)
        else:
            result.content = normalized_content
            result_metadata = getattr(result, "metadata", None)
            if not isinstance(result_metadata, dict):
                result_metadata = {}
                result.metadata = result_metadata
            result_metadata.update(external_metadata)

    # 提取模型回答
    answer = ""

    if isinstance(result, dict):

        answer = result.get(
            "content",
            "",
        ) or ""

    elif hasattr(result, "content"):

        answer = result.content or ""

    # 后台执行记忆提取，不阻塞聊天接口返回
    if query and not external_context:

        background_tasks.add_task(
            memory_extractor.extract,
            user_id,
            novel_id,
            query,
            answer,
            request.provider,
            request.model or "qwen3:8b"
        )


    return result
