from __future__ import annotations

import os
from typing import Protocol

import numpy as np
import numpy.typing as npt

Vec = npt.NDArray[np.float32]


class Embedder(Protocol):
    name: str
    dim: int

    def embed_docs(self, texts: list[str]) -> Vec: ...
    def embed_query(self, text: str) -> Vec: ...


def _normalize(x: Vec) -> Vec:
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (x / norms).astype(np.float32)


class BGEM3Embedder:
    name: str = "bge-m3"
    dim: int = 1024

    def __init__(self, batch_size: int = 12, max_length: int = 8192, use_fp16: bool = True) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as e:
            raise ImportError(
                "BGE-M3 backend requires `FlagEmbedding`. Install with:\n"
                "  uv sync --extra bge"
            ) from e
        self._model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=use_fp16)
        self._batch_size = batch_size
        self._max_length = max_length

    def _encode(self, texts: list[str], max_length: int, sparse: bool = False) -> dict:
        return self._model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=max_length,
            return_dense=True,
            return_sparse=sparse,
            return_colbert_vecs=False,
        )

    def embed_docs(self, texts: list[str]) -> Vec:
        out = self._encode(texts, self._max_length)
        return _normalize(np.asarray(out["dense_vecs"], dtype=np.float32))

    def embed_query(self, text: str) -> Vec:
        out = self._encode([text], 512)
        return _normalize(np.asarray(out["dense_vecs"], dtype=np.float32))[0]

    def embed_docs_dense_sparse(
        self, texts: list[str]
    ) -> tuple[Vec, list[dict[str, float]]]:
        """Returns (normalized_dense_vectors, lexical_weights_list).
        Each lexical_weights entry is a dict mapping token_id (as str) → weight.
        """
        out = self._encode(texts, self._max_length, sparse=True)
        dense = _normalize(np.asarray(out["dense_vecs"], dtype=np.float32))
        # FlagEmbedding emits defaultdict-like objects; coerce to plain dict for picklability.
        sparse: list[dict[str, float]] = [
            {str(k): float(v) for k, v in row.items()} for row in out["lexical_weights"]
        ]
        return dense, sparse

    def embed_query_dense_sparse(self, text: str) -> tuple[Vec, dict[str, float]]:
        dense, sparse = self.embed_docs_dense_sparse([text])
        return dense[0], sparse[0]

    @staticmethod
    def lexical_score(q: dict[str, float], d: dict[str, float]) -> float:
        # Sum of weight products over shared tokens — matches BGE-M3's
        # compute_lexical_matching_score.
        if len(q) > len(d):
            q, d = d, q
        return sum(w * d.get(tok, 0.0) for tok, w in q.items())


class VoyageEmbedder:
    dim: int = 1024

    def __init__(self, model: str = "voyage-3-large", api_key: str | None = None) -> None:
        try:
            import voyageai
        except ImportError as e:
            raise ImportError(
                "Voyage backend requires `voyageai`. Install with:\n"
                "  uv sync --extra voyage"
            ) from e
        key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise RuntimeError("Set VOYAGE_API_KEY in the environment.")
        self._client = voyageai.Client(api_key=key)
        self.name = model
        self._model = model

    def _batch_embed(self, texts: list[str], input_type: str) -> Vec:
        # Voyage allows up to 128 inputs per request; keep batches small for token limits.
        out: list[list[float]] = []
        for i in range(0, len(texts), 64):
            batch = texts[i : i + 64]
            resp = self._client.embed(batch, model=self._model, input_type=input_type)
            out.extend(resp.embeddings)
        return _normalize(np.asarray(out, dtype=np.float32))

    def embed_docs(self, texts: list[str]) -> Vec:
        return self._batch_embed(texts, input_type="document")

    def embed_query(self, text: str) -> Vec:
        vec: Vec = self._batch_embed([text], input_type="query")[0]
        return vec


def get_embedder(name: str) -> Embedder:
    if name == "bge-m3":
        return BGEM3Embedder()
    if name in {"voyage-3-large", "voyage-3", "voyage-3-lite"}:
        return VoyageEmbedder(model=name)
    raise ValueError(
        f"Unknown embedder: {name!r}. Known: bge-m3, voyage-3-large, voyage-3, voyage-3-lite."
    )
