from app.plugins.runtime import PluginRuntimeManager
from app.plugins.service import PluginCatalogService


plugin_catalog_service = PluginCatalogService()
plugin_runtime_manager = PluginRuntimeManager(plugin_catalog_service)
