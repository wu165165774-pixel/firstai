from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.workflows.run_service import (
    WorkflowRunService,
)
from app.workflows.run_schemas import (
    WorkflowRunDetail,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
)
from app.workflows.storage import (
    WorkflowRunStorage,
)


def make_result(
    *,
    agent: str,
    content: str,
    success: bool = True,
):
    return SimpleNamespace(
        agent=agent,
        success=success,
        content=content,
        provider="test",
        model="test-model",
        finish_reason="stop",
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        ),
        latency_ms=5.0,
        metadata={
            "test": True,
        },
    )


def review_json(
    *,
    approved: bool,
    severity: str | None = None,
) -> str:

    issues = []

    if severity is not None:

        issues.append(
            {
                "severity": severity,
                "category": "prose",
                "issue": (
                    "Repeated wording."
                ),
                "evidence": (
                    "A phrase repeats."
                ),
                "impact": (
                    "Reduces clarity."
                ),
                "recommendation": (
                    "Remove repetition."
                ),
            }
        )

    return json.dumps(
        {
            "approved": approved,
            "summary": (
                "Approved."
                if approved
                else "Revision required."
            ),
            "issues": issues,
            "scores": {
                "continuity": 90,
                "character_consistency": 90,
                "world_consistency": 90,
                "plot_logic": 90,
                "prose_quality": (
                    90
                    if approved
                    else 60
                ),
                "pacing": 90,
                "overall": (
                    90
                    if approved
                    else 70
                ),
            },
        }
    )


