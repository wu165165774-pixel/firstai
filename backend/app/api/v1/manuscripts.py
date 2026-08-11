from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.manuscripts.schemas import (
    ManuscriptAcceptRequest,
    ManuscriptAcceptResponse,
    ManuscriptChapterListResponse,
    ManuscriptChapterResponse,
    ManuscriptImportRequest,
    ManuscriptImportResponse,
    ManuscriptRevisionListResponse,
    ManuscriptRevisionResponse,
)
from app.manuscripts.service import ManuscriptService
from app.manuscripts.storage import (
    ManuscriptConflictError,
    ManuscriptNotFoundError,
)


router = APIRouter(prefix="/novels")
service = ManuscriptService()


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    )


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(exc),
    )


@router.post(
    "/{novel_id}/manuscript/chapters/import-workflow",
    response_model=ManuscriptImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_workflow_manuscript_candidate(
    novel_id: str,
    payload: ManuscriptImportRequest,
) -> ManuscriptImportResponse:
    try:
        result = service.import_workflow_candidate(novel_id, payload)
    except ManuscriptNotFoundError as exc:
        raise _not_found(exc) from exc
    except ManuscriptConflictError as exc:
        raise _conflict(exc) from exc
    return ManuscriptImportResponse(data=result)


@router.get(
    "/{novel_id}/manuscript/chapters",
    response_model=ManuscriptChapterListResponse,
)
async def list_manuscript_chapters(
    novel_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ManuscriptChapterListResponse:
    try:
        chapters = service.list_chapters(
            novel_id,
            limit=limit,
            offset=offset,
        )
    except ManuscriptNotFoundError as exc:
        raise _not_found(exc) from exc
    return ManuscriptChapterListResponse(data=chapters)


@router.get(
    "/{novel_id}/manuscript/chapters/{manuscript_chapter_id}",
    response_model=ManuscriptChapterResponse,
)
async def get_manuscript_chapter(
    novel_id: str,
    manuscript_chapter_id: str,
) -> ManuscriptChapterResponse:
    try:
        chapter = service.get_chapter(novel_id, manuscript_chapter_id)
    except ManuscriptNotFoundError as exc:
        raise _not_found(exc) from exc
    return ManuscriptChapterResponse(data=chapter)


@router.get(
    "/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions",
    response_model=ManuscriptRevisionListResponse,
)
async def list_manuscript_revisions(
    novel_id: str,
    manuscript_chapter_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> ManuscriptRevisionListResponse:
    try:
        revisions = service.list_revisions(
            novel_id,
            manuscript_chapter_id,
            limit=limit,
        )
    except ManuscriptNotFoundError as exc:
        raise _not_found(exc) from exc
    return ManuscriptRevisionListResponse(data=revisions)


@router.get(
    "/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}",
    response_model=ManuscriptRevisionResponse,
)
async def get_manuscript_revision(
    novel_id: str,
    manuscript_chapter_id: str,
    revision: int,
) -> ManuscriptRevisionResponse:
    try:
        item = service.get_revision(
            novel_id,
            manuscript_chapter_id,
            revision,
        )
    except ManuscriptNotFoundError as exc:
        raise _not_found(exc) from exc
    return ManuscriptRevisionResponse(data=item)


@router.post(
    "/{novel_id}/manuscript/chapters/{manuscript_chapter_id}"
    "/revisions/{revision}/accept",
    response_model=ManuscriptAcceptResponse,
)
async def accept_manuscript_revision(
    novel_id: str,
    manuscript_chapter_id: str,
    revision: int,
    payload: ManuscriptAcceptRequest,
) -> ManuscriptAcceptResponse:
    try:
        result = service.accept_revision(
            novel_id,
            manuscript_chapter_id,
            revision,
            payload,
        )
    except ManuscriptNotFoundError as exc:
        raise _not_found(exc) from exc
    except ManuscriptConflictError as exc:
        raise _conflict(exc) from exc
    return ManuscriptAcceptResponse(data=result)
