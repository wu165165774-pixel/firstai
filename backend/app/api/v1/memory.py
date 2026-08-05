from fastapi import (
    APIRouter,
    HTTPException,
)

from app.memory.manager import memory_manager
from app.memory.schemas import MemoryItem


router = APIRouter()


@router.post("/memory")
async def create_memory(
    memory: MemoryItem,
):

    result = await memory_manager.add_memory(
        memory
    )

    return {
        "code": 0,
        "message": "success",
        "data": result,
    }


@router.get(
    "/memory/{user_id}/{novel_id}"
)
async def query_memory(
    user_id: str,
    novel_id: str,
    memory_type: str | None = None,
):

    result = await memory_manager.get_memory(
        user_id,
        novel_id,
        memory_type,
    )

    return {
        "code": 0,
        "message": "success",
        "data": result,
    }


@router.delete(
    "/memory/{memory_id}"
)
async def delete_memory(
    memory_id: str,
):

    result = await memory_manager.delete_memory(
        memory_id
    )

    if result is None:

        raise HTTPException(
            status_code=404,
            detail="Memory not found.",
        )

    return {
        "code": 0,
        "message": "deleted",
        "data": result,
    }


@router.get("/retrieve")
async def retrieve(
    user_id: str,
    novel_id: str,
    query: str,
):

    result = await memory_manager.retrieve_memory(
        user_id,
        novel_id,
        query,
        top_k=5,
    )

    return {
        "code": 0,
        "message": "success",
        "data": result,
    }