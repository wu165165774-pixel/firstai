from __future__ import annotations

import hashlib
import json

from json import (
    JSONDecodeError,
    JSONDecoder,
)
from statistics import mean
from typing import Any

from pydantic import ValidationError

from app.agents.manager import AgentManager
from app.agents.schemas import AgentContext
from app.llm.schemas import ChatMessage
from app.workflows.grounding import (
    ChapterWorkflowGrounding,
    ChapterWorkflowGroundingService,
    chapter_workflow_grounding_service,
)
from app.workflows.quality import (
    QualityTracker,
    build_revision_diff,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResult,
    ReviewReport,
    ReviewScores,
    RevisionDiffSummary,
    TrackedIssue,
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

    _score_dimensions = (
        "continuity",
        "character_consistency",
        "world_consistency",
        "plot_logic",
        "prose_quality",
        "pacing",
    )

    def __init__(
        self,
        agent_manager: AgentManager,
        grounding_service: ChapterWorkflowGroundingService | None = None,
    ) -> None:

        self._agent_manager = agent_manager
        self._grounding_service = (
            grounding_service
            or chapter_workflow_grounding_service
        )

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

    @staticmethod
    def _clamp_score(
        value: Any,
        fallback: float,
    ) -> float:

        try:

            score = float(value)

        except (
            TypeError,
            ValueError,
        ):

            score = fallback

        return round(
            max(
                0.0,
                min(
                    100.0,
                    score,
                ),
            ),
            2,
        )

    @classmethod
    def _normalize_scores(
        cls,
        payload: dict[str, Any],
    ) -> tuple[
        dict[str, float],
        bool,
        bool,
    ]:

        raw_scores = (
            payload.get("scores")
            or payload.get(
                "quality_scores"
            )
        )

        approved = bool(
            payload.get(
                "approved",
                False,
            )
        )

        issues = (
            payload.get("issues")
            or []
        )

        if not isinstance(
            raw_scores,
            dict,
        ):

            penalties = {
                "critical": 45.0,
                "major": 30.0,
                "moderate": 15.0,
                "minor": 5.0,
            }

            highest_penalty = max(
                [
                    penalties.get(
                        str(
                            issue.get(
                                "severity",
                                "",
                            )
                        ).lower(),
                        0.0,
                    )
                    for issue in issues
                    if isinstance(
                        issue,
                        dict,
                    )
                ]
                or [
                    0.0
                ]
            )

            base = (
                90.0
                if approved
                else 72.0
            )

            inferred = max(
                25.0,
                base - highest_penalty,
            )

            return (
                {
                    name: inferred
                    for name
                    in cls._score_dimensions
                }
                | {
                    "overall": inferred
                },
                True,
                False,
            )

        aliases = {
            "continuity": (
                "continuity",
            ),
            "character_consistency": (
                "character_consistency",
                "character",
                "characters",
            ),
            "world_consistency": (
                "world_consistency",
                "world",
                "worldbuilding",
            ),
            "plot_logic": (
                "plot_logic",
                "plot",
                "logic",
            ),
            "prose_quality": (
                "prose_quality",
                "prose",
                "style",
            ),
            "pacing": (
                "pacing",
                "pace",
            ),
        }

        collected: dict[
            str,
            float,
        ] = {}

        raw_values: list[float] = []

        for aliases_for_name in (
            aliases.values()
        ):

            for alias in aliases_for_name:

                if alias not in raw_scores:
                    continue

                try:

                    raw_values.append(
                        float(
                            raw_scores[
                                alias
                            ]
                        )
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    pass

                break

        scale_by_ten = bool(
            raw_values
            and max(raw_values) <= 10.0
        )

        for name, aliases_for_name in (
            aliases.items()
        ):

            value: Any = None

            for alias in aliases_for_name:

                if alias in raw_scores:

                    value = raw_scores[
                        alias
                    ]
                    break

            if scale_by_ten:

                try:

                    value = (
                        float(value)
                        * 10.0
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    pass

            collected[name] = (
                cls._clamp_score(
                    value,
                    75.0,
                )
            )

        overall_value = (
            raw_scores.get("overall")
            if "overall" in raw_scores
            else raw_scores.get(
                "overall_score"
            )
        )

        if scale_by_ten:

            try:

                overall_value = (
                    float(overall_value)
                    * 10.0
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

        overall_fallback = mean(
            collected.values()
        )

        collected["overall"] = (
            cls._clamp_score(
                overall_value,
                overall_fallback,
            )
        )

        return (
            collected,
            False,
            scale_by_ten,
        )

    @classmethod
    def _normalize_review_payload(
        cls,
        payload: dict[str, Any],
    ) -> dict[str, Any]:

        normalized = dict(
            payload
        )

        issues = normalized.get(
            "issues",
            [],
        )

        if not isinstance(
            issues,
            list,
        ):

            issues = []

        normalized_issues: list[
            dict[str, Any]
        ] = []

        for issue in issues:

            if not isinstance(
                issue,
                dict,
            ):

                continue

            normalized_issue = dict(
                issue
            )

            normalized_issue.setdefault(
                "issue_id",
                "",
            )

            normalized_issues.append(
                normalized_issue
            )

        normalized["issues"] = (
            normalized_issues
        )

        (
            scores,
            scores_inferred,
            scores_normalized,
        ) = cls._normalize_scores(
            normalized
        )

        normalized["scores"] = scores
        normalized["scores_inferred"] = (
            scores_inferred
        )
        normalized["scores_normalized"] = (
            scores_normalized
        )

        normalized.pop(
            "quality_scores",
            None,
        )

        return normalized

    @classmethod
    def _parse_review(
        cls,
        content: str,
    ) -> ReviewReport:

        try:

            payload = cls._extract_json_object(
                content
            )

            normalized = (
                cls
                ._normalize_review_payload(
                    payload
                )
            )

            return ReviewReport.model_validate(
                normalized
            )

        except (
            ValidationError,
            ReviewOutputParseError,
        ) as exc:

            raise ReviewOutputParseError(
                str(exc)
            ) from exc

    @staticmethod
    def _tracked_issues_json(
        issues: list[TrackedIssue],
    ) -> str:

        return json.dumps(
            [
                issue.model_dump()
                for issue in issues
            ],
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def _review_instruction(
        cls,
        content: str,
        round_index: int,
        unresolved_issues: list[
            TrackedIssue
        ],
        request: ChapterWorkflowRequest,
    ) -> str:

        unresolved_json = (
            cls._tracked_issues_json(
                unresolved_issues
            )
        )

        return (
            "Review the supplied chapter against "
            "retrieved long-term memory. Return "
            "exactly one JSON object without Markdown "
            "or code fences.\n\n"
            "Score every dimension from 0 to 100. "
            "Use the same issue_id when a previously "
            "tracked issue still exists. Omit an old "
            "issue when it is resolved. Leave issue_id "
            "empty for a newly discovered issue.\n\n"
            "Required JSON schema:\n"
            "{\n"
            '  "approved": true,\n'
            '  "summary": "short review summary",\n'
            '  "scores": {\n'
            '    "continuity": 0,\n'
            '    "character_consistency": 0,\n'
            '    "world_consistency": 0,\n'
            '    "plot_logic": 0,\n'
            '    "prose_quality": 0,\n'
            '    "pacing": 0,\n'
            '    "overall": 0\n'
            "  },\n"
            '  "issues": [\n'
            "    {\n"
            '      "issue_id": "ISSUE-001 or empty",\n'
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
            "contains a confirmed conflict, requires "
            "substantive correction, or does not meet "
            "the configured quality thresholds. Do not "
            "invent missing canon to explain a conflict."
            "\n\n"
            "QUALITY_THRESHOLDS\n"
            f"minimum_overall_score="
            f"{request.minimum_overall_score}\n"
            f"minimum_dimension_score="
            f"{request.minimum_dimension_score}\n"
            "require_all_issues_resolved="
            f"{request.require_all_issues_resolved}\n"
            "QUALITY_THRESHOLDS_END\n\n"
            "PREVIOUS_UNRESOLVED_ISSUES\n"
            + unresolved_json
            + "\nPREVIOUS_UNRESOLVED_ISSUES_END\n\n"
            f"This is review round {round_index}.\n\n"
            "CHAPTER_BEGIN\n"
            + content
            + "\nCHAPTER_END"
        )

    @classmethod
    def _rewrite_instruction(
        cls,
        content: str,
        review: ReviewReport,
        unresolved_issues: list[
            TrackedIssue
        ],
        round_index: int,
        request: ChapterWorkflowRequest,
    ) -> str:

        score_json = json.dumps(
            review.scores.model_dump(),
            ensure_ascii=False,
            indent=2,
        )

        unresolved_json = (
            cls._tracked_issues_json(
                unresolved_issues
            )
        )

        return (
            "Revise the chapter using only the "
            "currently unresolved issues and quality "
            "scores below.\n\n"
            "Rules:\n"
            "1. Correct every listed unresolved issue.\n"
            "2. Improve score dimensions that are below "
            "the configured thresholds.\n"
            "3. Preserve confirmed character, world, "
            "and plot facts.\n"
            "4. Do not create new canon to explain "
            "unsupported statements.\n"
            "5. Preserve the intended scene, style, "
            "point of view, and event outcome.\n"
            "6. Implement at least one concrete textual "
            "change that addresses the review report.\n"
            "7. Do not return the source text unchanged. "
            "The revised output must differ from the "
            "input while preserving confirmed facts.\n"
            "8. Output only the complete revised "
            "chapter.\n"
            f"9. This is revision round {round_index}."
            "\n\n"
            "QUALITY_THRESHOLDS\n"
            f"minimum_overall_score="
            f"{request.minimum_overall_score}\n"
            f"minimum_dimension_score="
            f"{request.minimum_dimension_score}\n"
            "QUALITY_THRESHOLDS_END\n\n"
            "CURRENT_SCORES\n"
            + score_json
            + "\nCURRENT_SCORES_END\n\n"
            "UNRESOLVED_ISSUES\n"
            + unresolved_json
            + "\nUNRESOLVED_ISSUES_END\n\n"
            "DRAFT_BEGIN\n"
            + content
            + "\nDRAFT_END"
        )

    @classmethod
    def _quality_gate_reasons(
        cls,
        report: ReviewReport,
        unresolved_issues: list[
            TrackedIssue
        ],
        request: ChapterWorkflowRequest,
    ) -> list[str]:

        reasons: list[str] = []

        if not report.approved:

            reasons.append(
                "review_not_approved"
            )

        selected_severities = set(
            request.rewrite_on_severities
        )

        for issue in unresolved_issues:

            if (
                issue.severity
                in selected_severities
            ):

                reasons.append(
                    "severity:"
                    f"{issue.issue_id}:"
                    f"{issue.severity}"
                )

        if (
            request
            .require_all_issues_resolved
            and unresolved_issues
        ):

            reasons.append(
                "unresolved_issues"
            )

        if (
            report.scores.overall
            < request.minimum_overall_score
        ):

            reasons.append(
                "overall_score_below_threshold"
            )

        for dimension in (
            cls._score_dimensions
        ):

            value = getattr(
                report.scores,
                dimension,
            )

            if (
                value
                < request
                .minimum_dimension_score
            ):

                reasons.append(
                    "dimension_score_below_threshold:"
                    + dimension
                )

        return list(
            dict.fromkeys(
                reasons
            )
        )

    @staticmethod
    def _context(
        request: ChapterWorkflowRequest,
        *,
        grounding: ChapterWorkflowGrounding | None,
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

        messages: list[ChatMessage] = []
        if grounding is not None:
            metadata.update(grounding.metadata)
            messages.append(
                ChatMessage(
                    role="system",
                    content=grounding.message,
                    metadata={
                        "source": "chapter_plan_grounding",
                        "priority": "P0.3",
                    },
                )
            )

        return AgentContext.model_validate(
            {
                "user_id": request.user_id,
                "novel_id": request.novel_id,
                "instruction": instruction,
                "provider": request.provider,
                "model": request.model,
                "messages": messages,
                "use_memory": (
                    request.use_memory
                ),
                "task_mode": (
                    "grounded"
                    if grounding is not None
                    else "creative"
                ),
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
        grounding: ChapterWorkflowGrounding | None,
        current_content: str,
        review_round: int,
        unresolved_issues: list[
            TrackedIssue
        ],
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
                            grounding=grounding,
                            instruction=(
                                self
                                ._review_instruction(
                                    current_content,
                                    review_round,
                                    unresolved_issues,
                                    request,
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

            output_truncated = (
                review_step.finish_reason
                == "length"
            )
            review_step.metadata[
                "review_output_truncated"
            ] = output_truncated

            if (
                review_step.success
                and review_step.content.strip()
                and not output_truncated
            ):

                return (
                    attempt_steps,
                    review_step,
                    None,
                )

            if output_truncated:
                last_error = (
                    "ReviewAgent output was truncated "
                    "(finish_reason=length)."
                )
            else:
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
        quality_tracker: QualityTracker,
        revision_diffs: list[
            RevisionDiffSummary
        ],
        quality_gate_reasons: list[str],
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

        unresolved = (
            quality_tracker.unresolved()
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
            quality_scores=(
                latest_review.scores
                if latest_review
                else None
            ),
            quality_score_history=[
                report.scores
                for report in review_history
            ],
            issue_tracker=(
                quality_tracker.all_issues()
            ),
            issue_transitions=(
                quality_tracker.transitions()
            ),
            unresolved_issue_ids=[
                issue.issue_id
                for issue in unresolved
            ],
            quality_gate_reasons=(
                quality_gate_reasons
            ),
            revision_diffs=revision_diffs,
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

        grounding = (
            self._grounding_service.resolve(request)
            if self._grounding_service.has_binding(request)
            else None
        )

        steps: list[WorkflowStep] = []
        review_history: list[
            ReviewReport
        ] = []
        review_raw_history: list[str] = []
        revision_diffs: list[
            RevisionDiffSummary
        ] = []
        revision_rounds = 0
        quality_tracker = QualityTracker()
        quality_gate_reasons: list[str] = []

        def finish(
            *,
            status: str,
            draft: str,
            current_content: str,
            quality_gate_passed: bool,
            metadata: dict[str, Any],
        ) -> ChapterWorkflowResult:

            result_metadata = (
                dict(grounding.metadata)
                if grounding is not None
                else {}
            )
            result_metadata.update(metadata)

            return self._result(
                status=status,
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
                quality_gate_passed=(
                    quality_gate_passed
                ),
                metadata=result_metadata,
                quality_tracker=(
                    quality_tracker
                ),
                revision_diffs=(
                    revision_diffs
                ),
                quality_gate_reasons=(
                    quality_gate_reasons
                ),
            )

        try:

            draft_result = (
                await self
                ._agent_manager
                .execute(
                    agent_name="chapter",
                    context=self._context(
                        request,
                        grounding=grounding,
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

            return finish(
                status="draft_failed",
                draft="",
                current_content="",
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

            return finish(
                status="draft_failed",
                draft=draft,
                current_content=draft,
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

            previous_unresolved = (
                quality_tracker.unresolved()
            )

            (
                review_attempt_steps,
                review_step,
                review_error,
            ) = await self._execute_review_with_retry(
                request,
                grounding,
                current_content,
                review_round,
                previous_unresolved,
            )

            steps.extend(
                review_attempt_steps
            )

            if review_step is None:

                return finish(
                    status="review_failed",
                    draft=draft,
                    current_content=(
                        current_content
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

                return finish(
                    status=(
                        "review_parse_failed"
                    ),
                    draft=draft,
                    current_content=(
                        current_content
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

            review_report = (
                quality_tracker.apply_review(
                    review_report,
                    review_round,
                )
            )

            review_history.append(
                review_report
            )

            unresolved_issues = (
                quality_tracker.unresolved()
            )

            quality_gate_reasons = (
                self._quality_gate_reasons(
                    review_report,
                    unresolved_issues,
                    request,
                )
            )

            if not quality_gate_reasons:

                return finish(
                    status="completed",
                    draft=draft,
                    current_content=(
                        current_content
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
                        "minimum_overall_score": (
                            request
                            .minimum_overall_score
                        ),
                        "minimum_dimension_score": (
                            request
                            .minimum_dimension_score
                        ),
                    },
                )

            if not request.auto_rewrite:

                return finish(
                    status="completed",
                    draft=draft,
                    current_content=(
                        current_content
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

                return finish(
                    status=(
                        "max_revisions_reached"
                    ),
                    draft=draft,
                    current_content=(
                        current_content
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
                            grounding=grounding,
                            instruction=(
                                self
                                ._rewrite_instruction(
                                    current_content,
                                    review_report,
                                    unresolved_issues,
                                    next_revision_round,
                                    request,
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

                return finish(
                    status="rewrite_failed",
                    draft=draft,
                    current_content=(
                        current_content
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

                return finish(
                    status="rewrite_failed",
                    draft=draft,
                    current_content=(
                        current_content
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

            revision_diff = (
                build_revision_diff(
                    before=current_content,
                    after=revised_content,
                    round_index=(
                        next_revision_round
                    ),
                )
            )

            revision_diffs.append(
                revision_diff
            )

            fingerprint = (
                self._content_fingerprint(
                    revised_content
                )
            )

            if fingerprint in seen_fingerprints:

                return finish(
                    status=(
                        "stagnation_detected"
                    ),
                    draft=draft,
                    current_content=(
                        current_content
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
