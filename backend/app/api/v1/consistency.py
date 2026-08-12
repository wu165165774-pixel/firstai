from fastapi import APIRouter, HTTPException, status

from app.consistency.schemas import (
    ConsistencyAnalyzeRequest,
    ConsistencyAnalyzeResponse,
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
    ConsistencyConstraintRequest,
    ConsistencyConstraintResponse,
)
from app.consistency.service import (
    ConsistencyOutputError,
    consistency_engine,
)
from app.novels.storage import NovelProjectNotFoundError


router = APIRouter(prefix="/novels/{novel_id}/consistency")
service = consistency_engine


@router.post(
    "/constraints",
    response_model=ConsistencyConstraintResponse,
)
async def build_consistency_constraints(
    novel_id: str,
    payload: ConsistencyConstraintRequest,
) -> ConsistencyConstraintResponse:
    try:
        result = service.build_constraints(novel_id, payload)
    except NovelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ConsistencyConstraintResponse(data=result)


@router.post(
    "/check",
    response_model=ConsistencyCheckResponse,
)
async def check_consistency(
    novel_id: str,
    payload: ConsistencyCheckRequest,
) -> ConsistencyCheckResponse:
    try:
        result = service.check(novel_id, payload)
    except NovelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return ConsistencyCheckResponse(data=result)


@router.post(
    "/analyze",
    response_model=ConsistencyAnalyzeResponse,
)
async def analyze_consistency(
    novel_id: str,
    payload: ConsistencyAnalyzeRequest,
) -> ConsistencyAnalyzeResponse:
    try:
        result = await service.analyze(novel_id, payload)
    except NovelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ConsistencyOutputError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return ConsistencyAnalyzeResponse(data=result)
