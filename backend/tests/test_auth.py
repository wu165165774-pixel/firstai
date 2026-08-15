import asyncio
import json
import os
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.api.v1 import novels as novels_api
from app.config.settings import settings
from app.core.auth import configured_principals
from app.main import app
from app.memory.manager import memory_manager
from app.memory.schemas import MemoryItem, MemoryType
from app.memory.storage.sqlite import SQLiteMemoryStorage
from app.novels.service import NovelProjectService
from app.novels.storage import NovelProjectStorage
from app.workflows.schemas import ChapterWorkflowRequest
from app.workflows.storage import WorkflowRunStorage


class AuthenticationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_enabled = settings.auth_enabled
        self.previous_tokens = settings.auth_tokens_json
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_novel_service = novels_api.service
        novels_api.service = NovelProjectService(
            NovelProjectStorage(f"{self.temp_dir.name}/novels.db")
        )
        self.previous_workflow_db = os.environ.get("NOVELFORGE_WORKFLOW_DB_PATH")
        os.environ["NOVELFORGE_WORKFLOW_DB_PATH"] = (
            f"{self.temp_dir.name}/workflow_runs.db"
        )
        self.previous_memory_storage = memory_manager.storage["sqlite"]
        memory_manager.storage["sqlite"] = SQLiteMemoryStorage(
            f"{self.temp_dir.name}/memory.db"
        )
        settings.auth_enabled = True
        settings.auth_tokens_json = json.dumps(
            {
                "alpha-token-1234567890": {
                    "user_id": "auth-alpha",
                    "roles": ["user"],
                },
                "beta-token-12345678901": {
                    "user_id": "auth-beta",
                    "roles": ["user"],
                },
                "admin-token-1234567890": {
                    "user_id": "auth-admin",
                    "roles": ["admin"],
                },
            }
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        settings.auth_enabled = self.previous_enabled
        settings.auth_tokens_json = self.previous_tokens
        novels_api.service = self.previous_novel_service
        if self.previous_workflow_db is None:
            os.environ.pop("NOVELFORGE_WORKFLOW_DB_PATH", None)
        else:
            os.environ["NOVELFORGE_WORKFLOW_DB_PATH"] = self.previous_workflow_db
        memory_manager.storage["sqlite"] = self.previous_memory_storage
        self.temp_dir.cleanup()

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_health_is_public_and_protected_routes_require_bearer(self) -> None:
        self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
        missing = self.client.get("/api/v1/providers")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")
        invalid = self.client.get(
            "/api/v1/providers",
            headers=self.headers("invalid-token-123456"),
        )
        self.assertEqual(invalid.status_code, 401)
        valid = self.client.get(
            "/api/v1/providers",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(valid.status_code, 200)

    def test_identity_and_declared_user_scope_are_bound(self) -> None:
        identity = self.client.get(
            "/api/v1/auth/me",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(identity.status_code, 200)
        self.assertEqual(identity.json()["data"]["user_id"], "auth-alpha")
        self.assertTrue(identity.json()["data"]["authenticated"])

        mismatch = self.client.get(
            "/api/v1/novels?user_id=auth-beta",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(mismatch.status_code, 403)
        unscoped = self.client.get(
            "/api/v1/novels",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(unscoped.status_code, 403)
        scoped = self.client.get(
            "/api/v1/novels?user_id=auth-alpha",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(scoped.status_code, 200)

        chat_without_scope = self.client.post(
            "/api/v1/chat",
            headers=self.headers("alpha-token-1234567890"),
            json={
                "provider": "qwen_local",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        self.assertEqual(chat_without_scope.status_code, 403)

    def test_body_scope_and_novel_ownership_are_enforced(self) -> None:
        mismatch = self.client.post(
            "/api/v1/novels",
            headers=self.headers("alpha-token-1234567890"),
            json={"user_id": "auth-beta", "title": "Forbidden"},
        )
        self.assertEqual(mismatch.status_code, 403)

        created = self.client.post(
            "/api/v1/novels",
            headers=self.headers("alpha-token-1234567890"),
            json={
                "user_id": "auth-alpha",
                "title": f"Auth {uuid.uuid4().hex}",
            },
        )
        self.assertEqual(created.status_code, 201)
        novel_id = created.json()["data"]["novel_id"]
        hidden = self.client.get(
            f"/api/v1/novels/{novel_id}",
            headers=self.headers("beta-token-12345678901"),
        )
        self.assertEqual(hidden.status_code, 404)
        owner = self.client.get(
            f"/api/v1/novels/{novel_id}",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(owner.status_code, 200)

    def test_operations_require_admin_and_openapi_declares_security(self) -> None:
        forbidden = self.client.get(
            "/api/v1/workflows/workers",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(forbidden.status_code, 403)
        allowed = self.client.get(
            "/api/v1/workflows/workers",
            headers=self.headers("admin-token-1234567890"),
        )
        self.assertEqual(allowed.status_code, 200)

        schema = app.openapi()
        self.assertIn("BearerAuth", schema["components"]["securitySchemes"])
        self.assertEqual(
            schema["paths"]["/api/v1/providers"]["get"]["security"],
            [{"BearerAuth": []}],
        )
        self.assertNotIn(
            "security",
            schema["paths"]["/api/v1/health"]["get"],
        )

    def test_workflow_run_and_memory_ids_do_not_cross_user_boundaries(self) -> None:
        run = WorkflowRunStorage().create_run(
            ChapterWorkflowRequest(
                user_id="auth-alpha",
                novel_id="missing-auth-novel",
                instruction="authorization fixture",
                chapter_plan_id="chapter-plan-auth",
                chapter_plan_revision=1,
            )
        )
        hidden_run = self.client.get(
            f"/api/v1/workflows/runs/{run['run_id']}",
            headers=self.headers("beta-token-12345678901"),
        )
        self.assertEqual(hidden_run.status_code, 404)
        owned_run = self.client.get(
            f"/api/v1/workflows/runs/{run['run_id']}",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(owned_run.status_code, 200)

        memory_id = f"auth-memory-{uuid.uuid4().hex}"
        asyncio.run(
            memory_manager.storage["sqlite"].save(
                MemoryItem(
                    id=memory_id,
                    user_id="auth-alpha",
                    novel_id="missing-auth-novel",
                    memory_type=MemoryType.PLOT,
                    content="authorization fixture",
                )
            )
        )
        hidden_memory = self.client.get(
            f"/api/v1/memory/{memory_id}/lifecycle/events",
            headers=self.headers("beta-token-12345678901"),
        )
        self.assertEqual(hidden_memory.status_code, 404)
        owned_memory = self.client.get(
            f"/api/v1/memory/{memory_id}/lifecycle/events",
            headers=self.headers("alpha-token-1234567890"),
        )
        self.assertEqual(owned_memory.status_code, 200)

    def test_invalid_enabled_configuration_is_rejected(self) -> None:
        settings.auth_tokens_json = "{}"
        with self.assertRaisesRegex(ValueError, "at least one token"):
            configured_principals()


if __name__ == "__main__":
    unittest.main()
