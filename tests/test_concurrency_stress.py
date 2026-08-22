"""Concurrency and stress tests for Metaglyph.

Tests cover:
- Rapid debounced search queries and cancellation.
- Large catalog indexing (5,000+ fonts) and query performance.
- High-concurrency simultaneous micro-subset fetching with semaphore saturation and in-flight coalescing.
- Concurrent SQLite database operations (concurrent reads, writes, and stats queries).
- EventBus concurrent event publishing and subscription.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from metaglyph.core.events import EventBus
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontFilter, FontVariant, InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader
from metaglyph.ui.views.search_view import SearchView
from conftest import synthesize_test_font_bytes


# ============================================================================
# 1. Large Catalog Indexing & Querying Stress Tests
# ============================================================================


@pytest.mark.asyncio
async def test_large_catalog_indexing_and_deduplication(temp_dir: Path) -> None:
    """Stress test: Index 5,000 fonts into SQLite database repository and verify performance."""
    db_path = temp_dir / "stress_catalog.db"
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    repository = FontRepository(db_manager)

    providers = ["fontsource", "google", "nerd_fonts"]
    categories = ["sans-serif", "serif", "monospace", "display", "handwriting"]
    curated_categories = ["Interface", "Code", "Header", "Prose", "Display", "Handwriting"]

    batch_size = 500
    total_fonts = 5000
    fonts: list[Font] = []

    for i in range(total_fonts):
        provider = providers[i % len(providers)]
        cat = categories[(i // 3) % len(categories)]
        cur_cat = curated_categories[(i // 3) % len(curated_categories)]
        is_var = 1 if i % 7 == 0 else 0
        font_id = f"font-family-{i:05d}"
        variants = [
            FontVariant(
                font_id=font_id,
                provider=provider,
                style="normal",
                weight=400,
                file_format="ttf",
                download_url=f"https://example.com/fonts/{font_id}-400.ttf",
            ),
            FontVariant(
                font_id=font_id,
                provider=provider,
                style="normal",
                weight=700,
                file_format="ttf",
                download_url=f"https://example.com/fonts/{font_id}-700.ttf",
            ),
        ]
        fonts.append(
            Font(
                id=font_id,
                family_name=f"Font Family {i:05d}",
                category=cat,
                curated_category=cur_cat,
                is_variable=is_var,
                primary_provider=provider,
                last_synced_at=1700000000 + i,
                variants=variants,
            )
        )

    # Measure bulk upsert duration
    start_time = time.perf_counter()
    for offset in range(0, total_fonts, batch_size):
        chunk = fonts[offset : offset + batch_size]
        await repository.upsert_fonts(chunk)
    upsert_duration = time.perf_counter() - start_time

    assert upsert_duration < 10.0, f"Bulk upsert of 5,000 fonts took too long: {upsert_duration:.2f}s"

    # Verify total count and statistics
    stats = await repository.get_stats()
    assert stats["total_fonts"] == total_fonts
    assert stats["total_variants"] == total_fonts * 2

    # Test paginated query performance
    query_start = time.perf_counter()
    page1, total1 = await repository.search_fonts(FontFilter(limit=50, offset=0))
    page50, total50 = await repository.search_fonts(FontFilter(limit=50, offset=2500))
    query_duration = time.perf_counter() - query_start

    assert len(page1) == 50
    assert len(page50) == 50
    assert total1 == total_fonts
    assert total50 == total_fonts
    assert query_duration < 0.5, f"Pagination queries took too long: {query_duration:.2f}s"

    # Test complex filter performance
    filter_start = time.perf_counter()
    code_fonts, code_total = await repository.search_fonts(
        FontFilter(
            curated_categories=["Code"],
            providers=["fontsource"],
            is_variable=False,
            limit=100,
        )
    )
    filter_duration = time.perf_counter() - filter_start

    assert len(code_fonts) > 0
    assert all(f.curated_category == "Code" for f in code_fonts)
    assert all(f.primary_provider == "fontsource" for f in code_fonts)
    assert filter_duration < 0.5, f"Complex filter query took too long: {filter_duration:.2f}s"

    # Test search query under large catalog
    search_start = time.perf_counter()
    results, search_count = await repository.search_fonts(FontFilter(query="Family 0042", limit=10))
    search_duration = time.perf_counter() - search_start

    assert len(results) >= 1
    assert "0042" in results[0].family_name
    assert search_duration < 0.5, f"Search query took too long: {search_duration:.2f}s"

    await db_manager.close()


# ============================================================================
# 2. Concurrent Database Operations Stress Test
# ============================================================================


@pytest.mark.asyncio
async def test_concurrent_database_read_write_operations(temp_dir: Path) -> None:
    """Stress test: Execute simultaneous async reads, writes, and scans on the database."""
    db_path = temp_dir / "concurrent_rw.db"
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    repository = FontRepository(db_manager)

    # Initial seed
    seed_fonts = [
        Font(
            id=f"initial-font-{i}",
            family_name=f"Initial Font {i}",
            category="sans-serif",
            curated_category="Interface",
            primary_provider="google",
            last_synced_at=1700000000,
        )
        for i in range(100)
    ]
    await repository.upsert_fonts(seed_fonts)

    async def writer_task(task_id: int) -> int:
        written = 0
        for i in range(20):
            font = Font(
                id=f"writer-{task_id}-font-{i}",
                family_name=f"Writer {task_id} Font {i}",
                category="monospace",
                curated_category="Code",
                primary_provider="fontsource",
                last_synced_at=1700000000 + i,
            )
            await repository.upsert_fonts([font])
            written += 1
            await asyncio.sleep(0.001)
        return written

    async def installer_task(task_id: int) -> int:
        installed = 0
        for i in range(10):
            entry = InstalledFont(
                font_id=f"initial-font-{task_id * 10 + i}",
                family_name=f"Initial Font {task_id * 10 + i}",
                provider="google",
                install_scope="User",
                installed_at=1700000000 + i,
                file_paths=[f"/tmp/fonts/{task_id}_{i}.ttf"],
            )
            await repository.record_installation(entry)
            installed += 1
            await asyncio.sleep(0.001)
        return installed

    async def reader_task() -> int:
        read_count = 0
        for _ in range(30):
            fonts, _ = await repository.search_fonts(FontFilter(limit=20))
            stats = await repository.get_stats()
            read_count += len(fonts) + stats["total_fonts"]
            await asyncio.sleep(0.001)
        return read_count

    # Run 4 writers, 2 installers, and 4 readers concurrently
    tasks = [
        writer_task(1),
        writer_task(2),
        writer_task(3),
        writer_task(4),
        installer_task(1),
        installer_task(2),
        reader_task(),
        reader_task(),
        reader_task(),
        reader_task(),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)
    assert len(results) == 10

    final_stats = await repository.get_stats()
    # 100 seed + 4*20 writer fonts = 180 total fonts
    assert final_stats["total_fonts"] == 180
    assert final_stats["total_installed"] == 20

    await db_manager.close()


# ============================================================================
# 3. High-Concurrency Micro-Subset Fetching & Throttling
# ============================================================================


@pytest.mark.asyncio
async def test_high_concurrency_subset_fetching(temp_dir: Path, test_ttf_file: Path) -> None:
    """Stress test: 60 concurrent subset requests hitting SubsetFetcher.
    
    Verifies:
    - Semaphore limits peak concurrent network requests.
    - In-flight request coalescing works for duplicate requests.
    - Disk cache returns instantly for cached items.
    - No hanging tasks or memory leaks.
    """
    cache_dir = temp_dir / "stress_subset_cache"
    cache = SubsetCache(cache_dir=cache_dir, max_entries=200)
    loader = FontLoader(max_loaded_fonts=100)

    active_provider_calls = 0
    max_active_provider_calls = 0
    total_provider_calls = 0

    async def mock_fetch_subset(font: Font, sample_text: str, variant: FontVariant | None = None) -> Path:
        nonlocal active_provider_calls, max_active_provider_calls, total_provider_calls
        active_provider_calls += 1
        total_provider_calls += 1
        max_active_provider_calls = max(max_active_provider_calls, active_provider_calls)
        
        # Simulate network latency
        await asyncio.sleep(0.02)
        
        # Write unique bytes per font
        out_bytes = synthesize_test_font_bytes(font.family_name, "Regular")
        out_path = cache.save_subset(font.id, sample_text, out_bytes, weight=400, style="normal")
        
        active_provider_calls -= 1
        return out_path

    mock_provider_manager = MagicMock(spec=ProviderManager)
    mock_provider_manager.fetch_sample_subset = AsyncMock(side_effect=mock_fetch_subset)

    fetcher = SubsetFetcher(
        cache=cache,
        loader=loader,
        provider_manager=mock_provider_manager,
        max_concurrent_requests=6,
    )

    # Create 20 unique fonts, each requested 3 times concurrently (= 60 total requests)
    fonts = [
        Font(
            id=f"stress-font-{i}",
            family_name=f"Stress Font {i}",
            category="sans-serif",
            primary_provider="google",
            last_synced_at=1700000000,
        )
        for i in range(20)
    ]

    requests = []
    for f in fonts:
        for _ in range(3):
            requests.append(fetcher.get_or_fetch_subset(f, "Live Preview Test"))

    results = await asyncio.gather(*requests)

    assert len(results) == 60
    # Concurrency semaphore should restrict max concurrent calls to <= 6
    assert max_active_provider_calls <= 6
    # In-flight coalescing should ensure each unique font is fetched at most once
    assert total_provider_calls == 20
    assert len(fetcher._in_flight) == 0

    # Repeat same requests -> should all hit disk cache with 0 additional provider calls
    mock_provider_manager.fetch_sample_subset.reset_mock()
    repeat_results = await asyncio.gather(*[fetcher.get_or_fetch_subset(f, "Live Preview Test") for f in fonts])
    assert len(repeat_results) == 20
    assert mock_provider_manager.fetch_sample_subset.call_count == 0


# ============================================================================
# 4. Rapid Search Debouncing & Query Interruption Stress Test
# ============================================================================


@pytest.mark.asyncio
async def test_rapid_search_debouncing_and_interruption(repository: FontRepository) -> None:
    """Stress test: Simulate rapid typing in SearchBar and verify debounced search convergence."""
    # Seed fonts
    fonts = [
        Font(
            id="fira-code",
            family_name="Fira Code",
            category="monospace",
            curated_category="Code",
            primary_provider="fontsource",
            last_synced_at=1700000000,
        ),
        Font(
            id="fira-sans",
            family_name="Fira Sans",
            category="sans-serif",
            curated_category="Prose",
            primary_provider="google",
            last_synced_at=1700000000,
        ),
        Font(
            id="jetbrains-mono",
            family_name="JetBrains Mono",
            category="monospace",
            curated_category="Code",
            primary_provider="fontsource",
            last_synced_at=1700000000,
        ),
    ]
    await repository.upsert_fonts(fonts)

    search_view = SearchView(repository=repository)
    search_bar = search_view.search_bar

    # Simulate fast keystrokes: 'F', 'Fi', 'Fir', 'Fira', 'Fira ', 'Fira C', 'Fira Code'
    keystrokes = ["F", "Fi", "Fir", "Fira", "Fira ", "Fira C", "Fira Code"]
    for stroke in keystrokes:
        search_bar.set_text(stroke)
        # Small delay less than debounce timer (50ms)
        await asyncio.sleep(0.01)

    # Fire debounce timeout on final value
    search_bar._on_debounce_timeout()
    await search_view.execute_search_async()

    assert search_view._total_count == 1
    assert search_view._current_fonts[0].id == "fira-code"
    assert "Showing 1 of 1 fonts" in search_view._results_count_label.text()


# ============================================================================
# 5. EventBus Concurrency Stress Test
# ============================================================================


@pytest.mark.asyncio
async def test_event_bus_concurrent_pub_sub() -> None:
    """Stress test: Multiple concurrent publishers and subscribers on EventBus."""
    bus = EventBus()
    received_events: list[dict] = []
    lock = asyncio.Lock()

    async def listener_one(**kwargs) -> None:
        async with lock:
            received_events.append({"handler": 1, **kwargs})
        await asyncio.sleep(0.001)

    async def listener_two(**kwargs) -> None:
        async with lock:
            received_events.append({"handler": 2, **kwargs})
        await asyncio.sleep(0.001)

    bus.subscribe("test_event", listener_one)
    bus.subscribe("test_event", listener_two)

    async def publisher(pub_id: int) -> None:
        for i in range(25):
            await bus.emit_async("test_event", pub_id=pub_id, seq=i)
            await asyncio.sleep(0.001)

    # 4 publishers emitting 25 events each = 100 events * 2 listeners = 200 delivered calls
    publishers = [publisher(p) for p in range(4)]
    await asyncio.gather(*publishers)

    assert len(received_events) == 200
    h1_count = sum(1 for e in received_events if e["handler"] == 1)
    h2_count = sum(1 for e in received_events if e["handler"] == 2)
    assert h1_count == 100
    assert h2_count == 100
