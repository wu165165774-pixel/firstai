from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.novels.storage import NovelProjectNotFoundError
from app.temporal_graph.schemas import (
    TemporalContextType,
    TemporalEventCreate,
    TemporalEventListResponse,
    TemporalEventResponse,
    TemporalEventRevisionListResponse,
    TemporalEventUpdate,
    TemporalGraphQueryRequest,
    TemporalGraphQueryResponse,
    TemporalRelationCreate,
    TemporalRelationListResponse,
    TemporalRelationResponse,
    TemporalRelationRevisionListResponse,
    TemporalRelationUpdate,
)
from app.temporal_graph.service import temporal_graph_service
from app.temporal_graph.storage import (
    TemporalGraphConflictError,
    TemporalGraphNotFoundError,
)


router = APIRouter(prefix="/novels/{novel_id}/temporal-graph")
service = temporal_graph_service


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail=str(exc))


NOT_FOUND_ERRORS = (
    TemporalGraphNotFoundError,
    NovelProjectNotFoundError,
    LookupError,
)


@router.post(
    "/events",
    response_model=TemporalEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_temporal_event(
    novel_id: str,
    payload: TemporalEventCreate,
) -> TemporalEventResponse:
    try:
        item = service.create_event(novel_id, payload)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    except TemporalGraphConflictError as exc:
        raise _conflict(exc) from exc
    return TemporalEventResponse(data=item)


@router.get("/events", response_model=TemporalEventListResponse)
async def list_temporal_events(
    novel_id: str,
    active_entity_id: list[str] | None = Query(default=None),
    as_of_chapter: int | None = Query(default=None, ge=1),
    include_historical: bool = False,
    context_type: list[TemporalContextType] | None = Query(default=None),
    event_type: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> TemporalEventListResponse:
    try:
        items = service.list_events(
            novel_id,
            active_entity_ids=active_entity_id or [],
            as_of_chapter=as_of_chapter,
            include_historical=include_historical,
            context_types=context_type or [],
            event_types=event_type or [],
            limit=limit,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return TemporalEventListResponse(data=items)


@router.get(
    "/events/{event_id}",
    response_model=TemporalEventResponse,
)
async def get_temporal_event(
    novel_id: str,
    event_id: str,
) -> TemporalEventResponse:
    try:
        item = service.get_event(novel_id, event_id)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    return TemporalEventResponse(data=item)


@router.put(
    "/events/{event_id}",
    response_model=TemporalEventResponse,
)
async def update_temporal_event(
    novel_id: str,
    event_id: str,
    payload: TemporalEventUpdate,
) -> TemporalEventResponse:
    try:
        item = service.update_event(novel_id, event_id, payload)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    except TemporalGraphConflictError as exc:
        raise _conflict(exc) from exc
    return TemporalEventResponse(data=item)


@router.get(
    "/events/{event_id}/revisions",
    response_model=TemporalEventRevisionListResponse,
)
async def list_temporal_event_revisions(
    novel_id: str,
    event_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> TemporalEventRevisionListResponse:
    try:
        items = service.list_event_revisions(
            novel_id,
            event_id,
            limit=limit,
        )
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    return TemporalEventRevisionListResponse(data=items)


@router.post(
    "/relations",
    response_model=TemporalRelationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_temporal_relation(
    novel_id: str,
    payload: TemporalRelationCreate,
) -> TemporalRelationResponse:
    try:
        item = service.create_relation(novel_id, payload)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    except TemporalGraphConflictError as exc:
        raise _conflict(exc) from exc
    return TemporalRelationResponse(data=item)


@router.get("/relations", response_model=TemporalRelationListResponse)
async def list_temporal_relations(
    novel_id: str,
    active_entity_id: list[str] | None = Query(default=None),
    as_of_chapter: int | None = Query(default=None, ge=1),
    include_historical: bool = False,
    context_type: list[TemporalContextType] | None = Query(default=None),
    predicate: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> TemporalRelationListResponse:
    try:
        items = service.list_relations(
            novel_id,
            active_entity_ids=active_entity_id or [],
            as_of_chapter=as_of_chapter,
            include_historical=include_historical,
            context_types=context_type or [],
            predicates=predicate or [],
            limit=limit,
        )
    except NovelProjectNotFoundError as exc:
        raise _not_found(exc) from exc
    return TemporalRelationListResponse(data=items)


@router.get(
    "/relations/{relation_id}",
    response_model=TemporalRelationResponse,
)
async def get_temporal_relation(
    novel_id: str,
    relation_id: str,
) -> TemporalRelationResponse:
    try:
        item = service.get_relation(novel_id, relation_id)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    return TemporalRelationResponse(data=item)


@router.put(
    "/relations/{relation_id}",
    response_model=TemporalRelationResponse,
)
async def update_temporal_relation(
    novel_id: str,
    relation_id: str,
    payload: TemporalRelationUpdate,
) -> TemporalRelationResponse:
    try:
        item = service.update_relation(novel_id, relation_id, payload)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    except TemporalGraphConflictError as exc:
        raise _conflict(exc) from exc
    return TemporalRelationResponse(data=item)


@router.get(
    "/relations/{relation_id}/revisions",
    response_model=TemporalRelationRevisionListResponse,
)
async def list_temporal_relation_revisions(
    novel_id: str,
    relation_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> TemporalRelationRevisionListResponse:
    try:
        items = service.list_relation_revisions(
            novel_id,
            relation_id,
            limit=limit,
        )
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    return TemporalRelationRevisionListResponse(data=items)


@router.post("/query", response_model=TemporalGraphQueryResponse)
async def query_temporal_graph(
    novel_id: str,
    payload: TemporalGraphQueryRequest,
) -> TemporalGraphQueryResponse:
    try:
        result = service.query(novel_id, payload)
    except NOT_FOUND_ERRORS as exc:
        raise _not_found(exc) from exc
    return TemporalGraphQueryResponse(data=result)
