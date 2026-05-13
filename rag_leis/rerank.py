from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class BGERerankerV2M3:
    """Cross-encoder reranker using BAAI/bge-reranker-v2-m3.

    Implemented directly on top of `transformers` instead of FlagEmbedding's
    FlagReranker wrapper, which has a tokenizer-pathway bug on this model
    (`XLMRobertaTokenizer has no attribute prepare_for_model`).
    """

    name: str = "bge-reranker-v2-m3"

    def __init__(self, batch_size: int = 8, max_length: int = 1024, use_fp16: bool = True) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as e:
            raise ImportError(
                "BGE reranker requires `transformers` + `torch`. Install with:\n"
                "  uv sync --extra reranker"
            ) from e
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-v2-m3")
        self._model = AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-v2-m3")
        self._model.eval()
        if use_fp16 and torch.cuda.is_available():
            self._model = self._model.half().cuda()
            self._device = "cuda"
        else:
            self._device = "cpu"
        self._batch_size = batch_size
        self._max_length = max_length

    def score(self, query: str, passages: list[str]) -> list[float]:
        torch = self._torch
        out: list[float] = []
        for i in range(0, len(passages), self._batch_size):
            batch = passages[i : i + self._batch_size]
            pairs = [(query, p) for p in batch]
            enc = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=self._max_length,
            )
            if self._device == "cuda":
                enc = {k: v.cuda() for k, v in enc.items()}
            with torch.no_grad():
                logits = self._model(**enc, return_dict=True).logits.view(-1).float()
            out.extend(logits.cpu().tolist())
        return out


def get_reranker(name: str) -> Reranker:
    if name == "bge-reranker-v2-m3":
        return BGERerankerV2M3()
    raise ValueError(f"Unknown reranker: {name!r}. Known: bge-reranker-v2-m3.")
