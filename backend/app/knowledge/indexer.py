from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from app.rag.embedding import OllamaEmbeddingClient, embedding_client
from app.rag.faiss_store import PersistentFaissStore


@dataclass(frozen=True, slots=True)
class ExternalKnowledgeSemanticHit:
    chunk_id: str
    similarity: float


class ExternalKnowledgeIndexer:
    EMBEDDING_BATCH_SIZE = 32

    def __init__(
        self,
        embeddings: OllamaEmbeddingClient,
        vector_store: PersistentFaissStore,
    ) -> None:
        self.embeddings = embeddings
        self.vector_store = vector_store

    async def upsert_chunks(
        self,
        chunks: Iterable[tuple[str, str]],
    ) -> int:
        prepared = [
            (str(chunk_id).strip(), str(content).strip())
            for chunk_id, content in chunks
            if str(chunk_id).strip() and str(content).strip()
        ]
        if not prepared:
            return 0

        count = 0
        for start in range(0, len(prepared), self.EMBEDDING_BATCH_SIZE):
            batch = prepared[start : start + self.EMBEDDING_BATCH_SIZE]
            vectors = await self.embeddings.embed_texts(
                [content for _, content in batch]
            )
            count += await asyncio.to_thread(
                self.vector_store.upsert_many,
                [chunk_id for chunk_id, _ in batch],
                vectors,
            )
        return count

    async def remove_chunks(self, chunk_ids: Iterable[str]) -> int:
        removed = 0
        for chunk_id in dict.fromkeys(str(item) for item in chunk_ids):
            if await asyncio.to_thread(self.vector_store.remove, chunk_id):
                removed += 1
        return removed

    async def search(
        self,
        query: str,
        top_k: int,
    ) -> list[ExternalKnowledgeSemanticHit]:
        query = str(query or "").strip()
        if not query or top_k <= 0:
            return []
        vector = await self.embeddings.embed_text(query)
        matches = await asyncio.to_thread(
            self.vector_store.search,
            vector,
            top_k,
        )
        return [
            ExternalKnowledgeSemanticHit(
                chunk_id=match.memory_id,
                similarity=match.similarity,
            )
            for match in matches
        ]

    async def rebuild(self, chunks: Iterable[tuple[str, str]]) -> int:
        prepared = [
            (str(chunk_id).strip(), str(content).strip())
            for chunk_id, content in chunks
            if str(chunk_id).strip() and str(content).strip()
        ]
        if not prepared:
            vectors = np.empty(
                (0, self.vector_store.dimension),
                dtype=np.float32,
            )
            return await asyncio.to_thread(
                self.vector_store.rebuild,
                [],
                vectors,
            )

        batches = []
        for start in range(0, len(prepared), self.EMBEDDING_BATCH_SIZE):
            batch = prepared[start : start + self.EMBEDDING_BATCH_SIZE]
            batches.append(
                await self.embeddings.embed_texts(
                    [content for _, content in batch]
                )
            )
        vectors = np.vstack(batches)
        return await asyncio.to_thread(
            self.vector_store.rebuild,
            [chunk_id for chunk_id, _ in prepared],
            vectors,
        )

    def stats(self) -> dict[str, Any]:
        return self.vector_store.stats()

    def list_chunk_ids(self) -> list[str]:
        return self.vector_store.list_memory_ids()


external_knowledge_vector_store = PersistentFaissStore(
    index_name="external_knowledge"
)

external_knowledge_indexer = ExternalKnowledgeIndexer(
    embeddings=embedding_client,
    vector_store=external_knowledge_vector_store,
)
