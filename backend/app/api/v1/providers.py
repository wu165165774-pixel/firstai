from fastapi import APIRouter, Query

from app.llm.bootstrap import llm_manager, registry
from app.llm.schemas import ProviderCatalogData, ProviderCatalogResponse


router = APIRouter()


@router.get("/providers", response_model=ProviderCatalogResponse)
async def providers(
    probe: bool = False,
    timeout_ms: int = Query(default=3000, ge=100, le=30000),
) -> ProviderCatalogResponse:

    catalog = await llm_manager.provider_status(
        probe=probe,
        timeout_ms=timeout_ms,
    )
    return ProviderCatalogResponse(
        data=ProviderCatalogData(
            providers=registry.list(),
            catalog=catalog,
            probed=probe,
        )
    )
