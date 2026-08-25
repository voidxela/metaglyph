"""Font Squirrel API, @font-face kit downloader, and subset generator."""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import tempfile
import time
import zipfile
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

# Fallback curated list of high-quality Font Squirrel font families
CURATED_FONTSQUIRREL_FONTS: list[tuple[str, str, str, str, str]] = [
    ("ChunkFive", "chunkfive", "serif", "Header", "Chunkfive.otf"),
    ("League Gothic", "league-gothic", "sans-serif", "Header", "LeagueGothic-Regular.otf"),
    ("Junction", "junction", "sans-serif", "Interface", "junction.regular.otf"),
    ("Ostrich Sans", "ostrich-sans", "sans-serif", "Display", "ostrich-regular.ttf"),
    ("Great Vibes", "great-vibes", "handwriting", "Handwriting", "GreatVibes-Regular.otf"),
    ("Alex Brush", "alex-brush", "handwriting", "Handwriting", "AlexBrush-Regular.ttf"),
    ("1942 Report", "1942-report", "monospace", "Code", "1942.ttf"),
    ("20db", "20-db", "display", "Display", "20db.otf"),
    ("3Dumb", "3dumb", "display", "Display", "3Dumb.ttf"),
    ("Aaargh", "aaargh", "sans-serif", "Interface", "Aaargh.ttf"),
    ("Blackout", "blackout", "display", "Display", "blackout_two_am.ttf"),
    ("Cabin", "cabin", "sans-serif", "Interface", "Cabin-Regular.ttf"),
    ("Caviar Dreams", "caviar-dreams", "sans-serif", "Interface", "CaviarDreams.ttf"),
    ("Pacifico", "pacifico", "handwriting", "Handwriting", "Pacifico.ttf"),
    ("Amatic", "amatic", "handwriting", "Handwriting", "AmaticSC-Regular.ttf"),
    ("Bebas Neue", "bebas-neue", "display", "Display", "BebasNeue-Regular.otf"),
    ("League Spartan", "league-spartan", "sans-serif", "Header", "LeagueSpartan-Bold.otf"),
    ("Gidole", "gidole", "sans-serif", "Interface", "Gidole-Regular.ttf"),
    ("Kelson Sans", "kelson-sans", "sans-serif", "Interface", "Kelson-Sans-Regular.otf"),
    ("Aller", "aller", "sans-serif", "Interface", "Aller_Rg.ttf"),
]


