from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from loguru import logger


@dataclass(frozen=True)
class FaissSearchResult:

    memory_id: str
    vector_id: int
    similarity: float


class PersistentFaissStore:

    def __init__(
        self,
        index_dir: str | None = None,
        dimension: int | None = None,
    ) -> None:

        self.index_dir = Path(
            index_dir
            or os.getenv(
                "FAISS_INDEX_DIR",
                "/app/data/vector_db",
            )
        )

        self.dimension = (
            dimension
            if dimension is not None
            else int(
                os.getenv(
                    "OLLAMA_EMBEDDING_DIMENSION",
                    "1024",
                )
            )
        )

        if self.dimension <= 0:

            raise ValueError(
                "FAISS dimension must be greater than zero."
            )

        self.index_path = (
            self.index_dir
            / "memory.index"
        )

        self.mapping_path = (
            self.index_dir
            / "memory_ids.json"
        )

        self._lock = threading.RLock()

        self._index = self._create_empty_index()

        self._id_to_memory: dict[str, str] = {}

        self._load()

    def _create_empty_index(
        self,
    ) -> faiss.Index:

        # Inner Product + 单位向量 = 余弦相似度
        flat_index = faiss.IndexFlatIP(
            self.dimension
        )

        # IndexFlat 本身不支持自定义 ID，
        # 使用 IndexIDMap2 包装。
        return faiss.IndexIDMap2(
            flat_index
        )

    def _load(
        self,
    ) -> None:

        with self._lock:

            self.index_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            index_exists = self.index_path.exists()
            mapping_exists = self.mapping_path.exists()

            if not index_exists and not mapping_exists:
                return

            if index_exists != mapping_exists:

                raise RuntimeError(
                    "FAISS index and ID mapping are inconsistent. "
                    "Please rebuild the vector index."
                )

            loaded_index = faiss.read_index(
                str(self.index_path)
            )

            if loaded_index.d != self.dimension:

                raise RuntimeError(
                    "Stored FAISS dimension mismatch: "
                    f"configured={self.dimension}, "
                    f"stored={loaded_index.d}"
                )

            with self.mapping_path.open(
                "r",
                encoding="utf-8",
            ) as file:

                raw_mapping = json.load(
                    file
                )

            if not isinstance(
                raw_mapping,
                dict,
            ):

                raise RuntimeError(
                    "FAISS ID mapping must be a JSON object."
                )

            mapping = {
                str(vector_id): str(memory_id)
                for vector_id, memory_id
                in raw_mapping.items()
            }

            if loaded_index.ntotal != len(mapping):

                raise RuntimeError(
                    "FAISS vector count does not match "
                    "the ID mapping count."
                )

            self._index = loaded_index
            self._id_to_memory = mapping

            logger.info(
                "FAISS index loaded: "
                f"count={self._index.ntotal}, "
                f"dimension={self.dimension}"
            )

    def _save_locked(
        self,
    ) -> None:

        self.index_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_index_path = (
            self.index_dir
            / "memory.index.tmp"
        )

        temp_mapping_path = (
            self.index_dir
            / "memory_ids.json.tmp"
        )

        faiss.write_index(
            self._index,
            str(temp_index_path),
        )

        with temp_mapping_path.open(
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                self._id_to_memory,
                file,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )

            file.flush()

            os.fsync(
                file.fileno()
            )

        os.replace(
            temp_index_path,
            self.index_path,
        )

        os.replace(
            temp_mapping_path,
            self.mapping_path,
        )

    def _find_vector_id_locked(
        self,
        memory_id: str,
    ) -> int | None:

        for vector_id, stored_memory_id in (
            self._id_to_memory.items()
        ):

            if stored_memory_id == memory_id:
                return int(vector_id)

        return None

    def _allocate_vector_id_locked(
        self,
        memory_id: str,
    ) -> int:

        existing_id = self._find_vector_id_locked(
            memory_id
        )

        if existing_id is not None:
            return existing_id

        salt = 0

        while True:

            source = (
                memory_id
                if salt == 0
                else f"{memory_id}:{salt}"
            )

            digest = hashlib.blake2b(
                source.encode("utf-8"),
                digest_size=8,
                person=b"NovelForge",
            ).digest()

            # FAISS ID 使用有符号 int64，
            # 清除最高位，保证结果为正数。
            vector_id = (
                int.from_bytes(
                    digest,
                    byteorder="big",
                    signed=False,
                )
                & 0x7FFFFFFFFFFFFFFF
            )

            if vector_id == 0:
                vector_id = 1

            mapped_memory_id = (
                self._id_to_memory.get(
                    str(vector_id)
                )
            )

            if (
                mapped_memory_id is None
                or mapped_memory_id == memory_id
            ):
                return vector_id

            salt += 1

    def _prepare_vector(
        self,
        vector: np.ndarray,
    ) -> np.ndarray:

        prepared = np.asarray(
            vector,
            dtype=np.float32,
        ).reshape(1, -1)

        if prepared.shape[1] != self.dimension:

            raise ValueError(
                "Vector dimension mismatch: "
                f"expected={self.dimension}, "
                f"actual={prepared.shape[1]}"
            )

        if not np.isfinite(
            prepared
        ).all():

            raise ValueError(
                "Vector contains NaN or infinity."
            )

        norm = float(
            np.linalg.norm(
                prepared
            )
        )

        if norm <= 0:

            raise ValueError(
                "Cannot index a zero-length vector."
            )

        prepared /= norm

        return np.ascontiguousarray(
            prepared,
            dtype=np.float32,
        )

    def upsert(
        self,
        memory_id: str,
        vector: np.ndarray,
    ) -> int:

        memory_id = str(
            memory_id
        ).strip()

        if not memory_id:

            raise ValueError(
                "memory_id must not be empty."
            )

        prepared = self._prepare_vector(
            vector
        )

        with self._lock:

            existing_id = self._find_vector_id_locked(
                memory_id
            )

            vector_id = self._allocate_vector_id_locked(
                memory_id
            )

            if existing_id is not None:

                self._index.remove_ids(
                    np.asarray(
                        [existing_id],
                        dtype=np.int64,
                    )
                )

            self._index.add_with_ids(
                prepared,
                np.asarray(
                    [vector_id],
                    dtype=np.int64,
                ),
            )

            self._id_to_memory[
                str(vector_id)
            ] = memory_id

            self._save_locked()

            return vector_id

    def remove(
        self,
        memory_id: str,
    ) -> bool:

        with self._lock:

            vector_id = self._find_vector_id_locked(
                str(memory_id)
            )

            if vector_id is None:
                return False

            removed = int(
                self._index.remove_ids(
                    np.asarray(
                        [vector_id],
                        dtype=np.int64,
                    )
                )
            )

            self._id_to_memory.pop(
                str(vector_id),
                None,
            )

            self._save_locked()

            return removed > 0

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
    ) -> list[FaissSearchResult]:

        if top_k <= 0:
            return []

        prepared = self._prepare_vector(
            query_vector
        )

        with self._lock:

            if self._index.ntotal == 0:
                return []

            actual_k = min(
                int(top_k),
                int(self._index.ntotal),
            )

            similarities, vector_ids = (
                self._index.search(
                    prepared,
                    actual_k,
                )
            )

            results: list[
                FaissSearchResult
            ] = []

            for similarity, vector_id in zip(
                similarities[0],
                vector_ids[0],
                strict=True,
            ):

                vector_id = int(
                    vector_id
                )

                if vector_id < 0:
                    continue

                memory_id = (
                    self._id_to_memory.get(
                        str(vector_id)
                    )
                )

                if memory_id is None:

                    logger.warning(
                        "FAISS vector has no mapping: "
                        f"vector_id={vector_id}"
                    )

                    continue

                results.append(
                    FaissSearchResult(
                        memory_id=memory_id,
                        vector_id=vector_id,
                        similarity=float(
                            similarity
                        ),
                    )
                )

            return results

    def rebuild(
        self,
        memory_ids: list[str],
        vectors: np.ndarray,
    ) -> int:

        prepared_vectors = np.asarray(
            vectors,
            dtype=np.float32,
        )

        if prepared_vectors.ndim != 2:

            raise ValueError(
                "Rebuild vectors must be a 2D matrix."
            )

        if prepared_vectors.shape[0] != len(memory_ids):

            raise ValueError(
                "Memory ID count does not match vector count."
            )

        if prepared_vectors.shape[1] != self.dimension:

            raise ValueError(
                "Vector dimension mismatch: "
                f"expected={self.dimension}, "
                f"actual={prepared_vectors.shape[1]}"
            )

        if not np.isfinite(
            prepared_vectors
        ).all():

            raise ValueError(
                "Vectors contain NaN or infinity."
            )

        norms = np.linalg.norm(
            prepared_vectors,
            axis=1,
            keepdims=True,
        )

        if np.any(norms <= 0):

            raise ValueError(
                "Vectors contain a zero-length vector."
            )

        prepared_vectors = (
            prepared_vectors
            / norms
        )

        prepared_vectors = np.ascontiguousarray(
            prepared_vectors,
            dtype=np.float32,
        )

        with self._lock:

            self._index = (
                self._create_empty_index()
            )

            self._id_to_memory = {}

            if not memory_ids:

                self._save_locked()

                return 0

            vector_ids: list[int] = []

            for memory_id in memory_ids:

                normalized_id = str(
                    memory_id
                ).strip()

                if not normalized_id:

                    raise ValueError(
                        "Memory ID must not be empty."
                    )

                vector_id = (
                    self._allocate_vector_id_locked(
                        normalized_id
                    )
                )

                self._id_to_memory[
                    str(vector_id)
                ] = normalized_id

                vector_ids.append(
                    vector_id
                )

            self._index.add_with_ids(
                prepared_vectors,
                np.asarray(
                    vector_ids,
                    dtype=np.int64,
                ),
            )

            self._save_locked()

            logger.info(
                "FAISS index rebuilt: "
                f"count={self._index.ntotal}, "
                f"dimension={self.dimension}"
            )

            return int(
                self._index.ntotal
            )

    def clear(
        self,
    ) -> None:

        with self._lock:

            self._index = (
                self._create_empty_index()
            )

            self._id_to_memory = {}

            self._save_locked()

    def stats(
        self,
    ) -> dict[str, Any]:

        with self._lock:

            return {
                "count": int(
                    self._index.ntotal
                ),
                "dimension": self.dimension,
                "index_path": str(
                    self.index_path
                ),
                "mapping_path": str(
                    self.mapping_path
                ),
            }


faiss_store = PersistentFaissStore()