from fastapi import APIRouter

from app.prompts.bootstrap import prompt_registry
from app.prompts.schemas import PromptCatalogData, PromptCatalogResponse


router = APIRouter()


@router.get("/prompts", response_model=PromptCatalogResponse)
async def prompts() -> PromptCatalogResponse:
    return PromptCatalogResponse(
        data=PromptCatalogData(
            prompts=prompt_registry.list(),
        )
    )
