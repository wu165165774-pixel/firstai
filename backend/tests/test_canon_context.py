from __future__ import annotations

import asyncio
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import novel_agent as novel_module
from app.agents.novel_agent import NovelAgent
from app.agents.schemas import AgentContext
from app.llm.schemas import ChatResponse
from app.novels.context import CanonContextBuilder
from app.novels.schemas import (
    ChapterPlanCreate,
    EntityResolveRequest,
    NovelEntityCreate,
    NovelEntityUpdate,
    NovelPlanUpdate,
    NovelProjectCreate,
    StoryBibleEntityAlignRequest,
    StoryBibleUpdate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import (
    NovelEntityReferenceError,
    NovelProjectStorage,
)


class CanonFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.storage = NovelProjectStorage(
            str(Path(self.temp.name) / "novels.db")
        )
        self.service = NovelProjectService(self.storage)
        self.project = self.service.create_project(
            NovelProjectCreate(
                user_id="canon-user",
                title="Canonical Test",
                constraints=["人物身份不得互换"],
            )
        )
        self.novel_id = self.project.novel_id

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_entity(
        self,
        entity_id: str,
        canonical_name: str,
        *,
        aliases: list[str] | None = None,
        entity_type: str = "character",
    ):
        return self.service.create_entity(
            self.novel_id,
            NovelEntityCreate(
                entity_id=entity_id,
                entity_type=entity_type,
                canonical_name=canonical_name,
                aliases=aliases or [],
            ),
        )


class StoryBibleAlignmentTests(CanonFixture):
    def test_alignment_creates_and_binds_characters_atomically(self) -> None:
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                characters=[
                    {
                        "name": "林雪",
                        "aliases": ["小雪"],
                        "role": "妹妹",
                    },
                    {
                        "id": "char_su_xue",
                        "name": "苏雪",
                        "role": "法医",
                    },
                ],
            ),
        )

        result = self.service.align_story_bible_entities(
            self.novel_id,
            StoryBibleEntityAlignRequest(
                expected_revision=bible.revision,
            ),
        )

        self.assertTrue(result.changed)
        self.assertEqual(result.story_bible.revision, 3)
        self.assertEqual(len(result.created_entities), 2)
        self.assertEqual(
            [item.action for item in result.bindings],
            ["created", "created"],
        )
        characters = result.story_bible.characters
        self.assertTrue(characters[0]["entity_id"].startswith("char_"))
        self.assertEqual(characters[1]["entity_id"], "char_su_xue")
        resolved = self.service.resolve_entity(
            self.novel_id,
            EntityResolveRequest(
                name="小雪",
                entity_type="character",
            ),
        )
        self.assertEqual(
            resolved.entity.entity_id,
            characters[0]["entity_id"],
        )

    def test_alignment_resolves_existing_alias_without_duplication(self) -> None:
        entity = self.create_entity(
            "char_lin_xue",
            "林雪",
            aliases=["小雪"],
        )
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=2,
                characters=[{"name": "小雪"}],
            ),
        )

        result = self.service.align_story_bible_entities(
            self.novel_id,
            StoryBibleEntityAlignRequest(
                expected_revision=bible.revision,
            ),
        )

        self.assertEqual(result.created_entities, [])
        self.assertEqual(result.bindings[0].action, "resolved_name")
        self.assertEqual(
            result.story_bible.characters[0]["entity_id"],
            entity.entity_id,
        )
        self.assertEqual(
            len(self.service.list_entities(self.novel_id)),
            1,
        )

    def test_second_alignment_is_noop(self) -> None:
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                characters=[{"name": "林雪"}],
            ),
        )
        first = self.service.align_story_bible_entities(
            self.novel_id,
            StoryBibleEntityAlignRequest(
                expected_revision=bible.revision,
            ),
        )
        second = self.service.align_story_bible_entities(
            self.novel_id,
            StoryBibleEntityAlignRequest(
                expected_revision=first.story_bible.revision,
            ),
        )

        self.assertFalse(second.changed)
        self.assertEqual(
            second.story_bible.revision,
            first.story_bible.revision,
        )
        self.assertEqual(second.bindings[0].action, "existing_id")

    def test_ambiguous_name_rolls_back_without_guessing(self) -> None:
        self.create_entity("char_lin", "林雪", aliases=["小雪"])
        self.create_entity("char_su", "苏雪", aliases=["小雪"])
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=3,
                characters=[{"name": "小雪"}],
            ),
        )

        with self.assertRaises(NovelEntityReferenceError):
            self.service.align_story_bible_entities(
                self.novel_id,
                StoryBibleEntityAlignRequest(
                    expected_revision=bible.revision,
                ),
            )

        loaded = self.service.get_story_bible(self.novel_id)
        self.assertEqual(loaded.revision, bible.revision)
        self.assertNotIn("entity_id", loaded.characters[0])
        self.assertEqual(len(self.service.list_entities(self.novel_id)), 2)

    def test_explicit_id_name_conflict_rolls_back(self) -> None:
        self.create_entity("char_lin", "林雪")
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=2,
                characters=[
                    {"id": "char_lin", "name": "苏雪"}
                ],
            ),
        )

        with self.assertRaises(NovelEntityReferenceError):
            self.service.align_story_bible_entities(
                self.novel_id,
                StoryBibleEntityAlignRequest(
                    expected_revision=bible.revision,
                ),
            )

        self.assertEqual(
            self.service.get_story_bible(self.novel_id).revision,
            bible.revision,
        )

    def test_create_missing_false_rejects_unbound_character(self) -> None:
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=1,
                characters=[{"name": "林雪"}],
            ),
        )
        with self.assertRaises(NovelEntityReferenceError):
            self.service.align_story_bible_entities(
                self.novel_id,
                StoryBibleEntityAlignRequest(
                    expected_revision=bible.revision,
                    create_missing=False,
                ),
            )
        self.assertEqual(self.service.list_entities(self.novel_id), [])

    def test_duplicate_binding_is_rejected_atomically(self) -> None:
        self.create_entity("char_lin", "林雪", aliases=["小雪"])
        bible = self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=2,
                characters=[{"name": "林雪"}, {"name": "小雪"}],
            ),
        )
        with self.assertRaises(NovelEntityReferenceError):
            self.service.align_story_bible_entities(
                self.novel_id,
                StoryBibleEntityAlignRequest(
                    expected_revision=bible.revision,
                ),
            )
        self.assertNotIn(
            "entity_id",
            self.service.get_story_bible(self.novel_id).characters[0],
        )

    def test_entity_mutations_advance_canon_revision_and_stale_plan(self) -> None:
        entity = self.create_entity("char_lin", "林雪")
        after_create = self.service.get_story_bible(self.novel_id)
        self.assertEqual(after_create.revision, 2)
        self.assertTrue(self.service.get_novel_plan(self.novel_id).is_stale)

        self.service.update_entity(
            self.novel_id,
            entity.entity_id,
            NovelEntityUpdate(
                expected_revision=1,
                aliases=["小雪"],
            ),
        )
        self.assertEqual(
            self.service.get_story_bible(self.novel_id).revision,
            3,
        )
        self.assertEqual(
            [
                item.revision
                for item in self.service.list_story_bible_revisions(
                    self.novel_id
                )
            ],
            [3, 2, 1],
        )


