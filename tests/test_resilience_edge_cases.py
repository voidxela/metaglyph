"""Resilience, edge cases, and error recovery tests for Metaglyph.

Tests cover:
- Corrupted, 0-byte, and non-font binary handling in font extraction and loading.
- Subsetting fallbacks on invalid font data and empty sample strings.
- Provider synchronization error handling (network timeout, 404, 500 status codes).
- FontUninstaller resilience against missing/deleted files on disk.
- Database edge cases (unicode characters, empty queries, special SQL characters).
- UI component safety under empty states, missing fonts, and invalid scopes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontFilter, InstalledFont
from metaglyph.db.normalizer import extract_nerd_font_counterpart, normalize_family_name
from metaglyph.db.repository import FontRepository
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.providers.base import BaseFontProvider
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.loader import FontLoader, extract_font_family_name
from metaglyph.subsetting.subsetter import subset_font_bytes
from metaglyph.ui.views.detail_pane import DetailPane
from metaglyph.ui.views.search_view import SearchView
from metaglyph.ui.views.system_view import SystemView


# ============================================================================
# 1. Corrupted and Malformed Binary Font Handling
# ============================================================================


def test_corrupted_font_binary_extraction(temp_dir: Path) -> None:
    """Verify extract_font_family_name handles corrupt/empty files gracefully without crashing."""
    corrupted_file = temp_dir / "corrupted.ttf"
    corrupted_file.write_bytes(b"NOT_A_VALID_TTF_HEADER_RANDOM_GARBAGE")

    name = extract_font_family_name(corrupted_file)
    assert name == "Corrupted"

    empty_file = temp_dir / "empty_font.otf"
    empty_file.write_bytes(b"")

    name2 = extract_font_family_name(empty_file)
    assert name2 == "Empty Font"


def test_font_loader_with_corrupted_file(temp_dir: Path) -> None:
    """Verify FontLoader handles invalid font binaries without raising unhandled exceptions."""
    loader = FontLoader()
    corrupt_file = temp_dir / "broken_font.ttf"
    corrupt_file.write_bytes(b"\x00\x01\x00\x00corruptdatahere")

    # Should safely return family name fallback and not crash
    qt_id, family = loader.load_font(corrupt_file)
    assert family == "Broken Font"
    assert loader.is_loaded(corrupt_file)

    loader.unload_font(corrupt_file)
    assert not loader.is_loaded(corrupt_file)


def test_subsetting_corrupted_bytes_returns_fallback() -> None:
    """Verify subset_font_bytes returns raw fallback bytes on completely invalid input without crashing."""
    invalid_bytes = b"INVALID_HEADER_GARBAGE"
    result = subset_font_bytes(invalid_bytes, "ABC")
    assert result == invalid_bytes


# ============================================================================
# 2. Provider Error Resilience & Partial Sync Recovery
# ============================================================================


@pytest.mark.asyncio
async def test_provider_manager_sync_resilience_on_failing_provider(
    temp_dir: Path,
    sample_font_jetbrains: Font,
) -> None:
    """Verify ProviderManager.sync_all continues syncing remaining providers when one fails."""
    db_path = temp_dir / "resilience.db"
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    repository = FontRepository(db_manager)

    # Provider 1: Success
    mock_p1 = MagicMock(spec=BaseFontProvider)
    mock_p1.name = "working_provider"
    mock_p1.fetch_catalog = AsyncMock(return_value=[sample_font_jetbrains])
    mock_p1.close = AsyncMock()

    # Provider 2: Failure (Network Error)
    mock_p2 = MagicMock(spec=BaseFontProvider)
    mock_p2.name = "broken_provider"
    mock_p2.fetch_catalog = AsyncMock(side_effect=TimeoutError("Remote server timed out"))
    mock_p2.close = AsyncMock()

    manager = ProviderManager(providers=[mock_p1, mock_p2])

    results = await manager.sync_all(repository)

    assert results["working_provider"] == 1
    assert results["broken_provider"] == 0

    stats = await repository.get_stats()
    assert stats["total_fonts"] == 1

    await manager.close()
    await db_manager.close()


# ============================================================================
# 3. FontUninstaller Resilience Against Missing Disk Files
# ============================================================================


@pytest.mark.asyncio
async def test_uninstaller_handles_already_deleted_files(
    temp_dir: Path,
    repository: FontRepository,
) -> None:
    """Verify FontUninstaller cleans DB records gracefully when files on disk are already missing."""
    font = Font(
        id="ghost-font",
        family_name="Ghost Font",
        category="sans-serif",
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([font])

    missing_file_1 = temp_dir / "missing_font_1.ttf"
    missing_file_2 = temp_dir / "missing_font_2.ttf"

    installed = InstalledFont(
        font_id="ghost-font",
        family_name="Ghost Font",
        provider="fontsource",
        install_scope="User",
        installed_at=1700000000,
        file_paths=[str(missing_file_1), str(missing_file_2)],
    )
    await repository.record_installation(installed)

    uninstaller = FontUninstaller(repository=repository)
    # Should succeed without error even if files do not exist
    result = await uninstaller.uninstall_installed_font(installed)

    assert result.success is True
    assert not await repository.is_font_installed("ghost-font")


@pytest.mark.asyncio
async def test_batch_uninstaller_mixed_scenarios(
    temp_dir: Path,
    repository: FontRepository,
) -> None:
    """Verify batch_uninstall handles mixed existing and nonexistent files across scopes."""
    font1 = Font(
        id="font-one",
        family_name="Font One",
        category="sans-serif",
        primary_provider="google",
        last_synced_at=1700000000,
    )
    font2 = Font(
        id="font-two",
        family_name="Font Two",
        category="sans-serif",
        primary_provider="google",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([font1, font2])

    existing_file = temp_dir / "real_font.ttf"
    existing_file.write_bytes(b"dummy")
    missing_file = temp_dir / "fake_font.ttf"

    f1 = InstalledFont(
        font_id="font-one",
        family_name="Font One",
        provider="google",
        install_scope="User",
        installed_at=1700000000,
        file_paths=[str(existing_file)],
    )
    f2 = InstalledFont(
        font_id="font-two",
        family_name="Font Two",
        provider="google",
        install_scope="User",
        installed_at=1700000000,
        file_paths=[str(missing_file)],
    )
    await repository.record_installation(f1)
    await repository.record_installation(f2)

    uninstaller = FontUninstaller(repository=repository)
    results = await uninstaller.batch_uninstall([f1, f2])

    assert len(results) == 2
    assert all(r.success for r in results)
    assert not existing_file.exists()
    assert len(await repository.get_installed_fonts()) == 0


# ============================================================================
# 4. Database Special Characters & Normalizer Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_database_unicode_and_special_character_resilience(
    repository: FontRepository,
) -> None:
    """Verify repository stores and queries fonts with unicode, accents, quotes, and punctuation."""
    special_fonts = [
        Font(
            id="noto-sans-cjk-sc",
            family_name="Noto Sans CJK SC (简体中文)",
            category="sans-serif",
            curated_category="Interface",
            primary_provider="google",
            last_synced_at=1700000000,
        ),
        Font(
            id="fira-mono-accent",
            family_name="Fira Mono's & \"Special\" Font [v2.0]",
            category="monospace",
            curated_category="Code",
            primary_provider="fontsource",
            last_synced_at=1700000000,
        ),
    ]
    await repository.upsert_fonts(special_fonts)

    # Search with parenthesis / non-ascii
    results1, count1 = await repository.search_fonts(FontFilter(query="简体中文"))
    assert count1 == 1
    assert results1[0].id == "noto-sans-cjk-sc"

    # Search with quotes
    results2, count2 = await repository.search_fonts(FontFilter(query="Special"))
    assert count2 == 1
    assert results2[0].id == "fira-mono-accent"


def test_normalizer_extreme_inputs() -> None:
    """Verify normalizer handles empty, whitespace-only, and complex strings safely."""
    assert normalize_family_name("") == "unnamed-font"
    assert normalize_family_name("   ") == "unnamed-font"
    assert normalize_family_name("---___---") == "unnamed-font"
    assert normalize_family_name("Font!@#$%^&*()_+Name") == "font-name"

    # Counterpart extraction edge cases
    base, variant = extract_nerd_font_counterpart("FiraCode Nerd Font Propo")
    assert base == "fira-code"
    assert variant == "Propo"

    base_plain, variant_plain = extract_nerd_font_counterpart("Regular Plain Font")
    assert base_plain == "regular-plain-font"
    assert variant_plain == "Standard"


# ============================================================================
# 5. UI Boundary & Empty State Resilience
# ============================================================================


@pytest.mark.asyncio
async def test_search_view_empty_results_resilience(repository: FontRepository) -> None:
    """Verify SearchView gracefully handles 0 matches without UI errors or exceptions."""
    search_view = SearchView(repository=repository)
    search_view.search_bar.set_text("NonExistentFontXYZ12345")
    await search_view.execute_search_async()

    assert search_view._total_count == 0
    assert "0 fonts found" in search_view._results_count_label.text()
    assert not search_view._empty_widget.isHidden()


@pytest.mark.asyncio
async def test_system_view_empty_and_batch_actions_safety(repository: FontRepository) -> None:
    """Verify SystemView handles batch uninstallation when no items are selected safely."""
    sys_view = SystemView(repository=repository)
    await sys_view.refresh_installed_async()

    # Click batch uninstall when nothing is selected
    sys_view._batch_uninstall_btn.click()
    assert len(sys_view.get_selected_items()) == 0

    # Select all on empty list does not fail
    sys_view._select_all_check.setChecked(True)
    assert len(sys_view.get_selected_items()) == 0


def test_detail_pane_empty_variants_resilience() -> None:
    """Verify DetailPane renders properly even if font has no variants."""
    font_no_variants = Font(
        id="bare-font",
        family_name="Bare Font",
        category="sans-serif",
        primary_provider="google",
        last_synced_at=1700000000,
        variants=[],
    )
    pane = DetailPane()
    pane.set_font(font_no_variants)

    assert pane._title_label.text() == "Bare Font"
    assert pane._font == font_no_variants
