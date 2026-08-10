from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.novels.schemas import (
    EntityResolveRequest,
    NovelEntityCreate,
    NovelEntityUpdate,
    NovelProjectCreate,
)
from app.novels.service import NovelProjectService
from app.novels.storage import (
    NovelProjectNotFoundError,
    NovelProjectStorage,
    NovelRevisionConflictError,
)


class EntityRegistryStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "novels.db")
        self.storage = NovelProjectStorage(self.db_path)
        self.service = NovelProjectService(self.storage)
        self.project = self.service.create_project(
            NovelProjectCreate(
                user_id="entity-user",
                title="Entity Registry",
                premise="Test canonical identity.",
            )
        )
        self.novel_id = self.project.novel_id

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _create(
        self,
        canonical_name: str,
        *,
        entity_id: str | None = None,
        entity_type: str = "character",
        aliases: list[str] | None = None,
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

    def test_schema_contains_entity_and_alias_tables(self) -> None:
        with self.storage._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }

        self.assertIn("novel_entities", tables)
        self.assertIn("novel_entity_aliases", tables)

    def test_create_character_generates_stable_id(self) -> None:
        entity = self._create(
            "林雪",
            aliases=["小雪", " 雪儿 ", "小雪"],
        )

        self.assertTrue(entity.entity_id.startswith("char_"))
        self.assertEqual(entity.canonical_name, "林雪")
        self.assertEqual(entity.aliases, ["小雪", "雪儿"])
        self.assertEqual(entity.revision, 1)
        loaded = self.service.get_entity(
            self.novel_id,
            entity.entity_id,
        )
        self.assertEqual(loaded, entity)

    def test_explicit_entity_id_is_scoped_by_novel(self) -> None:
        first = self._create("林雪", entity_id="char_0002")
        other_project = self.service.create_project(
            NovelProjectCreate(
                user_id="entity-user",
                title="Other Novel",
            )
        )
        second = self.service.create_entity(
            other_project.novel_id,
            NovelEntityCreate(
                entity_id="char_0002",
                canonical_name="另一本书的林雪",
            ),
        )

        self.assertEqual(first.entity_id, second.entity_id)
        self.assertNotEqual(first.novel_id, second.novel_id)

    def test_exact_canonical_precedes_exact_alias(self) -> None:
        alias_owner = self._create(
            "林雪",
            entity_id="char_lin_xue",
            aliases=["小雪"],
        )
        canonical_owner = self._create(
            "小雪",
            entity_id="char_xiao_xue",
            aliases=["雪儿"],
        )

        result = self.service.resolve_entity(
            self.novel_id,
            EntityResolveRequest(name="小雪"),
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.match_strategy, "exact_canonical")
        self.assertEqual(result.entity, canonical_owner)
        self.assertNotEqual(result.entity, alias_owner)

    def test_normalized_alias_resolution(self) -> None:
        entity = self._create(
            "林雪",
            entity_id="char_lin_xue",
            aliases=["Snow"],
        )

        result = self.service.resolve_entity(
            self.novel_id,
            EntityResolveRequest(name="  ｓｎｏｗ  "),
        )

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.match_strategy, "normalized_alias")
        self.assertEqual(result.entity, entity)

    def test_ambiguous_alias_is_not_guessed(self) -> None:
        first = self._create(
            "林雪",
            entity_id="char_lin_xue",
            aliases=["小雪"],
        )
        second = self._create(
            "苏雪",
            entity_id="char_su_xue",
            aliases=["小雪"],
        )

        result = self.service.resolve_entity(
            self.novel_id,
            EntityResolveRequest(name="小雪"),
        )

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.match_strategy, "exact_alias")
        self.assertIsNone(result.entity)
        self.assertEqual(
            {item.entity_id for item in result.candidates},
            {first.entity_id, second.entity_id},
        )

    def test_entity_type_filter_can_disambiguate(self) -> None:
        self._create(
            "星港",
            entity_id="char_star_port",
            entity_type="character",
        )
        location = self._create(
            "星港",
            entity_id="loc_star_port",
            entity_type="location",
        )

        ambiguous = self.service.resolve_entity(
            self.novel_id,
            EntityResolveRequest(name="星港"),
        )
        resolved = self.service.resolve_entity(
            self.novel_id,
            EntityResolveRequest(
                name="星港",
                entity_type="location",
            ),
        )

        self.assertEqual(ambiguous.status, "ambiguous")
        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.entity, location)

    def test_update_preserves_id_and_rebuilds_alias_index(self) -> None:
        entity = self._create(
            "林雪",
            entity_id="char_lin_xue",
            aliases=["小雪"],
        )
        updated = self.service.update_entity(
            self.novel_id,
            entity.entity_id,
            NovelEntityUpdate(
                expected_revision=1,
                canonical_name="林霜",
                aliases=["霜儿"],
            ),
        )

        self.assertEqual(updated.entity_id, entity.entity_id)
        self.assertEqual(updated.revision, 2)
        self.assertEqual(updated.canonical_name, "林霜")
        self.assertEqual(
            self.service.resolve_entity(
                self.novel_id,
                EntityResolveRequest(name="小雪"),
            ).status,
            "not_found",
        )
        self.assertEqual(
            self.service.resolve_entity(
                self.novel_id,
                EntityResolveRequest(name="霜儿"),
            ).entity,
            updated,
        )

    def test_revision_and_entity_id_conflicts_are_rejected(self) -> None:
        entity = self._create(
            "林雪",
            entity_id="char_lin_xue",
        )

        with self.assertRaises(NovelRevisionConflictError):
            self._create(
                "另一个林雪",
                entity_id=entity.entity_id,
            )

        with self.assertRaises(NovelRevisionConflictError):
            self.service.update_entity(
                self.novel_id,
                entity.entity_id,
                NovelEntityUpdate(
                    expected_revision=99,
                    canonical_name="错误更新",
                ),
            )

        loaded = self.service.get_entity(
            self.novel_id,
            entity.entity_id,
        )
        self.assertEqual(loaded.revision, 1)
        self.assertEqual(loaded.canonical_name, "林雪")

    def test_registry_survives_storage_reopen(self) -> None:
        entity = self._create(
            "林雪",
            entity_id="char_lin_xue",
            aliases=["雪儿"],
        )
        reopened = NovelProjectService(
            NovelProjectStorage(self.db_path)
        )

        self.assertEqual(
            reopened.get_entity(self.novel_id, entity.entity_id),
            entity,
        )
        self.assertEqual(
            reopened.resolve_entity(
                self.novel_id,
                EntityResolveRequest(name="雪儿"),
            ).entity,
            entity,
        )

    def test_unknown_project_is_rejected(self) -> None:
        with self.assertRaises(NovelProjectNotFoundError):
            self.service.create_entity(
                "missing-novel",
                NovelEntityCreate(canonical_name="林雪"),
            )


