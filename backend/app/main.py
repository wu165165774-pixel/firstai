from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.api.health import router as health_router
from app.api.v1.agents import router as agent_router
from app.api.v1.chat import router as chat_router
from app.api.v1.memory import router as memory_router
from app.api.v1.providers import router as provider_router
from app.api.v1.workflows import router as workflow_router
from app.config.settings import settings
from app.core.exception_handler import novelforge_exception_handler
from app.core.exceptions import NovelForgeException
from app.core.middleware import RequestLogMiddleware
from app.rag.consistency import memory_index_consistency_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run NovelForge startup and shutdown tasks."""

    try:
        result = await memory_index_consistency_service.check_and_repair()

        if result.consistent:
            logger.info(
                "Memory index startup check complete: "
                f"sqlite_count={result.sqlite_count}, "
                f"faiss_count={result.faiss_count_after}, "
                f"rebuilt={result.rebuilt}"
            )
        else:
            logger.error(
                "Memory index startup check failed: "
                f"sqlite_count={result.sqlite_count}, "
                f"faiss_count={result.faiss_count_after}, "
                f"error={result.error}"
            )

    except Exception:
        logger.exception(
            "Unexpected memory index startup check failure. "
            "Backend will continue using SQLite."
        )

    yield


app = FastAPI(
    title=settings.app_name,
    version="0.15.0-alpha.12",
    lifespan=lifespan,
)

app.add_middleware(RequestLogMiddleware)

app.add_exception_handler(
    NovelForgeException,
    novelforge_exception_handler,
)

app.include_router(
    health_router,
    prefix="/api/v1",
    tags=["System"],
)

app.include_router(
    chat_router,
    prefix="/api/v1",
    tags=["LLM"],
)

app.include_router(
    provider_router,
    prefix="/api/v1",
    tags=["LLM"],
)

app.include_router(
    memory_router,
    prefix="/api/v1",
    tags=["Memory"],
)

app.include_router(
    agent_router,
    prefix="/api/v1",
    tags=["Agents"],
)

app.include_router(
    workflow_router,
    prefix="/api/v1",
    tags=["Workflows"],
)

from app.api.v1.novels import router as novel_router

app.include_router(
    novel_router,
    prefix="/api/v1",
    tags=["Novel Planning"],
)
