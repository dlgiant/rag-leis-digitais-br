from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from xml.etree.ElementTree import Element, fromstring

import httpx

SRU_ENDPOINT = "https://www.lexml.gov.br/busca/SRU"

_NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "srw_dc": "info:srw/schema/1/dc-schema",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; rag-leis-digitais-br/0.1; "
    "+https://github.com/dlgiant/rag-leis-digitais-br)"
)


class LexmlSRUError(RuntimeError):
    pass


@dataclass(frozen=True)
class LexmlRecord:
    urn: str
    title: str
    date: str | None
    raw: Element


class LexmlSRUClient:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_concurrency: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": _DEFAULT_USER_AGENT, "Accept": "application/xml"},
        )
        self._sem = asyncio.Semaphore(max_concurrency)

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

    async def search(
        self,
        cql: str,
        *,
        start_record: int = 1,
        max_records: int = 10,
    ) -> tuple[list[LexmlRecord], int]:
        params = {
            "operation": "searchRetrieve",
            "version": "1.1",
            "query": cql,
            "startRecord": str(start_record),
            "maximumRecords": str(max_records),
        }
        async with self._sem:
            resp = await self._client.get(SRU_ENDPOINT, params=params)
        resp.raise_for_status()
        return _parse_response(resp.text)

    async def get_by_urn(self, urn: str) -> LexmlRecord | None:
        records, _total = await self.search(f'urn="{urn}"', max_records=1)
        if records:
            return records[0]
        records, _total = await self.search(f'urn any "{urn}"', max_records=5)
        for r in records:
            if r.urn == urn:
                return r
        return None


def _parse_response(xml_text: str) -> tuple[list[LexmlRecord], int]:
    root = fromstring(xml_text)

    diag = root.find("srw:diagnostics", _NS)
    if diag is not None:
        msg = diag.findtext(".//srw:message", default="(no message)", namespaces=_NS)
        raise LexmlSRUError(f"SRU diagnostic: {msg}")

    total = int(root.findtext("srw:numberOfRecords", default="0", namespaces=_NS))

    records: list[LexmlRecord] = []
    for record_data in root.findall("srw:records/srw:record/srw:recordData", _NS):
        urn = _findtext_local(record_data, "urn") or _findtext_local(record_data, "identifier")
        title = _findtext_local(record_data, "title") or ""
        date = _findtext_local(record_data, "date")
        if urn:
            records.append(LexmlRecord(urn=urn, title=title, date=date, raw=record_data))
    return records, total


def _findtext_local(elem: Element, local_name: str) -> str | None:
    for child in elem.iter():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == local_name and child.text:
            return child.text.strip()
    return None