class CanonReferenceValidationTests(CanonFixture):
    def test_story_bible_explicit_entity_id_must_exist(self) -> None:
        with self.assertRaises(NovelEntityReferenceError):
            self.service.update_story_bible(
                self.novel_id,
                StoryBibleUpdate(
                    expected_revision=1,
                    characters=[
                        {"entity_id": "char_missing", "name": "林雪"}
                    ],
                ),
            )

    def test_legacy_planning_references_remain_compatible_without_registry(self) -> None:
        updated = self.service.update_novel_plan(
            self.novel_id,
            NovelPlanUpdate(
                expected_revision=1,
                character_arcs=[
                    {
                        "character_id": "legacy-character",
                        "character_name": "旧人物",
                    }
                ],
            ),
        )
        self.assertEqual(updated.revision, 2)

    def test_registry_rejects_unknown_planning_reference(self) -> None:
        self.create_entity("char_lin", "林雪")
        with self.assertRaises(NovelEntityReferenceError):
            self.service.validate_planning_entity_references(
                self.novel_id,
                "novel_plan",
                NovelPlanUpdate(
                    character_arcs=[
                        {
                            "character_id": "char_missing",
                            "character_name": "未知人物",
                        }
                    ],
                ),
            )

    def test_alias_display_name_matches_canonical_id(self) -> None:
        self.create_entity("char_lin", "林雪", aliases=["小雪"])
        self.service.validate_planning_entity_references(
            self.novel_id,
            "novel_plan",
            NovelPlanUpdate(
                character_arcs=[
                    {
                        "character_id": "char_lin",
                        "character_name": "小雪",
                    }
                ],
            ),
        )

    def test_id_name_mismatch_is_rejected(self) -> None:
        self.create_entity("char_lin", "林雪")
        with self.assertRaises(NovelEntityReferenceError):
            self.service.validate_planning_entity_references(
                self.novel_id,
                "novel_plan",
                NovelPlanUpdate(
                    character_arcs=[
                        {
                            "character_id": "char_lin",
                            "character_name": "苏雪",
                        }
                    ],
                ),
            )

    def test_scene_location_requires_location_entity(self) -> None:
        self.create_entity("char_lin", "林雪")
        with self.assertRaises(NovelEntityReferenceError):
            self.service.validate_planning_entity_references(
                self.novel_id,
                "chapter_plan",
                ChapterPlanCreate(
                    arc_id="arc-1",
                    chapter_number=1,
                    title="第一章",
                    scene_beats=[
                        {
                            "beat_id": "beat-1",
                            "order": 1,
                            "title": "抵达",
                            "location_id": "char_lin",
                        }
                    ],
                ),
            )

    def test_unmigrated_entity_type_remains_legacy_compatible(self) -> None:
        self.create_entity("char_lin", "林雪")
        self.service.validate_planning_entity_references(
            self.novel_id,
            "chapter_plan",
            ChapterPlanCreate(
                arc_id="arc-1",
                chapter_number=1,
                title="第一章",
                scene_beats=[
                    {
                        "beat_id": "beat-1",
                        "order": 1,
                        "title": "抵达",
                        "location_id": "legacy-location",
                    }
                ],
            ),
        )


