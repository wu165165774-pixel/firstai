from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import consistency as consistency_api
from app.consistency.schemas import (
    ConsistencyAnalyzeRequest,
    ConsistencyCheckRequest,
    ConsistencyConstraintRequest,
    ConsistencyFactCandidate,
)
from app.consistency.service import ConsistencyEngine, ConsistencyOutputError
from app.llm.schemas import ChatResponse, TokenUsage
from app.novels.schemas import (
    NovelEntityCreate,
    NovelProjectCreate,
    NovelProjectUpdate,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.temporal_graph.schemas import (
    TemporalEventCreate,
    TemporalRelationCreate,
    TemporalSourceReference,
)
from app.temporal_graph.service import TemporalGraphService
from app.temporal_graph.storage import TemporalGraphStorage
from app.workflows.chapter_workflow import ChapterWorkflow
from app.workflows.grounding import ChapterWorkflowGrounding
from app.workflows.schemas import ChapterWorkflowRequest


def _scores(value: int = 90) -> dict:
    return {
        "continuity": value,
        "character_consistency": value,
        "world_consistency": value,
        "plot_logic": value,
        "prose_quality": value,
        "pacing": value,
        "overall": value,
    }


def _agent_result(agent: str, content: str):
    return SimpleNamespace(
        agent=agent,
        success=True,
        content=content,
        provider="test",
        model="test-model",
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        latency_ms=1.0,
        metadata={},
    )


class ConsistencyFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.novel_storage = NovelProjectStorage(str(root / "novels.db"))
        self.novel_service = NovelProjectService(self.novel_storage)
        self.graph_storage = TemporalGraphStorage(str(root / "temporal.db"))
        self.graph_service = TemporalGraphService(
            storage=self.graph_storage,
            novel_service=self.novel_service,
        )
        self.llm = SimpleNamespace(chat=AsyncMock())
        self.engine = ConsistencyEngine(
            novel_service=self.novel_service,
            temporal_storage=self.graph_storage,
            llm_manager_instance=self.llm,
        )
        self.project = self.novel_service.create_project(
            NovelProjectCreate(
                user_id="consistency-user",
                title="一致性测试",
                constraints=["死者不得无解释复活。"],
            )
        )
        self.novel_id = self.project.novel_id
        for entity_id, entity_type, name, aliases in (
            ("char_lan", "character", "岚", ["小岚", "白影"]),
            ("char_qi", "character", "祁", ["白影"]),
            ("loc_tower", "location", "北塔", []),
            ("loc_gate", "location", "南门", []),
        ):
            self.novel_service.create_entity(
                self.novel_id,
                NovelEntityCreate(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    canonical_name=name,
                    aliases=aliases,
                ),
            )
        bible = self.novel_service.get_story_bible(self.novel_id)
        self.bible = self.novel_service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=bible.revision,
                rules=[{"rule": "盟约生效后双方不得无故互相攻击。"}],
            ),
        )
        source = TemporalSourceReference(
            source_type="story_bible",
            source_id=self.novel_id,
            source_revision=self.bible.revision,
        )
        self.allies = self.graph_service.create_relation(
            self.novel_id,
            TemporalRelationCreate(
                relation_id="rel_allies",
                subject_entity_id="char_lan",
                predicate="盟友",
                object_entity_id="char_qi",
                description="北塔盟约仍然有效。",
                valid_from_chapter=3,
                source=source,
                metadata={
                    "knowledge_scope": "CHARACTER_KNOWLEDGE",
                    "knower_entity_ids": ["char_lan"],
                },
            ),
        )
        self.graph_service.create_relation(
            self.novel_id,
            TemporalRelationCreate(
                relation_id="rel_old_hostile",
                subject_entity_id="char_lan",
                predicate="敌对",
                object_entity_id="char_qi",
                valid_from_chapter=1,
                valid_to_chapter=2,
                source=source,
            ),
        )
        self.death = self.graph_service.create_event(
            self.novel_id,
            TemporalEventCreate(
                event_id="evt_qi_death",
                event_type="death",
                title="祁死亡",
                summary="祁在北塔事故中死亡。",
                participant_entity_ids=["char_qi"],
                start_chapter=3,
                source=source,
            ),
        )
        self.location = self.graph_service.create_event(
            self.novel_id,
            TemporalEventCreate(
                event_id="evt_lan_location",
                event_type="location",
                title="岚位于北塔",
                participant_entity_ids=["char_lan"],
                location_entity_id="loc_tower",
                start_chapter=3,
                source=source,
                metadata={"state_type": "location"},
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def request(self, content: str, facts: list[dict]):
        return ConsistencyCheckRequest(
            user_id="consistency-user",
            chapter_number=3,
            active_entity_ids=["char_lan", "char_qi"],
            pov_character_id="char_lan",
            content=content,
            candidate_facts=[
                ConsistencyFactCandidate.model_validate(item)
                for item in facts
            ],
        )

    @staticmethod
    def relationship_fact(**updates) -> dict:
        value = {
            "fact_id": "FACT-REL",
            "fact_type": "relationship",
            "subject_entity_id": "char_lan",
            "predicate": "敌对",
            "object_entity_id": "char_qi",
            "evidence": "岚和祁是敌人。",
            "chapter_number": 3,
        }
        value.update(updates)
        return value


class ConsistencyConstraintTests(ConsistencyFixture):
    def test_constraints_are_bounded_current_and_provenanced(self) -> None:
        result = self.engine.build_constraints(
            self.novel_id,
            ConsistencyConstraintRequest(
                user_id="consistency-user",
                chapter_number=3,
                active_entity_ids=["char_lan", "char_qi"],
                pov_character_id="char_lan",
                char_budget=1000,
            ),
        )
        ids = {item.constraint_id for item in result.constraints}
        self.assertIn("relation:rel_allies:r1", ids)
        self.assertFalse(any("rel_old_hostile" in item for item in ids))
        self.assertTrue(any(item.category == "world_rule" for item in result.constraints))
        self.assertLessEqual(len(result.constraint_context), 1000)
        self.assertFalse(result.persisted)

    def test_oversized_first_constraint_is_truncated_not_empty(self) -> None:
        project = self.novel_service.get_project(self.novel_id)
        self.novel_service.update_project(
            self.novel_id,
            NovelProjectUpdate(
                expected_revision=project.revision,
                constraints=["不可违反" * 4000],
            ),
        )
        result = self.engine.build_constraints(
            self.novel_id,
            ConsistencyConstraintRequest(
                user_id="consistency-user",
                chapter_number=3,
                active_entity_ids=["char_lan"],
                char_budget=512,
            ),
        )
        self.assertTrue(result.constraint_context)
        self.assertLessEqual(len(result.constraint_context), 512)
        self.assertIn("novel_project", result.constraint_context)

    def test_wrong_user_scope_is_hidden(self) -> None:
        with self.assertRaises(KeyError):
            self.engine.build_constraints(
                self.novel_id,
                ConsistencyConstraintRequest(
                    user_id="wrong-user",
                    chapter_number=3,
                ),
            )


class ConsistencyCheckTests(ConsistencyFixture):
    def test_relationship_conflict_and_explicit_transition(self) -> None:
        conflict = self.engine.check(
            self.novel_id,
            self.request("岚和祁是敌人。", [self.relationship_fact()]),
        )
        self.assertEqual(
            [item.conflict_type for item in conflict.conflicts],
            ["relationship_conflict"],
        )
        self.assertEqual(conflict.conflicts[0].evidence[0].source_id, "rel_allies")

        transition = self.engine.check(
            self.novel_id,
            self.request(
                "岚和祁公开决裂，成为敌人。",
                [
                    self.relationship_fact(
                        evidence="岚和祁公开决裂，成为敌人。",
                        change_type="transition",
                    )
                ],
            ),
        )
        self.assertEqual(transition.conflicts, [])

        mislabeled = self.engine.check(
            self.novel_id,
            self.request(
                "岚和祁是敌人。",
                [self.relationship_fact(change_type="transition")],
            ),
        )
        self.assertEqual(
            [item.conflict_type for item in mislabeled.conflicts],
            ["relationship_conflict"],
        )

    def test_character_belief_may_contradict_world_state(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "岚误以为祁是敌人。",
                [
                    self.relationship_fact(
                        evidence="岚误以为祁是敌人。",
                        knowledge_scope="CHARACTER_BELIEF",
                        knowledge_holder_entity_id="char_lan",
                    )
                ],
            ),
        )
        self.assertEqual(result.conflicts, [])

    def test_character_scoped_graph_fact_is_not_world_truth(self) -> None:
        source = TemporalSourceReference(
            source_type="story_bible",
            source_id=self.novel_id,
            source_revision=self.bible.revision,
        )
        self.graph_service.create_relation(
            self.novel_id,
            TemporalRelationCreate(
                relation_id="rel_believed_hostile",
                subject_entity_id="char_lan",
                predicate="敌对",
                object_entity_id="char_qi",
                valid_from_chapter=3,
                source=source,
                metadata={
                    "knowledge_scope": "CHARACTER_BELIEF",
                    "knower_entity_ids": ["char_lan"],
                },
            ),
        )
        result = self.engine.check(
            self.novel_id,
            self.request(
                "岚和祁是盟友。",
                [self.relationship_fact(
                    predicate="盟友",
                    evidence="岚和祁是盟友。",
                )],
            ),
        )
        self.assertEqual(result.conflicts, [])

    def test_symmetric_relationship_conflict_checks_reverse_edge(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "祁把岚视为敌人。",
                [
                    self.relationship_fact(
                        subject_entity_id="char_qi",
                        object_entity_id="char_lan",
                        evidence="祁把岚视为敌人。",
                    )
                ],
            ),
        )
        self.assertEqual(
            [item.conflict_type for item in result.conflicts],
            ["relationship_conflict"],
        )

    def test_qwen_phrase_predicate_maps_by_controlled_token(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "岚对祁拔剑，宣称两人一直是敌人。",
                [
                    self.relationship_fact(
                        predicate="declares enmity toward",
                        evidence="岚对祁拔剑，宣称两人一直是敌人。",
                    )
                ],
            ),
        )
        self.assertEqual(
            [item.conflict_type for item in result.conflicts],
            ["relationship_conflict"],
        )

    def test_life_state_and_location_conflicts(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "祁仍然存活。岚一直待在南门。",
                [
                    {
                        "fact_id": "FACT-LIFE",
                        "fact_type": "life_state",
                        "subject_entity_id": "char_qi",
                        "value": "alive",
                        "evidence": "祁仍然存活。",
                    },
                    {
                        "fact_id": "FACT-LOC",
                        "fact_type": "location",
                        "subject_entity_id": "char_lan",
                        "object_entity_id": "loc_gate",
                        "evidence": "岚一直待在南门。",
                    },
                ],
            ),
        )
        self.assertEqual(
            {item.conflict_type for item in result.conflicts},
            {"life_state_conflict", "location_conflict"},
        )

    def test_unknown_ambiguous_and_identity_mismatch_are_not_guessed(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "陌生人出现。白影出现。祁自称岚。",
                [
                    {
                        "fact_id": "FACT-UNKNOWN",
                        "fact_type": "event",
                        "subject_name": "陌生人",
                        "evidence": "陌生人出现。",
                    },
                    {
                        "fact_id": "FACT-AMBIGUOUS",
                        "fact_type": "event",
                        "subject_name": "白影",
                        "evidence": "白影出现。",
                    },
                    {
                        "fact_id": "FACT-MISMATCH",
                        "fact_type": "event",
                        "subject_entity_id": "char_lan",
                        "subject_name": "祁",
                        "evidence": "祁自称岚。",
                    },
                ],
            ),
        )
        self.assertEqual(
            {item.conflict_type for item in result.conflicts},
            {"unknown_entity", "ambiguous_alias", "identity_mismatch"},
        )

    def test_candidate_evidence_must_exist_in_content(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request("正文没有这句话。", [self.relationship_fact()]),
        )
        self.assertEqual(result.conflicts[0].conflict_type, "unsupported_evidence")

    def test_character_knowledge_scope_requires_holder_evidence(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "祁知道北塔盟约仍然有效。",
                [
                    self.relationship_fact(
                        predicate="盟友",
                        evidence="祁知道北塔盟约仍然有效。",
                        knowledge_scope="CHARACTER_KNOWLEDGE",
                        knowledge_holder_entity_id="char_qi",
                    )
                ],
            ),
        )
        self.assertEqual(
            [item.conflict_type for item in result.conflicts],
            ["knowledge_scope_violation"],
        )

    def test_character_knowledge_holder_must_be_canonical_character(self) -> None:
        result = self.engine.check(
            self.novel_id,
            self.request(
                "北塔知道盟约仍然有效。",
                [
                    self.relationship_fact(
                        predicate="盟友",
                        evidence="北塔知道盟约仍然有效。",
                        knowledge_scope="CHARACTER_KNOWLEDGE",
                        knowledge_holder_entity_id="loc_tower",
                    )
                ],
            ),
        )
        self.assertEqual(
            [item.conflict_type for item in result.conflicts],
            ["identity_mismatch"],
        )


