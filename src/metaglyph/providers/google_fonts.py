"""Google Fonts API and CSS2 micro-subset provider."""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
import urllib.parse
import zipfile
from pathlib import Path
import httpx

from metaglyph.core.config import get_config
from metaglyph.db.models import Font, FontVariant
from metaglyph.db.normalizer import curate_category, normalize_family_name
from metaglyph.providers.base import BaseFontProvider
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.subsetter import subset_font_bytes

logger = logging.getLogger(__name__)

# User-Agent that triggers Google Fonts CSS2 API to deliver Truetype (.ttf) format
TTF_USER_AGENT = "Mozilla/5.0 (Linux; U; Android 2.2; en-us; Nexus One Build/FRF91) AppleWebKit/533.1 (KHTML, like Gecko) Version/4.0 Mobile Safari/533.1"


class GoogleFontsProvider(BaseFontProvider):
    """Provider integration for Google Fonts catalog, micro-subsets, and full packages."""

    name = "google"
    display_name = "Google Fonts"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        metadata_url: str = "https://fonts.google.com/metadata/fonts",
        css2_base_url: str = "https://fonts.googleapis.com/css2",
        download_base_url: str = "https://fonts.google.com/download",
        cache: SubsetCache | None = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout)
        self.metadata_url = metadata_url
        self.css2_base_url = css2_base_url
        self.download_base_url = download_base_url
        self.cache = cache or SubsetCache()

    def parse_variant_string(self, variant_str: str, font_id: str, family_name: str) -> FontVariant:
        """Parse Google Fonts variant token (e.g., 'regular', '700italic', '100') into FontVariant."""
        v_clean = variant_str.lower().strip()
        is_italic = "italic" in v_clean
        style = "italic" if is_italic else "normal"

        weight_str = re.sub(r"[^\d]", "", v_clean)
        if not weight_str:
            weight = 400
        else:
            weight = int(weight_str)

        encoded_family = urllib.parse.quote(family_name)
        dl_url = f"{self.download_base_url}?family={encoded_family}"

        return FontVariant(
            font_id=font_id,
            provider=self.name,
            style=style,
            weight=weight,
            file_format="ttf",
            download_url=dl_url,
        )

    async def fetch_catalog(self) -> list[Font]:
        """Fetch full Google Fonts catalog metadata and convert to Font models."""
        client = await self.get_client()
        logger.info("Fetching Google Fonts catalog from %s", self.metadata_url)
        response = await client.get(self.metadata_url)
        response.raise_for_status()

        data = response.json()
        raw_families = data.get("familyMetadataList", [])
        now = int(time.time())

        fonts: list[Font] = []
        for item in raw_families:
            family_name = item.get("family")
            if not family_name:
                continue

            font_id = normalize_family_name(family_name)
            raw_category = (item.get("category") or "sans-serif").lower()
            category_map = {
                "sans_serif": "sans-serif",
                "display": "display",
                "handwriting": "handwriting",
                "monospace": "monospace",
                "serif": "serif",
            }
            category = category_map.get(raw_category, raw_category)
            curated = curate_category(category, family_name)

            # Check variable font capabilities
            axes = item.get("axes", [])
            is_variable = bool(axes)

            # Parse variants
            raw_variants = item.get("variants", ["regular"])
            variants: list[FontVariant] = []
            seen_combos = set()
            for v_str in raw_variants:
                variant = self.parse_variant_string(v_str, font_id, family_name)
                combo_key = (variant.weight, variant.style)
                if combo_key not in seen_combos:
                    seen_combos.add(combo_key)
                    variants.append(variant)

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

        logger.info("Parsed %d fonts from Google Fonts catalog", len(fonts))
        return fonts

    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Fetch a micro-subset TTF file from Google Fonts CSS2 API for preview."""
        weight = variant.weight if variant else 400
        style = variant.style if variant else "normal"

        # Check local cache first
        if cached_path := self.cache.get_subset(font.id, sample_text, weight, style):
            return cached_path

        client = await self.get_client()

        # Build Google Fonts CSS2 query
        # Example: Roboto:ital,wght@0,400 or Roboto:wght@700
        family_param = font.family_name.replace(" ", "+")
        ital_val = 1 if style == "italic" else 0
        encoded_text = urllib.parse.quote(sample_text)

        css_url = (
            f"{self.css2_base_url}?family={family_param}:ital,wght@{ital_val},{weight}"
            f"&text={encoded_text}&display=swap"
        )

        try:
            css_response = await client.get(css_url, headers={"User-Agent": TTF_USER_AGENT})
            css_response.raise_for_status()
            css_content = css_response.text

            # Extract font URL from CSS
            urls = re.findall(r"src:\s*url\((https?://[^)]+)\)", css_content)
            if urls:
                font_url = urls[0]
                font_response = await client.get(font_url)
                font_response.raise_for_status()
                font_bytes = font_response.content

                # Cache and return
                return self.cache.save_subset(
                    font.id,
                    sample_text,
                    font_bytes,
                    weight=weight,
                    style=style,
                )
        except Exception as exc:
            logger.warning("Google Fonts CSS2 subset fetch failed for %s: %s", font.family_name, exc)

        # Fallback: Download full font or family zip and subset locally with fontTools
        return await self._fallback_subset(font, sample_text, weight, style)

    async def _fallback_subset(
        self,
        font: Font,
        sample_text: str,
        weight: int,
        style: str,
    ) -> Path:
        """Fallback subsetting via downloading full font package or CSS2 and slicing with fontTools."""
        client = await self.get_client()
        zip_url = f"{self.download_base_url}?family={urllib.parse.quote(font.family_name)}"

        raw_bytes: bytes | None = None
        try:
            res = await client.get(zip_url)
            if res.status_code == 200 and res.content.startswith(b"PK\x03\x04"):
                with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                    font_files = [n for n in z.namelist() if n.lower().endswith((".ttf", ".otf"))]
                    if font_files:
                        chosen = font_files[0]
                        for name in font_files:
                            name_lower = name.lower()
                            if str(weight) in name_lower or (style == "italic" and "italic" in name_lower):
                                chosen = name
                                break
                        raw_bytes = z.read(chosen)
        except Exception as exc:
            logger.warning("Failed to extract font from Google archive for %s: %s", font.family_name, exc)

        if raw_bytes is None:
            # Fetch complete variant via CSS2 without &text=
            family_param = font.family_name.replace(" ", "+")
            ital_val = 1 if style == "italic" else 0
            css_url = f"{self.css2_base_url}?family={family_param}:ital,wght@{ital_val},{weight}&display=swap"
            css_resp = await client.get(css_url, headers={"User-Agent": TTF_USER_AGENT})
            css_resp.raise_for_status()
            urls = re.findall(r"src:\s*url\((https?://[^)]+)\)", css_resp.text)
            if not urls:
                raise ValueError(f"Could not resolve font URL for {font.family_name}")
            f_resp = await client.get(urls[0])
            f_resp.raise_for_status()
            raw_bytes = f_resp.content

        subsetted = await asyncio.to_thread(subset_font_bytes, raw_bytes, sample_text)
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
        """Download complete Google Fonts family and extract TTF/OTF files."""
        logger.info("Ensuring target directory exists: %s", target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        client = await self.get_client()
        saved_files: list[Path] = []

        # 1. Check if download_base_url returns a valid zip archive
        zip_url = f"{self.download_base_url}?family={urllib.parse.quote(font.family_name)}"
        try:
            logger.info("Attempting Google Fonts archive download for %s from %s", font.family_name, zip_url)
            response = await client.get(zip_url)
            if response.status_code == 200 and response.content.startswith(b"PK\x03\x04"):
                with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                    for item in z.infolist():
                        filename = Path(item.filename).name
                        if filename.lower().endswith((".ttf", ".otf")) and not filename.startswith("."):
                            target_file = target_dir / filename
                            logger.info("Writing extracted Google Font file: %s", target_file)
                            target_file.write_bytes(z.read(item.filename))
                            saved_files.append(target_file)
                if saved_files:
                    logger.info("Extracted %d font files from archive for %s", len(saved_files), font.family_name)
                    return saved_files
        except Exception as exc:
            logger.warning("Archive download not available or failed for %s: %s", font.family_name, exc)

        # 2. Download TTF font files directly via Google Fonts CSS2 API
        family_param = font.family_name.replace(" ", "+")
        css_urls_to_try = [
            f"{self.css2_base_url}?family={family_param}:ital,wght@0,100..900;1,100..900&display=swap",
            f"{self.css2_base_url}?family={family_param}:ital,wght@0,400;0,700;1,400;1,700&display=swap",
            f"{self.css2_base_url}?family={family_param}&display=swap",
        ]

        css_content: str | None = None
        for css_url in css_urls_to_try:
            try:
                resp = await client.get(css_url, headers={"User-Agent": TTF_USER_AGENT})
                if resp.status_code == 200 and "src:" in resp.text:
                    css_content = resp.text
                    break
            except Exception as exc:
                logger.warning("Failed CSS2 query %s: %s", css_url, exc)
                continue

        if not css_content:
            raise ValueError(f"Could not retrieve CSS metadata for Google Font {font.family_name}")

        # Parse @font-face blocks to extract all variant TTF URLs
        blocks = css_content.split("@font-face")
        variant_targets: list[tuple[int, str, str]] = []
        seen_combos: set[tuple[int, str]] = set()

        for block in blocks[1:]:
            w_match = re.search(r"font-weight:\s*(\d+)", block)
            s_match = re.search(r"font-style:\s*(\w+)", block)
            u_match = re.search(r"src:\s*url\((https?://[^)]+)\)", block)
            if u_match:
                weight = int(w_match.group(1)) if w_match else 400
                style = s_match.group(1) if s_match else "normal"
                combo = (weight, style)
                if combo not in seen_combos:
                    seen_combos.add(combo)
                    variant_targets.append((weight, style, u_match.group(1)))

        semaphore = asyncio.Semaphore(6)
        clean_name = font.family_name.replace(" ", "")

        async def _download_variant(w: int, s: str, u: str) -> Path | None:
            dest = target_dir / f"{clean_name}-{w}-{s}.ttf"
            try:
                async with semaphore:
                    r = await client.get(u)
                    r.raise_for_status()
                    logger.info("Writing downloaded Google Font variant: %s", dest)
                    dest.write_bytes(r.content)
                    return dest
            except Exception as exc:
                logger.warning("Failed to download variant %d %s from %s: %s", w, s, u, exc)
                return None

        tasks = [_download_variant(w, s, u) for w, s, u in variant_targets]
        results = await asyncio.gather(*tasks)
        saved_files = [p for p in results if p is not None]

        logger.info("Extracted %d font files for %s to %s", len(saved_files), font.family_name, target_dir)
        return saved_files

