from __future__ import annotations

import tempfile
import unittest

from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import manuscripts as manuscript_api
from app.consistency.schemas import (
    ConsistencyCheckRequest,
    ConsistencyFactCandidate,
)
from app.consistency.service import ConsistencyEngine
from app.fact_projection.service import FactProjectionService
from app.manuscripts.schemas import ManuscriptAcceptRequest
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.temporal_graph.schemas import (
    TemporalRelationCreate,
    TemporalSourceReference,
)
from app.temporal_graph.service import TemporalGraphService
from app.temporal_graph.storage import TemporalGraphStorage
from test_manuscripts import ManuscriptFixture


class FakeIndexer:
    def __init__(self) -> None:
        self.indexed_ids: set[str] = set()
        self.upsert_memory = AsyncMock(side_effect=self._upsert)
        self.remove = AsyncMock(side_effect=self._remove)
        self.list_indexed_ids = AsyncMock(side_effect=self._list_ids)

    async def _upsert(self, memory) -> int:
        self.indexed_ids.add(str(memory.id))
        return 1

    async def _remove(self, memory_id: str) -> bool:
        self.indexed_ids.discard(str(memory_id))
        return True

    async def _list_ids(self) -> set[str]:
        return set(self.indexed_ids)


class FactProjectionTests(ManuscriptFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        root = Path(self.temp.name)
        self.memory_storage = SQLiteMemoryStorage(str(root / "memory.db"))
        self.graph_storage = TemporalGraphStorage(str(root / "temporal.db"))
        self.indexer = FakeIndexer()
        self.temporal_service = TemporalGraphService(
            storage=self.graph_storage,
            novel_service=self.novel_service,
            manuscript_service=self.manuscript_storage,
        )
        self.projector = FactProjectionService(
            manuscript_storage=self.manuscript_storage,
            novel_service=self.novel_service,
            memory_storage=self.memory_storage,
            indexer=self.indexer,
            temporal_service=self.temporal_service,
            consistency_engine=ConsistencyEngine(
                novel_service=self.novel_service,
                temporal_storage=self.graph_storage,
            ),
        )
    def _fact(self, **updates) -> dict:
        value = {
            "fact_id": "FACT-REL",
            "fact_type": "relationship",
            "subject_entity_id": "char_lan",
            "predicate": "盟友",
            "object_entity_id": "char_qi",
            "evidence": "岚与祁正式结盟。",
            "chapter_number": 1,
            "change_type": "assertion",
            "confidence": 0.92,
            "knowledge_scope": "WORLD_TRUTH",
        }
        value.update(updates)
        return value

    def _accept(self, fact: dict, *, content: str | None = None):
        run_id = self.create_workflow(
            contents=[content or fact["evidence"]],
            candidate_facts=[fact],
        )
        imported = self.import_run(run_id)
        accepted = self.service.accept_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        return imported, accepted

    async def test_accept_transaction_freezes_fact_and_enqueues_outbox(self) -> None:
        fact = self._fact()
        imported, accepted = self._accept(fact)
        revision = accepted.accepted_revision

        self.assertEqual(revision.candidate_facts[0].fact_id, "FACT-REL")
        summary = accepted.fact_projection
        self.assertEqual(summary.status, "pending")
        self.assertEqual(summary.total_count, 1)
        self.assertEqual(summary.items[0].operation, "project")
        self.assertEqual(summary.items[0].attempts, 0)

        repeated = self.service.accept_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=2),
        )
        self.assertFalse(repeated.changed)
        self.assertEqual(repeated.fact_projection.total_count, 1)

    async def test_projects_memory_vector_graph_with_exact_provenance(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id

        summary = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )

        self.assertEqual(summary.status, "completed")
        item = summary.items[0]
        memory = await self.memory_storage.get(item.memory_id)
        relation = self.temporal_service.get_relation(
            self.project.novel_id, item.graph_id
        )
        self.assertEqual(memory.memory_tier.value, "long_term")
        self.assertEqual(memory.hit_count, 1)
        self.assertEqual(
            memory.metadata["source_reference"],
            f"manuscript:{chapter_id}:r1:fact:0",
        )
        self.assertEqual(relation.source.source_id, chapter_id)
        self.assertEqual(relation.source.source_revision, 1)
        self.assertEqual(relation.source.source_chapter_number, 1)
        self.assertEqual(relation.metadata["projection_id"], item.projection_id)
        self.indexer.upsert_memory.assert_awaited_once()

    async def test_repeat_projection_is_idempotent(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        first = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        memory_id = first.items[0].memory_id
        graph_id = first.items[0].graph_id
        lifecycle_before = await self.memory_storage.list_lifecycle_events(memory_id)
        graph_before = self.graph_storage.list_relation_revisions(
            self.project.novel_id, graph_id
        )

        second = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )

        memory = await self.memory_storage.get(memory_id)
        lifecycle_after = await self.memory_storage.list_lifecycle_events(memory_id)
        graph_after = self.graph_storage.list_relation_revisions(
            self.project.novel_id, graph_id
        )
        self.assertEqual(second.items[0].attempts, 1)
        self.assertEqual(memory.hit_count, 1)
        self.assertEqual(len(lifecycle_before), len(lifecycle_after))
        self.assertEqual(len(graph_before), len(graph_after))
        self.indexer.upsert_memory.assert_awaited_once()

    async def test_retry_repairs_missing_completed_vector_checkpoint(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        first = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        item = first.items[0]
        self.indexer.indexed_ids.clear()
        with self.manuscript_storage._connect() as conn:
            conn.execute(
                """
                UPDATE manuscript_fact_projections
                SET status = 'failed', last_error = 'simulated replay'
                WHERE projection_id = ?
                """,
                (item.projection_id,),
            )
            conn.commit()

        repaired = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )

        self.assertEqual(repaired.status, "completed")
        self.assertIn(item.memory_id, self.indexer.indexed_ids)
        self.assertEqual(self.indexer.upsert_memory.await_count, 2)

    async def test_retry_repairs_missing_completed_memory_checkpoint(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        first = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        item = first.items[0]
        await self.memory_storage.delete(item.memory_id)
        with self.manuscript_storage._connect() as conn:
            conn.execute(
                """
                UPDATE manuscript_fact_projections
                SET status = 'failed', last_error = 'simulated replay'
                WHERE projection_id = ?
                """,
                (item.projection_id,),
            )
            conn.commit()

        repaired = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )

        self.assertEqual(repaired.status, "completed")
        self.assertIsNotNone(await self.memory_storage.get(item.memory_id))
        self.assertIn(item.memory_id, self.indexer.indexed_ids)
        self.assertGreaterEqual(self.indexer.upsert_memory.await_count, 2)

    async def test_retry_repairs_missing_completed_graph_checkpoint(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        first = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        item = first.items[0]
        with self.graph_storage._connect() as conn:
            conn.execute(
                "DELETE FROM temporal_relations WHERE relation_id = ?",
                (item.graph_id,),
            )
            conn.commit()
        with self.manuscript_storage._connect() as conn:
            conn.execute(
                """
                UPDATE manuscript_fact_projections
                SET status = 'failed', last_error = 'simulated replay'
                WHERE projection_id = ?
                """,
                (item.projection_id,),
            )
            conn.commit()

        repaired = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )

        relation = self.temporal_service.get_relation(
            self.project.novel_id, item.graph_id
        )
        self.assertEqual(repaired.status, "completed")
        self.assertEqual(relation.metadata["projection_id"], item.projection_id)

    async def test_vector_failure_is_checkpointed_and_retryable(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        calls = 0

        async def fail_once(memory):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("vector down")
            return await self.indexer._upsert(memory)

        self.indexer.upsert_memory.side_effect = fail_once

        failed = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        self.assertEqual(failed.status, "failed")
        self.assertTrue(failed.items[0].memory_projected)
        self.assertFalse(failed.items[0].vector_projected)
        memory_id = failed.items[0].memory_id
        lifecycle_before = await self.memory_storage.list_lifecycle_events(memory_id)

        completed = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        lifecycle_after = await self.memory_storage.list_lifecycle_events(memory_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.items[0].attempts, 2)
        self.assertEqual(len(lifecycle_before), len(lifecycle_after))
        self.assertEqual((await self.memory_storage.get(memory_id)).hit_count, 1)

    async def test_replacement_acceptance_retracts_old_fact(self) -> None:
        old_fact = self._fact()
        imported, _ = self._accept(old_fact)
        chapter_id = imported.chapter.manuscript_chapter_id
        old_summary = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        old_memory_id = old_summary.items[0].memory_id
        old_graph_id = old_summary.items[0].graph_id

        new_fact = self._fact(
            fact_id="FACT-HOSTILE",
            predicate="敌对",
            evidence="岚与祁公开决裂，成为敌人。",
            change_type="transition",
        )
        run_id = self.create_workflow(
            contents=[new_fact["evidence"]],
            candidate_facts=[new_fact],
        )
        appended = self.import_run(run_id, expected=2)
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            appended.imported_revisions[-1].revision,
            ManuscriptAcceptRequest(expected_manuscript_revision=3),
        )

        await self.projector.project_chapter(chapter_id)
        current = self.graph_storage.list_relations(
            self.project.novel_id,
            as_of_chapter=1,
        )
        old = self.temporal_service.get_relation(
            self.project.novel_id, old_graph_id
        )
        self.assertIsNone(await self.memory_storage.get(old_memory_id))
        self.assertTrue(old.metadata["retracted"])
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].predicate, "敌对")
        summary = self.manuscript_storage.get_fact_projection(
            self.project.novel_id,
            chapter_id,
            appended.imported_revisions[-1].revision,
        )
        self.assertEqual(summary.total_count, 2)
        self.assertTrue(all(item.status == "completed" for item in summary.items))
        self.assertEqual(
            {item.operation for item in summary.items},
            {"project", "retract"},
        )

    async def test_failed_retraction_blocks_replacement_projection(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        new_fact = self._fact(
            fact_id="FACT-HOSTILE",
            predicate="敌对",
            evidence="岚与祁公开决裂，成为敌人。",
            change_type="transition",
        )
        run_id = self.create_workflow(
            contents=[new_fact["evidence"]],
            candidate_facts=[new_fact],
        )
        appended = self.import_run(run_id, expected=2)
        replacement_revision = appended.imported_revisions[-1].revision
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            replacement_revision,
            ManuscriptAcceptRequest(expected_manuscript_revision=3),
        )
        self.indexer.remove.side_effect = RuntimeError("remove unavailable")

        await self.projector.project_chapter(chapter_id)

        summary = self.manuscript_storage.get_fact_projection(
            self.project.novel_id, chapter_id, replacement_revision
        )
        by_operation = {item.operation: item for item in summary.items}
        self.assertEqual(by_operation["retract"].status, "failed")
        self.assertEqual(by_operation["project"].status, "pending")
        self.assertEqual(summary.status, "failed")
        self.assertIsNone(by_operation["project"].memory_id)

    async def test_accepting_older_revision_reactivates_its_facts(self) -> None:
        first_fact = self._fact()
        first = self.import_run(self.create_workflow(
            contents=[first_fact["evidence"]],
            candidate_facts=[first_fact],
        ))
        chapter_id = first.chapter.manuscript_chapter_id
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        first_projected = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        first_graph_id = first_projected.items[0].graph_id
        second_fact = self._fact(
            fact_id="FACT-HOSTILE",
            predicate="敌对",
            evidence="岚与祁公开决裂，成为敌人。",
            change_type="transition",
        )
        second = self.import_run(
            self.create_workflow(
                contents=[second_fact["evidence"]],
                candidate_facts=[second_fact],
            ),
            expected=2,
        )
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            second.imported_revisions[-1].revision,
            ManuscriptAcceptRequest(expected_manuscript_revision=3),
        )
        await self.projector.project_chapter(chapter_id)

        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=4),
        )
        await self.projector.project_chapter(chapter_id)

        current = self.graph_storage.list_relations(
            self.project.novel_id, as_of_chapter=1
        )
        reactivated = self.temporal_service.get_relation(
            self.project.novel_id, first_graph_id
        )
        self.assertFalse(reactivated.metadata.get("retracted", False))
        self.assertEqual([item.predicate for item in current], ["盟友"])

    async def test_newer_replacement_retargets_failed_retraction(self) -> None:
        imported, _ = self._accept(self._fact())
        chapter_id = imported.chapter.manuscript_chapter_id
        await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        second_fact = self._fact(
            fact_id="FACT-SECOND",
            evidence="岚与祁仍维持正式同盟。",
        )
        second = self.import_run(
            self.create_workflow(
                contents=[second_fact["evidence"]],
                candidate_facts=[second_fact],
            ),
            expected=2,
        )
        second_revision = second.imported_revisions[-1].revision
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            second_revision,
            ManuscriptAcceptRequest(expected_manuscript_revision=3),
        )
        third_fact = self._fact(
            fact_id="FACT-THIRD",
            evidence="岚与祁再次确认同盟。",
        )
        third = self.import_run(
            self.create_workflow(
                contents=[third_fact["evidence"]],
                candidate_facts=[third_fact],
            ),
            expected=4,
        )
        third_revision = third.imported_revisions[-1].revision
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            third_revision,
            ManuscriptAcceptRequest(expected_manuscript_revision=5),
        )

        summary = self.manuscript_storage.get_fact_projection(
            self.project.novel_id, chapter_id, third_revision
        )
        retractions = [
            item for item in summary.items if item.operation == "retract"
        ]
        self.assertEqual(len(retractions), 2)
        self.assertTrue(
            all(
                item.superseded_by_revision == third_revision
                for item in retractions
            )
        )

    async def test_transition_closes_prior_relation_once(self) -> None:
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        old = self.temporal_service.create_relation(
            self.project.novel_id,
            TemporalRelationCreate(
                relation_id="rel_bible_allies",
                subject_entity_id="char_lan",
                predicate="盟友",
                object_entity_id="char_qi",
                valid_from_chapter=1,
                source=TemporalSourceReference(
                    source_type="story_bible",
                    source_id=self.project.novel_id,
                    source_revision=bible.revision,
                ),
            ),
        )
        fact = self._fact(
            predicate="敌对",
            evidence="岚与祁公开决裂，成为敌人。",
            change_type="transition",
            chapter_number=2,
        )
        run_id = self.create_workflow(
            chapter=self.chapter_two,
            contents=[fact["evidence"]],
            candidate_facts=[fact],
        )
        imported = self.import_run(run_id)
        self.service.accept_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )

        summary = await self.projector.project_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
        )
        closed = self.temporal_service.get_relation(
            self.project.novel_id, old.relation_id
        )
        self.assertEqual(summary.status, "completed")
        self.assertEqual(closed.valid_to_chapter, 1)
        self.assertEqual(closed.revision, 2)

    async def test_retracting_transition_restores_prior_interval(self) -> None:
        bible = self.novel_service.get_story_bible(self.project.novel_id)
        old = self.temporal_service.create_relation(
            self.project.novel_id,
            TemporalRelationCreate(
                relation_id="rel_restore_allies",
                subject_entity_id="char_lan",
                predicate="盟友",
                object_entity_id="char_qi",
                valid_from_chapter=1,
                source=TemporalSourceReference(
                    source_type="story_bible",
                    source_id=self.project.novel_id,
                    source_revision=bible.revision,
                ),
            ),
        )
        transition = self._fact(
            predicate="敌对",
            evidence="岚与祁公开决裂，成为敌人。",
            change_type="transition",
            chapter_number=2,
        )
        first_run = self.create_workflow(
            chapter=self.chapter_two,
            contents=[transition["evidence"]],
            candidate_facts=[transition],
        )
        first = self.import_run(first_run)
        chapter_id = first.chapter.manuscript_chapter_id
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            1,
            ManuscriptAcceptRequest(expected_manuscript_revision=1),
        )
        await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        replacement = self.import_run(
            self.create_workflow(
                chapter=self.chapter_two,
                contents=["岚独自整理旧档案。"],
                candidate_facts=[],
            ),
            expected=2,
        )
        replacement_revision = replacement.imported_revisions[-1].revision
        self.service.accept_revision(
            self.project.novel_id,
            chapter_id,
            replacement_revision,
            ManuscriptAcceptRequest(expected_manuscript_revision=3),
        )

        await self.projector.project_chapter(chapter_id)

        restored = self.temporal_service.get_relation(
            self.project.novel_id, old.relation_id
        )
        current = self.graph_storage.list_relations(
            self.project.novel_id, as_of_chapter=2
        )
        self.assertIsNone(restored.valid_to_chapter)
        self.assertEqual(
            [item.relation_id for item in current],
            [old.relation_id],
        )

    async def test_character_belief_does_not_pollute_world_state(self) -> None:
        belief = self._fact(
            predicate="敌对",
            evidence="岚误以为祁是敌人。",
            knowledge_scope="CHARACTER_BELIEF",
            knowledge_holder_entity_id="char_lan",
        )
        imported, _ = self._accept(belief)
        chapter_id = imported.chapter.manuscript_chapter_id
        summary = await self.projector.project_revision(
            self.project.novel_id, chapter_id, 1
        )
        self.assertEqual(summary.status, "completed")

        checked = self.projector.consistency_engine.check(
            self.project.novel_id,
            ConsistencyCheckRequest(
                user_id=self.project.user_id,
                chapter_number=1,
                content="岚与祁正式结盟。",
                candidate_facts=[
                    ConsistencyFactCandidate.model_validate(self._fact())
                ],
            ),
        )
        self.assertEqual(checked.conflicts, [])

    async def test_character_knowledge_projects_knower_metadata(self) -> None:
        fact = self._fact(
            evidence="岚得知自己与祁正式结盟。",
            change_type="transition",
            knowledge_scope="CHARACTER_KNOWLEDGE",
            knowledge_holder_entity_id="char_lan",
        )
        imported, _ = self._accept(fact)
        summary = await self.projector.project_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
        )
        relation = self.temporal_service.get_relation(
            self.project.novel_id, summary.items[0].graph_id
        )
        self.assertEqual(
            relation.metadata["knower_entity_ids"], ["char_lan"]
        )

    async def test_location_fact_projects_temporal_event(self) -> None:
        fact = self._fact(
            fact_id="FACT-LOC",
            fact_type="location",
            predicate="located_at",
            object_entity_id="loc_tower",
            evidence="岚进入北塔。",
            change_type="transition",
        )
        imported, _ = self._accept(fact)
        summary = await self.projector.project_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
        )
        item = summary.items[0]
        event = self.temporal_service.get_event(
            self.project.novel_id, item.graph_id
        )
        self.assertEqual(item.graph_kind, "event")
        self.assertEqual(event.event_type, "location")
        self.assertEqual(event.location_entity_id, "loc_tower")
        self.assertEqual(event.participant_entity_ids, ["char_lan"])

    async def test_projection_failure_does_not_rollback_acceptance(self) -> None:
        fact = self._fact(subject_entity_id="missing-character")
        imported, accepted = self._accept(fact)
        summary = await self.projector.project_revision(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
        )
        detail = self.manuscript_storage.get_chapter(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
        )
        self.assertTrue(accepted.changed)
        self.assertEqual(detail.chapter.accepted_revision, 1)
        self.assertEqual(summary.status, "failed")
        self.assertIn("unknown_entity", summary.items[0].last_error)

    async def test_startup_recovery_replays_processing_item(self) -> None:
        imported, accepted = self._accept(self._fact())
        item = accepted.fact_projection.items[0]
        claimed = self.manuscript_storage.claim_fact_projection(
            item.projection_id
        )
        self.assertEqual(claimed["operation"], "project")

        processed = await self.projector.recover_incomplete()

        summary = self.manuscript_storage.get_fact_projection(
            self.project.novel_id,
            imported.chapter.manuscript_chapter_id,
            1,
        )
        self.assertEqual(processed, 1)
        self.assertEqual(summary.status, "completed")

    async def test_fact_projection_api_get_retry_and_accept_response(self) -> None:
        fact = self._fact()
        run_id = self.create_workflow(
            contents=[fact["evidence"]],
            candidate_facts=[fact],
        )
        imported = self.import_run(run_id)
        chapter_id = imported.chapter.manuscript_chapter_id
        original_service = manuscript_api.service
        original_projection = manuscript_api.projection_service
        manuscript_api.service = self.service
        manuscript_api.projection_service = self.projector
        try:
            app = FastAPI()
            app.include_router(manuscript_api.router, prefix="/api/v1")
            with TestClient(app) as client:
                accepted = client.post(
                    f"/api/v1/novels/{self.project.novel_id}"
                    f"/manuscript/chapters/{chapter_id}/revisions/1/accept",
                    json={"expected_manuscript_revision": 1},
                )
                self.assertEqual(accepted.status_code, 200)
                self.assertEqual(
                    accepted.json()["data"]["fact_projection"]["status"],
                    "completed",
                )
                status_response = client.get(
                    f"/api/v1/novels/{self.project.novel_id}"
                    f"/manuscript/chapters/{chapter_id}/revisions/1"
                    "/fact-projection"
                )
                retry = client.post(
                    f"/api/v1/novels/{self.project.novel_id}"
                    f"/manuscript/chapters/{chapter_id}/revisions/1"
                    "/fact-projection/retry"
                )
                wrong_scope = client.post(
                    "/api/v1/novels/not-this-novel"
                    f"/manuscript/chapters/{chapter_id}/revisions/1"
                    "/fact-projection/retry"
                )
                self.assertEqual(status_response.status_code, 200)
                self.assertEqual(retry.status_code, 200)
                self.assertEqual(retry.json()["data"]["status"], "completed")
                self.assertEqual(wrong_scope.status_code, 404)
        finally:
            manuscript_api.service = original_service
            manuscript_api.projection_service = original_projection


if __name__ == "__main__":
    unittest.main()
