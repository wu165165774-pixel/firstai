from __future__ import annotations

from loguru import logger

from .indexer import (
    ExternalKnowledgeIndexer,
    external_knowledge_indexer,
)
from .schemas import (
    ExternalKnowledgeCitation,
    ExternalKnowledgeDeleteResult,
    ExternalKnowledgeHit,
    ExternalKnowledgeIndexStatus,
    ExternalKnowledgeRetrieveRequest,
    ExternalKnowledgeSourceCreate,
    ExternalKnowledgeSourceUpdate,
    ExternalKnowledgeWriteResult,
)
from .storage import (
    ExternalKnowledgeNotFoundError,
    SQLiteExternalKnowledgeStorage,
)


class ExternalKnowledgeManager:
    CHUNK_CHAR_BUDGET = 1000
    CHUNK_CHAR_OVERLAP = 120

    def __init__(
        self,
        db_path: str | None = None,
        *,
        storage: SQLiteExternalKnowledgeStorage | None = None,
        indexer: ExternalKnowledgeIndexer | None = None,
    ) -> None:
        self.storage = storage or SQLiteExternalKnowledgeStorage(db_path)
        self.indexer = indexer or external_knowledge_indexer

    @classmethod
    def chunk_content(cls, content: str) -> list[tuple[str, int, int]]:
        normalized = str(content or "").replace("\r\n", "\n").strip()
        if not normalized:
            return []

        result: list[tuple[str, int, int]] = []
        start = 0
        length = len(normalized)
        while start < length:
            end = min(start + cls.CHUNK_CHAR_BUDGET, length)
            chunk = normalized[start:end]
            result.append((chunk, start, end))
            if end >= length:
                break
            start = max(end - cls.CHUNK_CHAR_OVERLAP, start + 1)
        return result

    async def _index_chunks(self, chunks) -> bool:
        try:
            indexed = await self.indexer.upsert_chunks(
                (chunk.chunk_id, chunk.content)
                for chunk in chunks
            )
            return indexed == len(chunks)
        except Exception:
            logger.exception(
                "External knowledge FAISS sync failed; SQLite remains "
                "authoritative and startup consistency can rebuild it."
            )
            return False

    async def create_source(
        self,
        payload: ExternalKnowledgeSourceCreate,
    ) -> ExternalKnowledgeWriteResult:
        normalized = payload.model_copy(
            update={
                "content": str(payload.content).replace("\r\n", "\n").strip()
            }
        )
        chunks = self.chunk_content(normalized.content)
        source, saved_chunks = await self.storage.create(normalized, chunks)
        indexed = await self._index_chunks(saved_chunks)
        return ExternalKnowledgeWriteResult(
            source=source,
            chunk_count=len(saved_chunks),
            indexed=indexed,
        )

    async def update_source(
        self,
        source_id: str,
        payload: ExternalKnowledgeSourceUpdate,
    ) -> ExternalKnowledgeWriteResult:
        current = await self.storage.get(
            source_id,
            payload.user_id,
            payload.knowledge_base_id,
        )
        if current is None:
            raise ExternalKnowledgeNotFoundError(source_id)

        content = (
            str(payload.content).replace("\r\n", "\n").strip()
            if "content" in payload.model_fields_set
            else current.content
        )
        normalized = payload.model_copy(
            update={"content": content}
            if "content" in payload.model_fields_set
            else {}
        )
        chunks = self.chunk_content(content)
        source, saved_chunks, old_chunk_ids = await self.storage.update(
            source_id,
            normalized,
            chunks,
        )

        indexed = True
        try:
            await self.indexer.remove_chunks(old_chunk_ids)
        except Exception:
            indexed = False
            logger.exception(
                "External knowledge old vector cleanup failed: "
                f"source_id={source_id}"
            )
        indexed = await self._index_chunks(saved_chunks) and indexed
        return ExternalKnowledgeWriteResult(
            source=source,
            chunk_count=len(saved_chunks),
            indexed=indexed,
        )

    async def delete_source(
        self,
        source_id: str,
        user_id: str,
        knowledge_base_id: str,
    ) -> ExternalKnowledgeDeleteResult:
        revision_count, chunk_count, current_chunk_ids = (
            await self.storage.delete(
                source_id,
                user_id,
                knowledge_base_id,
            )
        )
        removed = 0
        try:
            removed = await self.indexer.remove_chunks(current_chunk_ids)
        except Exception:
            logger.exception(
                "External knowledge vector cleanup failed: "
                f"source_id={source_id}"
            )
        return ExternalKnowledgeDeleteResult(
            source_id=source_id,
            deleted_revision_count=revision_count,
            deleted_chunk_count=chunk_count,
            removed_vector_count=removed,
        )

    async def retrieve(
        self,
        payload: ExternalKnowledgeRetrieveRequest,
    ) -> list[ExternalKnowledgeHit]:
        count = int(self.indexer.stats().get("count", 0))
        if count <= 0:
            return []

        candidate_k = min(
            count,
            max(payload.top_k * 20, 100),
            900,
        )
        semantic_hits = await self.indexer.search(
            payload.query,
            candidate_k,
        )
        if not semantic_hits:
            return []

        similarity_by_id = {
            hit.chunk_id: float(hit.similarity)
            for hit in semantic_hits
        }
        rows = await self.storage.load_current_chunks(
            list(similarity_by_id),
            payload.user_id,
            payload.knowledge_base_ids,
        )

        results: list[ExternalKnowledgeHit] = []
        for row in rows:
            similarity = similarity_by_id.get(str(row["chunk_id"]), -1.0)
            if similarity < payload.min_similarity:
                continue
            citation_id = (
                f"EK:{row['source_id']}:r{row['source_revision']}:"
                f"c{row['chunk_number']}"
            )
            results.append(
                ExternalKnowledgeHit(
                    content=str(row["content"]),
                    similarity=similarity,
                    citation=ExternalKnowledgeCitation(
                        citation_id=citation_id,
                        source_id=str(row["source_id"]),
                        source_revision=int(row["source_revision"]),
                        chunk_id=str(row["chunk_id"]),
                        chunk_number=int(row["chunk_number"]),
                        start_char=int(row["start_char"]),
                        end_char=int(row["end_char"]),
                        knowledge_base_id=str(row["knowledge_base_id"]),
                        source_type=str(row["source_type"]),
                        title=str(row["title"]),
                        source_uri=str(row["source_uri"]),
                        author=(
                            str(row["author"])
                            if row["author"] is not None
                            else None
                        ),
                        published_at=(
                            str(row["published_at"])
                            if row["published_at"] is not None
                            else None
                        ),
                    ),
                )
            )

        results.sort(
            key=lambda item: (
                -item.similarity,
                item.citation.source_id,
                item.citation.chunk_number,
            ),
        )
        return results[: payload.top_k]

    async def check_and_repair_index(self) -> ExternalKnowledgeIndexStatus:
        sqlite_chunks = await self.storage.list_current_chunks()
        sqlite_ids = {chunk_id for chunk_id, _ in sqlite_chunks}
        faiss_ids = set(self.indexer.list_chunk_ids())
        missing = sorted(sqlite_ids - faiss_ids)
        orphaned = sorted(faiss_ids - sqlite_ids)
        before = len(faiss_ids)

        if not missing and not orphaned:
            return ExternalKnowledgeIndexStatus(
                consistent=True,
                sqlite_count=len(sqlite_ids),
                faiss_count_before=before,
                faiss_count_after=before,
                rebuilt=False,
            )

        try:
            await self.indexer.rebuild(sqlite_chunks)
        except Exception as exc:
            logger.exception("External knowledge index rebuild failed.")
            return ExternalKnowledgeIndexStatus(
                consistent=False,
                sqlite_count=len(sqlite_ids),
                faiss_count_before=before,
                faiss_count_after=len(self.indexer.list_chunk_ids()),
                rebuilt=False,
                missing_in_faiss=missing,
                orphaned_in_faiss=orphaned,
                error=str(exc),
            )

        faiss_ids_after = set(self.indexer.list_chunk_ids())
        return ExternalKnowledgeIndexStatus(
            consistent=faiss_ids_after == sqlite_ids,
            sqlite_count=len(sqlite_ids),
            faiss_count_before=before,
            faiss_count_after=len(faiss_ids_after),
            rebuilt=True,
            missing_in_faiss=missing,
            orphaned_in_faiss=orphaned,
        )


external_knowledge_manager = ExternalKnowledgeManager()
