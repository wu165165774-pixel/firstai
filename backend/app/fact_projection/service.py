from __future__ import annotations

import asyncio

from typing import Any

from loguru import logger

from app.consistency.schemas import (
    ConsistencyCheckRequest,
    ConsistencyFactCandidate,
)
from app.consistency.service import ConsistencyEngine
from app.manuscripts.storage import ManuscriptStorage
from app.memory.schemas import MemoryItem, MemoryTier, MemoryType
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.novels.service import NovelProjectService
from app.novels.storage import (
    NovelProjectNotFoundError,
    NovelProjectStorage,
)
from app.rag.memory_indexer import MemoryIndexer, memory_indexer
from app.temporal_graph.schemas import (
    TemporalEventCreate,
    TemporalEventUpdate,
    TemporalRelationCreate,
    TemporalRelationUpdate,
    TemporalSourceReference,
)
from app.temporal_graph.service import TemporalGraphService
from app.temporal_graph.storage import (
    TemporalGraphNotFoundError,
    TemporalGraphStorage,
)

from .schemas import FactProjectionSummary


class FactProjectionConflictError(RuntimeError):
    pass


class FactProjectionService:
    """Recoverable, idempotent accepted-fact projection coordinator."""

    def __init__(
        self,
        *,
        manuscript_storage: ManuscriptStorage | None = None,
        novel_service: NovelProjectService | None = None,
        memory_storage: SQLiteMemoryStorage | None = None,
        indexer: MemoryIndexer | None = None,
        temporal_service: TemporalGraphService | None = None,
        consistency_engine: ConsistencyEngine | None = None,
    ) -> None:
        self.manuscript_storage = manuscript_storage or ManuscriptStorage()
        self.novel_service = novel_service or NovelProjectService(
            NovelProjectStorage(self.manuscript_storage.db_path)
        )
        self.memory_storage = memory_storage or SQLiteMemoryStorage()
        self.indexer = indexer or memory_indexer
        if temporal_service is None:
            temporal_service = TemporalGraphService(
                storage=TemporalGraphStorage(),
                novel_service=self.novel_service,
                manuscript_service=self.manuscript_storage,
            )
        self.temporal_service = temporal_service
        self.consistency_engine = consistency_engine or ConsistencyEngine(
            novel_service=self.novel_service,
            temporal_storage=self.temporal_service.storage,
        )

    @staticmethod
    def _memory_type(fact: ConsistencyFactCandidate) -> MemoryType:
        if fact.fact_type in {"relationship", "life_state", "identity"}:
            return MemoryType.CHARACTER
        return MemoryType.PLOT

    @staticmethod
    def _source_reference(row: dict[str, Any]) -> str:
        return (
            f"manuscript:{row['manuscript_chapter_id']}:"
            f"r{row['manuscript_revision']}:fact:{row['fact_index']}"
        )

    @staticmethod
    def _memory_id(row: dict[str, Any]) -> str:
        return f"mem_{row['projection_id']}"

    @staticmethod
    def _graph_id(row: dict[str, Any], kind: str) -> str:
        prefix = "rel" if kind == "relation" else "evt"
        return f"{prefix}_{row['projection_id']}"

    @staticmethod
    def _scope(metadata: dict[str, Any]) -> str:
        return str(metadata.get("knowledge_scope") or "WORLD_TRUTH")

    @staticmethod
    def _closed_chain(metadata: dict[str, Any]) -> list[dict[str, Any]]:
        value = metadata.get("closed_by_fact_projections", [])
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
        legacy_id = metadata.get("closed_by_projection_id")
        if not legacy_id:
            return []
        return [
            {
                "projection_id": legacy_id,
                "source_reference": metadata.get(
                    "closed_by_source_reference", ""
                ),
                "prior_end_chapter": metadata.get(
                    "prior_end_chapter",
                    metadata.get("prior_valid_to_chapter"),
                ),
                "prior_source": metadata.get("prior_source"),
            }
        ]

    def _source(self, row: dict[str, Any]) -> TemporalSourceReference:
        return TemporalSourceReference(
            source_type="accepted_manuscript",
            source_id=row["manuscript_chapter_id"],
            source_revision=int(row["manuscript_revision"]),
            source_chapter_number=int(row["chapter_number"]),
        )

    def _retraction_source(
        self,
        row: dict[str, Any],
    ) -> TemporalSourceReference:
        superseded_by = row.get("superseded_by_revision")
        if superseded_by is None:
            raise FactProjectionConflictError(
                "Fact retraction has no replacement Manuscript revision."
            )
        return TemporalSourceReference(
            source_type="accepted_manuscript",
            source_id=row["manuscript_chapter_id"],
            source_revision=int(superseded_by),
            source_chapter_number=int(row["chapter_number"]),
        )

    def _fact_metadata(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
    ) -> dict[str, Any]:
        metadata = {
            "projection_id": row["projection_id"],
            "fact_id": fact.fact_id,
            "fact_type": fact.fact_type,
            "change_type": fact.change_type,
            "knowledge_scope": fact.knowledge_scope,
            "knowledge_holder_entity_id": fact.knowledge_holder_entity_id,
            "source_reference": self._source_reference(row),
        }
        if (
            fact.knowledge_scope == "CHARACTER_KNOWLEDGE"
            and fact.knowledge_holder_entity_id
        ):
            metadata["knower_entity_ids"] = [
                fact.knowledge_holder_entity_id
            ]
        return metadata

    def _validate_candidate(
        self,
        row: dict[str, Any],
    ) -> ConsistencyFactCandidate:
        project = self.novel_service.get_project(row["novel_id"])
        active_entity_ids: list[str] = []
        for entity_id in (
            row["fact"].subject_entity_id,
            row["fact"].object_entity_id,
        ):
            if not entity_id:
                continue
            try:
                self.novel_service.get_entity(row["novel_id"], entity_id)
            except NovelProjectNotFoundError:
                continue
            active_entity_ids.append(entity_id)
        checked = self.consistency_engine.check(
            row["novel_id"],
            ConsistencyCheckRequest(
                user_id=project.user_id,
                chapter_number=int(row["chapter_number"]),
                active_entity_ids=active_entity_ids,
                content=row["content"],
                candidate_facts=[row["fact"]],
            ),
        )
        blocking = [
            item
            for item in checked.conflicts
            if item.blocking and item.status == "confirmed"
        ]
        if blocking:
            kinds = ", ".join(item.conflict_type for item in blocking)
            raise FactProjectionConflictError(
                "Accepted fact failed current consistency validation: " + kinds
            )
        fact = checked.candidate_facts[0]
        if fact.chapter_number != int(row["chapter_number"]):
            raise FactProjectionConflictError(
                "Accepted fact chapter coordinate does not match its "
                "Manuscript Chapter."
            )
        return fact

    async def _project_memory(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
    ) -> MemoryItem:
        memory_id = self._memory_id(row)
        source_reference = self._source_reference(row)
        memory = await self.memory_storage.get(memory_id)
        if memory is None:
            project = self.novel_service.get_project(row["novel_id"])
            memory = await self.memory_storage.save(
                MemoryItem(
                    id=memory_id,
                    user_id=project.user_id,
                    novel_id=row["novel_id"],
                    memory_type=self._memory_type(fact),
                    memory_tier=MemoryTier.LONG_TERM,
                    content=fact.evidence,
                    importance=max(0.7, fact.confidence),
                    metadata={
                        **self._fact_metadata(row, fact),
                        "basis": "accepted_manuscript",
                    },
                )
            )
        elif (
            memory.user_id != self.novel_service.get_project(row["novel_id"]).user_id
            or memory.novel_id != row["novel_id"]
            or memory.content != fact.evidence
            or memory.metadata.get("source_reference") != source_reference
        ):
            raise FactProjectionConflictError(
                f"Stable Memory ID collision: {memory_id}"
            )
        self.manuscript_storage.update_fact_projection(
            row["projection_id"],
            memory_id=memory_id,
            memory_projected=True,
            expected_operation="project",
        )
        return memory

    async def _existing_memory(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
    ) -> MemoryItem | None:
        if not row.get("memory_projected"):
            return None
        memory = await self.memory_storage.get(
            row.get("memory_id") or self._memory_id(row)
        )
        if memory is None:
            return None
        if (
            memory.content != fact.evidence
            or memory.metadata.get("source_reference")
            != self._source_reference(row)
        ):
            raise FactProjectionConflictError(
                f"Stable Memory checkpoint collision: {memory.id}"
            )
        return memory

    async def _prepare_projection_retry(
        self,
        row: dict[str, Any],
    ) -> None:
        memory_id = row.get("memory_id") or self._memory_id(row)
        memory = await self.memory_storage.get(memory_id)
        if row.get("memory_projected") and memory is None:
            if row.get("vector_projected"):
                await self.indexer.remove(memory_id)
            self.manuscript_storage.update_fact_projection(
                row["projection_id"],
                memory_projected=False,
                vector_projected=False,
                expected_operation="project",
            )
            row["memory_projected"] = False
            row["vector_projected"] = False
        elif row.get("vector_projected"):
            indexed_ids = await self._indexed_memory_ids()
            if memory_id not in indexed_ids:
                self.manuscript_storage.update_fact_projection(
                    row["projection_id"],
                    vector_projected=False,
                    expected_operation="project",
                )
                row["vector_projected"] = False
        if row.get("graph_projected"):
            kind = row.get("graph_kind") or (
                "relation"
                if row["fact"].fact_type == "relationship"
                else "event"
            )
            graph_id = row.get("graph_id") or self._graph_id(row, kind)
            try:
                if kind == "relation":
                    graph = self.temporal_service.get_relation(
                        row["novel_id"], graph_id
                    )
                else:
                    graph = self.temporal_service.get_event(
                        row["novel_id"], graph_id
                    )
            except TemporalGraphNotFoundError:
                self.manuscript_storage.update_fact_projection(
                    row["projection_id"],
                    graph_projected=False,
                    expected_operation="project",
                )
                row["graph_projected"] = False
            else:
                if (
                    graph.metadata.get("projection_id")
                    != row["projection_id"]
                    or graph.metadata.get("retracted")
                ):
                    raise FactProjectionConflictError(
                        f"Stable Temporal Graph checkpoint collision: {graph_id}"
                    )

    async def _indexed_memory_ids(self) -> set[str]:
        list_ids = getattr(self.indexer, "list_indexed_ids", None)
        if list_ids is not None:
            values = await list_ids()
            return {str(value) for value in values}
        vector_store = getattr(self.indexer, "vector_store", None)
        if vector_store is None:
            return set()
        values = await asyncio.to_thread(
            vector_store.list_memory_ids
        )
        return {str(value) for value in values}

    async def _project_vector(
        self,
        row: dict[str, Any],
        memory: MemoryItem,
    ) -> None:
        await self.indexer.upsert_memory(memory)
        self.manuscript_storage.update_fact_projection(
            row["projection_id"],
            vector_projected=True,
            expected_operation="project",
        )

    def _close_prior_relationships(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
        source: TemporalSourceReference,
    ) -> None:
        if fact.change_type != "transition" or fact.knowledge_scope != "WORLD_TRUTH":
            return
        assert fact.subject_entity_id and fact.object_entity_id
        candidate_group = self.consistency_engine._relation_group(fact.predicate)
        for relation in self.temporal_service.list_relations(
            row["novel_id"],
            active_entity_ids=[fact.subject_entity_id, fact.object_entity_id],
            as_of_chapter=int(row["chapter_number"]),
            include_historical=False,
            limit=200,
        ):
            if self._scope(relation.metadata) != "WORLD_TRUTH":
                continue
            pair_matches = {
                relation.subject_entity_id,
                relation.object_entity_id,
            } == {fact.subject_entity_id, fact.object_entity_id}
            existing_group = self.consistency_engine._relation_group(
                relation.predicate
            )
            incompatible = (
                candidate_group
                and existing_group
                and frozenset((candidate_group, existing_group))
                in self.consistency_engine._INCOMPATIBLE_RELATION_GROUPS
            )
            if (
                pair_matches
                and incompatible
                and relation.valid_from_chapter < int(row["chapter_number"])
            ):
                metadata = dict(relation.metadata)
                chain = self._closed_chain(metadata)
                chain.append(
                    {
                        "projection_id": row["projection_id"],
                        "source_reference": self._source_reference(row),
                        "prior_end_chapter": relation.valid_to_chapter,
                        "prior_source": relation.source.model_dump(mode="json"),
                    }
                )
                metadata["closed_by_fact_projections"] = chain
                for key in (
                    "closed_by_projection_id",
                    "closed_by_source_reference",
                    "prior_valid_to_chapter",
                    "prior_source",
                ):
                    metadata.pop(key, None)
                self.temporal_service.update_relation(
                    row["novel_id"],
                    relation.relation_id,
                    TemporalRelationUpdate(
                        expected_revision=relation.revision,
                        source=source,
                        valid_to_chapter=int(row["chapter_number"]) - 1,
                        metadata=metadata,
                    ),
                )

    def _close_prior_events(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
        source: TemporalSourceReference,
    ) -> None:
        if fact.change_type != "transition" or fact.knowledge_scope != "WORLD_TRUTH":
            return
        assert fact.subject_entity_id
        chapter = int(row["chapter_number"])
        for event in self.temporal_service.list_events(
            row["novel_id"],
            active_entity_ids=[fact.subject_entity_id],
            as_of_chapter=chapter,
            include_historical=False,
            limit=200,
        ):
            if self._scope(event.metadata) != "WORLD_TRUTH":
                continue
            relevant = False
            if fact.fact_type == "life_state":
                existing = self.consistency_engine._event_life_state(event)
                candidate = self.consistency_engine._life_state(fact.value)
                relevant = bool(existing and candidate and existing != candidate)
            elif fact.fact_type == "location":
                relevant = bool(
                    event.location_entity_id
                    and event.location_entity_id != fact.object_entity_id
                    and (
                        self.consistency_engine._normalize(event.event_type)
                        in {"location", "located_at", "位置", "所在地"}
                        or event.metadata.get("state_type") == "location"
                    )
                )
            if relevant and event.start_chapter < chapter:
                metadata = dict(event.metadata)
                chain = self._closed_chain(metadata)
                chain.append(
                    {
                        "projection_id": row["projection_id"],
                        "source_reference": self._source_reference(row),
                        "prior_end_chapter": event.end_chapter,
                        "prior_source": event.source.model_dump(mode="json"),
                    }
                )
                metadata["closed_by_fact_projections"] = chain
                for key in (
                    "closed_by_projection_id",
                    "closed_by_source_reference",
                    "prior_end_chapter",
                    "prior_source",
                ):
                    metadata.pop(key, None)
                self.temporal_service.update_event(
                    row["novel_id"],
                    event.event_id,
                    TemporalEventUpdate(
                        expected_revision=event.revision,
                        source=source,
                        end_chapter=chapter - 1,
                        metadata=metadata,
                    ),
                )

    def _ensure_relation(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
        source: TemporalSourceReference,
    ) -> str:
        assert fact.subject_entity_id and fact.object_entity_id
        graph_id = self._graph_id(row, "relation")
        self._close_prior_relationships(row, fact, source)
        try:
            current = self.temporal_service.get_relation(row["novel_id"], graph_id)
        except TemporalGraphNotFoundError:
            self.temporal_service.create_relation(
                row["novel_id"],
                TemporalRelationCreate(
                    relation_id=graph_id,
                    subject_entity_id=fact.subject_entity_id,
                    predicate=fact.predicate,
                    object_entity_id=fact.object_entity_id,
                    context_type="character",
                    description=fact.evidence,
                    valid_from_chapter=int(row["chapter_number"]),
                    source=source,
                    confidence=fact.confidence,
                    metadata=self._fact_metadata(row, fact),
                ),
            )
        else:
            if (
                current.subject_entity_id != fact.subject_entity_id
                or current.object_entity_id != fact.object_entity_id
                or current.predicate != fact.predicate
                or current.metadata.get("projection_id") != row["projection_id"]
            ):
                raise FactProjectionConflictError(
                    f"Stable Temporal Relation ID collision: {graph_id}"
                )
            if current.metadata.get("retracted"):
                self.temporal_service.update_relation(
                    row["novel_id"],
                    graph_id,
                    TemporalRelationUpdate(
                        expected_revision=current.revision,
                        source=source,
                        metadata=self._fact_metadata(row, fact),
                    ),
                )
            elif current.source != source:
                raise FactProjectionConflictError(
                    f"Stable Temporal Relation source collision: {graph_id}"
                )
        return graph_id

    def _ensure_event(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
        source: TemporalSourceReference,
    ) -> str:
        assert fact.subject_entity_id
        graph_id = self._graph_id(row, "event")
        self._close_prior_events(row, fact, source)
        location_id = (
            fact.object_entity_id if fact.fact_type == "location" else None
        )
        participants = [fact.subject_entity_id]
        if fact.object_entity_id and fact.fact_type != "location":
            participants.append(fact.object_entity_id)
        event_type = (
            "location"
            if fact.fact_type == "location"
            else (
                str(fact.value or "life_state")
                if fact.fact_type == "life_state"
                else str(fact.predicate or fact.fact_type)
            )
        )
        title = str(fact.value or fact.predicate or fact.evidence)[:256]
        metadata = self._fact_metadata(row, fact)
        if fact.fact_type == "location":
            metadata["state_type"] = "location"
        try:
            current = self.temporal_service.get_event(row["novel_id"], graph_id)
        except TemporalGraphNotFoundError:
            self.temporal_service.create_event(
                row["novel_id"],
                TemporalEventCreate(
                    event_id=graph_id,
                    event_type=event_type[:128],
                    context_type=(
                        "character"
                        if fact.fact_type in {"life_state", "identity"}
                        else "plot"
                    ),
                    title=title,
                    summary=fact.evidence,
                    participant_entity_ids=participants,
                    location_entity_id=location_id,
                    start_chapter=int(row["chapter_number"]),
                    source=source,
                    confidence=fact.confidence,
                    metadata=metadata,
                ),
            )
        else:
            if (
                current.participant_entity_ids != participants
                or current.location_entity_id != location_id
                or current.metadata.get("projection_id") != row["projection_id"]
            ):
                raise FactProjectionConflictError(
                    f"Stable Temporal Event ID collision: {graph_id}"
                )
            if current.metadata.get("retracted"):
                self.temporal_service.update_event(
                    row["novel_id"],
                    graph_id,
                    TemporalEventUpdate(
                        expected_revision=current.revision,
                        source=source,
                        metadata=metadata,
                    ),
                )
            elif current.source != source:
                raise FactProjectionConflictError(
                    f"Stable Temporal Event source collision: {graph_id}"
                )
        return graph_id

    def _project_graph(
        self,
        row: dict[str, Any],
        fact: ConsistencyFactCandidate,
    ) -> None:
        source = self._source(row)
        if fact.fact_type == "relationship":
            kind = "relation"
            graph_id = self._ensure_relation(row, fact, source)
        else:
            kind = "event"
            graph_id = self._ensure_event(row, fact, source)
        self.manuscript_storage.update_fact_projection(
            row["projection_id"],
            graph_kind=kind,
            graph_id=graph_id,
            graph_projected=True,
            expected_operation="project",
        )

    async def _retract_memory(self, row: dict[str, Any]) -> None:
        memory_id = row.get("memory_id") or self._memory_id(row)
        memory = await self.memory_storage.get(memory_id)
        if memory is not None:
            await self.memory_storage.delete(memory_id)
        self.manuscript_storage.update_fact_projection(
            row["projection_id"],
            memory_id=memory_id,
            memory_projected=True,
            expected_operation="retract",
        )

    async def _retract_vector(self, row: dict[str, Any]) -> None:
        memory_id = row.get("memory_id") or self._memory_id(row)
        await self.indexer.remove(memory_id)
        self.manuscript_storage.update_fact_projection(
            row["projection_id"],
            vector_projected=True,
            expected_operation="retract",
        )

    def _restore_graph_intervals(
        self,
        row: dict[str, Any],
        source: TemporalSourceReference,
    ) -> None:
        projection_id = row["projection_id"]
        for relation in self.temporal_service.list_relations(
            row["novel_id"],
            include_historical=True,
            limit=500,
        ):
            chain = self._closed_chain(relation.metadata)
            matching = next(
                (
                    item
                    for item in reversed(chain)
                    if item.get("projection_id") == projection_id
                ),
                None,
            )
            if matching is None:
                continue
            metadata = dict(relation.metadata)
            prior_end = matching.get("prior_end_chapter")
            prior_source = matching.get("prior_source")
            chain.remove(matching)
            if chain:
                metadata["closed_by_fact_projections"] = chain
            else:
                metadata.pop("closed_by_fact_projections", None)
            for key in (
                "closed_by_projection_id",
                "closed_by_source_reference",
                "prior_valid_to_chapter",
                "prior_source",
            ):
                metadata.pop(key, None)
            if prior_source is not None:
                metadata["restored_prior_source"] = prior_source
            self.temporal_service.update_relation(
                row["novel_id"],
                relation.relation_id,
                TemporalRelationUpdate(
                    expected_revision=relation.revision,
                    source=source,
                    valid_to_chapter=prior_end,
                    metadata=metadata,
                ),
            )
        for event in self.temporal_service.list_events(
            row["novel_id"],
            include_historical=True,
            limit=500,
        ):
            chain = self._closed_chain(event.metadata)
            matching = next(
                (
                    item
                    for item in reversed(chain)
                    if item.get("projection_id") == projection_id
                ),
                None,
            )
            if matching is None:
                continue
            metadata = dict(event.metadata)
            prior_end = matching.get("prior_end_chapter")
            prior_source = matching.get("prior_source")
            chain.remove(matching)
            if chain:
                metadata["closed_by_fact_projections"] = chain
            else:
                metadata.pop("closed_by_fact_projections", None)
            for key in (
                "closed_by_projection_id",
                "closed_by_source_reference",
                "prior_end_chapter",
                "prior_source",
            ):
                metadata.pop(key, None)
            if prior_source is not None:
                metadata["restored_prior_source"] = prior_source
            self.temporal_service.update_event(
                row["novel_id"],
                event.event_id,
                TemporalEventUpdate(
                    expected_revision=event.revision,
                    source=source,
                    end_chapter=prior_end,
                    metadata=metadata,
                ),
            )

    def _retract_graph(self, row: dict[str, Any]) -> None:
        kind = row.get("graph_kind") or (
            "relation" if row["fact"].fact_type == "relationship" else "event"
        )
        graph_id = row.get("graph_id") or self._graph_id(row, kind)
        source = self._retraction_source(row)
        superseded_by = row.get("superseded_by_revision")
        self._restore_graph_intervals(row, source)
        try:
            if kind == "relation":
                current = self.temporal_service.get_relation(
                    row["novel_id"], graph_id
                )
                metadata = dict(current.metadata)
                metadata.update(
                    {
                        "retracted": True,
                        "retraction_reason": "manuscript_revision_superseded",
                        "superseded_by_revision": superseded_by,
                    }
                )
                if current.source != source or current.metadata != metadata:
                    self.temporal_service.update_relation(
                        row["novel_id"],
                        graph_id,
                        TemporalRelationUpdate(
                            expected_revision=current.revision,
                            source=source,
                            metadata=metadata,
                        ),
                    )
            else:
                current = self.temporal_service.get_event(
                    row["novel_id"], graph_id
                )
                metadata = dict(current.metadata)
                metadata.update(
                    {
                        "retracted": True,
                        "retraction_reason": "manuscript_revision_superseded",
                        "superseded_by_revision": superseded_by,
                    }
                )
                if current.source != source or current.metadata != metadata:
                    self.temporal_service.update_event(
                        row["novel_id"],
                        graph_id,
                        TemporalEventUpdate(
                            expected_revision=current.revision,
                            source=source,
                            metadata=metadata,
                        ),
                    )
        except TemporalGraphNotFoundError:
            pass
        self.manuscript_storage.update_fact_projection(
            row["projection_id"],
            graph_kind=kind,
            graph_id=graph_id,
            graph_projected=True,
            expected_operation="retract",
        )

    async def _retract(self, row: dict[str, Any]) -> None:
        if not row.get("vector_projected"):
            await self._retract_vector(row)
        if not row.get("graph_projected"):
            self._retract_graph(row)
        if not row.get("memory_projected"):
            await self._retract_memory(row)

    async def process_projection(self, projection_id: str) -> None:
        row = self.manuscript_storage.claim_fact_projection(projection_id)
        if row is None:
            return
        try:
            if row.get("operation") == "retract":
                await self._retract(row)
                self.manuscript_storage.update_fact_projection(
                    projection_id,
                    completed=True,
                    expected_operation="retract",
                )
                return
            await self._prepare_projection_retry(row)
            fact = self._validate_candidate(row)
            memory = await self._existing_memory(row, fact)
            if memory is None:
                memory = await self._project_memory(row, fact)
            if not row.get("vector_projected"):
                await self._project_vector(row, memory)
            if not row.get("graph_projected"):
                self._project_graph(row, fact)
            self.manuscript_storage.update_fact_projection(
                projection_id,
                completed=True,
                expected_operation="project",
            )
        except Exception as exc:
            try:
                self.manuscript_storage.update_fact_projection(
                    projection_id,
                    error=str(exc),
                    expected_operation=str(row.get("operation") or "project"),
                )
            except Exception:
                logger.exception(
                    "Accepted fact projection failure status update failed: "
                    f"projection_id={projection_id}"
                )
            logger.exception(
                "Accepted fact projection failed: "
                f"projection_id={projection_id}"
            )

    async def project_revision(
        self,
        novel_id: str,
        manuscript_chapter_id: str,
        manuscript_revision: int,
    ) -> FactProjectionSummary:
        summary = self.manuscript_storage.get_fact_projection(
            novel_id,
            manuscript_chapter_id,
            manuscript_revision,
        )
        for item in summary.items:
            if item.status in {"pending", "failed"}:
                await self.process_projection(item.projection_id)
        return self.manuscript_storage.get_fact_projection(
            novel_id,
            manuscript_chapter_id,
            manuscript_revision,
        )

    async def project_chapter(
        self,
        manuscript_chapter_id: str,
        *,
        limit: int | None = None,
    ) -> int:
        projection_ids = (
            self.manuscript_storage.list_incomplete_fact_projection_ids(
                manuscript_chapter_id=manuscript_chapter_id,
                limit=limit,
            )
        )
        completed = 0
        for projection_id in projection_ids:
            await self.process_projection(projection_id)
            if (
                self.manuscript_storage.get_projection_status(projection_id)
                != "completed"
            ):
                break
            completed += 1
        return completed

    async def recover_incomplete(self, *, limit: int | None = None) -> int:
        self.manuscript_storage.recover_processing_fact_projections()
        projection_ids = self.manuscript_storage.list_incomplete_fact_projection_ids(
            limit=limit
        )
        completed = 0
        blocked_chapters: set[str] = set()
        for projection_id in projection_ids:
            row = self.manuscript_storage.peek_fact_projection(projection_id)
            chapter_id = str(row["manuscript_chapter_id"])
            if chapter_id in blocked_chapters:
                continue
            await self.process_projection(projection_id)
            if (
                self.manuscript_storage.get_projection_status(projection_id)
                == "completed"
            ):
                completed += 1
            else:
                blocked_chapters.add(chapter_id)
        return completed


fact_projection_service = FactProjectionService()