class CanonContextBuilderTests(CanonFixture):
    def setUp(self) -> None:
        super().setUp()
        self.lin = self.create_entity(
            "char_lin",
            "林雪",
            aliases=["小雪"],
        )
        self.su = self.create_entity("char_su", "苏雪")
        self.service.update_story_bible(
            self.novel_id,
            StoryBibleUpdate(
                expected_revision=3,
                world={"city": "雾港"},
                rules=[{"rule": "死者不能无解释复活"}],
                characters=[
                    {
                        "entity_id": "char_lin",
                        "name": "林雪",
                        "role": "记者",
                        "secret": "凶手身份",
                    },
                    {"entity_id": "char_su", "name": "苏雪"},
                ],
            ),
        )
        self.builder = CanonContextBuilder(self.service)

    async def _build(self, ids: list[str] | None = None) -> str:
        return await self.builder.build(
            self.novel_id,
            active_entity_ids=ids,
        )

    def test_context_is_bounded_active_and_excludes_secret(self) -> None:
        context = asyncio.run(self._build(["char_lin"]))
        self.assertLessEqual(len(context), 3600)
        self.assertIn("[CANON FACTS - MUST NOT VIOLATE]", context)
        self.assertIn("char_lin", context)
        self.assertIn("小雪", context)
        self.assertIn("记者", context)
        self.assertNotIn("char_su", context)
        self.assertNotIn("凶手身份", context)

    def test_missing_active_id_is_explicit(self) -> None:
        context = asyncio.run(
            self._build(["char_missing"])
        )
        self.assertIn("char_missing", context)
        self.assertIn("unresolved_entity_ids", context)

    def test_unknown_novel_returns_empty_context(self) -> None:
        context = asyncio.run(
            self.builder.build("missing-novel")
        )
        self.assertEqual(context, "")


class CanonAgentInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_canon_precedes_memory_and_receives_active_ids(self) -> None:
        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="chapter",
                    model="qwen3:8b",
                    provider="qwen_local",
                )
            )
        )
        agent = NovelAgent(llm_manager)
        canon = AsyncMock(return_value="[CANON] char_lin")
        memory = AsyncMock(return_value="[MEMORY] old evidence")
        context = AgentContext(
            user_id="user",
            novel_id="novel",
            instruction="写一章",
            metadata={
                "active_character_ids": ["char_lin"],
                "pov_character_id": "char_lin",
            },
        )

        with patch.object(
            novel_module.canon_context_builder,
            "build",
            new=canon,
        ), patch.object(
            novel_module.memory_context_builder,
            "build",
            new=memory,
        ):
            await agent.run(context)

        canon.assert_awaited_once_with(
            novel_id="novel",
            active_entity_ids=["char_lin", "char_lin"],
        )
        request = llm_manager.chat.await_args.args[1]
        sources = [
            message.metadata.get("source")
            for message in request.messages
            if message.role == "system"
        ]
        self.assertLess(
            sources.index("canonical_entity_registry"),
            sources.index("long_term_memory"),
        )

    async def test_canon_can_be_disabled_independently(self) -> None:
        llm_manager = SimpleNamespace(
            chat=AsyncMock(
                return_value=ChatResponse(
                    content="ok",
                    model="qwen3:8b",
                    provider="qwen_local",
                )
            )
        )
        agent = NovelAgent(llm_manager)
        canon = AsyncMock()
        with patch.object(
            novel_module.canon_context_builder,
            "build",
            new=canon,
        ):
            await agent.run(
                AgentContext(
                    user_id="user",
                    novel_id="novel",
                    instruction="test",
                    use_canon=False,
                    use_memory=False,
                )
            )
        canon.assert_not_awaited()


class StoryBibleAlignmentApiTests(CanonFixture):
    def setUp(self) -> None:
        super().setUp()
        from app.api.v1 import novels

        self.module = novels
        self.original_service = novels.service
        novels.service = self.service
        app = FastAPI()
        app.include_router(novels.router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.module.service = self.original_service
        super().tearDown()

    def test_alignment_api_creates_binding_and_openapi_route(self) -> None:
        bible = self.client.put(
            f"/api/v1/novels/{self.novel_id}/story-bible",
            json={
                "expected_revision": 1,
                "characters": [{"name": "林雪"}],
            },
        ).json()["data"]
        response = self.client.post(
            f"/api/v1/novels/{self.novel_id}"
            "/story-bible/entities/align",
            json={"expected_revision": bible["revision"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["changed"])
        self.assertIn(
            "/api/v1/novels/{novel_id}/story-bible/entities/align",
            self.client.app.openapi()["paths"],
        )

    def test_alignment_conflict_returns_409(self) -> None:
        response = self.client.post(
            f"/api/v1/novels/{self.novel_id}"
            "/story-bible/entities/align",
            json={"expected_revision": 99},
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
