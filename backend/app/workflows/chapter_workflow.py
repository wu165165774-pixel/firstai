from __future__ import annotations

import hashlib
import json

from json import (
    JSONDecodeError,
    JSONDecoder,
)
from typing import Any

from pydantic import ValidationError

from app.agents.manager import AgentManager
from app.agents.schemas import AgentContext
from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResult,
    ReviewReport,
    WorkflowStep,
    WorkflowUsage,
)


class ReviewOutputParseError(ValueError):
    """
    Raised when ReviewAgent output cannot
    be converted into ReviewReport.
    """


class ChapterWorkflow:
    """
    Generate, review, rewrite, and re-review
    a complete novel chapter.
    """

    def __init__(
        self,
        agent_manager: AgentManager,
    ) -> None:

        self._agent_manager = agent_manager

    @staticmethod
    def _read_int(
        value: Any,
        name: str,
    ) -> int:

        if value is None:
            return 0

        if isinstance(
            value,
            dict,
        ):

            return int(
                value.get(
                    name,
                    0,
                )
                or 0
            )

        return int(
            getattr(
                value,
                name,
                0,
            )
            or 0
        )

    @classmethod
    def _step_from_result(
        cls,
        stage: str,
        round_index: int,
        result: Any,
        attempt_index: int = 1,
    ) -> WorkflowStep:

        usage = getattr(
            result,
            "usage",
            None,
        )

        metadata = getattr(
            result,
            "metadata",
            None,
        )

        return WorkflowStep(
            stage=stage,
            round_index=round_index,
            attempt_index=attempt_index,
            agent=str(
                getattr(
                    result,
                    "agent",
                    stage,
                )
            ),
            success=bool(
                getattr(
                    result,
                    "success",
                    True,
                )
            ),
            content=str(
                getattr(
                    result,
                    "content",
                    "",
                )
                or ""
            ),
            provider=str(
                getattr(
                    result,
                    "provider",
                    "",
                )
                or ""
            ),
            model=str(
                getattr(
                    result,
                    "model",
                    "",
                )
                or ""
            ),
            finish_reason=getattr(
                result,
                "finish_reason",
                None,
            ),
            prompt_tokens=cls._read_int(
                usage,
                "prompt_tokens",
            ),
            completion_tokens=cls._read_int(
                usage,
                "completion_tokens",
            ),
            total_tokens=cls._read_int(
                usage,
                "total_tokens",
            ),
            latency_ms=float(
                getattr(
                    result,
                    "latency_ms",
                    0.0,
                )
                or 0.0
            ),
            metadata=dict(
                metadata or {}
            ),
        )

    @staticmethod
    def _aggregate_usage(
        steps: list[WorkflowStep],
    ) -> WorkflowUsage:

        return WorkflowUsage(
            prompt_tokens=sum(
                step.prompt_tokens
                for step in steps
            ),
            completion_tokens=sum(
                step.completion_tokens
                for step in steps
            ),
            total_tokens=sum(
                step.total_tokens
                for step in steps
            ),
            latency_ms=sum(
                step.latency_ms
                for step in steps
            ),
        )

    @staticmethod
    def _content_fingerprint(
        content: str,
    ) -> str:

        normalized = " ".join(
            content.split()
        )

        return hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _extract_json_object(
        content: str,
    ) -> dict[str, Any]:

        decoder = JSONDecoder()

        for index, character in enumerate(
            content
        ):

            if character != "{":
                continue

            try:

                value, _ = decoder.raw_decode(
                    content[index:]
                )

            except JSONDecodeError:

                continue

            if isinstance(
                value,
                dict,
            ):

                return value

        raise ReviewOutputParseError(
            "ReviewAgent did not return "
            "a valid JSON object."
        )

    @classmethod
    def _parse_review(
        cls,
        content: str,
    ) -> ReviewReport:

        try:

            payload = cls._extract_json_object(
                content
            )

            return ReviewReport.model_validate(
                payload
            )

        except (
            ValidationError,
            ReviewOutputParseError,
        ) as exc:

            raise ReviewOutputParseError(
                str(exc)
            ) from exc

    @staticmethod
    def _review_instruction(
        content: str,
        round_index: int,
    ) -> str:

        return (
            "Review the supplied chapter against "
            "retrieved long-term memory. Return "
            "exactly one JSON object without Markdown "
            "or code fences.\n\n"
            "Required JSON schema:\n"
            "{\n"
            '  "approved": true,\n'
            '  "summary": "short review summary",\n'
            '  "issues": [\n'
            "    {\n"
            '      "severity": '
            '"critical|major|moderate|minor",\n'
            '      "category": "issue category",\n'
            '      "issue": "issue description",\n'
            '      "evidence": "specific evidence",\n'
            '      "impact": "why this matters",\n'
            '      "recommendation": "safe correction"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Set approved to false when the chapter "
            "contains a confirmed conflict or requires "
            "substantive correction. Do not invent "
            "missing canon to explain a conflict. "
            "Unsupported facts must be marked as "
            "unconfirmed.\n"
            f"This is review round {round_index}.\n\n"
            "CHAPTER_BEGIN\n"
            + content
            + "\nCHAPTER_END"
        )

    @staticmethod
    def _rewrite_instruction(
        content: str,
        review: ReviewReport,
        round_index: int,
    ) -> str:

        review_json = json.dumps(
            review.model_dump(),
            ensure_ascii=False,
            indent=2,
        )

        return (
            "Revise the chapter using the review "
            "report below.\n\n"
            "Rules:\n"
            "1. Correct all confirmed conflicts.\n"
            "2. Preserve confirmed character, world, "
            "and plot facts.\n"
            "3. Do not create new canon to explain "
            "unsupported statements.\n"
            "4. Preserve the intended scene, style, "
            "point of view, and event outcome.\n"
            "5. Implement at least one concrete textual "
            "change that addresses the review report.\n"
            "6. Do not return the source text unchanged. "
            "The revised output must differ from the "
            "input while preserving confirmed facts.\n"
            "7. Output only the complete revised "
            "chapter.\n"
            f"8. This is revision round {round_index}.\n\n"
            "REVIEW_REPORT_BEGIN\n"
            + review_json
            + "\nREVIEW_REPORT_END\n\n"
            "DRAFT_BEGIN\n"
            + content
            + "\nDRAFT_END"
        )

    @staticmethod
    def _requires_revision(
        report: ReviewReport,
        severities: list[str],
    ) -> bool:

        if not report.approved:
            return True

        selected = set(
            severities
        )

        return any(
            issue.severity in selected
            for issue in report.issues
        )

    @staticmethod
    def _context(
        request: ChapterWorkflowRequest,
        *,
        instruction: str,
        stage: str,
        round_index: int,
        reasoning_effort: str,
        temperature: float,
        max_tokens: int,
        attempt_index: int = 1,
    ) -> AgentContext:

        metadata = dict(
            request.metadata
        )

        metadata.update(
            {
                "workflow": (
                    "chapter_production"
                ),
                "workflow_stage": stage,
                "workflow_round": (
                    round_index
                ),
                "workflow_attempt": (
                    attempt_index
                ),
            }
        )

        return AgentContext.model_validate(
            {
                "user_id": request.user_id,
                "novel_id": request.novel_id,
                "instruction": instruction,
                "provider": request.provider,
                "model": request.model,
                "use_memory": (
                    request.use_memory
                ),
                "task_mode": "creative",
                "reasoning_effort": (
                    reasoning_effort
                ),
                "temperature": temperature,
                "max_tokens": max_tokens,
                "metadata": metadata,
            }
        )

    async def _execute_review_with_retry(
        self,
        request: ChapterWorkflowRequest,
        current_content: str,
        review_round: int,
    ) -> tuple[
        list[WorkflowStep],
        WorkflowStep | None,
        str | None,
    ]:

        attempt_steps: list[
            WorkflowStep
        ] = []

        last_error: str | None = None

        total_attempts = (
            1
            + request.review_retry_attempts
        )

        for attempt_index in range(
            1,
            total_attempts + 1,
        ):

            is_retry = attempt_index > 1

            reasoning_effort = (
                request
                .review_retry_reasoning_effort
                if is_retry
                else request
                .review_reasoning_effort
            )

            max_tokens = (
                max(
                    request.review_max_tokens,
                    1200,
                )
                if is_retry
                else request.review_max_tokens
            )

            try:

                review_result = (
                    await self
                    ._agent_manager
                    .execute(
                        agent_name="review",
                        context=self._context(
                            request,
                            instruction=(
                                self
                                ._review_instruction(
                                    current_content,
                                    review_round,
                                )
                            ),
                            stage="review",
                            round_index=(
                                review_round
                            ),
                            reasoning_effort=(
                                reasoning_effort
                            ),
                            temperature=(
                                request
                                .review_temperature
                            ),
                            max_tokens=max_tokens,
                            attempt_index=(
                                attempt_index
                            ),
                        ),
                    )
                )

            except Exception as exc:

                last_error = str(exc)
                continue

            review_step = (
                self._step_from_result(
                    "review",
                    review_round,
                    review_result,
                    attempt_index,
                )
            )

            review_step.metadata.update(
                {
                    "review_attempt_index": (
                        attempt_index
                    ),
                    "review_retry_count": (
                        attempt_index - 1
                    ),
                    "review_fallback_used": (
                        is_retry
                    ),
                    "effective_reasoning_effort": (
                        reasoning_effort
                    ),
                    "effective_max_tokens": (
                        max_tokens
                    ),
                }
            )

            attempt_steps.append(
                review_step
            )

            if (
                review_step.success
                and review_step.content.strip()
            ):

                return (
                    attempt_steps,
                    review_step,
                    None,
                )

            last_error = (
                "ReviewAgent returned an empty "
                "or unsuccessful result."
            )

        return (
            attempt_steps,
            None,
            last_error,
        )

    @staticmethod
    def _result(
        *,
        status: str,
        draft: str,
        current_content: str,
        steps: list[WorkflowStep],
        review_history: list[ReviewReport],
        review_raw_history: list[str],
        revision_rounds: int,
        quality_gate_passed: bool,
        metadata: dict[str, Any],
    ) -> ChapterWorkflowResult:

        latest_review = (
            review_history[-1]
            if review_history
            else None
        )

        latest_raw = (
            review_raw_history[-1]
            if review_raw_history
            else ""
        )

        return ChapterWorkflowResult(
            status=status,
            draft=draft,
            review_report=latest_review,
            review_history=review_history,
            review_raw=latest_raw,
            review_raw_history=(
                review_raw_history
            ),
            final_content=current_content,
            revision_applied=(
                revision_rounds > 0
            ),
            revision_rounds=revision_rounds,
            quality_gate_passed=(
                quality_gate_passed
            ),
            workflow_steps=steps,
            usage=ChapterWorkflow._aggregate_usage(
                steps
            ),
            metadata=metadata,
        )

    async def run(
        self,
        request: ChapterWorkflowRequest,
    ) -> ChapterWorkflowResult:

        steps: list[WorkflowStep] = []
        review_history: list[
            ReviewReport
        ] = []
        review_raw_history: list[str] = []
        revision_rounds = 0

        try:

            draft_result = (
                await self
                ._agent_manager
                .execute(
                    agent_name="chapter",
                    context=self._context(
                        request,
                        instruction=(
                            request.instruction
                        ),
                        stage="draft",
                        round_index=0,
                        reasoning_effort=(
                            request
                            .chapter_reasoning_effort
                        ),
                        temperature=(
                            request
                            .chapter_temperature
                        ),
                        max_tokens=(
                            request
                            .chapter_max_tokens
                        ),
                    ),
                )
            )

        except Exception as exc:

            return self._result(
                status="draft_failed",
                draft="",
                current_content="",
                steps=steps,
                review_history=review_history,
                review_raw_history=(
                    review_raw_history
                ),
                revision_rounds=0,
                quality_gate_passed=False,
                metadata={
                    "error": str(exc),
                    "failed_stage": "draft",
                    "termination_reason": (
                        "draft_exception"
                    ),
                },
            )

        draft_step = self._step_from_result(
            "draft",
            0,
            draft_result,
        )

        steps.append(
            draft_step
        )

        draft = draft_step.content
        current_content = draft

        if (
            not draft_step.success
            or not draft.strip()
        ):

            return self._result(
                status="draft_failed",
                draft=draft,
                current_content=draft,
                steps=steps,
                review_history=review_history,
                review_raw_history=(
                    review_raw_history
                ),
                revision_rounds=0,
                quality_gate_passed=False,
                metadata={
                    "failed_stage": "draft",
                    "termination_reason": (
                        "empty_or_failed_draft"
                    ),
                },
            )

        seen_fingerprints = {
            self._content_fingerprint(
                current_content
            )
        }

        review_round = 1

        while True:

            (
                review_attempt_steps,
                review_step,
                review_error,
            ) = await self._execute_review_with_retry(
                request,
                current_content,
                review_round,
            )

            steps.extend(
                review_attempt_steps
            )

            if review_step is None:

                return self._result(
                    status="review_failed",
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "error": review_error,
                        "failed_stage": "review",
                        "failed_round": (
                            review_round
                        ),
                        "review_attempts": (
                            1
                            + request
                            .review_retry_attempts
                        ),
                        "termination_reason": (
                            "review_retries_exhausted"
                        ),
                    },
                )

            review_raw = review_step.content

            review_raw_history.append(
                review_raw
            )

            try:

                review_report = (
                    self._parse_review(
                        review_raw
                    )
                )

            except ReviewOutputParseError as exc:

                return self._result(
                    status=(
                        "review_parse_failed"
                    ),
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "error": str(exc),
                        "failed_stage": (
                            "review_parse"
                        ),
                        "failed_round": (
                            review_round
                        ),
                        "termination_reason": (
                            "review_parse_failed"
                        ),
                    },
                )

            review_history.append(
                review_report
            )

            requires_revision = (
                self._requires_revision(
                    review_report,
                    request
                    .rewrite_on_severities,
                )
            )

            if not requires_revision:

                return self._result(
                    status="completed",
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=True,
                    metadata={
                        "auto_rewrite": (
                            request.auto_rewrite
                        ),
                        "revision_required": (
                            False
                        ),
                        "review_parse_success": (
                            True
                        ),
                        "termination_reason": (
                            "quality_gate_passed"
                        ),
                        "final_review_round": (
                            review_round
                        ),
                    },
                )

            if not request.auto_rewrite:

                return self._result(
                    status="completed",
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "auto_rewrite": False,
                        "revision_required": True,
                        "review_parse_success": (
                            True
                        ),
                        "termination_reason": (
                            "auto_rewrite_disabled"
                        ),
                    },
                )

            if (
                revision_rounds
                >= request.max_revision_rounds
            ):

                return self._result(
                    status=(
                        "max_revisions_reached"
                    ),
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "auto_rewrite": True,
                        "revision_required": True,
                        "review_parse_success": (
                            True
                        ),
                        "termination_reason": (
                            "max_revisions_reached"
                        ),
                        "max_revision_rounds": (
                            request
                            .max_revision_rounds
                        ),
                    },
                )

            next_revision_round = (
                revision_rounds + 1
            )

            try:

                rewrite_result = (
                    await self
                    ._agent_manager
                    .execute(
                        agent_name="rewrite",
                        context=self._context(
                            request,
                            instruction=(
                                self
                                ._rewrite_instruction(
                                    current_content,
                                    review_report,
                                    next_revision_round,
                                )
                            ),
                            stage="rewrite",
                            round_index=(
                                next_revision_round
                            ),
                            reasoning_effort=(
                                request
                                .rewrite_reasoning_effort
                            ),
                            temperature=(
                                request
                                .rewrite_temperature
                            ),
                            max_tokens=(
                                request
                                .rewrite_max_tokens
                            ),
                        ),
                    )
                )

            except Exception as exc:

                return self._result(
                    status="rewrite_failed",
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "error": str(exc),
                        "failed_stage": "rewrite",
                        "failed_round": (
                            next_revision_round
                        ),
                        "termination_reason": (
                            "rewrite_exception"
                        ),
                    },
                )

            rewrite_step = (
                self._step_from_result(
                    "rewrite",
                    next_revision_round,
                    rewrite_result,
                )
            )

            steps.append(
                rewrite_step
            )

            revised_content = (
                rewrite_step.content
            )

            if (
                not rewrite_step.success
                or not revised_content.strip()
            ):

                return self._result(
                    status="rewrite_failed",
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "failed_stage": "rewrite",
                        "failed_round": (
                            next_revision_round
                        ),
                        "termination_reason": (
                            "empty_or_failed_rewrite"
                        ),
                    },
                )

            fingerprint = (
                self._content_fingerprint(
                    revised_content
                )
            )

            if fingerprint in seen_fingerprints:

                return self._result(
                    status=(
                        "stagnation_detected"
                    ),
                    draft=draft,
                    current_content=(
                        current_content
                    ),
                    steps=steps,
                    review_history=(
                        review_history
                    ),
                    review_raw_history=(
                        review_raw_history
                    ),
                    revision_rounds=(
                        revision_rounds
                    ),
                    quality_gate_passed=False,
                    metadata={
                        "failed_stage": "rewrite",
                        "failed_round": (
                            next_revision_round
                        ),
                        "termination_reason": (
                            "repeated_content"
                        ),
                    },
                )

            seen_fingerprints.add(
                fingerprint
            )

            current_content = revised_content
            revision_rounds = (
                next_revision_round
            )
            review_round += 1