class ConsistencyAnalyzeTests(ConsistencyFixture, unittest.IsolatedAsyncioTestCase):
    async def test_qwen_candidate_is_checked_without_persistence(self) -> None:
        candidate = self.relationship_fact()
        self.llm.chat.return_value = ChatResponse(
            content=json.dumps({"candidate_facts": [candidate]}),
            provider="qwen_local",
            model="qwen3:8b",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            latency_ms=20,
        )
        with self.graph_storage._connect() as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM temporal_relation_revisions"
            ).fetchone()[0]
        result = await self.engine.analyze(
            self.novel_id,
            ConsistencyAnalyzeRequest(
                user_id="consistency-user",
                chapter_number=3,
                active_entity_ids=["char_lan", "char_qi"],
                content="岚和祁是敌人。",
            ),
        )
        with self.graph_storage._connect() as conn:
            after = conn.execute(
                "SELECT COUNT(*) FROM temporal_relation_revisions"
            ).fetchone()[0]
        self.assertEqual(before, after)
        self.assertFalse(result.persisted)
        self.assertEqual(result.conflicts[0].conflict_type, "relationship_conflict")
        self.assertEqual(result.usage.total_tokens, 150)
        request = self.llm.chat.await_args.args[1]
        prompt_ids = [
            item["prompt_id"]
            for item in request.metadata["prompt_provenance"]
        ]
        self.assertEqual(
            prompt_ids,
            [
                "consistency.fact_extraction.system",
                "consistency.fact_extraction.request",
            ],
        )
        self.assertEqual(
            result.metadata["prompt_provenance"],
            request.metadata["prompt_provenance"],
        )

    async def test_request_chapter_overrides_extractor_coordinate(self) -> None:
        candidate = self.relationship_fact(
            chapter_number="08D2-CRIMSON-20260812",
        )
        self.llm.chat.return_value = ChatResponse(
            content=json.dumps({"candidate_facts": [candidate]}),
            provider="qwen_local",
            model="qwen3:8b",
            finish_reason="stop",
        )

        result = await self.engine.analyze(
            self.novel_id,
            ConsistencyAnalyzeRequest(
                user_id="consistency-user",
                chapter_number=3,
                active_entity_ids=["char_lan", "char_qi"],
                content="岚和祁是敌人。",
            ),
        )

        self.assertEqual(result.candidate_facts[0].chapter_number, 3)
        self.assertEqual(
            result.conflicts[0].conflict_type,
            "relationship_conflict",
        )

    async def test_invalid_qwen_output_is_rejected(self) -> None:
        self.llm.chat.return_value = ChatResponse(
            content="not json",
            provider="qwen_local",
            model="qwen3:8b",
        )
        with self.assertRaises(ConsistencyOutputError):
            await self.engine.analyze(
                self.novel_id,
                ConsistencyAnalyzeRequest(
                    user_id="consistency-user",
                    chapter_number=3,
                    content="岚和祁是敌人。",
                ),
            )


