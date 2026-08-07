from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    status,
)

from app.novels.schemas import (
    ChapterPlanCreate,
    ChapterPlanListResponse,
    ChapterPlanResponse,
    ChapterPlanRevisionListResponse,
    ChapterPlanRevisionResponse,
    ChapterPlanUpdate,
    NovelPlanResponse,
    NovelPlanRevisionListResponse,
    NovelPlanRevisionResponse,
    NovelPlanUpdate,
    NovelProjectCreate,
    NovelProjectListResponse,
    NovelProjectResponse,
    NovelProjectUpdate,
    StoryArcCreate,
    StoryArcListResponse,
    StoryArcResponse,
    StoryArcRevisionListResponse,
    StoryArcRevisionResponse,
    StoryArcUpdate,
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

@router.get(
    "/{novel_id}/plan",
    response_model=NovelPlanResponse,
)
async def get_novel_plan(
    novel_id: str,
) -> NovelPlanResponse:
    try:
        plan = service.get_novel_plan(novel_id)
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return NovelPlanResponse(data=plan)


@router.put(
    "/{novel_id}/plan",
    response_model=NovelPlanResponse,
)
async def update_novel_plan(
    novel_id: str,
    payload: NovelPlanUpdate,
) -> NovelPlanResponse:
    try:
        plan = service.update_novel_plan(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return NovelPlanResponse(data=plan)


@router.get(
    "/{novel_id}/plan/revisions",
    response_model=NovelPlanRevisionListResponse,
)
async def list_novel_plan_revisions(
    novel_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> NovelPlanRevisionListResponse:
    try:
        revisions = service.list_novel_plan_revisions(
            novel_id,
            limit=limit,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return NovelPlanRevisionListResponse(
        data=revisions
    )


@router.get(
    "/{novel_id}/plan/revisions/{revision}",
    response_model=NovelPlanRevisionResponse,
)
async def get_novel_plan_revision(
    novel_id: str,
    revision: int,
) -> NovelPlanRevisionResponse:
    try:
        item = service.get_novel_plan_revision(
            novel_id,
            revision,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return NovelPlanRevisionResponse(data=item)

@router.post(
    "/{novel_id}/arcs",
    response_model=StoryArcResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_story_arc(
    novel_id: str,
    payload: StoryArcCreate,
) -> StoryArcResponse:
    try:
        arc = service.create_story_arc(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return StoryArcResponse(data=arc)


@router.get(
    "/{novel_id}/arcs",
    response_model=StoryArcListResponse,
)
async def list_story_arcs(
    novel_id: str,
    volume_number: int | None = Query(
        default=None,
        ge=1,
        le=10_000,
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> StoryArcListResponse:
    try:
        arcs = service.list_story_arcs(
            novel_id,
            volume_number=volume_number,
            limit=limit,
            offset=offset,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryArcListResponse(data=arcs)


@router.get(
    "/{novel_id}/arcs/{arc_id}",
    response_model=StoryArcResponse,
)
async def get_story_arc(
    novel_id: str,
    arc_id: str,
) -> StoryArcResponse:
    try:
        arc = service.get_story_arc(
            novel_id,
            arc_id,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryArcResponse(data=arc)


@router.put(
    "/{novel_id}/arcs/{arc_id}",
    response_model=StoryArcResponse,
)
async def update_story_arc(
    novel_id: str,
    arc_id: str,
    payload: StoryArcUpdate,
) -> StoryArcResponse:
    try:
        arc = service.update_story_arc(
            novel_id,
            arc_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return StoryArcResponse(data=arc)


@router.get(
    "/{novel_id}/arcs/{arc_id}/revisions",
    response_model=StoryArcRevisionListResponse,
)
async def list_story_arc_revisions(
    novel_id: str,
    arc_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> StoryArcRevisionListResponse:
    try:
        revisions = service.list_story_arc_revisions(
            novel_id,
            arc_id,
            limit=limit,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryArcRevisionListResponse(
        data=revisions
    )


@router.get(
    "/{novel_id}/arcs/{arc_id}/revisions/{revision}",
    response_model=StoryArcRevisionResponse,
)
async def get_story_arc_revision(
    novel_id: str,
    arc_id: str,
    revision: int,
) -> StoryArcRevisionResponse:
    try:
        item = service.get_story_arc_revision(
            novel_id,
            arc_id,
            revision,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return StoryArcRevisionResponse(data=item)

@router.post(
    "/{novel_id}/chapter-plans",
    response_model=ChapterPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chapter_plan(
    novel_id: str,
    payload: ChapterPlanCreate,
) -> ChapterPlanResponse:
    try:
        plan = service.create_chapter_plan(
            novel_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return ChapterPlanResponse(data=plan)


@router.get(
    "/{novel_id}/chapter-plans",
    response_model=ChapterPlanListResponse,
)
async def list_chapter_plans(
    novel_id: str,
    arc_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
    ),
    volume_number: int | None = Query(
        default=None,
        ge=1,
        le=10_000,
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ChapterPlanListResponse:
    try:
        plans = service.list_chapter_plans(
            novel_id,
            arc_id=arc_id,
            volume_number=volume_number,
            limit=limit,
            offset=offset,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return ChapterPlanListResponse(data=plans)


@router.get(
    "/{novel_id}/chapter-plans/{chapter_plan_id}",
    response_model=ChapterPlanResponse,
)
async def get_chapter_plan(
    novel_id: str,
    chapter_plan_id: str,
) -> ChapterPlanResponse:
    try:
        plan = service.get_chapter_plan(
            novel_id,
            chapter_plan_id,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return ChapterPlanResponse(data=plan)


@router.put(
    "/{novel_id}/chapter-plans/{chapter_plan_id}",
    response_model=ChapterPlanResponse,
)
async def update_chapter_plan(
    novel_id: str,
    chapter_plan_id: str,
    payload: ChapterPlanUpdate,
) -> ChapterPlanResponse:
    try:
        plan = service.update_chapter_plan(
            novel_id,
            chapter_plan_id,
            payload,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    except NovelRevisionConflictError as exc:
        raise _conflict(exc) from exc
    return ChapterPlanResponse(data=plan)


@router.get(
    "/{novel_id}/chapter-plans/{chapter_plan_id}/revisions",
    response_model=ChapterPlanRevisionListResponse,
)
async def list_chapter_plan_revisions(
    novel_id: str,
    chapter_plan_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> ChapterPlanRevisionListResponse:
    try:
        revisions = service.list_chapter_plan_revisions(
            novel_id,
            chapter_plan_id,
            limit=limit,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return ChapterPlanRevisionListResponse(
        data=revisions
    )


@router.get(
    "/{novel_id}/chapter-plans/{chapter_plan_id}/revisions/{revision}",
    response_model=ChapterPlanRevisionResponse,
)
async def get_chapter_plan_revision(
    novel_id: str,
    chapter_plan_id: str,
    revision: int,
) -> ChapterPlanRevisionResponse:
    try:
        item = service.get_chapter_plan_revision(
            novel_id,
            chapter_plan_id,
            revision,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return ChapterPlanRevisionResponse(data=item)
