from fastapi import APIRouter, BackgroundTasks

from app.llm.bootstrap import registry
from app.llm.manager import LLMManager
from app.llm.schemas import (
    ChatRequest,
    ChatMessage,
)

from app.memory.context import memory_context_builder
from app.memory.extractor import memory_extractor


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
    memory_context = await memory_context_builder.build(
        user_id=user_id,
        novel_id=novel_id,
        query=query,
    )

    if memory_context:

        request.messages.insert(
            0,
            ChatMessage(
                role="system",
                content=memory_context,
            ),
        )

    # 调用当前选择的模型
    result = await llm_manager.chat(
        request.provider,
        request,
    )

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
    if query:

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