"""Font Squirrel API, live catalog fetcher, font kit downloader, and subset generator."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import shutil
import tempfile
import time
import urllib.parse
import zipfile
from collections import defaultdict
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

# Standard browser navigation headers to reduce CloudFront challenge rates
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def classify_family(family_name: str, folder_name: str) -> tuple[str, str]:
    """Determine standard category and curated category based on family metadata."""
    text = f"{family_name} {folder_name}".lower()

    if any(k in text for k in ("mono", "code", "typewriter", "writer", "report", "console", "terminal", "fixed", "courier")):
        return "monospace", "Code"
    if any(k in text for k in ("script", "brush", "calligraph", "hand", "cursive", "signature", "pen", "sketch", "doodle", "vibes", "brush")):
        return "handwriting", "Handwriting"
    if any(k in text for k in ("serif", "slab", "roman", "antiqua", "bodoni", "garamond", "baskerville", "didot", "times", "caslon", "minion", "chunkfive")):
        return "serif", "Prose"
    if any(k in text for k in ("display", "titling", "poster", "blackletter", "gothic", "stencil", "retro", "comic", "grunge", "novelty", "3d", "outline", "shadow", "decorative", "20db", "3dumb", "bebas")):
        return "display", "Display"

    return "sans-serif", "Interface"


def parse_weight_and_style(filename: str, folder: str) -> tuple[int, str]:
    """Parse font weight number and style ('normal' | 'italic') from path cues."""
    text = f"{folder} {filename}".lower()
    style = "italic" if any(k in text for k in ("italic", "oblique", "it")) else "normal"

    if any(k in text for k in ("black", "heavy")):
        weight = 900
    elif any(k in text for k in ("extrabold", "ultrabold")):
        weight = 800
    elif any(k in text for k in ("bold", "bd")):
        weight = 700
    elif any(k in text for k in ("semibold", "demibold")):
        weight = 600
    elif any(k in text for k in ("medium", "md")):
        weight = 500
    elif any(k in text for k in ("light", "lt")):
        weight = 300
    elif any(k in text for k in ("extralight", "thin")):
        weight = 200
    else:
        weight = 400

    return weight, style


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
        github_tree_url: str = "https://api.github.com/repos/Jolg42/FontSquirrel-Fonts/git/trees/master?recursive=1",
        raw_base_url: str = "https://raw.githubusercontent.com/Jolg42/FontSquirrel-Fonts/master",
        cache: SubsetCache | None = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout)
        self.fontlist_url = fontlist_url
        self.familyinfo_url = familyinfo_url
        self.download_base_url = download_base_url
        self.github_tree_url = github_tree_url
        self.raw_base_url = raw_base_url
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
        """Parse a single Font Squirrel fontlist API dictionary item into a Font model."""
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

    def parse_github_tree(self, tree: list[dict[str, Any]], now: int) -> list[Font]:
        """Parse live GitHub tree entries into complete Font models with all variant files."""
        families_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for item in tree:
            path = item.get("path", "")
            if path.startswith("Fonts/") and path.lower().endswith((".ttf", ".otf")):
                parts = path.split("/")
                if len(parts) >= 3:
                    folder = parts[1]
                    families_map[folder].append(item)

        fonts: list[Font] = []
        for folder, items in families_map.items():
            raw_family_name = folder.replace("-", " ").replace("_", " ").strip()
            # Title case family name cleanly
            family_name = " ".join(word.capitalize() for word in raw_family_name.split())
            font_id = normalize_family_name(folder)
            category, curated = classify_family(family_name, folder)

            variants: list[FontVariant] = []
            for item in items:
                path = item["path"]
                filename = Path(path).name
                ext = filename.rsplit(".", 1)[-1].lower()
                parent_folder = Path(path).parent.name
                weight, style = parse_weight_and_style(filename, parent_folder)

                encoded_path = "/".join(urllib.parse.quote(part) for part in path.split("/"))
                dl_url = f"{self.raw_base_url}/{encoded_path}"

                variants.append(
                    FontVariant(
                        font_id=font_id,
                        provider=self.name,
                        style=style,
                        weight=weight,
                        file_format=ext,
                        download_url=dl_url,
                    )
                )

            if variants:
                fonts.append(
                    Font(
                        id=font_id,
                        family_name=family_name,
                        category=category,
                        curated_category=curated,
                        is_variable=False,
                        has_nerd_font=False,
                        primary_provider=self.name,
                        last_synced_at=now,
                        variants=variants,
                    )
                )

        return fonts

    async def fetch_catalog(self) -> list[Font]:
        """Fetch live Font Squirrel catalog index dynamically without hardcoded fallback lists."""
        client = await self.get_client()
        now = int(time.time())

        # 1. Attempt direct Font Squirrel API
        try:
            logger.info("Attempting to fetch Font Squirrel catalog from official API: %s", self.fontlist_url)
            response = await client.get(self.fontlist_url, headers=BROWSER_HEADERS)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    fonts = [
                        font for item in data
                        if isinstance(item, dict) and (font := self.parse_font_item(item, now))
                    ]
                    if fonts:
                        logger.info("Successfully parsed %d fonts from Font Squirrel official API", len(fonts))
                        return fonts
            else:
                logger.warning(
                    "Font Squirrel official API returned status %d (likely CloudFront WAF challenge)",
                    response.status_code,
                )
        except Exception as exc:
            logger.warning("Font Squirrel official API request failed: %s", exc)

        # 2. Fetch live full catalog tree from GitHub repository
        logger.info("Fetching Font Squirrel live catalog from repository tree: %s", self.github_tree_url)
        headers = {"User-Agent": "Metaglyph/1.0", "Accept": "application/json"}
        resp = await client.get(self.github_tree_url, headers=headers)
        resp.raise_for_status()

        tree_data = resp.json()
        tree = tree_data.get("tree", [])
        if not tree:
            raise ValueError(f"No tree items returned from {self.github_tree_url}")

        fonts = self.parse_github_tree(tree, now)
        if not fonts:
            raise ValueError(f"Failed to parse any fonts from repository tree at {self.github_tree_url}")

        logger.info("Successfully fetched and parsed %d Font Squirrel font families dynamically", len(fonts))
        return fonts

    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Fetch font or kit from Font Squirrel and generate micro-subset for preview."""
        weight = variant.weight if variant else 400
        style = variant.style if variant else "normal"

        if cached_path := self.cache.get_subset(font.id, sample_text, weight, style):
            return cached_path

        client = await self.get_client()

        # Determine target variant download URL
        dl_url: str | None = None
        if variant and variant.download_url:
            dl_url = variant.download_url
        elif font.variants:
            # Find best match for requested weight/style
            matching = [v for v in font.variants if v.weight == weight and v.style == style]
            chosen_var = matching[0] if matching else font.variants[0]
            dl_url = chosen_var.download_url
        else:
            dl_url = f"{self.download_base_url}/{font.id}"

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        logger.debug("Downloading font preview bytes from %s to %s", dl_url, tmp_path)

        font_bytes: bytes | None = None
        try:
            async with client.stream("GET", dl_url, headers=BROWSER_HEADERS) as resp:
                resp.raise_for_status()
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

            with tmp_path.open("rb") as f:
                magic = f.read(4)

            # If ZIP archive kit, extract font file
            if magic == b"PK\x03\x04":
                with zipfile.ZipFile(tmp_path) as z:
                    font_files = [
                        n for n in z.namelist()
                        if n.lower().endswith((".ttf", ".otf")) and not Path(n).name.startswith(".") and "__MACOSX" not in n
                    ]
                    if not font_files:
                        raise ValueError(f"No TTF/OTF font files found in Font Squirrel kit {dl_url}")

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
        """Download complete Font Squirrel font family and extract TTF/OTF files into target directory."""
        logger.info("Ensuring target directory exists: %s", target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        client = await self.get_client()

        saved_files: list[Path] = []

        if not font.variants:
            raise ValueError(f"No variants defined for font {font.family_name}")

        # Check if variants contain direct font URLs (e.g. from GitHub tree)
        direct_variants = [v for v in font.variants if v.download_url and v.download_url.lower().endswith((".ttf", ".otf"))]

        if direct_variants:
            logger.info("Downloading %d direct variant files for %s", len(direct_variants), font.family_name)
            semaphore = asyncio.Semaphore(6)

            async def _download_variant(var: FontVariant) -> Path | None:
                assert var.download_url is not None
                filename = urllib.parse.unquote(Path(var.download_url).name)
                dest = target_dir / filename
                async with semaphore:
                    try:
                        r = await client.get(var.download_url, headers=BROWSER_HEADERS)
                        r.raise_for_status()
                        dest.write_bytes(r.content)
                        logger.info("Saved font variant: %s", dest)
                        return dest
                    except Exception as exc:
                        logger.warning("Failed downloading variant %s: %s", var.download_url, exc)
                        return None

            results = await asyncio.gather(*[_download_variant(v) for v in direct_variants])
            saved_files = [p for p in results if p is not None]
            if saved_files:
                return saved_files

        # Fallback: download as zip kit
        dl_url = font.variants[0].download_url if font.variants and font.variants[0].download_url else f"{self.download_base_url}/{font.id}"
        logger.info("Downloading Font Squirrel zip kit for %s from %s", font.family_name, dl_url)

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            async with client.stream("GET", dl_url, headers=BROWSER_HEADERS) as resp:
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
                ext = font.variants[0].file_format if font.variants else "ttf"
                target_file = target_dir / f"{font.id}.{ext}"
                logger.info("Writing downloaded single font file: %s", target_file)
                shutil.copyfile(tmp_path, target_file)
                saved_files.append(target_file)
        finally:
            tmp_path.unlink(missing_ok=True)

        logger.info("Extracted %d Font Squirrel font files for %s to %s", len(saved_files), font.family_name, target_dir)
        return saved_files
