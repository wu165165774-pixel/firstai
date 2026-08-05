from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from loguru import logger

from app.rag.embedding import (
    OllamaEmbeddingClient,
    embedding_client,
)

from app.rag.faiss_store import (
    FaissSearchResult,
    PersistentFaissStore,
    faiss_store,
)


@dataclass(frozen=True)
class MemorySemanticHit:

    memory_id: str
    similarity: float


class MemoryIndexer:

    def __init__(
        self,
        embeddings: OllamaEmbeddingClient,
        vector_store: PersistentFaissStore,
    ) -> None:

        self.embeddings = embeddings
        self.vector_store = vector_store

    async def upsert(
        self,
        memory_id: str,
        content: str,
    ) -> int:

        memory_id = str(
            memory_id
        ).strip()

        content = str(
            content
        ).strip()

        if not memory_id:

            raise ValueError(
                "memory_id must not be empty."
            )

        if not content:

            raise ValueError(
                "Memory content must not be empty."
            )

        vector = await self.embeddings.embed_text(
            content
        )

        vector_id = await asyncio.to_thread(
            self.vector_store.upsert,
            memory_id,
            vector,
        )

        logger.info(
            "Memory indexed in FAISS: "
            f"memory_id={memory_id}, "
            f"vector_id={vector_id}"
        )

        return vector_id

    async def upsert_memory(
        self,
        memory: Any,
    ) -> int:

        memory_id = getattr(
            memory,
            "id",
            None,
        )

        content = getattr(
            memory,
            "content",
            None,
        )

        if memory_id is None:

            raise ValueError(
                "Memory object has no id."
            )

        return await self.upsert(
            str(memory_id),
            str(content or ""),
        )

    async def remove(
        self,
        memory_id: str,
    ) -> bool:

        return await asyncio.to_thread(
            self.vector_store.remove,
            str(memory_id),
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.30,
    ) -> list[MemorySemanticHit]:

        query = str(
            query
        ).strip()

        if not query or top_k <= 0:
            return []

        query_vector = (
            await self.embeddings.embed_text(
                query
            )
        )

        matches: list[
            FaissSearchResult
        ] = await asyncio.to_thread(
            self.vector_store.search,
            query_vector,
            top_k,
        )

        return [
            MemorySemanticHit(
                memory_id=match.memory_id,
                similarity=match.similarity,
            )
            for match in matches
            if match.similarity >= min_similarity
        ]

    async def rebuild(
        self,
        memories: Iterable[
            tuple[str, str]
        ],
    ) -> int:

        prepared: list[
            tuple[str, str]
        ] = []

        seen_ids: set[str] = set()

        for memory_id, content in memories:

            normalized_id = str(
                memory_id
            ).strip()

            normalized_content = str(
                content
            ).strip()

            if (
                not normalized_id
                or not normalized_content
                or normalized_id in seen_ids
            ):
                continue

            seen_ids.add(
                normalized_id
            )

            prepared.append(
                (
                    normalized_id,
                    normalized_content,
                )
            )

        if not prepared:

            empty_vectors = np.empty(
                (
                    0,
                    self.vector_store.dimension,
                ),
                dtype=np.float32,
            )

            return await asyncio.to_thread(
                self.vector_store.rebuild,
                [],
                empty_vectors,
            )

        memory_ids = [
            memory_id
            for memory_id, _
            in prepared
        ]

        contents = [
            content
            for _, content
            in prepared
        ]

        vectors = (
            await self.embeddings.embed_texts(
                contents
            )
        )

        count = await asyncio.to_thread(
            self.vector_store.rebuild,
            memory_ids,
            vectors,
        )

        logger.info(
            "Memory index rebuild complete: "
            f"count={count}"
        )

        return count

    def stats(
        self,
    ) -> dict[str, Any]:

        return self.vector_store.stats()


memory_indexer = MemoryIndexer(
    embeddings=embedding_client,
    vector_store=faiss_store,
)