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


class JinaRerankerV2:
    """Cross-encoder reranker using jinaai/jina-reranker-v2-base-multilingual.

    278M-param XLM-RoBERTa-base trained explicitly for multilingual + structured
    data. Smaller and faster than bge-reranker-v2-gemma; lighter compute than m3
    despite similar arch. Requires trust_remote_code=True (jina provides custom
    AutoModel class).
    """

    name: str = "jina-reranker-v2-base-multilingual"

    def __init__(self, batch_size: int = 8, max_length: int = 1024, use_fp16: bool = True) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as e:
            raise ImportError(
                "Jina reranker requires `transformers` + `torch`. Install with:\n"
                "  uv sync --extra reranker"
            ) from e
        # transformers 5.x removed `create_position_ids_from_input_ids` from the
        # xlm_roberta module, which jina-reranker-v2's custom modeling file still
        # imports. Shim it back before the model is loaded.
        from transformers.models.xlm_roberta import modeling_xlm_roberta as _xlm

        if not hasattr(_xlm, "create_position_ids_from_input_ids"):
            def _create_position_ids_from_input_ids(
                input_ids: torch.Tensor, padding_idx: int, past_key_values_length: int = 0
            ) -> torch.Tensor:
                mask = input_ids.ne(padding_idx).int()
                inc = (torch.cumsum(mask, dim=1).type_as(mask) + past_key_values_length) * mask
                return inc.long() + padding_idx

            _xlm.create_position_ids_from_input_ids = _create_position_ids_from_input_ids

        self._torch = torch
        repo = "jinaai/jina-reranker-v2-base-multilingual"
        self._tokenizer = AutoTokenizer.from_pretrained(repo, trust_remote_code=True)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            repo, trust_remote_code=True
        )
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


class BGERerankerV2Gemma:
    """Cross-encoder reranker using BAAI/bge-reranker-v2-gemma.

    2B-param Gemma-2B-based reranker, top of BEIR multilingual leaderboard.
    Uses LLM-style yes/no token scoring rather than direct classification head.
    Heavier than m3/jina but the quality ceiling for open-weight multilingual
    reranking.
    """

    name: str = "bge-reranker-v2-gemma"
    _YES_TOKEN: str = "Yes"

    def __init__(self, batch_size: int = 4, max_length: int = 1024, use_fp16: bool = True) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as e:
            raise ImportError(
                "BGE Gemma reranker requires `transformers` + `torch`. Install with:\n"
                "  uv sync --extra reranker"
            ) from e
        self._torch = torch
        repo = "BAAI/bge-reranker-v2-gemma"
        self._tokenizer = AutoTokenizer.from_pretrained(repo)
        dtype = torch.float16 if (use_fp16 and torch.cuda.is_available()) else torch.float32
        self._model = AutoModelForCausalLM.from_pretrained(repo, torch_dtype=dtype)
        self._model.eval()
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._device == "cuda":
            self._model = self._model.cuda()
        self._batch_size = batch_size
        self._max_length = max_length
        # bge-reranker-v2-gemma uses LLM-style prompting; score = logit of "Yes"
        # at the final position. Token id from tokenizer.
        self._yes_id = self._tokenizer(self._YES_TOKEN, add_special_tokens=False)["input_ids"][0]

    def _build_prompt(self, query: str, passage: str) -> str:
        # Format from the model card.
        return (
            "A: " + query + "\n"
            "B: " + passage + "\n"
            "Given a query A and a passage B, determine whether the passage "
            'contains an answer to the query by providing a prediction of either "Yes" or "No".'
        )

    def score(self, query: str, passages: list[str]) -> list[float]:
        torch = self._torch
        out: list[float] = []
        for i in range(0, len(passages), self._batch_size):
            batch = passages[i : i + self._batch_size]
            prompts = [self._build_prompt(query, p) for p in batch]
            enc = self._tokenizer(
                prompts,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=self._max_length,
            )
            if self._device == "cuda":
                enc = {k: v.cuda() for k, v in enc.items()}
            with torch.no_grad():
                logits = self._model(**enc, return_dict=True).logits
            # Use logit at the final non-pad position for the "Yes" token id.
            attn = enc["attention_mask"]
            last_idx = attn.sum(dim=1) - 1
            scores = logits[torch.arange(logits.size(0)), last_idx, self._yes_id]
            out.extend(scores.float().cpu().tolist())
        return out


class VoyageReranker:
    """Commercial reranker via Voyage's `client.rerank()` API.

    Voyage's rerank-2.5 family is trained on broader commercial corpora
    (including legal/contracts) and is the one second-stage retriever in
    the project that wasn't tested against the open cross-encoders.
    Compatible model names: rerank-2.5, rerank-2.5-lite, rerank-2,
    rerank-lite-1. We default to rerank-2.5 (strongest).

    Pricing reference (2026): rerank-2.5 at ~$0.05 per 1K documents
    reranked, so a 78-query × 20-doc eval is roughly $0.08.
    """

    def __init__(self, model: str = "rerank-2.5", api_key: str | None = None) -> None:
        try:
            import voyageai
        except ImportError as e:
            raise ImportError(
                "Voyage reranker requires `voyageai`. Install with:\n"
                "  uv sync --extra voyage"
            ) from e
        import os

        key = api_key or os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise RuntimeError("Set VOYAGE_API_KEY in the environment.")
        self._client = voyageai.Client(api_key=key)
        self.name = f"voyage-{model}"
        self._model = model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        # Voyage returns top_k results in score-desc order with an `index` field
        # pointing back into the original passages list. We need scores in the
        # ORIGINAL passage order so the run_eval reranker pathway can re-sort
        # consistently with its own argsort.
        result = self._client.rerank(
            query=query,
            documents=passages,
            model=self._model,
            top_k=len(passages),  # request all so we can place each
        )
        scores = [0.0] * len(passages)
        for entry in result.results:
            scores[entry.index] = float(entry.relevance_score)
        return scores


def get_reranker(name: str) -> Reranker:
    if name == "bge-reranker-v2-m3":
        return BGERerankerV2M3()
    if name == "jina-reranker-v2-base-multilingual":
        return JinaRerankerV2()
    if name == "bge-reranker-v2-gemma":
        return BGERerankerV2Gemma()
    if name in {"voyage-rerank-2.5", "voyage-rerank-2.5-lite", "voyage-rerank-2", "voyage-rerank-lite-1"}:
        # Strip the "voyage-" prefix to get Voyage's actual model id.
        return VoyageReranker(model=name.removeprefix("voyage-"))
    raise ValueError(
        f"Unknown reranker: {name!r}. Known: bge-reranker-v2-m3, "
        "jina-reranker-v2-base-multilingual, bge-reranker-v2-gemma, "
        "voyage-rerank-2.5, voyage-rerank-2.5-lite, voyage-rerank-2."
    )
