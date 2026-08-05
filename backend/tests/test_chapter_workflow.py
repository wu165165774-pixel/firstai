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
                "category": "continuity",
                "issue": "A conflict exists.",
                "evidence": "Known memory.",
                "impact": "Breaks continuity.",
                "recommendation": (
                    "Revise the conflict."
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
        }
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
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertTrue(
            result.quality_gate_passed
        )
        self.assertEqual(
            result.revision_rounds,
            0,
        )
        self.assertEqual(
            len(result.review_history),
            1,
        )
        self.assertEqual(
            len(result.workflow_steps),
            2,
        )

    async def test_rewrite_is_re_reviewed(
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
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Revised chapter.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertTrue(
            result.quality_gate_passed
        )
        self.assertTrue(
            result.revision_applied
        )
        self.assertEqual(
            result.revision_rounds,
            1,
        )
        self.assertEqual(
            result.final_content,
            "Revised chapter.",
        )
        self.assertEqual(
            [
                step.stage
                for step in result.workflow_steps
            ],
            [
                "draft",
                "review",
                "rewrite",
                "review",
            ],
        )
        self.assertEqual(
            [
                step.round_index
                for step in result.workflow_steps
            ],
            [
                0,
                1,
                1,
                2,
            ],
        )

    async def test_two_revision_rounds_can_pass(
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
                make_result(
                    agent="rewrite",
                    content="Revision one.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Revision two.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                max_revision_rounds=2
            )
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertTrue(
            result.quality_gate_passed
        )
        self.assertEqual(
            result.revision_rounds,
            2,
        )
        self.assertEqual(
            len(result.review_history),
            3,
        )
        self.assertEqual(
            len(result.workflow_steps),
            6,
        )
        self.assertEqual(
            result.usage.total_tokens,
            180,
        )

    async def test_max_revision_limit_stops_loop(
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
                make_result(
                    agent="rewrite",
                    content="Revision one.",
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

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                max_revision_rounds=1
            )
        )

        self.assertEqual(
            result.status,
            "max_revisions_reached",
        )
        self.assertFalse(
            result.quality_gate_passed
        )
        self.assertEqual(
            result.revision_rounds,
            1,
        )
        self.assertEqual(
            result.final_content,
            "Revision one.",
        )
        self.assertEqual(
            manager.execute.await_count,
            4,
        )

    async def test_auto_rewrite_can_be_disabled(
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

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                auto_rewrite=False
            )
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertFalse(
            result.quality_gate_passed
        )
        self.assertEqual(
            result.metadata[
                "termination_reason"
            ],
            "auto_rewrite_disabled",
        )
        self.assertEqual(
            manager.execute.await_count,
            2,
        )

    async def test_zero_revision_limit_is_safe(
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

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                max_revision_rounds=0
            )
        )

        self.assertEqual(
            result.status,
            "max_revisions_reached",
        )
        self.assertEqual(
            result.revision_rounds,
            0,
        )
        self.assertEqual(
            manager.execute.await_count,
            2,
        )

    async def test_empty_review_retries_without_reasoning(
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
                    content="",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True
                    ),
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                review_retry_attempts=1,
                review_reasoning_effort=(
                    "medium"
                ),
                review_retry_reasoning_effort=(
                    "none"
                ),
                review_max_tokens=900,
            )
        )

        self.assertEqual(
            result.status,
            "completed",
        )
        self.assertTrue(
            result.quality_gate_passed
        )
        self.assertEqual(
            manager.execute.await_count,
            3,
        )
        self.assertEqual(
            [
                step.stage
                for step in result.workflow_steps
            ],
            [
                "draft",
                "review",
                "review",
            ],
        )
        self.assertEqual(
            [
                step.attempt_index
                for step in result.workflow_steps
            ],
            [
                1,
                1,
                2,
            ],
        )

        retry_context = (
            manager.execute
            .await_args_list[2]
            .kwargs["context"]
        )

        self.assertEqual(
            retry_context.reasoning_effort,
            "none",
        )
        self.assertGreaterEqual(
            retry_context.max_tokens,
            1200,
        )

    async def test_review_retry_limit_stops_safely(
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
                    content="",
                ),
                make_result(
                    agent="review",
                    content="",
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                review_retry_attempts=1
            )
        )

        self.assertEqual(
            result.status,
            "review_failed",
        )
        self.assertEqual(
            result.metadata[
                "termination_reason"
            ],
            "review_retries_exhausted",
        )
        self.assertEqual(
            len(result.workflow_steps),
            3,
        )
        self.assertEqual(
            result.final_content,
            "Draft.",
        )

    async def test_first_review_parse_failure_is_safe(
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
                    content="not-json",
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "review_parse_failed",
        )
        self.assertEqual(
            result.final_content,
            "Draft.",
        )
        self.assertEqual(
            result.revision_rounds,
            0,
        )

    async def test_second_review_parse_failure_keeps_revision(
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
                make_result(
                    agent="rewrite",
                    content="Revised.",
                ),
                make_result(
                    agent="review",
                    content="not-json",
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "review_parse_failed",
        )
        self.assertEqual(
            result.final_content,
            "Revised.",
        )
        self.assertEqual(
            result.revision_rounds,
            1,
        )
        self.assertEqual(
            len(result.review_history),
            1,
        )
        self.assertEqual(
            len(result.review_raw_history),
            2,
        )

    def test_rewrite_prompt_requires_real_change(
        self,
    ) -> None:

        review = ChapterWorkflow._parse_review(
            review_json(
                approved=False,
                severity="moderate",
            )
        )

        prompt = (
            ChapterWorkflow
            ._rewrite_instruction(
                "Draft.",
                review,
                1,
            )
        )

        self.assertIn(
            "Implement at least one concrete textual change",
            prompt,
        )
        self.assertIn(
            "Do not return the source text unchanged",
            prompt,
        )

    async def test_repeated_rewrite_is_stopped(
        self,
    ) -> None:

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Same content.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Same content.",
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request()
        )

        self.assertEqual(
            result.status,
            "stagnation_detected",
        )
        self.assertFalse(
            result.revision_applied
        )
        self.assertEqual(
            result.metadata[
                "termination_reason"
            ],
            "repeated_content",
        )

    async def test_previous_revision_cycle_is_stopped(
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
                make_result(
                    agent="rewrite",
                    content="Revision.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        severity="major",
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Draft.",
                ),
            ]
        )

        result = await ChapterWorkflow(
            manager
        ).run(
            self._request(
                max_revision_rounds=3
            )
        )

        self.assertEqual(
            result.status,
            "stagnation_detected",
        )
        self.assertEqual(
            result.final_content,
            "Revision.",
        )
        self.assertEqual(
            result.revision_rounds,
            1,
        )

    async def test_json_inside_code_fence_is_parsed(
        self,
    ) -> None:

        content = (
            "```json\n"
            + review_json(
                approved=True
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

    def test_multiround_fields_are_registered(
        self,
    ) -> None:

        from app.main import app

        schema = app.openapi()
        paths = set(
            schema.get(
                "paths",
                {}
            ).keys()
        )
        components = (
            schema
            .get("components", {})
            .get("schemas", {})
        )

        request_schema = components[
            "ChapterWorkflowRequest"
        ]

        result_schema = components[
            "ChapterWorkflowResult"
        ]

        step_schema = components[
            "WorkflowStep"
        ]

        self.assertIn(
            "/api/v1/workflows/chapter",
            paths,
        )
        self.assertIn(
            "max_revision_rounds",
            request_schema[
                "properties"
            ],
        )
        self.assertIn(
            "review_retry_attempts",
            request_schema[
                "properties"
            ],
        )
        self.assertIn(
            "review_retry_reasoning_effort",
            request_schema[
                "properties"
            ],
        )
        self.assertIn(
            "review_history",
            result_schema[
                "properties"
            ],
        )
        self.assertIn(
            "revision_rounds",
            result_schema[
                "properties"
            ],
        )
        self.assertIn(
            "round_index",
            step_schema[
                "properties"
            ],
        )
        self.assertIn(
            "attempt_index",
            step_schema[
                "properties"
            ],
        )
