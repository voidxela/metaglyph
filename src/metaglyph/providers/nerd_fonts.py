"""Nerd Fonts GitHub release asset provider and variant mapper."""

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
from metaglyph.db.normalizer import extract_nerd_font_counterpart, normalize_family_name
from metaglyph.providers.base import BaseFontProvider
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.subsetter import subset_font_bytes

logger = logging.getLogger(__name__)

# Standard curated Nerd Font families in case GitHub API rate limits apply
CURATED_NERD_FONTS = [
    ("Agave", "Agave Nerd Font", "agave"),
    ("AnonymousPro", "AnonymousPro Nerd Font", "anonymous-pro"),
    ("CascadiaCode", "CaskaydiaCove Nerd Font", "cascadia-code"),
    ("CascadiaMono", "CaskaydiaMono Nerd Font", "cascadia-mono"),
    ("CodeNewRoman", "CodeNewRoman Nerd Font", "code-new-roman"),
    ("ComicShannsMono", "ComicShannsMono Nerd Font", "comic-shanns-mono"),
    ("DejaVuSansMono", "DejaVuSansMNerd Font", "dejavu-sans-mono"),
    ("DroidSansMono", "DroidSansMNerd Font", "droid-sans-mono"),
    ("FantasqueSansMono", "FantasqueSansMNerd Font", "fantasque-sans-mono"),
    ("FiraCode", "FiraCode Nerd Font", "fira-code"),
    ("FiraMono", "FiraMono Nerd Font", "fira-mono"),
    ("GeistMono", "GeistMono Nerd Font", "geist-mono"),
    ("Go-Mono", "GoMono Nerd Font", "go-mono"),
    ("Hack", "Hack Nerd Font", "hack"),
    ("Hasklig", "Hasklug Nerd Font", "hasklig"),
    ("Hermit", "Hurmit Nerd Font", "hermit"),
    ("IBMPlexMono", "BlexMono Nerd Font", "ibm-plex-mono"),
    ("Inconsolata", "Inconsolata Nerd Font", "inconsolata"),
    ("InconsolataGo", "InconsolataGo Nerd Font", "inconsolata-go"),
    ("InconsolataLGC", "InconsolataLGC Nerd Font", "inconsolata-lgc"),
    ("Iosevka", "Iosevka Nerd Font", "iosevka"),
    ("IosevkaTerm", "IosevkaTerm Nerd Font", "iosevka-term"),
    ("JetBrainsMono", "JetBrainsMono Nerd Font", "jetbrains-mono"),
    ("LiberationMono", "LiterationMono Nerd Font", "liberation-mono"),
    ("Lilex", "Lilex Nerd Font", "lilex"),
    ("Meslo", "MesloLG Nerd Font", "meslo"),
    ("Monofur", "Monofur Nerd Font", "monofur"),
    ("Monoid", "Monoid Nerd Font", "monoid"),
    ("Mononoki", "Mononoki Nerd Font", "mononoki"),
    ("MPlus", "MPlus Nerd Font", "m-plus"),
    ("Noto", "Noto Nerd Font", "noto-sans"),
    ("OpenDyslexic", "OpenDyslexic Nerd Font", "open-dyslexic"),
    ("Overpass", "Overpass Nerd Font", "overpass"),
    ("ProggyClean", "ProggyClean Nerd Font", "proggy-clean"),
    ("RobotoMono", "RobotoMono Nerd Font", "roboto-mono"),
    ("ShareTechMono", "ShureTechMono Nerd Font", "share-tech-mono"),
    ("SourceCodePro", "SauceCodePro Nerd Font", "source-code-pro"),
    ("SpaceMono", "SpaceMono Nerd Font", "space-mono"),
    ("Terminus", "Terminess Nerd Font", "terminus"),
    ("Ubuntu", "Ubuntu Nerd Font", "ubuntu"),
    ("UbuntuMono", "UbuntuMono Nerd Font", "ubuntu-mono"),
    ("VictorMono", "VictorMono Nerd Font", "victor-mono"),
]


def matches_nerd_font_variant(filename: str, variant: str) -> bool:
    """Check if a font filename corresponds to a specific Nerd Font variant (Standard, Mono, Propo)."""
    name_lower = filename.lower().replace(" ", "").replace("-", "").replace("_", "")
    is_propo = "propo" in name_lower or "nfp" in name_lower
    is_mono = (
        "nerdfontmono" in name_lower
        or "nfm" in name_lower
        or "monoregular" in name_lower
        or "monobold" in name_lower
        or "monoitalic" in name_lower
    )

    v = variant.lower().strip()
    if v == "propo":
        return is_propo
    elif v == "mono":
        return is_mono and not is_propo
    elif v in ("standard", "normal"):
        return not is_mono and not is_propo
    return True


