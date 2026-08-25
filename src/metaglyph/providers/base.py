"""Base abstract font provider interface and common networking utilities."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
import httpx

from metaglyph.core.config import get_config
from metaglyph.db.models import Font, FontVariant

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Metaglyph/0.1.0 (Font Manager; +https://github.com/voidxela/metaglyph)"


class BaseFontProvider(ABC):
    """Abstract base class for all remote font providers."""

    name: str
    display_name: str

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        cache_dir: Path | None = None,
    ) -> None:
        self._custom_client = client
        self._client: httpx.AsyncClient | None = client
        self.timeout = timeout
        self.cache_dir = cache_dir or get_config().cache_dir
        self.downloads_dir = get_config().downloads_cache_dir
        logger.info("Ensuring downloads cache directory exists: %s", self.downloads_dir)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

    async def get_client(self) -> httpx.AsyncClient:
        """Get or initialize the underlying httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": DEFAULT_USER_AGENT}
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    @abstractmethod
    async def fetch_catalog(self) -> list[Font]:
        """Fetch remote catalog index and return parsed Font models."""
        pass

    @abstractmethod
    async def fetch_sample_subset(
        self,
        font: Font,
        sample_text: str,
        variant: FontVariant | None = None,
    ) -> Path:
        """Download or generate a micro-subset font file containing only sample_text glyphs.

        Args:
            font: The font metadata model.
            sample_text: Text string for preview subset.
            variant: Optional specific variant/style (defaults to 400 normal).

        Returns:
            Path to the downloaded or generated micro-subset file.
        """
        pass

    @abstractmethod
    async def download_font_family(
        self,
        font: Font,
        target_dir: Path,
    ) -> list[Path]:
        """Download all font files (TTF/OTF) belonging to the font family.

        Args:
            font: The font metadata model.
            target_dir: Destination directory to store full font files.

        Returns:
            List of absolute paths to downloaded font files.
        """
        pass

    async def download_variant(
        self,
        font: Font,
        variant: FontVariant,
        target_dir: Path,
    ) -> Path:
        """Download a single font variant file.

        Default implementation streams the variant's download_url.
        """
        logger.info("Ensuring download target directory exists: %s", target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{font.id}-{variant.weight}-{variant.style}.{variant.file_format}"
        dest_path = target_dir / filename

        client = await self.get_client()
        response = await client.get(variant.download_url)
        response.raise_for_status()
        logger.info("Writing downloaded font variant to %s", dest_path)
        dest_path.write_bytes(response.content)
        return dest_path


    async def close(self) -> None:
        """Close HTTP client session."""
        if self._client is not None and not self._client.is_closed:
            if self._custom_client is None:
                await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BaseFontProvider:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
