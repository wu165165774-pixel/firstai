from __future__ import annotations

import re

from typing import Protocol

from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectNotFoundError

from .schemas import (
    TemporalEvent,
    TemporalEventCreate,
    TemporalEventRevision,
    TemporalEventUpdate,
    TemporalGraphEvidence,
    TemporalGraphQueryRequest,
    TemporalGraphQueryResult,
    TemporalRelation,
    TemporalRelationCreate,
    TemporalRelationRevision,
    TemporalRelationUpdate,
    TemporalSourceReference,
)
from .storage import TemporalGraphConflictError, TemporalGraphStorage


class ManuscriptSourceReader(Protocol):
    def get_revision(self, novel_id: str, source_id: str, revision: int): ...
    def get_chapter(self, novel_id: str, source_id: str): ...


class TemporalGraphService:
    def __init__(
        self,
        storage: TemporalGraphStorage | None = None,
        novel_service: NovelProjectService | None = None,
        manuscript_service: ManuscriptSourceReader | None = None,
    ) -> None:
        self.storage = storage or TemporalGraphStorage()
        self.novel_service = novel_service or NovelProjectService()
        self.manuscript_service = manuscript_service

    def _manuscript_reader(self) -> ManuscriptSourceReader:
        if self.manuscript_service is None:
            from app.manuscripts.service import ManuscriptService

            self.manuscript_service = ManuscriptService()
        return self.manuscript_service

    def _validate_novel(
        self,
        novel_id: str,
        *,
        expected_user_id: str | None = None,
    ) -> None:
        project = self.novel_service.get_project(novel_id)
        if (
            expected_user_id is not None
            and project.user_id != expected_user_id
        ):
            raise NovelProjectNotFoundError(
                f"Novel Project not found: {novel_id}"
            )

    def _validate_entity(
        self,
        novel_id: str,
        entity_id: str,
        *,
        required_type: str | None = None,
    ) -> None:
        entity = self.novel_service.get_entity(novel_id, entity_id)
        if required_type and entity.entity_type != required_type:
            raise TemporalGraphConflictError(
                f"Temporal entity type mismatch: entity_id={entity_id}, "
                f"expected={required_type}, actual={entity.entity_type}"
            )

    def _validate_source(
        self,
        novel_id: str,
        source: TemporalSourceReference,
    ) -> None:
        if source.source_type == "story_bible":
            if source.source_id != novel_id:
                raise TemporalGraphConflictError(
                    "Story Bible source_id must equal novel_id"
                )
            self.novel_service.get_story_bible_revision(
                novel_id,
                source.source_revision,
            )
            if source.source_chapter_number is not None:
                raise TemporalGraphConflictError(
                    "Story Bible source must not set source_chapter_number"
                )
            return

        manuscript_reader = self._manuscript_reader()
        revision = manuscript_reader.get_revision(
            novel_id,
            source.source_id,
            source.source_revision,
        )
        if not revision.is_accepted:
            raise TemporalGraphConflictError(
                "Temporal Graph source Manuscript revision must be accepted"
            )
        chapter = manuscript_reader.get_chapter(
            novel_id,
            source.source_id,
        ).chapter
        if source.source_chapter_number != chapter.chapter_number:
            raise TemporalGraphConflictError(
                "Manuscript source_chapter_number mismatch: "
                f"expected={chapter.chapter_number}, "
                f"actual={source.source_chapter_number}"
            )

    def _validate_event_values(
        self,
        novel_id: str,
        participant_entity_ids: list[str],
        location_entity_id: str | None,
        source: TemporalSourceReference,
    ) -> None:
        for entity_id in participant_entity_ids:
            self._validate_entity(novel_id, entity_id)
        if location_entity_id:
            self._validate_entity(
                novel_id,
                location_entity_id,
                required_type="location",
            )
        self._validate_source(novel_id, source)

    def create_event(
        self,
        novel_id: str,
        payload: TemporalEventCreate,
    ) -> TemporalEvent:
        self._validate_novel(novel_id)
        self._validate_event_values(
            novel_id,
            payload.participant_entity_ids,
            payload.location_entity_id,
            payload.source,
        )
        return self.storage.create_event(novel_id, payload)

    def get_event(self, novel_id: str, event_id: str) -> TemporalEvent:
        self._validate_novel(novel_id)
        return self.storage.get_event(novel_id, event_id)

    def update_event(
        self,
        novel_id: str,
        event_id: str,
        payload: TemporalEventUpdate,
    ) -> TemporalEvent:
        self._validate_novel(novel_id)
        current = self.storage.get_event(novel_id, event_id)
        if current.revision != payload.expected_revision:
            raise TemporalGraphConflictError(
                "Temporal Event revision conflict: "
                f"expected={payload.expected_revision}, "
                f"actual={current.revision}"
            )
        participants = (
            payload.participant_entity_ids
            if payload.participant_entity_ids is not None
            else current.participant_entity_ids
        )
        location = (
            payload.location_entity_id
            if "location_entity_id" in payload.model_fields_set
            else current.location_entity_id
        )
        self._validate_event_values(
            novel_id,
            participants,
            location,
            payload.source,
        )
        return self.storage.update_event(novel_id, event_id, payload)

    def list_events(
        self,
        novel_id: str,
        **filters,
    ) -> list[TemporalEvent]:
        self._validate_novel(novel_id)
        return self.storage.list_events(novel_id, **filters)

    def list_event_revisions(
        self,
        novel_id: str,
        event_id: str,
        *,
        limit: int = 100,
    ) -> list[TemporalEventRevision]:
        self._validate_novel(novel_id)
        return self.storage.list_event_revisions(
            novel_id,
            event_id,
            limit=limit,
        )

    def _validate_relation_values(
        self,
        novel_id: str,
        subject_entity_id: str,
        object_entity_id: str,
        source: TemporalSourceReference,
    ) -> None:
        self._validate_entity(novel_id, subject_entity_id)
        self._validate_entity(novel_id, object_entity_id)
        self._validate_source(novel_id, source)

    def create_relation(
        self,
        novel_id: str,
        payload: TemporalRelationCreate,
    ) -> TemporalRelation:
        self._validate_novel(novel_id)
        self._validate_relation_values(
            novel_id,
            payload.subject_entity_id,
            payload.object_entity_id,
            payload.source,
        )
        return self.storage.create_relation(novel_id, payload)

    def get_relation(
        self,
        novel_id: str,
        relation_id: str,
    ) -> TemporalRelation:
        self._validate_novel(novel_id)
        return self.storage.get_relation(novel_id, relation_id)

    def update_relation(
        self,
        novel_id: str,
        relation_id: str,
        payload: TemporalRelationUpdate,
    ) -> TemporalRelation:
        self._validate_novel(novel_id)
        current = self.storage.get_relation(novel_id, relation_id)
        if current.revision != payload.expected_revision:
            raise TemporalGraphConflictError(
                "Temporal Relation revision conflict: "
                f"expected={payload.expected_revision}, "
                f"actual={current.revision}"
            )
        self._validate_relation_values(
            novel_id,
            payload.subject_entity_id or current.subject_entity_id,
            payload.object_entity_id or current.object_entity_id,
            payload.source,
        )
        return self.storage.update_relation(novel_id, relation_id, payload)

    def list_relations(
        self,
        novel_id: str,
        **filters,
    ) -> list[TemporalRelation]:
        self._validate_novel(novel_id)
        return self.storage.list_relations(novel_id, **filters)

    def list_relation_revisions(
        self,
        novel_id: str,
        relation_id: str,
        *,
        limit: int = 100,
    ) -> list[TemporalRelationRevision]:
        self._validate_novel(novel_id)
        return self.storage.list_relation_revisions(
            novel_id,
            relation_id,
            limit=limit,
        )

    @staticmethod
    def _terms(query: str) -> list[str]:
        return list(
            dict.fromkeys(
                term.casefold()
                for term in re.findall(r"[\w\u3400-\u9fff]+", query)
                if term.strip()
            )
        )

    @staticmethod
    def _lexical_score(content: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        normalized = content.casefold()
        return sum(1.0 for term in terms if term in normalized) / len(terms)

    def query(
        self,
        novel_id: str,
        payload: TemporalGraphQueryRequest,
        *,
        expected_user_id: str | None = None,
    ) -> TemporalGraphQueryResult:
        self._validate_novel(novel_id, expected_user_id=expected_user_id)
        fetch_limit = min(max(payload.top_k * 5, payload.top_k), 500)
        contexts = list(payload.context_types)
        events = self.storage.list_events(
            novel_id,
            active_entity_ids=payload.active_entity_ids,
            as_of_chapter=payload.as_of_chapter,
            include_historical=payload.include_historical,
            context_types=contexts,
            event_types=payload.event_types,
            limit=fetch_limit,
        )
        relations = self.storage.list_relations(
            novel_id,
            active_entity_ids=payload.active_entity_ids,
            as_of_chapter=payload.as_of_chapter,
            include_historical=payload.include_historical,
            context_types=contexts,
            predicates=payload.predicates,
            limit=fetch_limit,
        )
        entity_cache = {}

        def entity_name(entity_id: str) -> str:
            if entity_id not in entity_cache:
                entity_cache[entity_id] = self.novel_service.get_entity(
                    novel_id,
                    entity_id,
                ).canonical_name
            return entity_cache[entity_id]

        terms = self._terms(payload.query)
        active = set(payload.active_entity_ids)
        evidence: list[TemporalGraphEvidence] = []
        for event in events:
            names = [entity_name(item) for item in event.participant_entity_ids]
            if event.location_entity_id:
                names.append(entity_name(event.location_entity_id))
            content = f"事件「{event.title}」"
            if names:
                content += f"（涉及：{'、'.join(names)}）"
            if event.summary:
                content += f"：{event.summary}"
            overlap = len(active.intersection(event.participant_entity_ids))
            if event.location_entity_id in active:
                overlap += 1
            evidence.append(
                TemporalGraphEvidence(
                    graph_id=event.event_id,
                    graph_kind="event",
                    context_type=event.context_type,
                    content=content,
                    entity_ids=list(
                        dict.fromkeys(
                            [
                                *event.participant_entity_ids,
                                *(
                                    [event.location_entity_id]
                                    if event.location_entity_id
                                    else []
                                ),
                            ]
                        )
                    ),
                    valid_from_chapter=event.start_chapter,
                    valid_to_chapter=event.end_chapter,
                    score=(
                        event.confidence
                        + self._lexical_score(content, terms)
                        + min(overlap, 3) * 0.25
                    ),
                    source=event.source,
                    metadata={
                        "event_type": event.event_type,
                        "revision": event.revision,
                    },
                )
            )
        for relation in relations:
            subject_name = entity_name(relation.subject_entity_id)
            object_name = entity_name(relation.object_entity_id)
            content = f"{subject_name} —{relation.predicate}→ {object_name}"
            if relation.description:
                content += f"：{relation.description}"
            overlap = len(
                active.intersection(
                    {relation.subject_entity_id, relation.object_entity_id}
                )
            )
            evidence.append(
                TemporalGraphEvidence(
                    graph_id=relation.relation_id,
                    graph_kind="relation",
                    context_type=relation.context_type,
                    content=content,
                    entity_ids=[
                        relation.subject_entity_id,
                        relation.object_entity_id,
                    ],
                    valid_from_chapter=relation.valid_from_chapter,
                    valid_to_chapter=relation.valid_to_chapter,
                    score=(
                        relation.confidence
                        + self._lexical_score(content, terms)
                        + min(overlap, 2) * 0.25
                    ),
                    source=relation.source,
                    metadata={
                        "predicate": relation.predicate,
                        "revision": relation.revision,
                    },
                )
            )
        evidence.sort(
            key=lambda item: (
                -item.score,
                -item.valid_from_chapter,
                0 if item.graph_kind == "event" else 1,
                item.graph_id,
            )
        )
        return TemporalGraphQueryResult(
            novel_id=novel_id,
            as_of_chapter=payload.as_of_chapter,
            include_historical=payload.include_historical,
            evidence=evidence[: payload.top_k],
        )


temporal_graph_service = TemporalGraphService()
