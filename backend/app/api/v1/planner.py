from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.novels.storage import (
    NovelProjectNotFoundError,
    NovelRevisionConflictError,
)
from app.planner.parser import PlannerOutputError
from app.planner.schemas import (
    PlannerAcceptRequest,
    PlannerAcceptResponse,
    PlannerGenerateRequest,
    PlannerGenerateResponse,
)
from app.planner.service import (
    PlannerAcceptanceConflictError,
    PlannerCoordinateError,
    PlannerService,
    PlannerSourceStaleError,
)


router = APIRouter(
    prefix="/novels/{novel_id}/planner"
)
service = PlannerService()


@router.post(
    "/generate",
    response_model=PlannerGenerateResponse,
)
async def generate_planning_candidate(
    novel_id: str,
    payload: PlannerGenerateRequest,
) -> PlannerGenerateResponse:
    try:
        result = await service.generate(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlannerSourceStaleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        PlannerOutputError,
        PlannerCoordinateError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return PlannerGenerateResponse(data=result)


@router.post(
    "/accept",
    response_model=PlannerAcceptResponse,
)
async def accept_planning_candidate(
    novel_id: str,
    payload: PlannerAcceptRequest,
) -> PlannerAcceptResponse:
    try:
        result = service.accept(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        PlannerAcceptanceConflictError,
        PlannerSourceStaleError,
        NovelRevisionConflictError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return PlannerAcceptResponse(data=result)
