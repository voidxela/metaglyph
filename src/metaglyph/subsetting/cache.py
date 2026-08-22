"""Micro-font disk and memory cache manager."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from metaglyph.core.config import get_config

logger = logging.getLogger(__name__)


class SubsetCache:
    """Manages disk caching for micro-subset font files."""

    def __init__(self, cache_dir: Path | None = None, max_entries: int = 1000) -> None:
        self.cache_dir = cache_dir or get_config().subsets_cache_dir
        self.max_entries = max_entries
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_cache_key(
        self,
        font_id: str,
        sample_text: str,
        weight: int = 400,
        style: str = "normal",
    ) -> str:
        """Generate a deterministic filename for a subset font.

        Args:
            font_id: Normalized font slug (e.g., 'jetbrains-mono').
            sample_text: Exact sample string to preview.
            weight: Font weight (100-900).
            style: Font style ('normal', 'italic').

        Returns:
            Filename string, e.g. 'jetbrains-mono_400_normal_a1b2c3d4e5f6.ttf'.
        """
        text_hash = hashlib.sha256(sample_text.encode("utf-8")).hexdigest()[:12]
        clean_id = font_id.replace("/", "_").replace("\\", "_")
        clean_style = style.lower().strip()
        return f"{clean_id}_{weight}_{clean_style}_{text_hash}.ttf"

    def get_path(
        self,
        font_id: str,
        sample_text: str,
        weight: int = 400,
        style: str = "normal",
    ) -> Path:
        """Compute the full file path in the cache."""
        filename = self.compute_cache_key(font_id, sample_text, weight, style)
        return self.cache_dir / filename

    def has_subset(
        self,
        font_id: str,
        sample_text: str,
        weight: int = 400,
        style: str = "normal",
    ) -> bool:
        """Check if a valid cached subset exists on disk."""
        path = self.get_path(font_id, sample_text, weight, style)
        return path.exists() and path.stat().st_size > 0

    def get_subset(
        self,
        font_id: str,
        sample_text: str,
        weight: int = 400,
        style: str = "normal",
    ) -> Path | None:
        """Retrieve the path to a cached subset if present, updating its mtime."""
        path = self.get_path(font_id, sample_text, weight, style)
        if path.exists() and path.stat().st_size > 0:
            try:
                path.touch()
            except OSError:
                pass
            return path
        return None

    def save_subset(
        self,
        font_id: str,
        sample_text: str,
        data: bytes,
        weight: int = 400,
        style: str = "normal",
    ) -> Path:
        """Save subset font bytes to cache and prune if necessary."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.get_path(font_id, sample_text, weight, style)
        temp_path = path.with_suffix(".tmp")
        try:
            temp_path.write_bytes(data)
            temp_path.replace(path)
        except OSError:
            # Fallback to direct write if atomic replace fails
            path.write_bytes(data)

        self.prune()
        return path

    def prune(self, max_entries: int | None = None) -> int:
        """Prune oldest cache entries if total count exceeds limit.

        Returns:
            Number of deleted cache files.
        """
        limit = max_entries or self.max_entries
        if limit <= 0:
            return 0

        files = [p for p in self.cache_dir.glob("*.ttf") if p.is_file()]
        if len(files) <= limit:
            return 0

        # Sort by modification time ascending (oldest first)
        files.sort(key=lambda p: p.stat().st_mtime)
        deleted_count = 0
        excess = len(files) - limit
        for p in files[:excess]:
            try:
                p.unlink(missing_ok=True)
                deleted_count += 1
            except OSError as exc:
                logger.warning("Failed to delete cached subset %s: %s", p, exc)

        return deleted_count

    def clear(self) -> int:
        """Delete all cached subsets in directory.

        Returns:
            Number of deleted files.
        """
        deleted = 0
        for p in self.cache_dir.glob("*"):
            if p.is_file():
                try:
                    p.unlink(missing_ok=True)
                    deleted += 1
                except OSError:
                    pass
        return deleted

    def get_stats(self) -> dict[str, int]:
        """Return cache statistics (file count, total bytes)."""
        files = [p for p in self.cache_dir.glob("*.ttf") if p.is_file()]
        total_size = sum(p.stat().st_size for p in files)
        return {
            "count": len(files),
            "total_size_bytes": total_size,
        }
