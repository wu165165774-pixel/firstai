from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.orchestrator.schemas import (
    NovelOrchestrationControlRequest,
    NovelOrchestrationCreateRequest,
    NovelOrchestrationCreateResponse,
    NovelOrchestrationListResponse,
    NovelOrchestrationResponse,
    NovelOrchestrationRetryRequest,
)
from app.orchestrator.service import NovelOrchestrationService
from app.orchestrator.storage import (
    NovelOrchestrationConflictError,
    NovelOrchestrationNotFoundError,
)
from app.workflows.async_queue import WorkflowAdmissionError


router = APIRouter(prefix="/novels")
service = NovelOrchestrationService()


def _ensure_worker(request: Request) -> None:
    from app.api.v1.workflows import _async_executor

    _async_executor(request)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _admission(exc: WorkflowAdmissionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": exc.code, "message": str(exc)},
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


@router.post(
    "/{novel_id}/orchestrations",
    response_model=NovelOrchestrationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_novel_orchestration(
    novel_id: str,
    payload: NovelOrchestrationCreateRequest,
    request: Request,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> NovelOrchestrationCreateResponse:
    try:
        result = service.create(
            novel_id,
            payload,
            idempotency_key=idempotency_key,
        )
        _ensure_worker(request)
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelOrchestrationConflictError as exc:
        raise _conflict(exc) from exc
    except WorkflowAdmissionError as exc:
        raise _admission(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return NovelOrchestrationCreateResponse(data=result)


@router.get(
    "/{novel_id}/orchestrations",
    response_model=NovelOrchestrationListResponse,
)
async def list_novel_orchestrations(
    novel_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> NovelOrchestrationListResponse:
    try:
        items = service.list(novel_id, limit=limit, offset=offset)
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    return NovelOrchestrationListResponse(data=items)


@router.get(
    "/{novel_id}/orchestrations/{orchestration_id}",
    response_model=NovelOrchestrationResponse,
)
async def get_novel_orchestration(
    novel_id: str,
    orchestration_id: str,
) -> NovelOrchestrationResponse:
    try:
        detail = service.get(novel_id, orchestration_id)
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    return NovelOrchestrationResponse(data=detail)


@router.post(
    "/{novel_id}/orchestrations/{orchestration_id}/advance",
    response_model=NovelOrchestrationResponse,
)
async def advance_novel_orchestration(
    novel_id: str,
    orchestration_id: str,
    payload: NovelOrchestrationControlRequest,
    request: Request,
) -> NovelOrchestrationResponse:
    try:
        _ensure_worker(request)
        detail = service.advance(
            novel_id,
            orchestration_id,
            expected_revision=payload.expected_revision,
        )
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelOrchestrationConflictError as exc:
        raise _conflict(exc) from exc
    except WorkflowAdmissionError as exc:
        raise _admission(exc) from exc
    return NovelOrchestrationResponse(data=detail)


@router.post(
    "/{novel_id}/orchestrations/{orchestration_id}/pause",
    response_model=NovelOrchestrationResponse,
)
async def pause_novel_orchestration(
    novel_id: str,
    orchestration_id: str,
    payload: NovelOrchestrationControlRequest,
) -> NovelOrchestrationResponse:
    try:
        detail = service.pause(
            novel_id,
            orchestration_id,
            expected_revision=payload.expected_revision,
        )
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelOrchestrationConflictError as exc:
        raise _conflict(exc) from exc
    return NovelOrchestrationResponse(data=detail)


@router.post(
    "/{novel_id}/orchestrations/{orchestration_id}/resume",
    response_model=NovelOrchestrationResponse,
)
async def resume_novel_orchestration(
    novel_id: str,
    orchestration_id: str,
    payload: NovelOrchestrationControlRequest,
    request: Request,
) -> NovelOrchestrationResponse:
    try:
        _ensure_worker(request)
        detail = service.resume(
            novel_id,
            orchestration_id,
            expected_revision=payload.expected_revision,
        )
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelOrchestrationConflictError as exc:
        raise _conflict(exc) from exc
    except WorkflowAdmissionError as exc:
        raise _admission(exc) from exc
    return NovelOrchestrationResponse(data=detail)


@router.post(
    "/{novel_id}/orchestrations/{orchestration_id}/retry",
    response_model=NovelOrchestrationResponse,
)
async def retry_novel_orchestration(
    novel_id: str,
    orchestration_id: str,
    payload: NovelOrchestrationRetryRequest,
    request: Request,
) -> NovelOrchestrationResponse:
    try:
        _ensure_worker(request)
        detail = service.retry(
            novel_id,
            orchestration_id,
            expected_revision=payload.expected_revision,
            reset_attempts=payload.reset_attempts,
        )
    except NovelOrchestrationNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelOrchestrationConflictError as exc:
        raise _conflict(exc) from exc
    except WorkflowAdmissionError as exc:
        raise _admission(exc) from exc
    except ValueError as exc:
        raise _conflict(exc) from exc
    return NovelOrchestrationResponse(data=detail)
