from __future__ import annotations

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)

from app.agents.bootstrap import (
    agent_manager as bootstrap_agent_manager,
)

from app.workflows.async_executor import (
    AsyncWorkflowExecutor,
)

from app.workflows.chapter_workflow import (
    ChapterWorkflow,
)
from app.workflows.run_schemas import (
    WorkflowAsyncSubmissionResponse,
    WorkflowResumeRequest,
    WorkflowRunListResponse,
    WorkflowRunResponse,
)
from app.workflows.run_service import (
    WorkflowRunService,
)
from app.workflows.schemas import (
    ChapterWorkflowRequest,
    ChapterWorkflowResponse,
)
from app.workflows.storage import (
    WorkflowRunStorage,
)


router = APIRouter(
    prefix="/workflows",
    tags=[
        "Workflows",
    ],
)


_async_executor_instance: (
    AsyncWorkflowExecutor
    | None
) = None


def _async_executor(
    request: Request,
) -> AsyncWorkflowExecutor:

    global _async_executor_instance

    _ = request

    if _async_executor_instance is None:

        _async_executor_instance = (
            AsyncWorkflowExecutor(
                bootstrap_agent_manager
            )
        )

    _async_executor_instance.ensure_started()

    return _async_executor_instance


def _agent_manager(
    request: Request,
):

    _ = request

    return bootstrap_agent_manager


def _run_service(
    request: Request,
) -> WorkflowRunService:

    return WorkflowRunService(
        _agent_manager(
            request
        ),
        WorkflowRunStorage(),
    )


@router.post(
    "/chapter",
    response_model=(
        ChapterWorkflowResponse
    ),
)
async def execute_chapter_workflow(
    payload: ChapterWorkflowRequest,
    request: Request,
) -> ChapterWorkflowResponse:

    workflow = ChapterWorkflow(
        _agent_manager(
            request
        )
    )

    result = await workflow.run(
        payload
    )

    return ChapterWorkflowResponse(
        data=result
    )


@router.post(
    "/chapter/runs",
    response_model=WorkflowRunResponse,
)
async def create_chapter_workflow_run(
    payload: ChapterWorkflowRequest,
    request: Request,
) -> WorkflowRunResponse:

    detail = await _run_service(
        request
    ).start(
        payload
    )

    return WorkflowRunResponse(
        data=detail
    )


@router.get(
    "/runs",
    response_model=(
        WorkflowRunListResponse
    ),
)
async def list_workflow_runs(
    request: Request,
    user_id: str | None = None,
    novel_id: str | None = None,
    root_run_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
) -> WorkflowRunListResponse:

    items = _run_service(
        request
    ).list(
        user_id=user_id,
        novel_id=novel_id,
        root_run_id=root_run_id,
        limit=limit,
    )

    return WorkflowRunListResponse(
        data=items
    )


@router.get(
    "/runs/{run_id}",
    response_model=WorkflowRunResponse,
)
async def get_workflow_run(
    run_id: str,
    request: Request,
) -> WorkflowRunResponse:

    try:

        detail = _run_service(
            request
        ).get(
            run_id
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=(
                status
                .HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    return WorkflowRunResponse(
        data=detail
    )


@router.post(
    "/runs/{run_id}/resume",
    response_model=WorkflowRunResponse,
)
async def resume_workflow_run(
    run_id: str,
    payload: WorkflowResumeRequest,
    request: Request,
) -> WorkflowRunResponse:

    try:

        detail = await _run_service(
            request
        ).resume(
            run_id,
            payload.request_overrides,
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=(
                status
                .HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except ValueError as exc:

        raise HTTPException(
            status_code=(
                status
                .HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc

    return WorkflowRunResponse(
        data=detail
    )

@router.post(
    "/chapter/runs/async",
    response_model=(
        WorkflowAsyncSubmissionResponse
    ),
    status_code=(
        status.HTTP_202_ACCEPTED
    ),
)
async def enqueue_chapter_workflow_run(
    payload: ChapterWorkflowRequest,
    request: Request,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
) -> WorkflowAsyncSubmissionResponse:

    executor = _async_executor(
        request
    )

    try:

        submission = await executor.submit(
            payload,
            idempotency_key=(
                idempotency_key
            ),
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=(
                status
                .HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc

    return WorkflowAsyncSubmissionResponse(
        data=submission
    )


@router.get(
    "/runs/{run_id}/control",
    response_model=(
        WorkflowAsyncSubmissionResponse
    ),
)
async def get_workflow_run_control(
    run_id: str,
    request: Request,
) -> WorkflowAsyncSubmissionResponse:

    executor = _async_executor(
        request
    )

    try:

        submission = (
            executor.get_submission(
                run_id
            )
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=(
                status
                .HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    return WorkflowAsyncSubmissionResponse(
        data=submission
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=(
        WorkflowAsyncSubmissionResponse
    ),
)
async def cancel_workflow_run(
    run_id: str,
    request: Request,
) -> WorkflowAsyncSubmissionResponse:

    executor = _async_executor(
        request
    )

    try:

        submission = await executor.cancel(
            run_id
        )

    except KeyError as exc:

        raise HTTPException(
            status_code=(
                status
                .HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    return WorkflowAsyncSubmissionResponse(
        data=submission
    )
