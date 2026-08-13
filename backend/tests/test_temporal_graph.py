from __future__ import annotations

import tempfile
import threading
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1 import temporal_graph as temporal_api
from app.novels.schemas import NovelEntityCreate, NovelProjectCreate
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.retrieval.providers import TemporalGraphRetrievalProvider
from app.retrieval.schemas import DualRetrievalRequest, RetrievalPath
from app.temporal_graph.schemas import (
    TemporalEventCreate,
    TemporalEventUpdate,
    TemporalGraphQueryRequest,
    TemporalRelationCreate,
    TemporalRelationUpdate,
    TemporalSourceReference,
)
from app.temporal_graph.service import TemporalGraphService
from app.temporal_graph.storage import (
    TemporalGraphConflictError,
    TemporalGraphStorage,
)


class FakeManuscriptService:
    def __init__(self) -> None:
        self.accepted = True
        self.chapter_number = 3

    def get_revision(self, novel_id, source_id, revision):
        del novel_id, source_id, revision
        return SimpleNamespace(is_accepted=self.accepted)

    def get_chapter(self, novel_id, source_id):
        del novel_id, source_id
        return SimpleNamespace(
            chapter=SimpleNamespace(chapter_number=self.chapter_number)
        )


class TemporalGraphFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.novel_storage = NovelProjectStorage(str(root / "novels.db"))
        self.novel_service = NovelProjectService(self.novel_storage)
        self.graph_storage = TemporalGraphStorage(
            str(root / "temporal_graph.db")
        )
        self.manuscripts = FakeManuscriptService()
        self.service = TemporalGraphService(
            storage=self.graph_storage,
            novel_service=self.novel_service,
            manuscript_service=self.manuscripts,
        )
        self.project = self.novel_service.create_project(
            NovelProjectCreate(user_id="graph-user", title="Temporal Test")
        )
        self.novel_id = self.project.novel_id
        for entity_id, entity_type, name in (
            ("char_lan", "character", "岚"),
            ("char_qi", "character", "祁"),
            ("loc_tower", "location", "北塔"),
        ):
            self.novel_service.create_entity(
                self.novel_id,
                NovelEntityCreate(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    canonical_name=name,
                ),
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def bible_source(self, revision: int = 1) -> TemporalSourceReference:
        return TemporalSourceReference(
            source_type="story_bible",
            source_id=self.novel_id,
            source_revision=revision,
        )

    @staticmethod
    def manuscript_source() -> TemporalSourceReference:
        return TemporalSourceReference(
            source_type="accepted_manuscript",
            source_id="manuscript-001",
            source_revision=2,
            source_chapter_number=3,
        )

    def create_event(self, **updates):
        values = {
            "event_id": "evt_arrival",
            "event_type": "arrival",
            "title": "抵达北塔",
            "summary": "岚抵达北塔并遇见祁。",
            "participant_entity_ids": ["char_lan", "char_qi"],
            "location_entity_id": "loc_tower",
            "start_chapter": 3,
            "end_chapter": 4,
            "source": self.manuscript_source(),
        }
        values.update(updates)
        return self.service.create_event(
            self.novel_id,
            TemporalEventCreate(**values),
        )

    def create_relation(self, **updates):
        values = {
            "relation_id": "rel_allies",
            "subject_entity_id": "char_lan",
            "predicate": "盟友",
            "object_entity_id": "char_qi",
            "description": "两人为共同目标结盟。",
            "valid_from_chapter": 3,
            "valid_to_chapter": 5,
            "source": self.manuscript_source(),
        }
        values.update(updates)
        return self.service.create_relation(
            self.novel_id,
            TemporalRelationCreate(**values),
        )


class TemporalGraphSchemaTests(unittest.TestCase):
    def test_invalid_intervals_are_rejected(self) -> None:
        source = TemporalSourceReference(
            source_type="story_bible",
            source_id="novel",
            source_revision=1,
        )
        with self.assertRaises(ValidationError):
            TemporalEventCreate(
                event_type="event",
                title="bad",
                start_chapter=4,
                end_chapter=3,
                source=source,
            )
        with self.assertRaises(ValidationError):
            TemporalRelationCreate(
                subject_entity_id="a",
                predicate="knows",
                object_entity_id="b",
                valid_from_chapter=4,
                valid_to_chapter=3,
                source=source,
            )
        with self.assertRaises(ValidationError):
            TemporalEventCreate(
                event_type="event",
                title="bad location",
                location_entity_id="   ",
                start_chapter=1,
                source=source,
            )


class TemporalGraphStorageTests(TemporalGraphFixture):
    def test_physical_schema_is_independent_and_normalized(self) -> None:
        with self.graph_storage._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertEqual(
            tables,
            {
                "temporal_events",
                "temporal_event_participants",
                "temporal_event_revisions",
                "temporal_relations",
                "temporal_relation_revisions",
            },
        )
        self.assertNotEqual(
            Path(self.graph_storage.db_path),
            Path(self.novel_storage.db_path),
        )

    def test_current_and_historical_chapter_queries(self) -> None:
        event = self.create_event()
        relation = self.create_relation()

        self.assertEqual(
            [item.event_id for item in self.service.list_events(
                self.novel_id, as_of_chapter=4
            )],
            [event.event_id],
        )
        self.assertEqual(
            self.service.list_events(self.novel_id, as_of_chapter=5),
            [],
        )
        self.assertEqual(self.service.list_events(self.novel_id), [])
        self.assertEqual(
            [item.event_id for item in self.service.list_events(
                self.novel_id,
                as_of_chapter=5,
                include_historical=True,
            )],
            [event.event_id],
        )
        self.assertEqual(
            [item.relation_id for item in self.service.list_relations(
                self.novel_id, as_of_chapter=5
            )],
            [relation.relation_id],
        )
        self.assertEqual(
            self.service.list_relations(self.novel_id, as_of_chapter=6),
            [],
        )

    def test_retracted_graph_fact_is_hidden_from_all_query_modes(self) -> None:
        relation = self.create_relation()
        self.service.update_relation(
            self.novel_id,
            relation.relation_id,
            TemporalRelationUpdate(
                expected_revision=relation.revision,
                source=self.manuscript_source(),
                metadata={"retracted": True},
            ),
        )

        self.assertEqual(
            self.service.list_relations(
                self.novel_id,
                as_of_chapter=5,
            ),
            [],
        )
        self.assertEqual(
            self.service.list_relations(
                self.novel_id,
                as_of_chapter=5,
                include_historical=True,
            ),
            [],
        )
        detail = self.service.get_relation(
            self.novel_id, relation.relation_id
        )
        self.assertTrue(detail.metadata["retracted"])

    def test_active_entity_filter_uses_participant_table(self) -> None:
        self.create_event()
        self.create_relation()
        self.assertEqual(
            len(self.service.list_events(
                self.novel_id,
                active_entity_ids=["char_qi"],
                include_historical=True,
            )),
            1,
        )
        self.assertEqual(
            self.service.list_events(
                self.novel_id,
                active_entity_ids=["missing"],
                include_historical=True,
            ),
            [],
        )

    def test_query_labels_character_belief_scope(self) -> None:
        self.create_relation(
            metadata={
                "knowledge_scope": "CHARACTER_BELIEF",
                "knower_entity_ids": ["char_lan"],
            }
        )
        result = self.service.query(
            self.novel_id,
            TemporalGraphQueryRequest(
                query="敌对",
                active_entity_ids=["char_lan", "char_qi"],
                as_of_chapter=5,
            ),
        )

        self.assertEqual(len(result.evidence), 1)
        self.assertTrue(
            result.evidence[0].content.startswith("[CHARACTER_BELIEF]")
        )
        self.assertEqual(
            result.evidence[0].metadata["knower_entity_ids"],
            ["char_lan"],
        )

    def test_update_is_revision_guarded_and_snapshots_are_append_only(self) -> None:
        event = self.create_event()
        updated = self.service.update_event(
            self.novel_id,
            event.event_id,
            TemporalEventUpdate(
                expected_revision=1,
                title="北塔会合",
                end_chapter=6,
                source=self.manuscript_source(),
            ),
        )
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.title, "北塔会合")
        with self.assertRaises(TemporalGraphConflictError):
            self.service.update_event(
                self.novel_id,
                event.event_id,
                TemporalEventUpdate(
                    expected_revision=1,
                    title="stale",
                    source=self.manuscript_source(),
                ),
            )
        revisions = self.service.list_event_revisions(
            self.novel_id,
            event.event_id,
        )
        self.assertEqual([item.revision for item in revisions], [2, 1])
        self.assertEqual(revisions[1].snapshot.title, "抵达北塔")

    def test_concurrent_event_updates_allow_exactly_one_revision_winner(self) -> None:
        event = self.create_event()
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def update(title: str) -> None:
            service = TemporalGraphService(
                storage=TemporalGraphStorage(self.graph_storage.db_path),
                novel_service=NovelProjectService(
                    NovelProjectStorage(self.novel_storage.db_path)
                ),
                manuscript_service=FakeManuscriptService(),
            )
            barrier.wait()
            try:
                service.update_event(
                    self.novel_id,
                    event.event_id,
                    TemporalEventUpdate(
                        expected_revision=1,
                        title=title,
                        source=self.manuscript_source(),
                    ),
                )
                outcome = "success"
            except TemporalGraphConflictError:
                outcome = "conflict"
            with lock:
                outcomes.append(outcome)

        threads = [
            threading.Thread(target=update, args=("版本甲",)),
            threading.Thread(target=update, args=("版本乙",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(sorted(outcomes), ["conflict", "success"])
        current = self.service.get_event(self.novel_id, event.event_id)
        self.assertEqual(current.revision, 2)
        self.assertEqual(
            [item.revision for item in self.service.list_event_revisions(
                self.novel_id, event.event_id
            )],
            [2, 1],
        )

    def test_relation_update_and_reopen_preserve_history(self) -> None:
        relation = self.create_relation()
        updated = self.service.update_relation(
            self.novel_id,
            relation.relation_id,
            TemporalRelationUpdate(
                expected_revision=1,
                predicate="互不信任",
                valid_from_chapter=6,
                valid_to_chapter=None,
                source=self.bible_source(),
            ),
        )
        self.assertEqual(updated.revision, 2)
        reopened = TemporalGraphStorage(self.graph_storage.db_path)
        self.assertEqual(
            reopened.get_relation(self.novel_id, relation.relation_id),
            updated,
        )
        self.assertEqual(
            [item.revision for item in reopened.list_relation_revisions(
                self.novel_id, relation.relation_id
            )],
            [2, 1],
        )


class TemporalGraphSourceValidationTests(TemporalGraphFixture):
    def test_entity_and_location_references_are_strict(self) -> None:
        with self.assertRaises(KeyError):
            self.create_event(participant_entity_ids=["missing"])
        with self.assertRaises(TemporalGraphConflictError):
            self.create_event(location_entity_id="char_lan")

    def test_story_bible_source_revision_must_exist(self) -> None:
        with self.assertRaises(KeyError):
            self.create_event(source=self.bible_source(999))
        event = self.create_event(source=self.bible_source(1))
        self.assertEqual(event.source.source_type, "story_bible")

    def test_manuscript_source_must_be_accepted_and_match_chapter(self) -> None:
        self.manuscripts.accepted = False
        with self.assertRaises(TemporalGraphConflictError):
            self.create_event()
        self.manuscripts.accepted = True
        self.manuscripts.chapter_number = 4
        with self.assertRaises(TemporalGraphConflictError):
            self.create_event()


class TemporalGraphQueryTests(TemporalGraphFixture):
    def test_query_ranks_active_entity_and_keeps_source(self) -> None:
        self.create_event()
        self.create_relation()
        result = self.service.query(
            self.novel_id,
            TemporalGraphQueryRequest(
                query="岚 北塔 盟友",
                active_entity_ids=["char_lan"],
                as_of_chapter=4,
                top_k=10,
            ),
            expected_user_id="graph-user",
        )
        self.assertEqual(len(result.evidence), 2)
        self.assertIn("岚", result.evidence[0].content)
        self.assertEqual(
            result.evidence[0].source.source_type,
            "accepted_manuscript",
        )

    def test_query_user_scope_is_enforced(self) -> None:
        self.create_event()
        with self.assertRaises(KeyError):
            self.service.query(
                self.novel_id,
                TemporalGraphQueryRequest(query="北塔"),
                expected_user_id="other-user",
            )


class TemporalGraphProviderTests(TemporalGraphFixture):
    async def _retrieve(self):
        provider = TemporalGraphRetrievalProvider()
        with patch(
            "app.retrieval.providers.temporal_graph_service",
            self.service,
        ):
            return await provider.retrieve(
                DualRetrievalRequest(
                    user_id="graph-user",
                    novel_id=self.novel_id,
                    query="岚 北塔",
                    active_entity_ids=["char_lan"],
                    as_of="chapter:4",
                ),
                10,
            )

    def test_provider_maps_graph_evidence_and_coordinates(self) -> None:
        self.create_event()
        items = __import__("asyncio").run(self._retrieve())
        self.assertEqual(items[0].path, RetrievalPath.GRAPH)
        self.assertEqual(items[0].source_id, "evt_arrival")
        self.assertEqual(items[0].metadata["valid_from_chapter"], 3)

    def test_provider_marks_unknown_novel_scope_unavailable(self) -> None:
        provider = TemporalGraphRetrievalProvider()
        with (
            patch(
                "app.retrieval.providers.temporal_graph_service",
                self.service,
            ),
            self.assertRaises(Exception) as raised,
        ):
            __import__("asyncio").run(
                provider.retrieve(
                    DualRetrievalRequest(
                        user_id="graph-user",
                        novel_id="missing",
                        query="q",
                    ),
                    10,
                )
            )
        self.assertEqual(
            type(raised.exception).__name__,
            "RetrievalPathUnavailable",
        )


class TemporalGraphApiTests(TemporalGraphFixture):
    def setUp(self) -> None:
        super().setUp()
        api = FastAPI()
        api.include_router(temporal_api.router, prefix="/api/v1")
        self.client = TestClient(api)
        self.patch = patch.object(temporal_api, "service", self.service)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.client.close()
        super().tearDown()

    def test_event_relation_query_revisions_and_openapi(self) -> None:
        source = self.manuscript_source().model_dump(mode="json")
        event = self.client.post(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/events",
            json={
                "event_id": "evt_api",
                "event_type": "arrival",
                "title": "抵达北塔",
                "participant_entity_ids": ["char_lan"],
                "location_entity_id": "loc_tower",
                "start_chapter": 3,
                "source": source,
            },
        )
        self.assertEqual(event.status_code, 201)
        relation = self.client.post(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/relations",
            json={
                "relation_id": "rel_api",
                "subject_entity_id": "char_lan",
                "predicate": "盟友",
                "object_entity_id": "char_qi",
                "valid_from_chapter": 3,
                "source": source,
            },
        )
        self.assertEqual(relation.status_code, 201)
        query = self.client.post(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/query",
            json={"query": "岚 盟友", "as_of_chapter": 3},
        )
        self.assertEqual(query.status_code, 200)
        self.assertEqual(len(query.json()["data"]["evidence"]), 2)
        revisions = self.client.get(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/"
            "events/evt_api/revisions"
        )
        self.assertEqual(revisions.status_code, 200)
        paths = self.client.app.openapi()["paths"]
        self.assertIn(
            "/api/v1/novels/{novel_id}/temporal-graph/query",
            paths,
        )

    def test_conflict_and_not_found_statuses(self) -> None:
        missing = self.client.get(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/events/missing"
        )
        self.assertEqual(missing.status_code, 404)
        source = self.manuscript_source().model_dump(mode="json")
        created = self.client.post(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/relations",
            json={
                "relation_id": "rel_conflict",
                "subject_entity_id": "char_lan",
                "predicate": "盟友",
                "object_entity_id": "char_qi",
                "valid_from_chapter": 3,
                "source": source,
            },
        )
        self.assertEqual(created.status_code, 201)
        stale = self.client.put(
            f"/api/v1/novels/{self.novel_id}/temporal-graph/"
            "relations/rel_conflict",
            json={
                "expected_revision": 99,
                "predicate": "敌对",
                "source": source,
            },
        )
        self.assertEqual(stale.status_code, 409)


if __name__ == "__main__":
    unittest.main()