class FontSquirrelProvider(BaseFontProvider):
    """Provider integration for Font Squirrel open-source catalog, kits, and subsets."""

    name = "fontsquirrel"
    display_name = "Font Squirrel"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        fontlist_url: str = "https://www.fontsquirrel.com/api/fontlist/all",
        familyinfo_url: str = "https://www.fontsquirrel.com/api/familyinfo",
        download_base_url: str = "https://www.fontsquirrel.com/fontfacekit",
        cache: SubsetCache | None = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout)
        self.fontlist_url = fontlist_url
        self.familyinfo_url = familyinfo_url
        self.download_base_url = download_base_url
        self.cache = cache or SubsetCache()

    def map_classification(self, classification: str | None) -> str:
        """Map raw Font Squirrel classification string to standard category."""
        if not classification:
            return "sans-serif"

        c_lower = classification.strip().lower()
        if "sans" in c_lower:
            return "sans-serif"
        if "serif" in c_lower:
            return "serif"
        if any(t in c_lower for t in ("typewriter", "monospace", "code")):
            return "monospace"
        if any(t in c_lower for t in ("script", "hand", "calligraph", "drawn")):
            return "handwriting"
        if any(t in c_lower for t in ("display", "novelty", "comic", "grunge", "retro", "blackletter", "stencil", "dingbat", "decorative")):
            return "display"

        return "sans-serif"

    def parse_font_item(self, item: dict[str, Any], now: int) -> Font | None:
        """Parse a single Font Squirrel fontlist dictionary item into a Font model."""
        family_name = (item.get("family_name") or "").strip()
        if not family_name:
            return None

        font_id = normalize_family_name(family_name)
        family_urlname = (item.get("family_urlname") or item.get("family_url_name") or font_id).strip()
        raw_classification = item.get("classification")
        category = self.map_classification(raw_classification)
        curated = curate_category(category, family_name)

        font_filename = (item.get("font_filename") or "").lower()
        file_format = "otf" if font_filename.endswith(".otf") else "ttf"

        download_url = f"{self.download_base_url}/{family_urlname}"

        variant = FontVariant(
            font_id=font_id,
            provider=self.name,
            style="normal",
            weight=400,
            file_format=file_format,
            download_url=download_url,
        )

        return Font(
            id=font_id,
            family_name=family_name,
            category=category,
            curated_category=curated,
            is_variable=False,
            has_nerd_font=False,
            primary_provider=self.name,
            last_synced_at=now,
            variants=[variant],
        )

    async def fetch_catalog(self) -> list[Font]:
        """Fetch Font Squirrel font catalog index from API, falling back to curated list."""
        client = await self.get_client()
        now = int(time.time())
        fonts: list[Font] = []

        try:
            logger.info("Fetching Font Squirrel catalog from %s", self.fontlist_url)
            response = await client.get(self.fontlist_url)
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        font = self.parse_font_item(item, now)
                        if font:
                            fonts.append(font)

                if fonts:
                    logger.info("Parsed %d fonts from Font Squirrel catalog", len(fonts))
                    return fonts
        except Exception as exc:
            logger.warning(
                "Failed to fetch Font Squirrel catalog from API (%s), using curated fallback catalog: %s",
                self.fontlist_url,
                exc,
            )

        # Fallback to curated catalog
        for fam_name, urlname, cat, cur_cat, filename in CURATED_FONTSQUIRREL_FONTS:
            font_id = normalize_family_name(fam_name)
            file_format = "otf" if filename.lower().endswith(".otf") else "ttf"
            dl_url = f"{self.download_base_url}/{urlname}"
            variant = FontVariant(
                font_id=font_id,
                provider=self.name,
                style="normal",
                weight=400,
                file_format=file_format,
                download_url=dl_url,
            )
            fonts.append(
                Font(
                    id=font_id,
                    family_name=fam_name,
                    category=cat,
                    curated_category=cur_cat,
                    is_variable=False,
                    has_nerd_font=False,
                    primary_provider=self.name,
                    last_synced_at=now,
                    variants=[variant],
                )
            )

        logger.info("Loaded %d curated Font Squirrel fallback fonts", len(fonts))
        return fonts

    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Fetch font or fontface kit from Font Squirrel and generate micro-subset for preview."""
        weight = variant.weight if variant else 400
        style = variant.style if variant else "normal"

        if cached_path := self.cache.get_subset(font.id, sample_text, weight, style):
            return cached_path

        client = await self.get_client()
        dl_url = variant.download_url if variant and variant.download_url else f"{self.download_base_url}/{font.id}"

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        logger.debug("Created temporary file for Font Squirrel preview download: %s", tmp_path)

        font_bytes: bytes | None = None
        try:
            async with client.stream("GET", dl_url) as resp:
                resp.raise_for_status()
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

            with tmp_path.open("rb") as f:
                magic = f.read(4)

            # Check if ZIP archive (standard for @font-face kits)
            if magic == b"PK\x03\x04":
                with zipfile.ZipFile(tmp_path) as z:
                    font_files = [
                        n for n in z.namelist()
                        if n.lower().endswith((".ttf", ".otf")) and not Path(n).name.startswith(".") and "__MACOSX" not in n
                    ]
                    if not font_files:
                        raise ValueError(f"No TTF/OTF font files found in Font Squirrel kit {dl_url}")

                    # Prefer regular/normal style
                    chosen = font_files[0]
                    for name in font_files:
                        n_lower = name.lower()
                        if "regular" in n_lower or "normal" in n_lower:
                            chosen = name
                            break

                    font_bytes = z.read(chosen)
            else:
                font_bytes = tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)

        if not font_bytes:
            raise ValueError(f"Could not extract font data for Font Squirrel font {font.family_name}")

        subsetted = await asyncio.to_thread(subset_font_bytes, font_bytes, sample_text)
        return self.cache.save_subset(
            font.id,
            sample_text,
            subsetted,
            weight=weight,
            style=style,
        )

    async def download_font_family(
        self,
        font: Font,
        target_dir: Path,
    ) -> list[Path]:
        """Download Font Squirrel font kit and extract TTF/OTF files into target directory."""
        logger.info("Ensuring target directory exists: %s", target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        client = await self.get_client()

        dl_url = font.variants[0].download_url if font.variants and font.variants[0].download_url else f"{self.download_base_url}/{font.id}"

        logger.info("Downloading Font Squirrel kit for %s from %s", font.family_name, dl_url)

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        saved_files: list[Path] = []
        try:
            async with client.stream("GET", dl_url) as resp:
                resp.raise_for_status()
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

            with tmp_path.open("rb") as f:
                magic = f.read(4)

            if magic == b"PK\x03\x04":
                with zipfile.ZipFile(tmp_path) as z:
                    for item in z.infolist():
                        filename = Path(item.filename).name
                        if not filename.lower().endswith((".ttf", ".otf")) or filename.startswith(".") or "__MACOSX" in item.filename:
                            continue

                        target_file = target_dir / filename
                        logger.info("Writing extracted Font Squirrel file: %s", target_file)
                        target_file.write_bytes(z.read(item.filename))
                        saved_files.append(target_file)
            else:
                ext = "otf" if font.variants and font.variants[0].file_format == "otf" else "ttf"
                target_file = target_dir / f"{font.id}.{ext}"
                logger.info("Writing downloaded single font file: %s", target_file)
                shutil.copyfile(tmp_path, target_file)
                saved_files.append(target_file)
        finally:
            tmp_path.unlink(missing_ok=True)

        logger.info("Extracted %d Font Squirrel font files for %s to %s", len(saved_files), font.family_name, target_dir)
        return saved_files
