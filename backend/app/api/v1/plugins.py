from fastapi import APIRouter

from app.plugins.bootstrap import plugin_runtime_manager
from app.plugins.schemas import PluginCatalogResponse


router = APIRouter()


@router.get("/plugins", response_model=PluginCatalogResponse)
async def plugins() -> PluginCatalogResponse:
    return PluginCatalogResponse(data=plugin_runtime_manager.catalog())
