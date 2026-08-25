"""End-to-end integration tests for complete user workflows in Metaglyph.

Tests cover:
- End-to-end flow: Discover View -> Select Category -> Filter Search -> Live Preview -> Detail Pane -> Install -> System Registry -> Uninstall.
- End-to-end Nerd Font counterpart flow: Standard Font Selection -> Nerd Font Counterpart Banner -> Switch to Patched Font -> Variant Picker -> Installation.
- Headless CLI sync workflow (--sync flag) execution and output.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from metaglyph.__main__ import run_sync
from metaglyph.core.config import Config
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontFilter, FontVariant, InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.providers.base import BaseFontProvider
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader
from metaglyph.ui.main_window import MainWindow
from conftest import synthesize_test_font_bytes


# ============================================================================
# 1. Full User Lifecycle: Browse -> Inspect -> Install -> Verify -> Uninstall
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_browse_inspect_install_uninstall_workflow(
    temp_dir: Path,
    test_ttf_file: Path,
) -> None:
    """End-to-end test simulating complete user journey through GUI."""
    # 1. Setup isolated database and config
    db_path = temp_dir / "e2e.db"
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    repository = FontRepository(db_manager)

    user_fonts_dir = temp_dir / "user_fonts"
    user_fonts_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = temp_dir / "e2e_subsets"
    cache_dir.mkdir(parents=True, exist_ok=True)

    config = Config(
        app_name="metaglyph-test",
        config_dir=temp_dir / "config",
        data_dir=temp_dir / "data",
        cache_dir=temp_dir / "cache",
        user_fonts_dir=user_fonts_dir,
        system_fonts_dir=temp_dir / "system_fonts",
        subsets_cache_dir=cache_dir,
        database_path=db_path,
    )

    # 2. Seed catalog with test fonts
    test_font = Font(
        id="inter",
        family_name="Inter",
        category="sans-serif",
        curated_category="Interface",
        primary_provider="fontsquirrel",
        last_synced_at=1700000000,
        variants=[
            FontVariant(
                font_id="inter",
                provider="fontsquirrel",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://example.com/inter.ttf",
            )
        ],
    )
    await repository.upsert_fonts([test_font])

    # 3. Setup mock provider manager to supply font binaries
    mock_provider_manager = MagicMock(spec=ProviderManager)
    mock_provider_manager.fetch_sample_subset = AsyncMock(return_value=test_ttf_file)
    mock_provider_manager.download_font_family = AsyncMock(
        return_value=[test_ttf_file]
    )

    cache = SubsetCache(cache_dir=cache_dir)
    loader = FontLoader()
    fetcher = SubsetFetcher(
        cache=cache,
        loader=loader,
        provider_manager=mock_provider_manager,
    )

    user_installer = UserFontInstaller(repository=repository, config=config)
    uninstaller = FontUninstaller(repository=repository, config=config, user_installer=user_installer)
    detector = FontDetector(config=config)

    # 4. Initialize UI Window
    window = MainWindow(
        repository=repository,
        subset_fetcher=fetcher,
        provider_manager=mock_provider_manager,
        user_installer=user_installer,
        uninstaller=uninstaller,
        detector=detector,
    )
    window.show()
    await window._initial_load_async()

    # Step A: User is on Discover page -> clicks "Interface" category
    assert window.stack.currentIndex() == 0  # Discover View
    interface_card = window.discover_view._category_cards["Interface"]
    QTest.mouseClick(interface_card, Qt.MouseButton.LeftButton)

    # UI automatically transitions to Search view with category active
    assert window.stack.currentIndex() == 1  # Search View
    assert window.search_view._current_filter.curated_categories == ["Interface"]
    await window.search_view.execute_search_async()
    assert window.search_view._total_count == 1

    # Step B: User selects the font card from the search list
    window.search_view.font_selected.emit(test_font)
    assert not window.detail_pane.isHidden()
    assert window.detail_pane._title_label.text() == "Inter"

    # Step C: User clicks "Install Font" (User scope)
    assert window.detail_pane._radio_user.isChecked()
    await window.detail_pane.install_font_async(scope="User")

    # Step D: Verify installation in DB and filesystem
    assert await repository.is_font_installed("inter")
    installed_records = await repository.get_installed_fonts(scope="User")
    assert len(installed_records) == 1
    assert installed_records[0].family_name == "Inter"
    installed_file = Path(installed_records[0].file_paths[0])
    assert installed_file.exists()

    # Step E: User switches to System View -> verifies installed font is listed
    window.sidebar.page_changed.emit(2)  # System View
    assert window.stack.currentIndex() == 2
    await window.system_view.refresh_installed_async()
    assert len(window.system_view._installed_fonts) == 1
    assert window.system_view._installed_fonts[0].family_name == "Inter"

    # Step F: User uninstalls font via System View
    await window.system_view.uninstall_single_async(installed_records[0])
    assert not await repository.is_font_installed("inter")
    assert not installed_file.exists()

    window.close()
    await db_manager.close()


# ============================================================================
# 2. End-to-End Nerd Font Counterpart Workflow
# ============================================================================


@pytest.mark.asyncio
async def test_e2e_nerd_font_counterpart_workflow(
    temp_dir: Path,
    test_ttf_file: Path,
) -> None:
    """Verify selecting a standard font discovers counterpart Nerd Font and allows switching."""
    db_path = temp_dir / "e2e_nf.db"
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize()
    repository = FontRepository(db_manager)

    # Standard font and its Nerd Font counterpart
    std_font = Font(
        id="jetbrains-mono",
        family_name="JetBrains Mono",
        category="monospace",
        curated_category="Code",
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )
    nf_font = Font(
        id="jetbrainsmono-nerd-font",
        family_name="JetBrainsMono Nerd Font",
        category="monospace",
        curated_category="Code",
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([std_font, nf_font])
    await repository.link_nerd_fonts()

    # Verify linking in repository
    refreshed_std = await repository.get_font("jetbrains-mono")
    assert refreshed_std is not None
    assert refreshed_std.has_nerd_font is True
    assert refreshed_std.nerd_font_slug == "jetbrainsmono-nerd-font"

    # Load UI MainWindow
    window = MainWindow(repository=repository)
    window.show()
    await window._initial_load_async()

    # Load standard font into Detail Pane
    window.detail_pane.set_font(refreshed_std)
    assert window.detail_pane._title_label.text() == "JetBrains Mono"
    assert not window.detail_pane.nerd_badge.isHidden()

    # User clicks switch to Nerd Font counterpart
    window.detail_pane.nerd_badge._variant_combo.setCurrentText("Mono")
    await window._switch_nerd_font_async("jetbrainsmono-nerd-font", "Mono")

    assert window.detail_pane._title_label.text() == "JetBrainsMono Nerd Font"
    assert window.detail_pane.nerd_badge.get_selected_variant() == "Mono"

    window.close()
    await db_manager.close()


# ============================================================================
# 3. Headless CLI Sync Workflow (--sync CLI option)
# ============================================================================


@pytest.mark.asyncio
async def test_headless_cli_sync_execution(temp_dir: Path) -> None:
    """Verify headless CLI --sync mode executes correctly and updates catalog stats."""
    db_path = temp_dir / "cli_sync.db"

    with patch("metaglyph.core.config.get_config") as mock_get_config:
        cfg = Config(
            app_name="metaglyph-test",
            config_dir=temp_dir / "config",
            data_dir=temp_dir / "data",
            cache_dir=temp_dir / "cache",
            user_fonts_dir=temp_dir / "fonts",
            system_fonts_dir=temp_dir / "sys_fonts",
            subsets_cache_dir=temp_dir / "subsets",
            database_path=db_path,
        )
        mock_get_config.return_value = cfg

        # Mock providers to return deterministic font list
        mock_p = MagicMock(spec=BaseFontProvider)
        mock_p.name = "mock_provider"
        mock_p.fetch_catalog = AsyncMock(
            return_value=[
                Font(
                    id="cli-font",
                    family_name="CLI Test Font",
                    category="sans-serif",
                    primary_provider="mock_provider",
                    last_synced_at=1700000000,
                )
            ]
        )
        mock_p.close = AsyncMock()

        with patch("metaglyph.providers.manager.ProviderManager") as MockPM:
            instance = MockPM.return_value
            instance.sync_all = AsyncMock(return_value={"mock_provider": 1})
            instance.close = AsyncMock()

            exit_code = await run_sync()
            assert exit_code == 0
            assert instance.sync_all.call_count == 1
            assert instance.close.call_count == 1
