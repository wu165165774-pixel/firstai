from __future__ import annotations

import re

from difflib import SequenceMatcher

from app.workflows.schemas import (
    IssueTransition,
    ReviewIssue,
    ReviewReport,
    RevisionDiffSummary,
    TrackedIssue,
)


class QualityTracker:
    """
    Track review issues across multiple rounds.
    """

    def __init__(
        self,
    ) -> None:

        self._issues: dict[
            str,
            TrackedIssue,
        ] = {}

        self._transitions: list[
            IssueTransition
        ] = []

        self._next_issue_number = 1

    @staticmethod
    def _normalize_text(
        value: str,
    ) -> str:

        return re.sub(
            r"\s+",
            " ",
            value.strip().lower(),
        )

    @classmethod
    def _issue_signature(
        cls,
        issue: ReviewIssue,
    ) -> str:

        return "|".join(
            [
                cls._normalize_text(
                    issue.category
                ),
                cls._normalize_text(
                    issue.issue
                ),
                cls._normalize_text(
                    issue.recommendation
                ),
            ]
        )

    @classmethod
    def _tracked_signature(
        cls,
        issue: TrackedIssue,
    ) -> str:

        return "|".join(
            [
                cls._normalize_text(
                    issue.category
                ),
                cls._normalize_text(
                    issue.issue
                ),
                cls._normalize_text(
                    issue.recommendation
                ),
            ]
        )

    def _new_issue_id(
        self,
    ) -> str:

        issue_id = (
            f"ISSUE-{self._next_issue_number:03d}"
        )

        self._next_issue_number += 1

        return issue_id

    def _match_issue_id(
        self,
        issue: ReviewIssue,
    ) -> str | None:

        requested_id = (
            issue.issue_id.strip()
        )

        if (
            requested_id
            and requested_id in self._issues
        ):

            return requested_id

        signature = self._issue_signature(
            issue
        )

        for tracked in self._issues.values():

            if (
                self._tracked_signature(
                    tracked
                )
                == signature
            ):

                return tracked.issue_id

        best_issue_id: str | None = None
        best_ratio = 0.0

        normalized_category = (
            self._normalize_text(
                issue.category
            )
        )

        for tracked in self._issues.values():

            if (
                self._normalize_text(
                    tracked.category
                )
                != normalized_category
            ):

                continue

            ratio = SequenceMatcher(
                None,
                self._normalize_text(
                    issue.issue
                ),
                self._normalize_text(
                    tracked.issue
                ),
            ).ratio()

            if ratio > best_ratio:

                best_ratio = ratio
                best_issue_id = (
                    tracked.issue_id
                )

        if best_ratio >= 0.72:

            return best_issue_id

        return None

    def apply_review(
        self,
        report: ReviewReport,
        round_index: int,
    ) -> ReviewReport:

        active_ids: set[str] = set()

        for issue in report.issues:

            issue_id = (
                self._match_issue_id(
                    issue
                )
                or self._new_issue_id()
            )

            issue.issue_id = issue_id
            active_ids.add(
                issue_id
            )

            existing = self._issues.get(
                issue_id
            )

            if existing is None:

                self._issues[
                    issue_id
                ] = TrackedIssue(
                    issue_id=issue_id,
                    status="open",
                    first_seen_round=(
                        round_index
                    ),
                    last_seen_round=(
                        round_index
                    ),
                    severity=issue.severity,
                    category=issue.category,
                    issue=issue.issue,
                    evidence=issue.evidence,
                    impact=issue.impact,
                    recommendation=(
                        issue.recommendation
                    ),
                )

                self._transitions.append(
                    IssueTransition(
                        issue_id=issue_id,
                        round_index=(
                            round_index
                        ),
                        transition="new",
                        note=(
                            "Issue first observed."
                        ),
                    )
                )

                continue

            transition = (
                "reopened"
                if existing.status
                == "resolved"
                else "persisting"
            )

            existing.status = "open"
            existing.last_seen_round = (
                round_index
            )
            existing.severity = (
                issue.severity
            )
            existing.category = (
                issue.category
            )
            existing.issue = issue.issue
            existing.evidence = (
                issue.evidence
            )
            existing.impact = issue.impact
            existing.recommendation = (
                issue.recommendation
            )
            existing.resolution_note = ""

            self._transitions.append(
                IssueTransition(
                    issue_id=issue_id,
                    round_index=round_index,
                    transition=transition,
                    note=(
                        "Issue remains present."
                        if transition
                        == "persisting"
                        else (
                            "Previously resolved "
                            "issue reappeared."
                        )
                    ),
                )
            )

        for tracked in self._issues.values():

            if (
                tracked.status == "open"
                and tracked.issue_id
                not in active_ids
            ):

                tracked.status = "resolved"
                tracked.last_seen_round = (
                    round_index
                )
                tracked.resolution_note = (
                    "Not reported in review "
                    f"round {round_index}."
                )

                self._transitions.append(
                    IssueTransition(
                        issue_id=(
                            tracked.issue_id
                        ),
                        round_index=(
                            round_index
                        ),
                        transition="resolved",
                        note=(
                            tracked
                            .resolution_note
                        ),
                    )
                )

        return report

    def unresolved(
        self,
    ) -> list[TrackedIssue]:

        return sorted(
            [
                issue.model_copy(
                    deep=True
                )
                for issue
                in self._issues.values()
                if issue.status == "open"
            ],
            key=lambda item: item.issue_id,
        )

    def all_issues(
        self,
    ) -> list[TrackedIssue]:

        return sorted(
            [
                issue.model_copy(
                    deep=True
                )
                for issue
                in self._issues.values()
            ],
            key=lambda item: item.issue_id,
        )

    def transitions(
        self,
    ) -> list[IssueTransition]:

        return [
            transition.model_copy(
                deep=True
            )
            for transition
            in self._transitions
        ]


def build_revision_diff(
    *,
    before: str,
    after: str,
    round_index: int,
) -> RevisionDiffSummary:

    matcher = SequenceMatcher(
        None,
        before,
        after,
    )

    added = 0
    removed = 0
    replaced = 0

    for (
        tag,
        before_start,
        before_end,
        after_start,
        after_end,
    ) in matcher.get_opcodes():

        before_size = (
            before_end
            - before_start
        )

        after_size = (
            after_end
            - after_start
        )

        if tag == "insert":

            added += after_size

        elif tag == "delete":

            removed += before_size

        elif tag == "replace":

            replaced += max(
                before_size,
                after_size,
            )

    changed = before != after

    summary = (
        f"Round {round_index}: "
        f"added {added}, "
        f"removed {removed}, "
        f"replaced {replaced} characters; "
        f"similarity {matcher.ratio():.4f}."
    )

    return RevisionDiffSummary(
        round_index=round_index,
        changed=changed,
        before_length=len(before),
        after_length=len(after),
        added_characters=added,
        removed_characters=removed,
        replaced_characters=replaced,
        similarity_ratio=matcher.ratio(),
        summary=summary,
    )
