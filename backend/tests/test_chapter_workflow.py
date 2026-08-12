from __future__ import annotations

import json
import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.workflows.chapter_workflow import (
    ChapterWorkflow,
)
from app.workflows.quality import (
    build_revision_diff,
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


def issue_payload(
    *,
    severity: str = "major",
    issue_id: str = "",
    category: str = "continuity",
    issue: str = "A conflict exists.",
    evidence: str = "Known memory.",
    impact: str = "Breaks continuity.",
    recommendation: str = (
        "Revise the conflict."
    ),
) -> dict:

    return {
        "issue_id": issue_id,
        "severity": severity,
        "category": category,
        "issue": issue,
        "evidence": evidence,
        "impact": impact,
        "recommendation": recommendation,
    }


def score_payload(
    score: float,
) -> dict:

    return {
        "continuity": score,
        "character_consistency": score,
        "world_consistency": score,
        "plot_logic": score,
        "prose_quality": score,
        "pacing": score,
        "overall": score,
    }


def review_json(
    *,
    approved: bool,
    issues: list[dict] | None = None,
    score: float | None = None,
    include_scores: bool = True,
) -> str:

    if issues is None:
        issues = []

    if score is None:
        score = (
            90.0
            if approved
            else 60.0
        )

    payload = {
        "approved": approved,
        "summary": (
            "Approved."
            if approved
            else "Revision required."
        ),
        "issues": issues,
    }

    if include_scores:
        payload["scores"] = (
            score_payload(
                score
            )
        )

    return json.dumps(
        payload
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
            result.quality_scores.overall,
            90.0,
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
                        issues=[
                            issue_payload()
                        ],
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
        self.assertEqual(
            len(result.revision_diffs),
            1,
        )
        self.assertTrue(
            result.revision_diffs[
                0
            ].changed
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
                        issues=[
                            issue_payload()
                        ],
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
                        issues=[
                            issue_payload(
                                issue_id=(
                                    "ISSUE-001"
                                )
                            )
                        ],
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
        self.assertEqual(
            len(result.revision_diffs),
            2,
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
                        issues=[
                            issue_payload()
                        ],
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
                        issues=[
                            issue_payload(
                                issue_id=(
                                    "ISSUE-001"
                                )
                            )
                        ],
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
                        issues=[
                            issue_payload()
                        ],
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
                        issues=[
                            issue_payload()
                        ],
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

    async def test_truncated_review_retries_without_reasoning(
        self,
    ) -> None:

        truncated_review = make_result(
            agent="review",
            content='{"approved": true',
        )
        truncated_review.finish_reason = "length"

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                truncated_review,
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
        self.assertTrue(
            result.workflow_steps[1]
            .metadata[
                "review_output_truncated"
            ]
        )
        self.assertFalse(
            result.workflow_steps[2]
            .metadata[
                "review_output_truncated"
            ]
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
                        issues=[
                            issue_payload()
                        ],
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
                issues=[
                    issue_payload()
                ],
            )
        )

        from app.workflows.quality import (
            QualityTracker,
        )

        tracker = QualityTracker()
        tracker.apply_review(
            review,
            1,
        )

        prompt = (
            ChapterWorkflow
            ._rewrite_instruction(
                "Draft.",
                review,
                tracker.unresolved(),
                1,
                self._request(),
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
                        issues=[
                            issue_payload()
                        ],
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
        self.assertEqual(
            len(result.revision_diffs),
            1,
        )
        self.assertFalse(
            result.revision_diffs[
                0
            ].changed
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
                        issues=[
                            issue_payload()
                        ],
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
                        issues=[
                            issue_payload(
                                issue_id=(
                                    "ISSUE-001"
                                )
                            )
                        ],
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

    def test_grounded_chapter_overrides_review_fact_coordinate(
        self,
    ) -> None:

        payload = json.loads(
            review_json(approved=True)
        )
        payload["candidate_facts"] = [
            {
                "fact_id": "FACT-001",
                "fact_type": "relationship",
                "subject_name": "岚",
                "predicate": "敌对",
                "object_name": "祁",
                "evidence": "岚和祁是敌人。",
                "chapter_number": "wrong-coordinate",
            }
        ]

        report = ChapterWorkflow._parse_review(
            json.dumps(payload),
            chapter_number=3,
        )

        self.assertEqual(
            report.candidate_facts[0].chapter_number,
            3,
        )

    def test_missing_scores_are_inferred(
        self,
    ) -> None:

        report = ChapterWorkflow._parse_review(
            review_json(
                approved=True,
                include_scores=False,
            )
        )

        self.assertTrue(
            report.scores_inferred
        )
        self.assertEqual(
            report.scores.overall,
            90.0,
        )

    def test_ten_point_scores_are_normalized(
        self,
    ) -> None:

        payload = {
            "approved": True,
            "summary": "Approved.",
            "scores": score_payload(
                8.5
            ),
            "issues": [],
        }

        report = ChapterWorkflow._parse_review(
            json.dumps(
                payload
            )
        )

        self.assertTrue(
            report.scores_normalized
        )
        self.assertEqual(
            report.scores.overall,
            85.0,
        )

    async def test_low_score_triggers_rewrite_without_issues(
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
                        approved=True,
                        score=65.0,
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Improved.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=True,
                        score=90.0,
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
            1,
        )

    async def test_issue_id_is_assigned_and_resolved(
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
                        issues=[
                            issue_payload()
                        ],
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Revised.",
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
            result.review_history[
                0
            ].issues[0].issue_id,
            "ISSUE-001",
        )
        self.assertEqual(
            result.issue_tracker[
                0
            ].status,
            "resolved",
        )
        self.assertEqual(
            result.unresolved_issue_ids,
            [],
        )
        self.assertEqual(
            [
                item.transition
                for item
                in result.issue_transitions
            ],
            [
                "new",
                "resolved",
            ],
        )

    async def test_persisting_issue_reuses_id(
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
                        issues=[
                            issue_payload()
                        ],
                    ),
                ),
                make_result(
                    agent="rewrite",
                    content="Revised.",
                ),
                make_result(
                    agent="review",
                    content=review_json(
                        approved=False,
                        issues=[
                            issue_payload(
                                issue_id=(
                                    "ISSUE-001"
                                )
                            )
                        ],
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
        self.assertEqual(
            result.unresolved_issue_ids,
            [
                "ISSUE-001"
            ],
        )
        self.assertEqual(
            [
                item.transition
                for item
                in result.issue_transitions
            ],
            [
                "new",
                "persisting",
            ],
        )

    async def test_second_rewrite_receives_only_unresolved_issue(
        self,
    ) -> None:

        first_issues = [
            issue_payload(
                category="continuity",
                issue="Conflict A.",
                recommendation="Fix A.",
            ),
            issue_payload(
                category="pacing",
                issue="Conflict B.",
                recommendation="Fix B.",
            ),
        ]

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
                        issues=first_issues,
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
                        issues=[
                            issue_payload(
                                issue_id=(
                                    "ISSUE-002"
                                ),
                                category="pacing",
                                issue="Conflict B.",
                                recommendation=(
                                    "Fix B."
                                ),
                            )
                        ],
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

        second_rewrite_context = (
            manager.execute
            .await_args_list[4]
            .kwargs["context"]
        )

        self.assertIn(
            "ISSUE-002",
            second_rewrite_context.instruction,
        )
        self.assertNotIn(
            "ISSUE-001",
            second_rewrite_context.instruction,
        )

    def test_revision_diff_summary(
        self,
    ) -> None:

        diff = build_revision_diff(
            before="abc",
            after="abXYZ",
            round_index=1,
        )

        self.assertTrue(
            diff.changed
        )
        self.assertEqual(
            diff.before_length,
            3,
        )
        self.assertEqual(
            diff.after_length,
            5,
        )
        self.assertLess(
            diff.similarity_ratio,
            1.0,
        )

    async def test_dimension_score_reason_is_reported(
        self,
    ) -> None:

        payload = {
            "approved": True,
            "summary": "Pacing is weak.",
            "scores": (
                score_payload(
                    90.0
                )
                | {
                    "pacing": 60.0,
                    "overall": 85.0,
                }
            ),
            "issues": [],
        }

        manager = SimpleNamespace()
        manager.execute = AsyncMock(
            side_effect=[
                make_result(
                    agent="chapter",
                    content="Draft.",
                ),
                make_result(
                    agent="review",
                    content=json.dumps(
                        payload
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

        self.assertIn(
            "dimension_score_below_threshold:pacing",
            result.quality_gate_reasons,
        )


class WorkflowOpenApiTests(
    unittest.TestCase
):

    def test_quality_tracking_fields_are_registered(
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

        for name in [
            "minimum_overall_score",
            "minimum_dimension_score",
            "require_all_issues_resolved",
        ]:

            self.assertIn(
                name,
                request_schema[
                    "properties"
                ],
            )

        for name in [
            "quality_scores",
            "quality_score_history",
            "issue_tracker",
            "issue_transitions",
            "unresolved_issue_ids",
            "quality_gate_reasons",
            "revision_diffs",
        ]:

            self.assertIn(
                name,
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

        for schema_name in [
            "ReviewScores",
            "TrackedIssue",
            "IssueTransition",
            "RevisionDiffSummary",
        ]:

            self.assertIn(
                schema_name,
                components,
            )
