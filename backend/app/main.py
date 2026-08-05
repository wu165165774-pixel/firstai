from fastapi import FastAPI


from app.config.settings import settings

from app.api.health import router as health_router


from app.core.middleware import RequestLogMiddleware

from app.core.exceptions import NovelForgeException
from app.api.v1.memory import router as memory_router

from app.core.exception_handler import (
    novelforge_exception_handler
)



app = FastAPI(

    title=settings.app_name,

    version="0.2.0"

)



app.add_middleware(
    RequestLogMiddleware
)



app.add_exception_handler(
    NovelForgeException,
    novelforge_exception_handler
)



app.include_router(

    health_router,

    prefix="/api/v1",

    tags=["System"]

)



from app.api.v1.chat import router as chat_router
from app.api.v1.providers import router as provider_router



app.include_router(
    chat_router,
    prefix="/api/v1",
    tags=["LLM"]
)



app.include_router(
    provider_router,
    prefix="/api/v1",
    tags=["LLM"]
)

app.include_router(
    memory_router,
    prefix="/api/v1",
    tags=["Memory"]
)
