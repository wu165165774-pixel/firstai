from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.workflows.chapter_workflow import (
    ChapterWorkflow,
)
from app.workflows.grounding import (
    ChapterWorkflowGroundingService,
    chapter_workflow_grounding_service,
)
from app.workflows.run_schemas import (
    WorkflowRunDetail,
    WorkflowRunSummary,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
)
from app.workflows.storage import (
    WorkflowRunStorage,
)


RESUME_OVERRIDE_FIELDS = {
    "provider",
    "model",
    "use_memory",
    "auto_rewrite",
    "max_revision_rounds",
    "review_retry_attempts",
    "review_retry_reasoning_effort",
    "chapter_reasoning_effort",
    "review_reasoning_effort",
    "rewrite_reasoning_effort",
    "chapter_temperature",
    "review_temperature",
    "rewrite_temperature",
    "chapter_max_tokens",
    "review_max_tokens",
    "rewrite_max_tokens",
    "rewrite_on_severities",
    "minimum_overall_score",
    "minimum_dimension_score",
    "require_all_issues_resolved",
    "metadata",
}


class CheckpointAgentManager:
    """
    Inject a stored checkpoint as the
    chapter stage, then delegate all later
    stages to the real AgentManager.
    """

    def __init__(
        self,
        delegate: Any,
        checkpoint_content: str,
        source_run_id: str,
    ) -> None:

        self._delegate = delegate

        self._checkpoint_content = (
            checkpoint_content
        )

        self._source_run_id = (
            source_run_id
        )

        self._checkpoint_used = False

    async def execute(
        self,
        *,
        agent_name: str,
        context: Any,
    ) -> Any:

        if (
            agent_name == "chapter"
            and not self._checkpoint_used
        ):

            self._checkpoint_used = True

            return SimpleNamespace(
                agent="checkpoint",
                success=True,
                content=(
                    self
                    ._checkpoint_content
                ),
                provider=(
                    "workflow_checkpoint"
                ),
                model="stored-content",
                finish_reason=(
                    "checkpoint"
                ),
                usage=SimpleNamespace(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                ),
                latency_ms=0.0,
                metadata={
                    "checkpoint": True,
                    "source_run_id": (
                        self
                        ._source_run_id
                    ),
                    "reasoning_effort": (
                        "none"
                    ),
                },
            )

        return await self._delegate.execute(
            agent_name=agent_name,
            context=context,
        )


class WorkflowRunService:

    def __init__(
        self,
        agent_manager: Any,
        storage: WorkflowRunStorage,
        grounding_service: ChapterWorkflowGroundingService | None = None,
    ) -> None:

        self._agent_manager = (
            agent_manager
        )

        self._storage = storage
        self._grounding_service = (
            grounding_service
            or chapter_workflow_grounding_service
        )

    @staticmethod
    def _detail(
        value: dict[str, Any],
    ) -> WorkflowRunDetail:

        return (
            WorkflowRunDetail
            .model_validate(
                value
            )
        )

    @staticmethod
    def _summary(
        value: dict[str, Any],
    ) -> WorkflowRunSummary:

        return (
            WorkflowRunSummary
            .model_validate(
                value
            )
        )

    async def start(
        self,
        request: ChapterWorkflowRequest,
    ) -> WorkflowRunDetail:

        created = (
            self._storage.create_run(
                request
            )
        )

        run_id = created["run_id"]

        try:

            result = await ChapterWorkflow(
                self._agent_manager,
                grounding_service=self._grounding_service,
            ).run(
                request
            )

            stored = (
                self
                ._storage
                .finalize_run(
                    run_id,
                    result,
                )
            )

            return self._detail(
                stored
            )

        except Exception as exc:

            self._storage.fail_run(
                run_id,
                str(exc),
            )

            raise

    async def resume(
        self,
        run_id: str,
        request_overrides: dict[
            str,
            Any,
        ],
    ) -> WorkflowRunDetail:

        parent = (
            self._storage.get_run(
                run_id
            )
        )

        if not parent["resumable"]:

            raise ValueError(
                "Workflow run is not "
                "resumable."
            )

        checkpoint_content = (
            parent[
                "latest_content"
            ]
            or ""
        )

        if not checkpoint_content.strip():

            raise ValueError(
                "Workflow run has no valid "
                "checkpoint content."
            )

        unknown_fields = (
            set(
                request_overrides
            )
            - RESUME_OVERRIDE_FIELDS
        )

        if unknown_fields:

            joined = ", ".join(
                sorted(
                    unknown_fields
                )
            )

            raise ValueError(
                "Unsupported resume "
                "override fields: "
                + joined
            )

        request_payload = dict(
            parent["request"]
        )

        original_metadata = dict(
            request_payload.get(
                "metadata"
            )
            or {}
        )

        override_metadata = dict(
            request_overrides.get(
                "metadata"
            )
            or {}
        )

        request_payload.update(
            {
                key: value
                for key, value
                in request_overrides.items()
                if key != "metadata"
            }
        )

        original_metadata.update(
            override_metadata
        )

        original_metadata.update(
            {
                "resumed_from_run_id": (
                    run_id
                ),
                "root_run_id": (
                    parent[
                        "root_run_id"
                    ]
                ),
                "checkpoint_content_length": (
                    len(
                        checkpoint_content
                    )
                ),
            }
        )

        request_payload["metadata"] = (
            original_metadata
        )

        resume_request = (
            ChapterWorkflowRequest
            .model_validate(
                request_payload
            )
        )

        created = (
            self._storage.create_run(
                resume_request,
                parent_run_id=run_id,
                root_run_id=(
                    parent[
                        "root_run_id"
                    ]
                ),
            )
        )

        child_run_id = (
            created["run_id"]
        )

        checkpoint_manager = (
            CheckpointAgentManager(
                self._agent_manager,
                checkpoint_content,
                run_id,
            )
        )

        try:

            result = await ChapterWorkflow(
                checkpoint_manager,
                grounding_service=self._grounding_service,
            ).run(
                resume_request
            )

            stored = (
                self
                ._storage
                .finalize_run(
                    child_run_id,
                    result,
                )
            )

            return self._detail(
                stored
            )

        except Exception as exc:

            self._storage.fail_run(
                child_run_id,
                str(exc),
            )

            raise

    def get(
        self,
        run_id: str,
    ) -> WorkflowRunDetail:

        return self._detail(
            self._storage.get_run(
                run_id
            )
        )

    def list(
        self,
        *,
        user_id: str | None = None,
        novel_id: str | None = None,
        root_run_id: str | None = None,
        limit: int = 50,
    ) -> list[
        WorkflowRunSummary
    ]:

        return [
            self._summary(
                item
            )
            for item
            in self._storage.list_runs(
                user_id=user_id,
                novel_id=novel_id,
                root_run_id=(
                    root_run_id
                ),
                limit=limit,
            )
        ]
