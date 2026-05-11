from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; rag-leis-digitais-br/0.1; "
    "+https://github.com/dlgiant/rag-leis-digitais-br)"
)


@dataclass(frozen=True)
class PlanaltoDocument:
    url: str
    html: str
    encoding: str
    status_code: int
    final_url: str


class PlanaltoScraper:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_concurrency: int = 3,
        timeout: float = 60.0,
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

    async def fetch(self, url: str) -> PlanaltoDocument:
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                async with self._sem:
                    resp = await self._client.get(url)
                resp.raise_for_status()
                encoding = "ISO-8859-1"
                html = resp.content.decode(encoding)
                return PlanaltoDocument(
                    url=url,
                    html=html,
                    encoding=encoding,
                    status_code=resp.status_code,
                    final_url=str(resp.url),
                )
            except (httpx.HTTPError, httpx.HTTPStatusError) as e:
                last_error = e
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
        raise RuntimeError(
            f"Planalto fetch failed after {self._max_retries} attempts: {url}"
        ) from last_error
