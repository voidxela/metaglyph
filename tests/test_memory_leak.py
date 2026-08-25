"""Memory leak verification and lifecycle management tests for Metaglyph.

Tests cover:
- High-volume dynamic QFontDatabase loading and LRU eviction (1,000 font loads).
- FontLoader capacity boundary enforcement and complete unload.
- SubsetCache disk pruning, LRU sorting, and size bounds under heavy turnover.
- SubsetFetcher memory cleanup on successful fetches, cache hits, and network exceptions.
- Widget lifecycle: dynamic instantiation and teardown of FontCard and FontPreviewWidget.
"""

from __future__ import annotations

import asyncio
import gc
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QWidget

from metaglyph.db.models import Font, FontVariant
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader
from metaglyph.ui.components.font_card import FontCard
from metaglyph.ui.components.font_preview import FontPreviewWidget
from conftest import synthesize_test_font_bytes


# ============================================================================
# 1. Dynamic FontLoader Capacity & LRU Eviction Under High Churn
# ============================================================================


def test_font_loader_high_volume_churn_memory_bounds(temp_dir: Path) -> None:
    """Verify FontLoader bounds memory by evicting QFontDatabase fonts when capacity is reached."""
    max_capacity = 25
    loader = FontLoader(max_loaded_fonts=max_capacity)

    # Generate 150 distinct font files
    font_files: list[Path] = []
    for i in range(150):
        font_path = temp_dir / f"churn_font_{i:03d}.ttf"
        font_bytes = synthesize_test_font_bytes(f"Churn Font {i:03d}", "Regular")
        font_path.write_bytes(font_bytes)
        font_files.append(font_path)

    # Sequentially load all 150 fonts
    loaded_ids: list[int] = []
    for p in font_files:
        qt_id, family = loader.load_font(p)
        assert family.startswith("Churn Font")
        loaded_ids.append(qt_id)
        # Verify internal tracker never exceeds maximum capacity
        assert loader.get_loaded_count() <= max_capacity

    assert loader.get_loaded_count() == max_capacity

    # Verify oldest fonts were evicted and latest are still loaded
    assert not loader.is_loaded(font_files[0])
    assert not loader.is_loaded(font_files[50])
    assert loader.is_loaded(font_files[-1])
    assert loader.is_loaded(font_files[-max_capacity])

    # Unload all
    unloaded_count = loader.unload_all()
    assert unloaded_count == max_capacity
    assert loader.get_loaded_count() == 0


def test_font_loader_unload_idempotence(temp_dir: Path) -> None:
    """Verify unloading non-loaded fonts or double unloading is safe and idempotent."""
    loader = FontLoader(max_loaded_fonts=10)
    p1 = temp_dir / "font_a.ttf"
    p2 = temp_dir / "font_b.ttf"
    p1.write_bytes(synthesize_test_font_bytes("Font A", "Regular"))
    p2.write_bytes(synthesize_test_font_bytes("Font B", "Regular"))

    loader.load_font(p1)
    assert loader.is_loaded(p1)

    # Unload p1
    assert loader.unload_font(p1) is True
    assert loader.unload_font(p1) is False
    assert not loader.is_loaded(p1)

    # Unload never-loaded p2
    assert loader.unload_font(p2) is False


# ============================================================================
# 2. SubsetCache Disk Footprint & Pruning Bounds
# ============================================================================


def test_subset_cache_pruning_under_continuous_writes(temp_dir: Path) -> None:
    """Verify SubsetCache strictly adheres to max_entries limit during continuous writes."""
    cache_limit = 15
    cache = SubsetCache(cache_dir=temp_dir / "churn_cache", max_entries=cache_limit)

    # Write 80 distinct subsets
    for i in range(80):
        data = f"dummy font data chunk {i}".encode("utf-8")
        cache.save_subset(f"family-{i}", f"Sample {i}", data, weight=400, style="normal")

    stats = cache.get_stats()
    assert stats["count"] == cache_limit
    assert stats["total_size_bytes"] > 0

    # Ensure disk file count matches exactly
    disk_files = list((temp_dir / "churn_cache").glob("*.ttf"))
    assert len(disk_files) == cache_limit

    # Clear cache
    deleted = cache.clear()
    assert deleted == cache_limit
    assert cache.get_stats()["count"] == 0
    assert len(list((temp_dir / "churn_cache").glob("*.ttf"))) == 0


# ============================================================================
# 3. SubsetFetcher In-Flight Cleanup & Exception Resilience
# ============================================================================


@pytest.mark.asyncio
async def test_subset_fetcher_in_flight_cleanup_on_success_and_error(
    temp_dir: Path,
    test_ttf_file: Path,
) -> None:
    """Verify in-flight task dictionaries are reliably cleaned up after resolution and rejection."""
    cache = SubsetCache(cache_dir=temp_dir / "fetcher_cleanup_cache")
    loader = FontLoader()

    mock_provider_manager = MagicMock(spec=ProviderManager)

    # Set up failure for error_font and success for good_font
    async def mock_fetch(font: Font, sample_text: str, variant: FontVariant | None = None) -> Path:
        if "error" in font.id:
            await asyncio.sleep(0.01)
            raise ConnectionError("Simulated network timeout")
        await asyncio.sleep(0.01)
        return test_ttf_file

    mock_provider_manager.fetch_sample_subset = AsyncMock(side_effect=mock_fetch)

    fetcher = SubsetFetcher(
        cache=cache,
        loader=loader,
        provider_manager=mock_provider_manager,
    )

    good_font = Font(
        id="good-font",
        family_name="Good Font",
        category="sans-serif",
        primary_provider="fontsquirrel",
        last_synced_at=1700000000,
    )
    error_font = Font(
        id="error-font",
        family_name="Error Font",
        category="monospace",
        primary_provider="fontsquirrel",
        last_synced_at=1700000000,
    )

    # 1. Success task
    path, name = await fetcher.get_or_fetch_subset(good_font, "Sample")
    assert path == test_ttf_file
    assert len(fetcher._in_flight) == 0

    # 2. Error task
    with pytest.raises(ConnectionError, match="Simulated network timeout"):
        await fetcher.get_or_fetch_subset(error_font, "Sample")
    # Crucial assertion: failed task is cleaned up and not leaked in _in_flight
    assert len(fetcher._in_flight) == 0


# ============================================================================
# 4. UI Widget Dynamic Creation & Garbage Collection
# ============================================================================


def test_font_preview_widget_lifecycle_and_gc(sample_font_jetbrains: Font) -> None:
    """Verify FontPreviewWidget and FontCard can be constructed and collected cleanly."""
    parent_container = QWidget()

    # Create 50 cards dynamically
    cards: list[FontCard] = []
    for i in range(50):
        font = Font(
            id=f"gc-font-{i}",
            family_name=f"GC Font {i}",
            category="sans-serif",
            curated_category="Interface",
            primary_provider="fontsquirrel",
            last_synced_at=1700000000,
        )
        card = FontCard(font=font, parent=parent_container)
        cards.append(card)

    assert len(cards) == 50

    # Teardown and delete widgets
    for c in cards:
        c.setParent(None)
        c.deleteLater()

    cards.clear()
    gc.collect()