def resolve_nerd_font_download_url(font: Font, variant: FontVariant | None = None) -> str:
    """Resolve direct GitHub release download URL for a Nerd Font family."""
    if variant and variant.download_url:
        return variant.download_url
    if font.variants and font.variants[0].download_url:
        return font.variants[0].download_url

    # Check curated map
    norm_id = normalize_family_name(font.family_name)
    archive_stem: str | None = None
    for stem, fam, _ in CURATED_NERD_FONTS:
        if normalize_family_name(fam) == norm_id or normalize_family_name(fam) == font.id:
            archive_stem = stem
            break

    if not archive_stem:
        clean_name = font.family_name
        for token in ("Nerd Font Mono", "Nerd Font Propo", "Nerd Font", "NFPropo", "NFM", "NF"):
            clean_name = clean_name.replace(token, "")
        archive_stem = clean_name.strip().replace(" ", "")

    return f"https://github.com/ryanoasis/nerd-fonts/releases/latest/download/{archive_stem}.zip"


class NerdFontsProvider(BaseFontProvider):
    """Provider integration for Nerd Fonts releases on GitHub."""

    name = "nerd_fonts"
    display_name = "Nerd Fonts"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        release_api_url: str = "https://api.github.com/repos/ryanoasis/nerd-fonts/releases/latest",
        cache: SubsetCache | None = None,
    ) -> None:
        super().__init__(client=client, timeout=timeout)
        self.release_api_url = release_api_url
        self.cache = cache or SubsetCache()

    async def fetch_catalog(self) -> list[Font]:
        """Fetch Nerd Fonts release catalog from GitHub API, falling back to curated list."""
        client = await self.get_client()
        now = int(time.time())
        fonts: list[Font] = []

        try:
            logger.info("Fetching Nerd Fonts releases from %s", self.release_api_url)
            headers = {"Accept": "application/vnd.github.v3+json"}
            response = await client.get(self.release_api_url, headers=headers)
            response.raise_for_status()

            release_data = response.json()
            assets: list[dict[str, Any]] = release_data.get("assets", [])

            for asset in assets:
                filename = asset.get("name", "")
                if not filename.endswith(".zip") or filename.startswith(("FontPatcher", "cheat-sheet")):
                    continue

                archive_stem = filename[:-4]
                family_name = f"{archive_stem} Nerd Font"
                font_id = normalize_family_name(family_name)
                download_url = asset.get("browser_download_url", "")
                filesize = asset.get("size", 0)

                # Generate standard NF variants
                variants = [
                    FontVariant(
                        font_id=font_id,
                        provider=self.name,
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url=download_url,
                        filesize=filesize,
                    ),
                    FontVariant(
                        font_id=font_id,
                        provider=self.name,
                        style="normal",
                        weight=700,
                        file_format="ttf",
                        download_url=download_url,
                        filesize=filesize,
                    ),
                    FontVariant(
                        font_id=font_id,
                        provider=self.name,
                        style="italic",
                        weight=400,
                        file_format="ttf",
                        download_url=download_url,
                        filesize=filesize,
                    ),
                ]

                font = Font(
                    id=font_id,
                    family_name=family_name,
                    category="monospace",
                    curated_category="Code",
                    is_variable=False,
                    has_nerd_font=True,
                    nerd_font_slug=font_id,
                    primary_provider=self.name,
                    last_synced_at=now,
                    variants=variants,
                )
                fonts.append(font)

            logger.info("Parsed %d Nerd Fonts from GitHub release", len(fonts))
            return fonts

        except Exception as exc:
            logger.warning(
                "Failed to fetch Nerd Fonts from GitHub API (%s), using curated fallback catalog: %s",
                self.release_api_url,
                exc,
            )

        # Fallback to curated catalog
        for archive_stem, family_name, base_slug in CURATED_NERD_FONTS:
            font_id = normalize_family_name(family_name)
            dl_url = f"https://github.com/ryanoasis/nerd-fonts/releases/latest/download/{archive_stem}.zip"
            variants = [
                FontVariant(
                    font_id=font_id,
                    provider=self.name,
                    style="normal",
                    weight=400,
                    file_format="ttf",
                    download_url=dl_url,
                ),
                FontVariant(
                    font_id=font_id,
                    provider=self.name,
                    style="normal",
                    weight=700,
                    file_format="ttf",
                    download_url=dl_url,
                ),
            ]
            fonts.append(
                Font(
                    id=font_id,
                    family_name=family_name,
                    category="monospace",
                    curated_category="Code",
                    is_variable=False,
                    has_nerd_font=True,
                    nerd_font_slug=font_id,
                    primary_provider=self.name,
                    last_synced_at=now,
                    variants=variants,
                )
            )

        return fonts

    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Fetch or extract font from Nerd Font release zip and create micro-subset."""
        weight = variant.weight if variant else 400
        style = variant.style if variant else "normal"

        if cached_path := self.cache.get_subset(font.id, sample_text, weight, style):
            return cached_path

        client = await self.get_client()
        dl_url = resolve_nerd_font_download_url(font, variant)

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        logger.debug("Created temporary file for Nerd Font preview download: %s", tmp_path)

        try:
            async with client.stream("GET", dl_url) as resp:
                resp.raise_for_status()
                logger.debug("Writing downloaded preview stream to temporary file: %s", tmp_path)
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

            font_bytes: bytes | None = None
            logger.debug("Reading header from temporary preview file: %s", tmp_path)
            with tmp_path.open("rb") as f:
                magic = f.read(4)

            # If the downloaded file is a zip archive
            if magic == b"PK\x03\x04":
                with zipfile.ZipFile(tmp_path) as z:
                    font_files = [n for n in z.namelist() if n.lower().endswith((".ttf", ".otf"))]
                    if not font_files:
                        raise ValueError(f"No font files in Nerd Font archive {dl_url}")

                    # Choose best matching variant file (e.g. Regular or Mono)
                    chosen = font_files[0]
                    for name in font_files:
                        name_lower = name.lower()
                        if "regular" in name_lower and not ("italic" in name_lower or "bold" in name_lower):
                            chosen = name
                            break
                        elif "mono" in name_lower:
                            chosen = name

                    font_bytes = z.read(chosen)
            else:
                logger.debug("Reading preview font bytes from %s", tmp_path)
                font_bytes = tmp_path.read_bytes()
        finally:
            logger.debug("Removing temporary preview download file: %s", tmp_path)
            tmp_path.unlink(missing_ok=True)


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
        variant_filter: str | None = None,
    ) -> list[Path]:
        """Download Nerd Font zip archive and extract matching TTF/OTF files.

        Args:
            font: Font metadata.
            target_dir: Destination folder.
            variant_filter: Optional filter ('Standard', 'Mono', 'Propo').
        """
        logger.info("Ensuring target directory exists: %s", target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        client = await self.get_client()
        dl_url = resolve_nerd_font_download_url(font)

        logger.info("Downloading Nerd Font zip for %s from %s", font.family_name, dl_url)

        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        logger.info("Created temporary archive file: %s", tmp_path)

        saved_files: list[Path] = []
        try:
            async with client.stream("GET", dl_url) as resp:
                resp.raise_for_status()
                logger.info("Writing downloaded zip stream to %s", tmp_path)
                with tmp_path.open("wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

            logger.info("Reading header from temporary file: %s", tmp_path)
            with tmp_path.open("rb") as f:
                magic = f.read(4)

            if magic == b"PK\x03\x04":
                with zipfile.ZipFile(tmp_path) as z:
                    for item in z.infolist():
                        filename = Path(item.filename).name
                        if not filename.lower().endswith((".ttf", ".otf")) or filename.startswith("."):
                            continue

                        # Apply variant filter if specified
                        if variant_filter and not matches_nerd_font_variant(filename, variant_filter):
                            continue

                        target_file = target_dir / filename
                        logger.info("Writing extracted Nerd Font file: %s", target_file)
                        target_file.write_bytes(z.read(item.filename))
                        saved_files.append(target_file)
            else:
                # Single font file response
                target_file = target_dir / f"{font.id}.ttf"
                logger.info("Copying font file from %s to %s", tmp_path, target_file)
                shutil.copyfile(tmp_path, target_file)
                saved_files.append(target_file)
        finally:
            logger.info("Removing temporary download file: %s", tmp_path)
            tmp_path.unlink(missing_ok=True)

        logger.info("Extracted %d Nerd Font files for %s to %s", len(saved_files), font.family_name, target_dir)
        return saved_files

