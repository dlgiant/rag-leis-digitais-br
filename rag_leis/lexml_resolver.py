from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import httpx

RESOLVER_BASE = "https://www.lexml.gov.br/urn"

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; rag-leis-digitais-br/0.1; "
    "+https://github.com/dlgiant/rag-leis-digitais-br)"
)

_FIELD_PATTERN = re.compile(
    r"<div[^>]*text-right[^>]*>\s*<strong[^>]*>([^<]+)</strong>\s*</div>\s*"
    r"<div[^>]*text-left[^>]*>(.*?)</div>",
    re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class LexmlResolverError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolverRecord:
    urn: str
    title: str | None
    date: str | None
    ementa: str | None
    locality: str | None
    authority: str | None
    apelidos: tuple[str, ...]
    publication_date: str | None
    fields: dict[str, str] = field(default_factory=dict)


class LexmlResolverClient:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_concurrency: int = 3,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": _DEFAULT_USER_AGENT, "Accept": "text/html"},
            follow_redirects=True,
        )
        self._sem = asyncio.Semaphore(max_concurrency)
        self._max_retries = max_retries

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_by_urn(self, urn: str) -> ResolverRecord | None:
        url = f"{RESOLVER_BASE}/{urn}"
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                async with self._sem:
                    resp = await self._client.get(url)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return _parse_resolver_html(urn, resp.text)
            except httpx.HTTPError as e:
                last_error = e
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
        raise LexmlResolverError(
            f"Resolver fetch failed after {self._max_retries} attempts: {url}"
        ) from last_error


def _clean(text: str) -> str:
    return _WS.sub(" ", _TAG.sub(" ", text)).strip()


def _parse_resolver_html(urn: str, html: str) -> ResolverRecord:
    multi: dict[str, list[str]] = {}
    for match in _FIELD_PATTERN.finditer(html):
        label = match.group(1).strip().rstrip(":").strip()
        value = _clean(match.group(2))
        if label and value:
            multi.setdefault(label, []).append(value)

    def first(*labels: str) -> str | None:
        for lbl in labels:
            if lbl in multi:
                return multi[lbl][0]
        return None

    apelidos = tuple(multi.get("Apelido", ()))
    flat = {k: v[0] for k, v in multi.items()}

    return ResolverRecord(
        urn=first("Nome Uniforme") or urn,
        title=first("Título"),
        date=first("Data"),
        ementa=first("Ementa"),
        locality=first("Localidade"),
        authority=first("Autoridade"),
        apelidos=apelidos,
        publication_date=first("Publicação Original"),
        fields=flat,
    )
