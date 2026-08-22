"""End-to-end real font installation and uninstallation tests for Google Fonts and Nerd Fonts."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from metaglyph.core.config import Config, set_config
from metaglyph.db.database import DatabaseManager
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector
from metaglyph.installer.system_installer import SystemFontInstaller
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.providers.google_fonts import GoogleFontsProvider
from metaglyph.providers.nerd_fonts import NerdFontsProvider
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader
from metaglyph.ui.app import create_application
from metaglyph.ui.main_window import MainWindow
from tests.visual.driver import UIDriver


@pytest.mark.asyncio
async def test_real_font_installations_and_uninstalls(tmp_path: Path) -> None:
    """Test real font installations of Google Fonts and Nerd Fonts, validate System View and uninstalls."""
    # 1. Prepare environment
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    user_fonts_dir = tmp_path / "user_fonts"
    system_fonts_dir = tmp_path / "system_fonts"
    subsets_dir = tmp_path / "subsets"

    for d in (config_dir, data_dir, cache_dir, user_fonts_dir, system_fonts_dir, subsets_dir):
        d.mkdir(parents=True, exist_ok=True)

    config = Config(
        app_name="metaglyph-test-real",
        config_dir_override=config_dir,
        data_dir_override=data_dir,
        cache_dir_override=cache_dir,
        user_fonts_dir_override=user_fonts_dir,
        system_fonts_dir_override=system_fonts_dir,
        system_font_search_paths_override=[user_fonts_dir, system_fonts_dir],
    )
    set_config(config)

    db = DatabaseManager(config.database_path)
    await db.initialize()
    repository = FontRepository(db)

    # 2. Providers and catalog
    google_provider = GoogleFontsProvider()
    nerd_provider = NerdFontsProvider()
    provider_manager = ProviderManager(providers=[google_provider, nerd_provider])

    google_fonts = await google_provider.fetch_catalog()
    cinzel_font = next(f for f in google_fonts if f.family_name == "Cinzel")
    playfair_font = next(f for f in google_fonts if f.family_name == "Playfair Display")

    nerd_fonts = await nerd_provider.fetch_catalog()
    hack_nf_font = next(f for f in nerd_fonts if "Hack" in f.family_name)

    await repository.upsert_fonts([cinzel_font, playfair_font, hack_nf_font])

    # 3. Loaders and UI components
    loader = FontLoader()
    subset_cache = SubsetCache(subsets_dir)
    subset_fetcher = SubsetFetcher(cache=subset_cache, loader=loader, provider_manager=provider_manager)

    user_installer = UserFontInstaller(repository=repository, config=config)
    system_installer = SystemFontInstaller(repository=repository, config=config)
    uninstaller = FontUninstaller(
        repository=repository,
        config=config,
        user_installer=user_installer,
        system_installer=system_installer,
    )
    detector = FontDetector(config=config)

    app = QApplication.instance() or create_application()
    window = MainWindow(
        repository=repository,
        subset_fetcher=subset_fetcher,
        provider_manager=provider_manager,
        user_installer=user_installer,
        system_installer=system_installer,
        uninstaller=uninstaller,
        detector=detector,
    )
    window.resize(1280, 820)
    window.show()
    driver = UIDriver(window)
    driver.pump_events(10)
    await driver.wait_for_idle(200)

    try:
        # 4. Install Cinzel (Google Font) from Detail Pane
        await driver.navigate_to("search")
        await driver.search("Cinzel")
        await driver.wait_for_idle(200)
        await driver.select_font_card("Cinzel")
        await driver.wait_for_idle(200)

        res_cinzel = await window.detail_pane.install_font_async(scope="User")
        assert res_cinzel.success is True
        assert len(res_cinzel.installed_files) > 0
        for f in res_cinzel.installed_files:
            assert f.exists()

        # 5. Install Hack Nerd Font (Standard variant) from Detail Pane
        await driver.search("Hack")
        await driver.wait_for_idle(200)
        await driver.select_font_card(hack_nf_font.family_name)
        await driver.wait_for_idle(200)

        res_hack = await window.detail_pane.install_font_async(scope="User", variant_filter="Standard")
        assert res_hack.success is True
        assert len(res_hack.installed_files) > 0
        for f in res_hack.installed_files:
            assert f.exists()

        # 6. Install Playfair Display
        await driver.search("Playfair")
        await driver.wait_for_idle(200)
        await driver.select_font_card("Playfair Display")
        await driver.wait_for_idle(200)

        res_playfair = await window.detail_pane.install_font_async(scope="User")
        assert res_playfair.success is True
        assert len(res_playfair.installed_files) > 0

        # 7. Validate System Fonts list appearance and display
        await driver.close_detail_pane()
        await driver.navigate_to("system")
        await driver.wait_for_idle(300)

        assert len(window.system_view._family_widgets) == 3
        assert len(window.system_view._card_widgets) == 10
        card_titles = [c.name_label.text() for c in window.system_view._card_widgets]
        assert any("Cinzel" in t for t in card_titles)
        assert any(hack_nf_font.family_name in t for t in card_titles)
        assert any("Playfair Display" in t for t in card_titles)

        # 8. Test Single Uninstall from System View (Playfair Display)
        pf_card = next(c for c in window.system_view._card_widgets if "Playfair Display" in c.name_label.text())
        await window.system_view.uninstall_single_async(pf_card.item)
        await driver.wait_for_idle(200)

        assert len(window.system_view._family_widgets) == 2
        assert len(window.system_view._card_widgets) == 6
        assert await repository.get_installed_font("playfair-display") is None
        for f in res_playfair.installed_files:
            assert not f.exists()

        # 9. Test Uninstall from Detail Pane (Cinzel)
        await driver.navigate_to("search")
        await driver.search("Cinzel")
        await driver.wait_for_idle(200)
        await driver.select_font_card("Cinzel")
        await driver.wait_for_idle(200)

        assert window.detail_pane._uninstall_btn.isVisible()
        uninst_cinzel = await window.detail_pane.uninstall_font_async(scope="User")
        assert uninst_cinzel.success is True
        assert not window.detail_pane._uninstall_btn.isVisible()
        assert window.detail_pane._install_btn.text() == "Install Font Family"
        assert await repository.get_installed_font("cinzel") is None
        for f in res_cinzel.installed_files:
            assert not f.exists()

        # Reinstall Cinzel to test batch uninstall
        res_cinzel2 = await window.detail_pane.install_font_async(scope="User")
        assert res_cinzel2.success is True

        # 10. Test Batch Uninstall from System View
        await driver.close_detail_pane()
        await driver.navigate_to("system")
        await driver.wait_for_idle(300)
        assert len(window.system_view._family_widgets) == 2
        assert len(window.system_view._card_widgets) == 6

        await driver.select_all_system_fonts(True)
        assert window.system_view._batch_uninstall_btn.isEnabled()
        assert "6 of 6 selected" in window.system_view._batch_count_label.text()

        selected = window.system_view.get_selected_items()
        batch_results = await window.system_view.batch_uninstall_async(selected)
        assert len(batch_results) >= 2
        assert all(r.success for r in batch_results)
        await driver.wait_for_idle(200)

        assert len(window.system_view._card_widgets) == 0
        assert len(window.system_view._family_widgets) == 0
        assert not window.system_view._empty_label.isHidden()
        assert await repository.get_installed_font("cinzel") is None
        assert await repository.get_installed_font(hack_nf_font.id) is None
        for f in res_cinzel2.installed_files + res_hack.installed_files:
            assert not f.exists()

    finally:
        window.close()
        window.deleteLater()
        await db.close()