class _GroundingService:
    def __init__(self, novel_service: NovelProjectService) -> None:
        self.novel_service = novel_service

    @staticmethod
    def has_binding(request) -> bool:
        return True

    @staticmethod
    def resolve(request) -> ChapterWorkflowGrounding:
        return ChapterWorkflowGrounding(
            message="[PLAN]",
            metadata={
                "chapter_number": 3,
                "pov_character_id": "char_lan",
                "active_entity_ids": ["char_lan", "char_qi"],
                "active_character_ids": ["char_lan", "char_qi"],
                "planning_freshness_validated": True,
            },
        )


class ConsistencyWorkflowTests(ConsistencyFixture, unittest.IsolatedAsyncioTestCase):
    async def test_hard_conflict_blocks_then_rewrite_clears_gate(self) -> None:
        first_review = json.dumps(
            {
                "approved": True,
                "summary": "看似通过。",
                "scores": _scores(),
                "issues": [],
                "candidate_facts": [self.relationship_fact()],
            }
        )
        second_review = json.dumps(
            {
                "approved": True,
                "summary": "冲突已修正。",
                "scores": _scores(),
                "issues": [],
                "candidate_facts": [],
            }
        )
        manager = SimpleNamespace(
            execute=AsyncMock(
                side_effect=[
                    _agent_result("chapter", "岚和祁是敌人。"),
                    _agent_result("review", first_review),
                    _agent_result("rewrite", "岚和祁仍是盟友。"),
                    _agent_result("review", second_review),
                ]
            )
        )
        result = await ChapterWorkflow(
            manager,
            grounding_service=_GroundingService(self.novel_service),
            consistency_service=self.engine,
        ).run(
            ChapterWorkflowRequest(
                user_id="consistency-user",
                novel_id=self.novel_id,
                instruction="写第三章",
                chapter_plan_id="chapter-3",
                chapter_plan_revision=1,
            )
        )
        self.assertTrue(result.quality_gate_passed)
        self.assertEqual(result.revision_rounds, 1)
        self.assertEqual(
            result.consistency_conflict_history[0][0].conflict_type,
            "relationship_conflict",
        )
        self.assertEqual(result.consistency_conflict_history[1], [])
        self.assertEqual(result.consistency_conflicts, [])
        self.assertFalse(result.metadata["consistency_fact_persisted"])
        self.assertEqual(result.metadata["consistency_conflict_count"], 0)
        self.assertLessEqual(result.metadata["consistency_context_chars"], 1400)
        draft_context = manager.execute.await_args_list[0].kwargs["context"]
        self.assertEqual(
            [item.metadata.get("source") for item in draft_context.messages],
            ["chapter_plan_grounding", "consistency_constraints"],
        )
        rewrite_instruction = manager.execute.await_args_list[2].kwargs[
            "context"
        ].instruction
        self.assertIn("relationship_conflict", rewrite_instruction)
        review_instruction = manager.execute.await_args_list[1].kwargs[
            "context"
        ].instruction
        self.assertIn('"chapter_number": 3', review_instruction)
        self.assertNotIn(
            "[CONSISTENCY CONSTRAINTS - MUST FOLLOW]",
            review_instruction,
        )


