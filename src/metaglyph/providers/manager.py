"""Multi-provider coordinator and sync engine."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from metaglyph.core.events import get_event_bus
from metaglyph.db.models import Font, FontVariant
from metaglyph.db.repository import FontRepository
from metaglyph.providers.base import BaseFontProvider
from metaglyph.providers.fontsource import FontsourceProvider
from metaglyph.providers.fontsquirrel import FontSquirrelProvider
from metaglyph.providers.nerd_fonts import NerdFontsProvider

logger = logging.getLogger(__name__)


class ProviderManager:
    """Coordinates multiple font providers, catalog synchronization, and downloads."""

    def __init__(self, providers: list[BaseFontProvider] | None = None) -> None:
        self._providers: dict[str, BaseFontProvider] = {}

        if providers:
            for p in providers:
                self.register_provider(p)
        else:
            # Register standard default providers
            self.register_provider(FontsourceProvider())
            self.register_provider(FontSquirrelProvider())
            self.register_provider(NerdFontsProvider())

    def register_provider(self, provider: BaseFontProvider) -> None:
        """Register a font provider instance."""
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> BaseFontProvider:
        """Retrieve a registered provider by name."""
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' is not registered. Available: {list(self._providers.keys())}")
        return self._providers[name]

    def list_providers(self) -> list[str]:
        """List names of all registered providers."""
        return list(self._providers.keys())

    async def sync_provider(self, provider_name: str, repository: FontRepository) -> int:
        """Sync catalog for a specific provider and update database."""
        provider = self.get_provider(provider_name)
        logger.info("Starting catalog sync for provider '%s'", provider_name)

        fonts = await provider.fetch_catalog()
        inserted_count = await repository.upsert_fonts(fonts)
        await repository.prune_stale_provider_fonts(provider_name, [f.id for f in fonts])

        event_bus = get_event_bus()
        await event_bus.emit_async(
            "provider_synced",
            provider=provider_name,
            total_fetched=len(fonts),
            inserted=inserted_count,
        )

        logger.info("Completed sync for '%s': %d fonts fetched", provider_name, len(fonts))
        return len(fonts)

    async def sync_all(
        self,
        repository: FontRepository,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> dict[str, int]:
        """Synchronize catalogs from all registered providers in priority order.

        Args:
            repository: FontRepository to store the deduplicated catalog.
            progress_callback: Optional callback(provider_name, fraction_done).

        Returns:
            Dictionary mapping provider names to count of fetched fonts.
        """
        results: dict[str, int] = {}
        total = len(self._providers)
        event_bus = get_event_bus()

        for idx, (name, provider) in enumerate(self._providers.items()):
            if progress_callback:
                progress_callback(name, idx / max(1, total))

            try:
                count = await self.sync_provider(name, repository)
                results[name] = count
            except Exception as exc:
                logger.error("Error syncing provider '%s': %s", name, exc)
                results[name] = 0

        # Link Nerd Fonts counterparts
        linked_nf_count = await repository.link_nerd_fonts()
        logger.info("Linked %d standard fonts to Nerd Fonts counterparts", linked_nf_count)

        if progress_callback:
            progress_callback("complete", 1.0)

        await event_bus.emit_async(
            "catalog_synced",
            results=results,
            linked_nerd_fonts=linked_nf_count,
        )

        return results

    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Route subset preview request to appropriate provider."""
        provider_name = variant.provider if variant else font.primary_provider
        if provider_name in self._providers:
            provider = self._providers[provider_name]
        else:
            # Fallback to first available provider
            provider = next(iter(self._providers.values()))

        return await provider.fetch_sample_subset(font, sample_text, variant)

    async def download_font_family(
        self,
        font: Font,
        target_dir: Path,
        preferred_provider: str | None = None,
    ) -> list[Path]:
        """Download complete font files using preferred or primary provider."""
        provider_name = preferred_provider or font.primary_provider
        if provider_name in self._providers:
            provider = self._providers[provider_name]
        else:
            provider = next(iter(self._providers.values()))

        return await provider.download_font_family(font, target_dir)

    async def close(self) -> None:
        """Close all registered provider sessions."""
        for provider in self._providers.values():
            try:
                await provider.close()
            except Exception as exc:
                logger.warning("Error closing provider %s: %s", provider.name, exc)
