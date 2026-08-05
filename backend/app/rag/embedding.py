from __future__ import annotations

import os
from collections.abc import Sequence

import httpx
import numpy as np
from loguru import logger


class EmbeddingError(RuntimeError):
    """Embedding 服务异常。"""


class OllamaEmbeddingClient:

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:

        self.base_url = (
            base_url
            or os.getenv(
                "OLLAMA_BASE_URL",
                "http://ollama:11434",
            )
        ).rstrip("/")

        self.model = (
            model
            or os.getenv(
                "OLLAMA_EMBEDDING_MODEL",
                "qwen3-embedding:0.6b",
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
                "Embedding dimension must be greater than zero."
            )

        self.timeout_seconds = timeout_seconds

    async def embed_texts(
        self,
        texts: Sequence[str],
    ) -> np.ndarray:

        normalized_texts = [
            str(text).strip()
            for text in texts
        ]

        if not normalized_texts:

            return np.empty(
                (0, self.dimension),
                dtype=np.float32,
            )

        if any(
            not text
            for text in normalized_texts
        ):

            raise ValueError(
                "Embedding input must not contain empty text."
            )

        try:

            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            ) as client:

                response = await client.post(
                    "/api/embed",
                    json={
                        "model": self.model,
                        "input": normalized_texts,
                        "truncate": True,
                        "keep_alive": "10m",
                    },
                )

                response.raise_for_status()

        except httpx.HTTPStatusError as exc:

            detail = exc.response.text[:1000]

            raise EmbeddingError(
                "Ollama embedding request failed: "
                f"status={exc.response.status_code}, "
                f"detail={detail}"
            ) from exc

        except httpx.HTTPError as exc:

            raise EmbeddingError(
                f"Unable to call Ollama: {exc}"
            ) from exc

        data = response.json()

        vectors = np.asarray(
            data.get("embeddings", []),
            dtype=np.float32,
        )

        if vectors.ndim != 2:

            raise EmbeddingError(
                "Ollama returned an invalid embedding matrix."
            )

        if vectors.shape[0] != len(normalized_texts):

            raise EmbeddingError(
                "Embedding result count mismatch: "
                f"expected={len(normalized_texts)}, "
                f"actual={vectors.shape[0]}"
            )

        if vectors.shape[1] != self.dimension:

            raise EmbeddingError(
                "Embedding dimension mismatch: "
                f"expected={self.dimension}, "
                f"actual={vectors.shape[1]}"
            )

        if not np.isfinite(vectors).all():

            raise EmbeddingError(
                "Embedding contains NaN or infinity."
            )

        # Ollama 已经返回单位向量。
        # 这里再次归一化，防止后续更换模型时出现偏差。
        norms = np.linalg.norm(
            vectors,
            axis=1,
            keepdims=True,
        )

        if np.any(norms <= 0):

            raise EmbeddingError(
                "Embedding contains a zero-length vector."
            )

        vectors = vectors / norms

        vectors = np.ascontiguousarray(
            vectors,
            dtype=np.float32,
        )

        logger.debug(
            "Embedding generated: "
            f"model={self.model}, "
            f"count={vectors.shape[0]}, "
            f"dimension={vectors.shape[1]}"
        )

        return vectors

    async def embed_text(
        self,
        text: str,
    ) -> np.ndarray:

        vectors = await self.embed_texts(
            [text]
        )

        return vectors[0]


embedding_client = OllamaEmbeddingClient()