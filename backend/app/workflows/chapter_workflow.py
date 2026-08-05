from __future__ import annotations

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


class ReviewOutputParseError(
    ValueError
):
    """
    Raised when ReviewAgent output cannot
    be converted into ReviewReport.
    """


class ChapterWorkflow:
    """
    Generate, review, and optionally rewrite
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
        result: Any,
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
        draft: str,
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
            "unconfirmed.\n\n"
            "CHAPTER_BEGIN\n"
            + draft
            + "\nCHAPTER_END"
        )

    @staticmethod
    def _rewrite_instruction(
        draft: str,
        review: ReviewReport,
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
            "5. Output only the complete revised "
            "chapter.\n\n"
            "REVIEW_REPORT_BEGIN\n"
            + review_json
            + "\nREVIEW_REPORT_END\n\n"
            "DRAFT_BEGIN\n"
            + draft
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
        reasoning_effort: str,
        temperature: float,
        max_tokens: int,
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

    async def run(
        self,
        request: ChapterWorkflowRequest,
    ) -> ChapterWorkflowResult:

        steps: list[WorkflowStep] = []

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

            return ChapterWorkflowResult(
                status="draft_failed",
                metadata={
                    "error": str(exc),
                    "failed_stage": "draft",
                },
            )

        draft_step = self._step_from_result(
            "draft",
            draft_result,
        )

        steps.append(
            draft_step
        )

        draft = draft_step.content

        if (
            not draft_step.success
            or not draft.strip()
        ):

            return ChapterWorkflowResult(
                status="draft_failed",
                draft=draft,
                final_content=draft,
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "failed_stage": "draft",
                },
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
                                draft
                            )
                        ),
                        stage="review",
                        reasoning_effort=(
                            request
                            .review_reasoning_effort
                        ),
                        temperature=(
                            request
                            .review_temperature
                        ),
                        max_tokens=(
                            request
                            .review_max_tokens
                        ),
                    ),
                )
            )

        except Exception as exc:

            return ChapterWorkflowResult(
                status="review_failed",
                draft=draft,
                final_content=draft,
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "error": str(exc),
                    "failed_stage": "review",
                },
            )

        review_step = self._step_from_result(
            "review",
            review_result,
        )

        steps.append(
            review_step
        )

        review_raw = review_step.content

        if (
            not review_step.success
            or not review_raw.strip()
        ):

            return ChapterWorkflowResult(
                status="review_failed",
                draft=draft,
                review_raw=review_raw,
                final_content=draft,
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "failed_stage": "review",
                },
            )

        try:

            review_report = (
                self._parse_review(
                    review_raw
                )
            )

        except ReviewOutputParseError as exc:

            return ChapterWorkflowResult(
                status="review_parse_failed",
                draft=draft,
                review_raw=review_raw,
                final_content=draft,
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "error": str(exc),
                    "failed_stage": (
                        "review_parse"
                    ),
                },
            )

        requires_revision = (
            self._requires_revision(
                review_report,
                request.rewrite_on_severities,
            )
        )

        if (
            not requires_revision
            or not request.auto_rewrite
        ):

            return ChapterWorkflowResult(
                status="completed",
                draft=draft,
                review_report=review_report,
                review_raw=review_raw,
                final_content=draft,
                revision_applied=False,
                quality_gate_passed=(
                    not requires_revision
                ),
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "auto_rewrite": (
                        request.auto_rewrite
                    ),
                    "revision_required": (
                        requires_revision
                    ),
                    "review_parse_success": (
                        True
                    ),
                },
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
                                draft,
                                review_report,
                            )
                        ),
                        stage="rewrite",
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

            return ChapterWorkflowResult(
                status="rewrite_failed",
                draft=draft,
                review_report=review_report,
                review_raw=review_raw,
                final_content=draft,
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "error": str(exc),
                    "failed_stage": "rewrite",
                    "review_parse_success": (
                        True
                    ),
                },
            )

        rewrite_step = self._step_from_result(
            "rewrite",
            rewrite_result,
        )

        steps.append(
            rewrite_step
        )

        final_content = (
            rewrite_step.content
            if (
                rewrite_step.success
                and rewrite_step.content.strip()
            )
            else draft
        )

        if final_content == draft:

            return ChapterWorkflowResult(
                status="rewrite_failed",
                draft=draft,
                review_report=review_report,
                review_raw=review_raw,
                final_content=draft,
                workflow_steps=steps,
                usage=self._aggregate_usage(
                    steps
                ),
                metadata={
                    "failed_stage": "rewrite",
                    "review_parse_success": (
                        True
                    ),
                },
            )

        return ChapterWorkflowResult(
            status="completed",
            draft=draft,
            review_report=review_report,
            review_raw=review_raw,
            final_content=final_content,
            revision_applied=True,
            quality_gate_passed=False,
            workflow_steps=steps,
            usage=self._aggregate_usage(
                steps
            ),
            metadata={
                "auto_rewrite": True,
                "revision_required": True,
                "review_parse_success": True,
                "post_rewrite_review": False,
            },
        )