class ConsistencyApiTests(ConsistencyFixture):
    def setUp(self) -> None:
        super().setUp()
        app = FastAPI()
        app.include_router(consistency_api.router, prefix="/api/v1")
        self.patch = patch.object(consistency_api, "service", self.engine)
        self.patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.patch.stop()
        super().tearDown()

    def test_constraints_check_and_openapi(self) -> None:
        root = f"/api/v1/novels/{self.novel_id}/consistency"
        self.llm.chat.return_value = ChatResponse(
            content=json.dumps(
                {"candidate_facts": [self.relationship_fact()]}
            ),
            provider="qwen_local",
            model="qwen3:8b",
            finish_reason="stop",
        )
        constraints = self.client.post(
            root + "/constraints",
            json={
                "user_id": "consistency-user",
                "chapter_number": 3,
                "active_entity_ids": ["char_lan", "char_qi"],
            },
        )
        checked = self.client.post(
            root + "/check",
            json={
                "user_id": "consistency-user",
                "chapter_number": 3,
                "content": "岚和祁是敌人。",
                "candidate_facts": [self.relationship_fact()],
            },
        )
        analyzed = self.client.post(
            root + "/analyze",
            json={
                "user_id": "consistency-user",
                "chapter_number": 3,
                "content": "岚和祁是敌人。",
                "active_entity_ids": ["char_lan", "char_qi"],
            },
        )
        missing = self.client.post(
            root + "/constraints",
            json={"user_id": "wrong-user", "chapter_number": 3},
        )
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertEqual(constraints.status_code, 200)
        self.assertFalse(constraints.json()["data"]["persisted"])
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(
            checked.json()["data"]["conflicts"][0]["conflict_type"],
            "relationship_conflict",
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(analyzed.status_code, 200)
        self.assertFalse(analyzed.json()["data"]["persisted"])
        self.assertEqual(
            analyzed.json()["data"]["conflicts"][0]["conflict_type"],
            "relationship_conflict",
        )
        self.assertIn(
            "/api/v1/novels/{novel_id}/consistency/analyze",
            paths,
        )
