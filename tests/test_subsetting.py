"""Tests for dynamic micro-subsetting, caching, and font loading."""

from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from fontTools.ttLib import TTFont

from metaglyph.core.config import Config
from metaglyph.db.models import Font, FontVariant
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader, extract_font_family_name
from metaglyph.subsetting.subsetter import (
    create_subset_options,
    subset_font_bytes,
    subset_font_file,
)
from conftest import synthesize_test_font_bytes


def test_create_subset_options() -> None:
    """Verify default subset options strip non-essential tables."""
    opts = create_subset_options()
    assert opts.desubroutinize is True
    assert "DSIG" in opts.drop_tables
    assert "MATH" in opts.drop_tables


def test_subset_font_bytes(test_ttf_bytes: bytes) -> None:
    """Verify subsetting reduces glyph count to only requested characters."""
    sample_text = "ABC"
    subset_bytes = subset_font_bytes(test_ttf_bytes, sample_text)
    assert len(subset_bytes) > 0

    original_font = TTFont(io.BytesIO(test_ttf_bytes))
    subset_font = TTFont(io.BytesIO(subset_bytes))

    orig_glyphs = original_font.getGlyphOrder()
    subset_glyphs = subset_font.getGlyphOrder()

    assert len(subset_glyphs) < len(orig_glyphs)
    assert "A" in subset_glyphs
    assert "B" in subset_glyphs
    assert "C" in subset_glyphs
    assert "Z" not in subset_glyphs


def test_subset_font_bytes_empty_string(test_ttf_bytes: bytes) -> None:
    """Verify empty text falls back gracefully to whitespace subset."""
    subset_bytes = subset_font_bytes(test_ttf_bytes, "")
    assert len(subset_bytes) > 0


def test_subset_font_file(temp_dir: Path, test_ttf_file: Path) -> None:
    """Verify subsetting from and to file paths."""
    out_path = temp_dir / "subsets" / "test_subset.ttf"
    result = subset_font_file(test_ttf_file, out_path, "TEST")

    assert result == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_subset_cache_operations(temp_dir: Path) -> None:
    """Verify SubsetCache storage, key generation, and retrieval."""
    cache_dir = temp_dir / "cache_subsets"
    cache = SubsetCache(cache_dir=cache_dir, max_entries=5)

    key = cache.compute_cache_key("jetbrains-mono", "Hello", weight=700, style="italic")
    assert "jetbrains-mono_700_italic_" in key
    assert key.endswith(".ttf")

    assert not cache.has_subset("jetbrains-mono", "Hello", weight=700, style="italic")
    assert cache.get_subset("jetbrains-mono", "Hello", weight=700, style="italic") is None

    # Save subset
    font_bytes = b"\x00\x01\x00\x00testfontdata"
    saved_path = cache.save_subset("jetbrains-mono", "Hello", font_bytes, weight=700, style="italic")
    assert saved_path.exists()
    assert cache.has_subset("jetbrains-mono", "Hello", weight=700, style="italic")

    retrieved = cache.get_subset("jetbrains-mono", "Hello", weight=700, style="italic")
    assert retrieved == saved_path
    assert retrieved.read_bytes() == font_bytes


def test_subset_cache_pruning(temp_dir: Path) -> None:
    """Verify LRU pruning removes oldest cache entries."""
    cache_dir = temp_dir / "prune_cache"
    cache = SubsetCache(cache_dir=cache_dir, max_entries=3)

    # Save 4 items
    for i in range(4):
        p = cache.save_subset(f"font-{i}", f"sample-{i}", b"\x00\x01\x00\x00" + f"bytes-{i}".encode(), weight=400, style="normal")
        # Ensure distinct timestamps
        time.sleep(0.01)

    stats = cache.get_stats()
    assert stats["count"] <= 3


def test_subset_cache_clear(temp_dir: Path) -> None:
    """Verify clear removes all subset files."""
    cache_dir = temp_dir / "clear_cache"
    cache = SubsetCache(cache_dir=cache_dir)
    cache.save_subset("font-a", "sample", b"\x00\x01\x00\x00123")
    cache.save_subset("font-b", "sample", b"\x00\x01\x00\x00456")

    assert cache.get_stats()["count"] == 2
    deleted = cache.clear()
    assert deleted == 2
    assert cache.get_stats()["count"] == 0


def test_font_loader_extract_name(test_ttf_file: Path) -> None:
    """Verify font family name extraction from TTF metadata."""
    name = extract_font_family_name(test_ttf_file)
    assert name == "Test Font"


def test_font_loader_lifecycle(test_ttf_file: Path) -> None:
    """Verify FontLoader registration, lookup, and unloading."""
    loader = FontLoader(max_loaded_fonts=2)

    font_id, family = loader.load_font(test_ttf_file)
    assert family == "Test Font"
    assert loader.is_loaded(test_ttf_file)
    assert loader.get_loaded_count() == 1

    # Reloading returns same metadata
    font_id2, family2 = loader.load_font(test_ttf_file)
    assert font_id2 == font_id
    assert family2 == family

    # Unload
    unloaded = loader.unload_font(test_ttf_file)
    assert unloaded is True
    assert not loader.is_loaded(test_ttf_file)
    assert loader.get_loaded_count() == 0

    # Unload nonexistent
    assert not loader.unload_font(test_ttf_file)