class EntityRegistryValidationTests(unittest.TestCase):
    def test_blank_alias_and_invalid_id_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            NovelEntityCreate(
                entity_id="bad id",
                canonical_name="林雪",
            )

        with self.assertRaises(ValidationError):
            NovelEntityCreate(
                canonical_name="林雪",
                aliases=[" "],
            )


class EntityRegistryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        storage = NovelProjectStorage(
            str(Path(self.temp.name) / "novels.db")
        )
        self.service = NovelProjectService(storage)
        self.project = self.service.create_project(
            NovelProjectCreate(
                user_id="entity-api",
                title="Entity API",
            )
        )

        from app.api.v1 import novels

        self.novels_module = novels
        self.original_service = novels.service
        novels.service = self.service

        app = FastAPI()
        app.include_router(novels.router, prefix="/api/v1")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.novels_module.service = self.original_service
        self.temp.cleanup()

    def test_api_create_list_update_and_resolve(self) -> None:
        novel_id = self.project.novel_id
        created_response = self.client.post(
            f"/api/v1/novels/{novel_id}/entities",
            json={
                "entity_id": "char_0002",
                "entity_type": "character",
                "canonical_name": "林雪",
                "aliases": ["小雪", "雪儿"],
                "description": "林凡的妹妹。",
            },
        )
        self.assertEqual(created_response.status_code, 201)
        created = created_response.json()["data"]

        listed = self.client.get(
            f"/api/v1/novels/{novel_id}/entities",
            params={"entity_type": "character"},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["data"]), 1)

        loaded = self.client.get(
            f"/api/v1/novels/{novel_id}/entities/char_0002"
        )
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["data"], created)

        resolved = self.client.post(
            f"/api/v1/novels/{novel_id}/entities/resolve",
            json={"name": "雪儿", "entity_type": "character"},
        )
        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()["data"]["status"], "resolved")
        self.assertEqual(
            resolved.json()["data"]["entity"]["entity_id"],
            "char_0002",
        )

        updated = self.client.patch(
            f"/api/v1/novels/{novel_id}/entities/char_0002",
            json={
                "expected_revision": 1,
                "aliases": ["雪儿", "林小姐"],
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["data"]["revision"], 2)

    def test_api_duplicate_id_returns_409(self) -> None:
        novel_id = self.project.novel_id
        payload = {
            "entity_id": "char_0002",
            "canonical_name": "林雪",
        }
        first = self.client.post(
            f"/api/v1/novels/{novel_id}/entities",
            json=payload,
        )
        second = self.client.post(
            f"/api/v1/novels/{novel_id}/entities",
            json=payload,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)

    def test_openapi_registers_entity_routes(self) -> None:
        paths = self.client.app.openapi()["paths"]
        prefix = "/api/v1/novels/{novel_id}/entities"

        self.assertIn(prefix, paths)
        self.assertIn(prefix + "/resolve", paths)
        self.assertIn(prefix + "/{entity_id}", paths)


if __name__ == "__main__":
    unittest.main()
