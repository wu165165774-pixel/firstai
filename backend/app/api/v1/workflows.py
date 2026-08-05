from fastapi import APIRouter

from app.workflows import (
    ChapterWorkflowRequest,
    ChapterWorkflowResponse,
    chapter_workflow,
)


router = APIRouter(
    prefix="/workflows"
)


@router.post(
    "/chapter",
    response_model=ChapterWorkflowResponse,
)
async def run_chapter_workflow(
    request: ChapterWorkflowRequest,
) -> ChapterWorkflowResponse:
    """
    Generate, review, and optionally rewrite
    a complete novel chapter.
    """

    result = await chapter_workflow.run(
        request
    )

    return ChapterWorkflowResponse(
        data=result
    )
