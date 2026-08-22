"""Asynchronous font subset fetcher, request deduplicator, and preview manager."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from metaglyph.core.events import get_event_bus
from metaglyph.db.models import Font, FontVariant
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.loader import FontLoader

if TYPE_CHECKING:
    from metaglyph.providers.manager import ProviderManager

logger = logging.getLogger(__name__)


class SubsetFetcher:
    """Coordinates micro-subset caching, dynamic Qt font loading, and background downloading."""

    def __init__(
        self,
        cache: SubsetCache | None = None,
        loader: FontLoader | None = None,
        provider_manager: ProviderManager | None = None,
        max_concurrent_requests: int = 8,
    ) -> None:
        self.cache = cache or SubsetCache()
        self.loader = loader or FontLoader()

        if provider_manager is None:
            from metaglyph.providers.manager import ProviderManager as DefaultProviderManager

            self.provider_manager = DefaultProviderManager()
        else:
            self.provider_manager = provider_manager

        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._in_flight: dict[str, asyncio.Task[tuple[Path, str]]] = {}

    def _get_request_key(
        self,
        font_id: str,
        sample_text: str,
        weight: int,
        style: str,
    ) -> str:
        """Create unique key for deduplicating in-flight requests."""
        return f"{font_id}::{weight}::{style}::{sample_text}"

    async def get_or_fetch_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> tuple[Path, str]:
        """Retrieve cached subset or fetch/subset from provider asynchronously.

        Args:
            font: Font metadata model.
            sample_text: Sample text string for preview.
            variant: Optional variant (weight/style).

        Returns:
            Tuple of (Path to subset file, registered Qt family name).
        """
        weight = variant.weight if variant else 400
        style = variant.style if variant else "normal"

        # 1. Fast path: check local disk cache
        if self.cache.has_subset(font.id, sample_text, weight, style):
            cached_path = self.cache.get_subset(font.id, sample_text, weight, style)
            if cached_path:
                _, family_name = self.loader.load_font(cached_path)
                return cached_path, family_name

        # 2. Check if identical request is already in-flight
        req_key = self._get_request_key(font.id, sample_text, weight, style)
        if req_key in self._in_flight:
            return await self._in_flight[req_key]

        # 3. Schedule async download task
        task = asyncio.create_task(
            self._fetch_and_load(font, sample_text, variant, weight, style, req_key)
        )
        self._in_flight[req_key] = task

        try:
            return await task
        finally:
            self._in_flight.pop(req_key, None)

    async def _fetch_and_load(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None,
        weight: int,
        style: str,
        req_key: str,
    ) -> tuple[Path, str]:
        """Worker executing network fetch under concurrency semaphore."""
        async with self._semaphore:
            # Double-check cache in case another task loaded it while waiting on semaphore
            if self.cache.has_subset(font.id, sample_text, weight, style):
                cached_path = self.cache.get_subset(font.id, sample_text, weight, style)
                if cached_path:
                    _, family_name = self.loader.load_font(cached_path)
                    return cached_path, family_name

            # Route to provider
            subset_path = await self.provider_manager.fetch_sample_subset(font, sample_text, variant)

            # Load into Qt QFontDatabase
            _, family_name = self.loader.load_font(subset_path)

            # Emit event notification
            event_bus = get_event_bus()
            await event_bus.emit_async(
                "subset_loaded",
                font_id=font.id,
                sample_text=sample_text,
                path=str(subset_path),
                family_name=family_name,
            )

            return subset_path, family_name

    async def prefetch_subsets(
        self,
        fonts: list[Font],
        sample_text: str,
        limit: int = 20,
    ) -> list[tuple[Path, str]]:
        """Prefetch micro-subsets in background for a batch of fonts."""
        targets = fonts[:limit]
        tasks = [self.get_or_fetch_subset(f, sample_text) for f in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_results: list[tuple[Path, str]] = []
        for r in results:
            if isinstance(r, tuple):
                valid_results.append(r)
            else:
                logger.debug("Prefetch failed for one font: %s", r)

        return valid_results

    def clear_cache(self) -> None:
        """Purge disk cache and unload dynamic fonts."""
        self.loader.unload_all()
        self.cache.clear()
