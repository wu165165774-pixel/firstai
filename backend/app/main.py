from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.api.health import router as health_router
from app.api.v1.agents import router as agent_router
from app.api.v1.chat import router as chat_router
from app.api.v1.consistency import router as consistency_router
from app.api.v1.external_knowledge import router as external_knowledge_router
from app.api.v1.memory import router as memory_router
from app.api.v1.retrieval import router as retrieval_router
from app.api.v1.temporal_graph import router as temporal_graph_router
from app.api.v1.providers import router as provider_router
from app.api.v1.workflows import router as workflow_router
from app.config.settings import settings
from app.core.exception_handler import novelforge_exception_handler
from app.core.exceptions import NovelForgeException
from app.core.middleware import RequestLogMiddleware
from app.fact_projection.service import fact_projection_service
from app.rag.consistency import memory_index_consistency_service
from app.knowledge.manager import external_knowledge_manager


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

    try:
        result = await external_knowledge_manager.check_and_repair_index()
        logger.info(
            "External knowledge index startup check complete: "
            f"sqlite_count={result.sqlite_count}, "
            f"faiss_count={result.faiss_count_after}, "
            f"rebuilt={result.rebuilt}, "
            f"consistent={result.consistent}"
        )
    except Exception:
        logger.exception(
            "Unexpected external knowledge index startup check failure. "
            "Backend will continue using authoritative SQLite data."
        )

    try:
        recovered = await fact_projection_service.recover_incomplete(
            limit=1000
        )
        logger.info(
            "Accepted fact projection startup recovery complete: "
            f"processed={recovered}"
        )
    except Exception:
        logger.exception(
            "Unexpected accepted fact projection recovery failure. "
            "Backend will continue; pending projections remain retryable."
        )

    yield


app = FastAPI(
    title=settings.app_name,
    version="0.15.0-alpha.30",
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
    retrieval_router,
    prefix="/api/v1",
    tags=["Retrieval"],
)

app.include_router(
    temporal_graph_router,
    prefix="/api/v1",
    tags=["Temporal Graph"],
)

app.include_router(
    consistency_router,
    prefix="/api/v1",
    tags=["Consistency"],
)

app.include_router(
    external_knowledge_router,
    prefix="/api/v1",
    tags=["External Knowledge"],
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

from app.api.v1.planner import router as planner_router

app.include_router(
    planner_router,
    prefix="/api/v1",
    tags=["Planner"],
)

from app.api.v1.manuscripts import router as manuscript_router

app.include_router(
    manuscript_router,
    prefix="/api/v1",
    tags=["Manuscript"],
)

from app.api.v1.orchestrations import router as orchestration_router

app.include_router(
    orchestration_router,
    prefix="/api/v1",
    tags=["Orchestrator"],
)
