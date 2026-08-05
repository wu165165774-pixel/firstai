from __future__ import annotations

import json
import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.workflows.chapter_workflow import (
    ChapterWorkflow,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
)


def make_result(
    *,
    agent: str,
    content: str,
    success: bool = True,
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    latency_ms: float = 5.0,
):
    return SimpleNamespace(
        agent=agent,
        success=success,
        content=content,
        provider="test",
        model="test-model",
        finish_reason="stop",
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=(
                prompt_tokens
                + completion_tokens
            ),
        ),
        latency_ms=latency_ms,
        metadata={
            "test": True
        },
    )


class ChapterWorkflowTests(
    unittest.IsolatedAsyncioTestCase
):

    def _request(
        self,
        **updates,
    ) -> ChapterWorkflowRequest:

        payload = {
            "user_id": "user001",
            "novel_id": "novel001",
            "instruction": (
                "Write a complete chapter."
            ),
        }

        payload.update(
            updates
        )

        return ChapterWorkflowRequest(
            **payload
        )

    async def test_approved_review_skips_rewrite(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft chapter.",
                ),
                make_result(
                    agent="review",
                    content=json.dumps(
                        {
                            "approved": True,
                            "summary": "Approved.",
                            "issues": [],
                        }
                    ),
                ),
            ]
        )

        workflow = ChapterWorkflow(
            manager
        )

        result = await workflow.run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertTrue(
            result.quality_gate_passed
        )
        self.assertFalse(
            result.revision_applied
        )
        self.assertEqual(
            result.final_content,
            "Draft chapter.",
        )
        self.assertEqual(
            len(result.workflow_steps),
            2,
        )
        self.assertEqual(
            manager.execute.await_count,
            2,
        )

    async def test_major_issue_triggers_rewrite(
        self,
    ) -> None:

        review = {
            "approved": False,
            "summary": "Conflict found.",
            "issues": [
                {
                    "severity": "major",
                    "category": "character",
                    "issue": "Behavior conflict.",
                    "evidence": "Known memory.",
                    "impact": "Breaks continuity.",
                    "recommendation": (
                        "Revise the behavior."
                    ),
                }
            ],
        }

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft chapter.",
                ),
                make_result(
                    agent="review",
                    content=json.dumps(
                        review
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Revised chapter.",
                ),
            ]
        )

        workflow = ChapterWorkflow(
            manager
        )

        result = await workflow.run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertTrue(
            result.revision_applied
        )
        self.assertFalse(
            result.quality_gate_passed
        )
        self.assertEqual(
            result.final_content,
            "Revised chapter.",
        )
        self.assertEqual(
            len(result.workflow_steps),
            3,
        )
        self.assertEqual(
            result.usage.total_tokens,
            90,
        )

    async def test_auto_rewrite_can_be_disabled(
        self,
    ) -> None:

        review = {
            "approved": False,
            "summary": "Conflict found.",
            "issues": [
                {
                    "severity": "major",
                    "category": "world",
                    "issue": "Rule conflict.",
                    "evidence": "Known rule.",
                    "impact": "Breaks canon.",
                    "recommendation": (
                        "Follow the known rule."
                    ),
                }
            ],
        }

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft chapter.",
                ),
                make_result(
                    agent="review",
                    content=json.dumps(
                        review
                    ),
                ),
            ]
        )

        workflow = ChapterWorkflow(
            manager
        )

        result = await workflow.run(
            self._request(
                auto_rewrite=False
            )
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertFalse(
            result.revision_applied
        )
        self.assertFalse(
            result.quality_gate_passed
        )
        self.assertTrue(
            result.metadata[
                "revision_required"
            ]
        )
        self.assertEqual(
            manager.execute.await_count,
            2,
        )

    async def test_invalid_review_json_is_safe(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft chapter.",
                ),
                make_result(
                    agent="review",
                    content="not-json",
                ),
            ]
        )

        workflow = ChapterWorkflow(
            manager
        )

        result = await workflow.run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "review_parse_failed",
        )
        self.assertEqual(
            result.final_content,
            "Draft chapter.",
        )
        self.assertFalse(
            result.revision_applied
        )

    async def test_json_inside_code_fence_is_parsed(
        self,
    ) -> None:

        content = (
            "```json\n"
            + json.dumps(
                {
                    "approved": True,
                    "summary": "Approved.",
                    "issues": [],
                }
            )
            + "\n```"
        )

        report = (
            ChapterWorkflow._parse_review(
                content
            )
        )

        self.assertTrue(
            report.approved
        )


class WorkflowOpenApiTests(
    unittest.TestCase
):

    def test_chapter_workflow_route_is_registered(
        self,
    ) -> None:

        from app.main import app

        paths = set(
            app.openapi()
            .get("paths", {})
            .keys()
        )

        self.assertIn(
            "/api/v1/workflows/chapter",
            paths,
        )
