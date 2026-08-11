from fastapi import (
    APIRouter,
    HTTPException,
)

from app.memory.manager import memory_manager
from app.memory.schemas import (
    MemoryItem,
    MemoryLifecycleSweepRequest,
    MemoryPromotionRequest,
    MemorySessionCloseRequest,
    MemoryTier,
)
from app.memory.storage.sqlite import (
    MemoryLifecycleConflictError,
    MemoryNotFoundError,
)


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
    memory_tier: MemoryTier | None = None,
    session_id: str | None = None,
    include_expired: bool = False,
):

    result = await memory_manager.get_memory(
        user_id,
        novel_id,
        memory_type,
        memory_tier,
        session_id,
        include_expired,
    )

    return {
        "code": 0,
        "message": "success",
        "data": result,
    }


@router.post("/memory/{memory_id}/promote")
async def promote_memory(
    memory_id: str,
    payload: MemoryPromotionRequest,
):

    try:
        result = await memory_manager.promote_memory(
            memory_id,
            payload,
        )
    except MemoryNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except MemoryLifecycleConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return {
        "code": 0,
        "message": "promoted",
        "data": result,
    }


@router.get("/memory/{memory_id}/lifecycle/events")
async def list_memory_lifecycle_events(
    memory_id: str,
):

    events = await memory_manager.list_lifecycle_events(
        memory_id
    )
    if not events:
        raise HTTPException(
            status_code=404,
            detail="Memory lifecycle events not found.",
        )

    return {
        "code": 0,
        "message": "success",
        "data": events,
    }


@router.post("/memory/lifecycle/sweep")
async def sweep_memory_lifecycle(
    payload: MemoryLifecycleSweepRequest,
):

    result = await memory_manager.sweep_lifecycle(
        user_id=payload.user_id,
        novel_id=payload.novel_id,
        session_id=payload.session_id,
        now=payload.now,
        dry_run=payload.dry_run,
    )

    return {
        "code": 0,
        "message": "success",
        "data": result,
    }


@router.post("/memory/sessions/{session_id}/close")
async def close_memory_session(
    session_id: str,
    payload: MemorySessionCloseRequest,
):

    result = await memory_manager.close_session(
        user_id=payload.user_id,
        novel_id=payload.novel_id,
        session_id=session_id,
    )

    return {
        "code": 0,
        "message": "closed",
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