class WorkflowRunPersistenceTests(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(
        self,
    ) -> None:

        self.temp_dir = (
            tempfile
            .TemporaryDirectory()
        )

        self.db_path = str(
            Path(
                self.temp_dir.name
            )
            / "workflow_runs.db"
        )

    def tearDown(
        self,
    ) -> None:

        self.temp_dir.cleanup()

    def _storage(
        self,
    ) -> WorkflowRunStorage:

        return WorkflowRunStorage(
            self.db_path
        )

    def _request(
        self,
        **updates,
    ) -> ChapterWorkflowRequest:

        payload = {
            "user_id": "user001",
            "novel_id": "novel001",
            "instruction": (
                "Write a chapter."
            ),
            "max_revision_rounds": 0,
        }

        payload.update(
            updates
        )

        return ChapterWorkflowRequest(
            **payload
        )

    async def test_run_persists_events_and_versions(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        detail = await WorkflowRunService(
            manager,
            self._storage(),
        ).start(
            self._request()
        )

        self.assertEqual(
            detail.execution_status,
            "succeeded",
        )
        self.assertFalse(
            detail.resumable
        )
        self.assertEqual(
            detail.workflow_status,
            "completed",
        )
        self.assertEqual(
            len(detail.versions),
            1,
        )
        self.assertEqual(
            detail.versions[0].content,
            "Draft.",
        )
        self.assertGreaterEqual(
            len(detail.events),
            4,
        )

    async def test_resumable_run_is_marked(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
            ]
        )

        detail = await WorkflowRunService(
            manager,
            self._storage(),
        ).start(
            self._request(
                max_revision_rounds=0
            )
        )

        self.assertEqual(
            detail.execution_status,
            "resumable",
        )
        self.assertTrue(
            detail.resumable
        )
        self.assertEqual(
            detail.workflow_status,
            "max_revisions_reached",
        )
        self.assertEqual(
            detail.latest_content,
            "Draft.",
        )

    async def test_resume_uses_exact_checkpoint_and_lineage(
        self,
    ) -> None:

        storage = self._storage()

        first_manager = SimpleNamespace()
        first_manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content=(
                        "Stored checkpoint."
                    ),
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
            ]
        )

        parent = await WorkflowRunService(
            first_manager,
            storage,
        ).start(
            self._request(
                max_revision_rounds=0
            )
        )

        resume_manager = SimpleNamespace()
        resume_manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        child = await WorkflowRunService(
            resume_manager,
            storage,
        ).resume(
            parent.run_id,
            {
                "max_revision_rounds": 1
            },
        )

        self.assertEqual(
            child.parent_run_id,
            parent.run_id,
        )
        self.assertEqual(
            child.root_run_id,
            parent.root_run_id,
        )
        self.assertEqual(
            child.result.draft,
            "Stored checkpoint.",
        )
        self.assertEqual(
            child.versions[0].source_stage,
            "checkpoint",
        )
        self.assertEqual(
            child.versions[0].content,
            "Stored checkpoint.",
        )
        self.assertEqual(
            resume_manager
            .execute.await_count,
            1,
        )
        self.assertEqual(
            child.execution_status,
            "succeeded",
        )

    async def test_successful_run_cannot_resume(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        service = WorkflowRunService(
            manager,
            self._storage(),
        )

        detail = await service.start(
            self._request()
        )

        with self.assertRaises(
            ValueError
        ):

            await service.resume(
                detail.run_id,
                {},
            )

    async def test_unknown_resume_override_is_rejected(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
            ]
        )

        service = WorkflowRunService(
            manager,
            self._storage(),
        )

        detail = await service.start(
            self._request()
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported resume",
        ):

            await service.resume(
                detail.run_id,
                {
                    "user_id": "other"
                },
            )

    async def test_run_survives_storage_reopen(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        detail = await WorkflowRunService(
            manager,
            self._storage(),
        ).start(
            self._request()
        )

        reopened = (
            WorkflowRunService(
                manager,
                self._storage(),
            ).get(
                detail.run_id
            )
        )

        self.assertIsInstance(
            reopened,
            WorkflowRunDetail,
        )
        self.assertEqual(
            reopened.run_id,
            detail.run_id,
        )
        self.assertEqual(
            reopened.result.final_content,
            "Draft.",
        )

    async def test_list_filters_user_and_novel(
        self,
    ) -> None:

        storage = self._storage()

        for user_id, novel_id in [
            (
                "user001",
                "novel001",
            ),
            (
                "user002",
                "novel002",
            ),
        ]:

            manager = SimpleNamespace()
            manager.execute = AsyncMock(
                side_effect=[
                    make_result(
                        agent="chapter",
                        content="Draft.",
                    ),
                    make_result(
                        agent="review",
                        content=review_json(
                            approved=True
                        ),
                    ),
                ]
            )

            await WorkflowRunService(
                manager,
                storage,
            ).start(
                self._request(
                    user_id=user_id,
                    novel_id=novel_id,
                )
            )

        items = WorkflowRunService(
            SimpleNamespace(),
            storage,
        ).list(
            user_id="user001",
            novel_id="novel001",
        )

        self.assertEqual(
            len(items),
            1,
        )
        self.assertEqual(
            items[0].user_id,
            "user001",
        )

    async def test_workflow_failure_is_persisted(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=RuntimeError(
                "boom"
            )
        )

        storage = self._storage()

        detail = await WorkflowRunService(
            manager,
            storage,
        ).start(
            self._request()
        )

        self.assertEqual(
            detail.execution_status,
            "failed",
        )
        self.assertEqual(
            detail.workflow_status,
            "draft_failed",
        )
        self.assertFalse(
            detail.resumable
        )
        self.assertEqual(
            detail.result.metadata[
                "error"
            ],
            "boom",
        )

        reopened = storage.get_run(
            detail.run_id
        )

        self.assertEqual(
            reopened[
                "execution_status"
            ],
            "failed",
        )
        self.assertEqual(
            reopened[
                "workflow_status"
            ],
            "draft_failed",
        )


class WorkflowRunOpenApiTests(
    unittest.TestCase
):

    def test_run_routes_are_registered(
        self,
    ) -> None:

        from app.agents.bootstrap import (
            agent_manager,
        )
        from app.api.v1.workflows import (
            _agent_manager,
        )
        from app.main import app

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace()
            )
        )

        self.assertIs(
            _agent_manager(request),
            agent_manager,
        )

        schema = app.openapi()
        paths = schema.get(
            "paths",
            {},
        )
        components = (
            schema
            .get("components", {})
            .get("schemas", {})
        )

        self.assertIn(
            "/api/v1/workflows/chapter/runs",
            paths,
        )
        self.assertIn(
            "/api/v1/workflows/runs",
            paths,
        )
        self.assertIn(
            "/api/v1/workflows/runs/{run_id}",
            paths,
        )
        self.assertIn(
            (
                "/api/v1/workflows/"
                "runs/{run_id}/resume"
            ),
            paths,
        )

        for name in [
            "WorkflowRunSummary",
            "WorkflowRunDetail",
            "WorkflowRunEvent",
            "WorkflowChapterVersion",
            "WorkflowResumeRequest",
        ]:

            self.assertIn(
                name,
                components,
            )
