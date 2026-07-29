"""Replaceable source adapters and an Agent-Reach-inspired capability mesh."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import ipaddress
import json
import socket
import time
from dataclasses import replace
from typing import Iterable, Sequence
from urllib.parse import urlparse

import requests

from aether.contracts.opportunities import (
    ContentSnapshot, ScoutQuery, SearchHit, SourceAdapter, SourceAdapterManifest,
    SourceAdapterStatus, SourceCapability, SourceHealth, SourceKind, source_manifest_hash,
)
from aether.utils.time import utc_now


def _is_public_host(host: str) -> bool:
    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            return False
    return True


def validate_public_url(url: str, allowed_domains: Sequence[str] = (), blocked_domains: Sequence[str] = ()) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only public HTTP(S) URLs are allowed")
    host = (parsed.hostname or "").casefold()
    if not host:
        raise ValueError("URL hostname is required")
    if any(host == item.casefold() or host.endswith("." + item.casefold()) for item in blocked_domains):
        raise ValueError("URL domain is blocked by scout policy")
    if allowed_domains and not any(host == item.casefold() or host.endswith("." + item.casefold()) for item in allowed_domains):
        raise ValueError("URL domain is outside scout allowlist")
    if not _is_public_host(host):
        raise ValueError("private, loopback, link-local, or unresolved network target is denied")


class SourceCapabilityMesh:
    """Health-aware ordered adapter registry; authority remains in Aether Core."""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        self._eligibility_guard = None

    def register(self, adapter: SourceAdapter) -> None:
        manifest = adapter.manifest
        if manifest.adapter_id in self._adapters:
            raise ValueError(f"duplicate source adapter {manifest.adapter_id}")
        self._adapters[manifest.adapter_id] = adapter

    def adapters(self) -> tuple[SourceAdapter, ...]:
        return tuple(sorted(self._adapters.values(), key=lambda item: (item.manifest.priority, item.manifest.adapter_id)))

    def set_eligibility_guard(self, guard) -> None:
        self._eligibility_guard = guard

    def get(self, adapter_id: str) -> SourceAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise KeyError(f"unknown source adapter {adapter_id}") from exc

    async def status(self) -> tuple[SourceAdapterStatus, ...]:
        values = await asyncio.gather(*(item.health() for item in self.adapters()), return_exceptions=True)
        out: list[SourceAdapterStatus] = []
        for adapter, value in zip(self.adapters(), values):
            if isinstance(value, Exception):
                out.append(SourceAdapterStatus(
                    source_id=adapter.manifest.source_id, adapter_id=adapter.manifest.adapter_id,
                    health=SourceHealth.UNAVAILABLE, reason=str(value), checked_at=utc_now(),
                ))
            else:
                out.append(value)
        return tuple(out)

    async def eligible(self, query: ScoutQuery) -> tuple[SourceAdapter, ...]:
        statuses = {item.adapter_id: item for item in await self.status()}
        eligible = []
        for adapter in self.adapters():
            manifest = adapter.manifest
            status = statuses[manifest.adapter_id]
            if status.health != SourceHealth.HEALTHY:
                continue
            if query.source_kinds and manifest.kind not in query.source_kinds:
                continue
            if not manifest.public_observation and query.autonomy_level.value in {"observe", "synthesize"}:
                continue
            if self._eligibility_guard is not None and not self._eligibility_guard(manifest):
                continue
            eligible.append(adapter)
        return tuple(eligible[: query.maximum_sources])


class GenericPublicHttpAdapter:
    """Bounded public HTTP fetcher; no private network, local file, or credential inheritance."""

    def __init__(self, *, maximum_bytes: int = 1_000_000, timeout_seconds: float = 15.0, priority: int = 80) -> None:
        self.maximum_bytes = maximum_bytes
        self.timeout_seconds = timeout_seconds
        base = SourceAdapterManifest(
            source_id="source.web.public-http", adapter_id="source.adapter.public-http",
            name="Bounded Public HTTP", kind=SourceKind.WEB,
            capabilities=(SourceCapability.FETCH,), priority=priority,
            forbidden_capabilities=("private-network", "file-scheme", "credential-export", "arbitrary-javascript"),
            metadata={"maximum_bytes": maximum_bytes, "timeout_seconds": timeout_seconds},
        )
        self._manifest = replace(base, manifest_hash=source_manifest_hash(base))

    @property
    def manifest(self) -> SourceAdapterManifest:
        return self._manifest

    async def health(self) -> SourceAdapterStatus:
        return SourceAdapterStatus(
            source_id=self.manifest.source_id, adapter_id=self.manifest.adapter_id,
            health=SourceHealth.HEALTHY, reason="requests client available", version=requests.__version__, checked_at=utc_now(),
        )

    async def search(self, query: ScoutQuery) -> Sequence[SearchHit]:
        return ()

    async def fetch(self, hit: SearchHit, query: ScoutQuery) -> ContentSnapshot:
        validate_public_url(hit.url, query.allowed_domains, query.blocked_domains)
        started = time.perf_counter()
        response = await asyncio.to_thread(
            requests.get, hit.url, timeout=min(self.timeout_seconds, query.maximum_duration_seconds),
            headers={"User-Agent": "AetherOpportunityScout/0.19 (+governed-public-observation)"},
            allow_redirects=True, stream=True,
        )
        response.raise_for_status()
        chunks: list[bytes] = []
        consumed = 0
        for chunk in response.iter_content(chunk_size=65536):
            consumed += len(chunk)
            if consumed > min(self.maximum_bytes, query.maximum_bytes):
                raise ValueError("source response exceeded bounded byte budget")
            chunks.append(chunk)
        raw = b"".join(chunks)
        text = raw.decode(response.encoding or "utf-8", errors="replace")
        final_url = str(response.url)
        validate_public_url(final_url, query.allowed_domains, query.blocked_domains)
        return ContentSnapshot(
            source_id=hit.source_id, adapter_id=self.manifest.adapter_id, canonical_url=final_url,
            title=hit.title, content_text=text, content_type=response.headers.get("content-type", "text/plain"),
            retrieved_at=utc_now(), content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            raw_hash=hashlib.sha256(raw).hexdigest(), status_code=response.status_code,
            redirect_chain=tuple(item.url for item in response.history), policy_fingerprint=self.manifest.manifest_hash,
            source_reference=hit.url, metadata={"duration_ms": round((time.perf_counter() - started) * 1000, 3)},
        )


class Crawl4AIRestrictedAdapter:
    """Optional Crawl4AI web-intelligence substrate with a hard Aether policy boundary.

    The adapter advertises availability only when crawl4ai is installed. Actual crawling is
    intentionally isolated behind this adapter so Core never imports or knows Crawl4AI.
    """

    def __init__(self, *, maximum_pages: int = 10, maximum_depth: int = 3, maximum_bytes: int = 2_000_000, priority: int = 10) -> None:
        self.maximum_pages = maximum_pages
        self.maximum_depth = maximum_depth
        self.maximum_bytes = maximum_bytes
        base = SourceAdapterManifest(
            source_id="source.web.crawl4ai", adapter_id="source.adapter.crawl4ai-restricted",
            name="Crawl4AI Restricted Web Intelligence", kind=SourceKind.WEB,
            capabilities=(SourceCapability.FETCH, SourceCapability.CRAWL, SourceCapability.EXTRACT),
            priority=priority,
            forbidden_capabilities=(
                "private-network", "file-scheme", "credential-export", "filesystem-download",
                "persistent-browser-profile", "arbitrary-model-generated-javascript", "unbounded-recursion",
            ),
            metadata={
                "maximum_pages": maximum_pages, "maximum_depth": maximum_depth,
                "maximum_bytes": maximum_bytes, "role": "web-intelligence-substrate",
            },
        )
        self._manifest = replace(base, manifest_hash=source_manifest_hash(base))

    @property
    def manifest(self) -> SourceAdapterManifest:
        return self._manifest

    async def health(self) -> SourceAdapterStatus:
        available = importlib.util.find_spec("crawl4ai") is not None
        return SourceAdapterStatus(
            source_id=self.manifest.source_id, adapter_id=self.manifest.adapter_id,
            health=SourceHealth.HEALTHY if available else SourceHealth.UNAVAILABLE,
            reason="crawl4ai package available" if available else "crawl4ai package is not installed",
            version="installed" if available else "", checked_at=utc_now(),
            metadata={"restricted_profile": True},
        )

    async def search(self, query: ScoutQuery) -> Sequence[SearchHit]:
        return ()

    async def fetch(self, hit: SearchHit, query: ScoutQuery) -> ContentSnapshot:
        validate_public_url(hit.url, query.allowed_domains, query.blocked_domains)
        if importlib.util.find_spec("crawl4ai") is None:
            raise RuntimeError("crawl4ai package is unavailable")
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
        browser_config = BrowserConfig(headless=True, verbose=False)
        run_config = CrawlerRunConfig(cache_mode=CacheMode.ENABLED, page_timeout=min(query.maximum_duration_seconds * 1000, 120000))
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=hit.url, config=run_config)
        if not getattr(result, "success", False):
            raise RuntimeError(str(getattr(result, "error_message", "crawl failed")))
        markdown = str(getattr(result, "markdown", ""))
        if len(markdown.encode("utf-8")) > min(self.maximum_bytes, query.maximum_bytes):
            raise ValueError("crawl output exceeded bounded byte budget")
        final_url = str(getattr(result, "url", hit.url))
        validate_public_url(final_url, query.allowed_domains, query.blocked_domains)
        return ContentSnapshot(
            source_id=hit.source_id, adapter_id=self.manifest.adapter_id, canonical_url=final_url,
            title=hit.title, content_text=markdown, content_type="text/markdown", retrieved_at=utc_now(),
            content_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(), status_code=int(getattr(result, "status_code", 200) or 200),
            policy_fingerprint=self.manifest.manifest_hash, source_reference=hit.url,
            metadata={"restricted_profile": True, "maximum_pages": self.maximum_pages, "maximum_depth": self.maximum_depth},
        )


class StaticCatalogAdapter:
    """Deterministic catalog/source adapter for curated ecosystem feeds and tests."""

    def __init__(self, manifest: SourceAdapterManifest, documents: Iterable[tuple[str, str, str]]) -> None:
        self._manifest = replace(manifest, manifest_hash=manifest.manifest_hash or source_manifest_hash(manifest))
        self._documents = tuple(documents)

    @property
    def manifest(self) -> SourceAdapterManifest:
        return self._manifest

    async def health(self) -> SourceAdapterStatus:
        return SourceAdapterStatus(
            source_id=self.manifest.source_id, adapter_id=self.manifest.adapter_id,
            health=SourceHealth.HEALTHY, reason="catalog snapshot available", version="fixture-v1", checked_at=utc_now(),
        )

    async def search(self, query: ScoutQuery) -> Sequence[SearchHit]:
        terms = {token.casefold() for item in query.queries for token in item.split() if len(token) > 2}
        hits = []
        for index, (url, title, content) in enumerate(self._documents, start=1):
            haystack = f"{title} {content}".casefold()
            if terms and not any(term in haystack for term in terms):
                continue
            hits.append(SearchHit(
                source_id=self.manifest.source_id, url=url, title=title,
                snippet=content[:240], rank=index, query=query.queries[0] if query.queries else query.objective,
                observed_at=utc_now(), metadata={"catalog": True},
            ))
        return tuple(hits)

    async def fetch(self, hit: SearchHit, query: ScoutQuery) -> ContentSnapshot:
        for url, title, content in self._documents:
            if url == hit.url:
                return ContentSnapshot(
                    source_id=self.manifest.source_id, adapter_id=self.manifest.adapter_id,
                    canonical_url=url, title=title, content_text=content, content_type="text/markdown",
                    retrieved_at=utc_now(), content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    raw_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(), policy_fingerprint=self.manifest.manifest_hash,
                    source_reference=url, metadata={"catalog": True},
                )
        raise KeyError(hit.url)
