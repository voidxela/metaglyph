"""Fontsource API client, CDN downloader, and subset generator."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from pathlib import Path
from typing import Any
import httpx

from metaglyph.core.config import get_config
from metaglyph.db.models import Font, FontVariant
from metaglyph.db.normalizer import curate_category, normalize_family_name
from metaglyph.providers.base import BaseFontProvider
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.subsetter import subset_font_bytes

logger = logging.getLogger(__name__)


class FontsourceProvider(BaseFontProvider):
    """Provider integration for Fontsource open-source fonts API and CDN."""

    name = "fontsource"
    display_name = "Fontsource"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        index_url: str = "https://api.fontsource.org/v1/fonts",
        cdn_base_url: str = "https://cdn.jsdelivr.net/fontsource/fonts",
        cache: SubsetCache | None = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout)
        self.index_url = index_url
        self.cdn_base_url = cdn_base_url
        self.cache = cache or SubsetCache()

    def build_cdn_variant_url(
        self,
        font_id: str,
        weight: int = 400,
        style: str = "normal",
        subset: str = "latin",
        format_ext: str = "ttf",
    ) -> str:
        """Construct direct CDN URL for a Fontsource font file."""
        return f"{self.cdn_base_url}/{font_id}@latest/{subset}-{weight}-{style}.{format_ext}"

    async def fetch_catalog(self) -> list[Font]:
        """Fetch Fontsource catalog index from API and convert to Font models."""
        client = await self.get_client()
        logger.info("Fetching Fontsource catalog from %s", self.index_url)
        response = await client.get(self.index_url)
        response.raise_for_status()

        data: list[dict[str, Any]] = response.json()
        now = int(time.time())

        fonts: list[Font] = []
        for item in data:
            raw_id = item.get("id")
            family_name = item.get("family")
            if not raw_id or not family_name:
                continue

            font_id = normalize_family_name(family_name)
            category = (item.get("category") or "sans-serif").lower()
            curated = curate_category(category, family_name)
            is_variable = bool(item.get("variable", False))

            weights = item.get("weights", [400])
            styles = item.get("styles", ["normal"])

            variants: list[FontVariant] = []
            for weight in weights:
                for style in styles:
                    dl_url = self.build_cdn_variant_url(
                        raw_id, weight=weight, style=style, subset="latin", format_ext="ttf"
                    )
                    variants.append(
                        FontVariant(
                            font_id=font_id,
                            provider=self.name,
                            style=style,
                            weight=int(weight),
                            file_format="ttf",
                            download_url=dl_url,
                        )
                    )

            font = Font(
                id=font_id,
                family_name=family_name,
                category=category,
                curated_category=curated,
                is_variable=is_variable,
                has_nerd_font=False,
                primary_provider=self.name,
                last_synced_at=now,
                variants=variants,
            )
            fonts.append(font)

        logger.info("Parsed %d fonts from Fontsource catalog", len(fonts))
        return fonts

    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Fetch font file from Fontsource CDN and generate a micro-subset for preview."""
        weight = variant.weight if variant else 400
        style = variant.style if variant else "normal"

        # Check local cache first
        if cached_path := self.cache.get_subset(font.id, sample_text, weight, style):
            return cached_path

        client = await self.get_client()

        # Determine download URL for the target or fallback variant
        target_url = None
        for v in font.variants:
            if v.weight == weight and v.style == style:
                target_url = v.download_url
                break

        if not target_url:
            target_url = self.build_cdn_variant_url(
                font.id, weight=weight, style=style, subset="latin", format_ext="ttf"
            )

        try:
            res = await client.get(target_url)
            res.raise_for_status()
            font_bytes = res.content
        except Exception as exc:
            logger.warning(
                "Failed to download variant %d-%s for %s from CDN (%s), trying fallback 400 normal: %s",
                weight,
                style,
                font.family_name,
                target_url,
                exc,
            )
            # Fallback to 400 normal if specific weight/style not available
            fallback_url = self.build_cdn_variant_url(
                font.id, weight=400, style="normal", subset="latin", format_ext="ttf"
            )
            res = await client.get(fallback_url)
            res.raise_for_status()
            font_bytes = res.content

        # Create micro-subset with fontTools
        subsetted_bytes = await asyncio.to_thread(subset_font_bytes, font_bytes, sample_text)
        return await asyncio.to_thread(
            self.cache.save_subset,
            font.id,
            sample_text,
            subsetted_bytes,
            weight=weight,
            style=style,
        )

    async def download_font_family(
        self,
        font: Font,
        target_dir: Path,
    ) -> list[Path]:
        """Download all font files (TTF) for the Fontsource family."""
        logger.info("Ensuring target directory exists: %s", target_dir)
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
        client = await self.get_client()

        # If font has no variants, create default 400 normal
        raw_variants = font.variants or [
            FontVariant(
                font_id=font.id,
                provider=self.name,
                style="normal",
                weight=400,
                file_format="ttf",
                download_url=self.build_cdn_variant_url(font.id, 400, "normal"),
            )
        ]

        # Deduplicate variants by (weight, style, file_format) to avoid duplicate downloads / file collisions
        seen_keys: set[tuple[int, str, str]] = set()
        variants_to_download: list[FontVariant] = []
        for v in raw_variants:
            key = (v.weight, v.style, v.file_format)
            if key not in seen_keys:
                seen_keys.add(key)
                variants_to_download.append(v)

        # Download up to 8 variants concurrently
        semaphore = asyncio.Semaphore(8)

        async def _download_one(v: FontVariant) -> Path | None:
            clean_family = font.family_name.replace(" ", "")
            dest_filename = f"{clean_family}-{v.weight}-{v.style}.{v.file_format}"
            dest_path = target_dir / dest_filename
            try:
                async with semaphore:
                    res = await client.get(v.download_url)
                    res.raise_for_status()
                    logger.info("Writing downloaded font file: %s", dest_path)
                    await asyncio.to_thread(dest_path.write_bytes, res.content)
                    return dest_path
            except Exception as exc:
                logger.warning("Failed to download variant %s: %s", v.download_url, exc)
                return None

        tasks = [_download_one(v) for v in variants_to_download]
        results = await asyncio.gather(*tasks)

        saved_files = [p for p in results if p is not None]
        logger.info(
            "Downloaded %d font files for %s to %s",
            len(saved_files),
            font.family_name,
            target_dir,
        )
        return saved_files
