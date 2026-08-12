from fastapi import APIRouter, HTTPException, Query, status

from app.knowledge.manager import external_knowledge_manager
from app.knowledge.schemas import (
    ExternalKnowledgeRetrieveRequest,
    ExternalKnowledgeSourceCreate,
    ExternalKnowledgeSourceUpdate,
)
from app.knowledge.storage import (
    ExternalKnowledgeConflictError,
    ExternalKnowledgeNotFoundError,
)


router = APIRouter(prefix="/external-knowledge")


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"External knowledge source not found: {exc}",
    )


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def create_external_knowledge_source(
    payload: ExternalKnowledgeSourceCreate,
):
    try:
        result = await external_knowledge_manager.create_source(payload)
    except ExternalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": 0, "message": "created", "data": result}


@router.get("/sources")
async def list_external_knowledge_sources(
    user_id: str = Query(min_length=1, max_length=128),
    knowledge_base_id: str = Query(min_length=1, max_length=128),
):
    result = await external_knowledge_manager.storage.list_sources(
        user_id,
        knowledge_base_id,
    )
    return {"code": 0, "message": "success", "data": result}


@router.get("/sources/{source_id}")
async def get_external_knowledge_source(
    source_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    knowledge_base_id: str = Query(min_length=1, max_length=128),
):
    result = await external_knowledge_manager.storage.get(
        source_id,
        user_id,
        knowledge_base_id,
    )
    if result is None:
        raise _not_found(ExternalKnowledgeNotFoundError(source_id))
    return {"code": 0, "message": "success", "data": result}


@router.get("/sources/{source_id}/revisions")
async def list_external_knowledge_source_revisions(
    source_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    knowledge_base_id: str = Query(min_length=1, max_length=128),
):
    try:
        result = await external_knowledge_manager.storage.list_revisions(
            source_id,
            user_id,
            knowledge_base_id,
        )
    except ExternalKnowledgeNotFoundError as exc:
        raise _not_found(exc) from exc
    return {"code": 0, "message": "success", "data": result}


@router.put("/sources/{source_id}")
async def update_external_knowledge_source(
    source_id: str,
    payload: ExternalKnowledgeSourceUpdate,
):
    try:
        result = await external_knowledge_manager.update_source(
            source_id,
            payload,
        )
    except ExternalKnowledgeNotFoundError as exc:
        raise _not_found(exc) from exc
    except ExternalKnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": 0, "message": "updated", "data": result}


@router.delete("/sources/{source_id}")
async def delete_external_knowledge_source(
    source_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    knowledge_base_id: str = Query(min_length=1, max_length=128),
):
    try:
        result = await external_knowledge_manager.delete_source(
            source_id,
            user_id,
            knowledge_base_id,
        )
    except ExternalKnowledgeNotFoundError as exc:
        raise _not_found(exc) from exc
    return {"code": 0, "message": "deleted", "data": result}


@router.post("/retrieve")
async def retrieve_external_knowledge(
    payload: ExternalKnowledgeRetrieveRequest,
):
    result = await external_knowledge_manager.retrieve(payload)
    return {"code": 0, "message": "success", "data": result}