def test_font_loader_capacity_eviction(temp_dir: Path) -> None:
    """Verify FontLoader evicts oldest font when max_loaded_fonts is reached."""
    loader = FontLoader(max_loaded_fonts=2)

    f1 = temp_dir / "font1.ttf"
    f2 = temp_dir / "font2.ttf"
    f3 = temp_dir / "font3.ttf"

    f1.write_bytes(synthesize_test_font_bytes("Font One", "Regular"))
    f2.write_bytes(synthesize_test_font_bytes("Font Two", "Regular"))
    f3.write_bytes(synthesize_test_font_bytes("Font Three", "Regular"))

    loader.load_font(f1)
    loader.load_font(f2)
    assert loader.get_loaded_count() == 2

    # Loading third font should evict f1
    loader.load_font(f3)
    assert loader.get_loaded_count() == 2
    assert not loader.is_loaded(f1)
    assert loader.is_loaded(f2)
    assert loader.is_loaded(f3)

    loader.unload_all()
    assert loader.get_loaded_count() == 0


@pytest.mark.asyncio
async def test_subset_fetcher_cache_hit_and_miss(
    temp_dir: Path,
    sample_font_jetbrains: Font,
    test_ttf_file: Path,
) -> None:
    """Verify SubsetFetcher hits cache when available or fetches from provider."""
    cache = SubsetCache(cache_dir=temp_dir / "fetcher_cache")
    loader = FontLoader()

    mock_provider_manager = MagicMock(spec=ProviderManager)
    mock_provider_manager.fetch_sample_subset = AsyncMock(return_value=test_ttf_file)

    fetcher = SubsetFetcher(
        cache=cache,
        loader=loader,
        provider_manager=mock_provider_manager,
    )

    # 1. Miss: calls provider
    path, name = await fetcher.get_or_fetch_subset(sample_font_jetbrains, "Preview Text")
    assert path == test_ttf_file
    assert name == "Test Font"
    assert mock_provider_manager.fetch_sample_subset.call_count == 1

    # Pre-populate cache for another call
    cache.save_subset(sample_font_jetbrains.id, "Cached Text", test_ttf_file.read_bytes())
    # 2. Hit: does not call provider again
    mock_provider_manager.fetch_sample_subset.reset_mock()
    path2, name2 = await fetcher.get_or_fetch_subset(sample_font_jetbrains, "Cached Text")
    assert path2.exists()
    assert mock_provider_manager.fetch_sample_subset.call_count == 0


@pytest.mark.asyncio
async def test_subset_fetcher_in_flight_coalescing(
    temp_dir: Path,
    sample_font_jetbrains: Font,
    test_ttf_file: Path,
) -> None:
    """Verify multiple concurrent requests for the same font coalesce into one provider call."""
    cache = SubsetCache(cache_dir=temp_dir / "coalesce_cache")
    loader = FontLoader()

    call_count = 0

    async def slow_fetch(font: Font, sample_text: str, variant: FontVariant | None = None) -> Path:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return test_ttf_file

    mock_manager = MagicMock(spec=ProviderManager)
    mock_manager.fetch_sample_subset = AsyncMock(side_effect=slow_fetch)

    fetcher = SubsetFetcher(
        cache=cache,
        loader=loader,
        provider_manager=mock_manager,
    )

    # Trigger 5 concurrent requests for identical font & sample
    results = await asyncio.gather(
        fetcher.get_or_fetch_subset(sample_font_jetbrains, "Concurrent Sample"),
        fetcher.get_or_fetch_subset(sample_font_jetbrains, "Concurrent Sample"),
        fetcher.get_or_fetch_subset(sample_font_jetbrains, "Concurrent Sample"),
        fetcher.get_or_fetch_subset(sample_font_jetbrains, "Concurrent Sample"),
        fetcher.get_or_fetch_subset(sample_font_jetbrains, "Concurrent Sample"),
    )

    assert len(results) == 5
    for path, name in results:
        assert path == test_ttf_file
        assert name == "Test Font"

    # Crucial assertion: provider was called only once despite 5 requests
    assert call_count == 1


@pytest.mark.asyncio
async def test_subset_fetcher_prefetch(
    temp_dir: Path,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
    test_ttf_file: Path,
) -> None:
    """Verify prefetch_subsets handles batch font list."""
    cache = SubsetCache(cache_dir=temp_dir / "prefetch_cache")
    loader = FontLoader()

    mock_manager = MagicMock(spec=ProviderManager)
    mock_manager.fetch_sample_subset = AsyncMock(return_value=test_ttf_file)

    fetcher = SubsetFetcher(
        cache=cache,
        loader=loader,
        provider_manager=mock_manager,
    )

    results = await fetcher.prefetch_subsets([sample_font_jetbrains, sample_font_inter], "Sample Text")
    assert len(results) == 2
    assert mock_manager.fetch_sample_subset.call_count == 2
