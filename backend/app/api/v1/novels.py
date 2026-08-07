from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.novels.schemas import (
    NovelProjectCreate,
    NovelProjectListResponse,
    NovelProjectResponse,
    NovelProjectUpdate,
    StoryBibleResponse,
    StoryBibleRevisionListResponse,
    StoryBibleRevisionResponse,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import (
    NovelProjectNotFoundError,
    NovelRevisionConflictError,
)


router = APIRouter(prefix="/novels")
service = NovelProjectService()


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
    "",
    response_model=NovelProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_novel_project(
    payload: NovelProjectCreate,
) -> NovelProjectResponse:
    project = service.create_project(payload)
    return NovelProjectResponse(data=project)


@router.get(
    "",
    response_model=NovelProjectListResponse,
)
async def list_novel_projects(
    user_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
    ),
    project_status: str | None = Query(
        default=None,
        alias="status",
        min_length=1,
        max_length=32,
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> NovelProjectListResponse:
    projects = service.list_projects(
        user_id=user_id,
        status=project_status,
        limit=limit,
        offset=offset,
    )
    return NovelProjectListResponse(data=projects)


@router.get(
    "/{novel_id}",
    response_model=NovelProjectResponse,
)
async def get_novel_project(
    novel_id: str,
) -> NovelProjectResponse:
    try:
        project = service.get_project(novel_id)
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return NovelProjectResponse(data=project)


@router.patch(
    "/{novel_id}",
    response_model=NovelProjectResponse,
)
async def update_novel_project(
    novel_id: str,
    payload: NovelProjectUpdate,
) -> NovelProjectResponse:
    try:
        project = service.update_project(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return NovelProjectResponse(data=project)


@router.get(
    "/{novel_id}/story-bible",
    response_model=StoryBibleResponse,
)
async def get_story_bible(
    novel_id: str,
) -> StoryBibleResponse:
    try:
        bible = service.get_story_bible(novel_id)
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryBibleResponse(data=bible)


@router.put(
    "/{novel_id}/story-bible",
    response_model=StoryBibleResponse,
)
async def update_story_bible(
    novel_id: str,
    payload: StoryBibleUpdate,
) -> StoryBibleResponse:
    try:
        bible = service.update_story_bible(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return StoryBibleResponse(data=bible)


@router.get(
    "/{novel_id}/story-bible/revisions",
    response_model=StoryBibleRevisionListResponse,
)
async def list_story_bible_revisions(
    novel_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> StoryBibleRevisionListResponse:
    try:
        revisions = service.list_story_bible_revisions(
            novel_id,
            limit=limit,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryBibleRevisionListResponse(data=revisions)


@router.get(
    "/{novel_id}/story-bible/revisions/{revision}",
    response_model=StoryBibleRevisionResponse,
)
async def get_story_bible_revision(
    novel_id: str,
    revision: int,
) -> StoryBibleRevisionResponse:
    try:
        item = service.get_story_bible_revision(
            novel_id,
            revision,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryBibleRevisionResponse(data=item)
