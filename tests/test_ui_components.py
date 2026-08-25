"""Unit and integration tests for Metaglyph PySide6 UI components and views."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from metaglyph.core.config import Config
from metaglyph.db.models import Font, FontFilter, FontVariant, InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.ui.app import MetaglyphApp, create_application
from metaglyph.ui.components.filter_bar import FilterBar
from metaglyph.ui.components.font_card import FontCard
from metaglyph.ui.components.font_preview import FontPreviewWidget
from metaglyph.ui.components.search_bar import SearchBar
from metaglyph.ui.components.sidebar import SidebarWidget
from metaglyph.ui.main_window import MainWindow
from metaglyph.ui.theme.qss_builder import ThemeManager, apply_theme, get_theme_manager
from metaglyph.ui.views.detail_pane import DetailPane
from metaglyph.ui.views.discover_view import CategoryCardWidget, DiscoverView
from metaglyph.ui.views.search_view import SearchView
from metaglyph.ui.views.system_view import SystemView




# ============================================================================
# Theme Manager Tests
# ============================================================================


def test_theme_manager_load_and_apply(tmp_path: Path) -> None:
    manager = ThemeManager()
    stylesheet = manager.get_stylesheet("dark")

    assert stylesheet != ""
    assert "#sidebar" in stylesheet
    assert "#fontCard" in stylesheet
    assert "QPushButton" in stylesheet

    # Test applying to widget
    widget = QWidget()
    success = manager.apply_theme(widget, "dark")
    assert success is True
    assert widget.styleSheet() != ""

    # Test caching
    assert "dark" in manager._cache
    manager.clear_cache()
    assert len(manager._cache) == 0


def test_theme_manager_fallback(tmp_path: Path) -> None:
    manager = ThemeManager(theme_dir=tmp_path)
    # No custom theme file -> fallback to empty or dark
    assert manager.get_stylesheet("non_existent_theme") == ""


# ============================================================================
# FontPreviewWidget Tests
# ============================================================================


def test_font_preview_widget_properties() -> None:
    preview = FontPreviewWidget(
        font_family="Roboto",
        sample_text="Hello World",
        point_size=28.0,
        weight=QFont.Weight.Bold,
        italic=True,
    )

    assert preview.sample_text == "Hello World"
    assert preview.font_family == "Roboto"
    assert preview.point_size == 28.0
    assert preview.weight == QFont.Weight.Bold
    assert preview.italic is True

    # Mutators
    preview.set_sample_text("New Sample Text")
    assert preview.sample_text == "New Sample Text"

    preview.set_font_size(36.0)
    assert preview.point_size == 36.0

    preview.set_font_weight(QFont.Weight.Light)
    assert preview.weight == QFont.Weight.Light

    preview.set_italic(False)
    assert preview.italic is False

    preview.set_font_family("JetBrains Mono")
    assert preview.font_family == "JetBrains Mono"

    preview.set_loading(True)
    assert preview._is_loading is True
    preview.set_loading(False)
    assert preview._is_loading is False

    # Error state
    preview.set_error(True, "Preview unavailable")
    assert preview.is_error is True
    preview.set_error(False)
    assert preview.is_error is False


# ============================================================================
# SearchBar Tests
# ============================================================================


def test_search_bar_debouncing_and_clear() -> None:
    search_bar = SearchBar(debounce_ms=50)

    emitted_texts: list[str] = []
    debounced_queries: list[str] = []
    cleared = []

    search_bar.text_changed.connect(emitted_texts.append)
    search_bar.search_debounced.connect(debounced_queries.append)
    search_bar.search_cleared.connect(lambda: cleared.append(True))

    search_bar.set_text("JetBrains")
    assert search_bar.text() == "JetBrains"
    assert "JetBrains" in emitted_texts

    # Simulate debounce timer timeout
    search_bar._on_debounce_timeout()
    assert "JetBrains" in debounced_queries

    # Return key press
    search_bar._on_return_pressed()
    assert len(debounced_queries) >= 2

    # Clear
    search_bar.clear()
    assert search_bar.text() == ""
    assert len(cleared) == 1


# ============================================================================
# FilterBar Tests
# ============================================================================


def test_filter_bar_selections() -> None:
    filter_bar = FilterBar()

    emitted_filters: list[FontFilter] = []
    filter_bar.filter_changed.connect(emitted_filters.append)

    # Initial state
    init_filter = filter_bar.get_filter()
    assert init_filter.categories == []
    assert init_filter.providers == []
    assert init_filter.is_variable is None
    assert init_filter.has_nerd_font is None

    # Select category
    filter_bar.set_category("monospace")
    f1 = filter_bar.get_filter()
    assert f1.categories == ["monospace"]

    # Select curated category
    filter_bar.set_curated_category("Code")
    f2 = filter_bar.get_filter()
    assert f2.curated_categories == ["Code"]
    assert f2.categories == []

    # Select provider
    filter_bar.set_provider("fontsource")
    f3 = filter_bar.get_filter()
    assert f3.providers == ["fontsource"]

    # Toggle variable and nerd font
    filter_bar._variable_check.setChecked(True)
    filter_bar._nerd_check.setChecked(True)
    f4 = filter_bar.get_filter()
    assert f4.is_variable is True
    assert f4.has_nerd_font is True

    # Reset
    filter_bar.reset_filters()
    f_reset = filter_bar.get_filter()
    assert f_reset.categories == []
    assert f_reset.curated_categories == []
    assert f_reset.providers == []
    assert f_reset.is_variable is None
    assert f_reset.has_nerd_font is None


# ============================================================================
# FontCard Tests
# ============================================================================


def test_font_card_rendering_and_click(sample_font_jetbrains: Font) -> None:
    card = FontCard(font=sample_font_jetbrains, sample_text="Quick brown fox")

    assert card._name_label.text() == "JetBrains Mono"
    cat_texts = [b.text() for b in card._cat_badges]
    assert "Code" in cat_texts
    assert "Monospace" in cat_texts
    assert card._provider_badge.text() == "Fontsource"
    assert "2 Styles" in card._styles_badge.text()
    assert hasattr(card, "_nerd_badge")
    assert hasattr(card, "_var_badge")
    assert hasattr(card, "_error_badge")
    assert card._error_badge.isVisible() is False

    # Click signal
    clicked_fonts: list[Font] = []
    card.clicked.connect(clicked_fonts.append)

    QTest.mouseClick(card, Qt.MouseButton.LeftButton)
    assert len(clicked_fonts) == 1
    assert clicked_fonts[0].id == "jetbrains-mono"

    # Selected state
    card.set_selected(True)
    assert card._is_selected is True
    card.set_selected(False)
    assert card._is_selected is False

    # Sample text update
    card.set_sample_text("Updated Preview")
    assert card.preview_widget.sample_text == "Updated Preview"


# ============================================================================
# SidebarWidget Tests
# ============================================================================


def test_sidebar_widget_navigation() -> None:
    sidebar = SidebarWidget()

    pages: list[int] = []
    syncs: list[bool] = []

    sidebar.page_changed.connect(pages.append)
    sidebar.sync_requested.connect(lambda: syncs.append(True))

    # Click navigation buttons
    sidebar._nav_buttons[1].click()
    assert 1 in pages

    sidebar._nav_buttons[2].click()
    assert 2 in pages

    sidebar.set_current_page(0)
    assert sidebar._nav_buttons[0].isChecked()

    # Update stats
    sidebar.update_stats(total_fonts=4500, installed_count=12)
    assert "4,500 fonts indexed" in sidebar._stats_label.text()
    assert "12 installed" in sidebar._stats_label.text()

    # Sync button
    sidebar._sync_btn.click()
    assert len(syncs) == 1

    sidebar.set_syncing(True, "Syncing catalog...")
    assert not sidebar._sync_btn.isEnabled()
    assert "Syncing catalog..." in sidebar._sync_btn.text()

    sidebar.set_syncing(False)
    assert sidebar._sync_btn.isEnabled()


# ============================================================================
# DiscoverView Tests
# ============================================================================


@pytest.mark.asyncio
async def test_discover_view_category_clicks_and_counts(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    # JetBrains Mono is in Code and Inter is in Interface.
    # Add a featured font: Fira Code
    sample_font_fira = Font(
        id="fira-code",
        family_name="Fira Code",
        category="monospace",
        curated_category="Code",
        is_variable=True,
        has_nerd_font=True,
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )
    sample_font_iosevka_term = Font(
        id="iosevka-term-nerd-font",
        family_name="IosevkaTerm Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    sample_font_meslo = Font(
        id="meslo-lg-nerd-font",
        family_name="MesloLG Nerd Font",
        category="monospace",
        curated_category="Code",
        is_variable=False,
        has_nerd_font=True,
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([
        sample_font_jetbrains,
        sample_font_inter,
        sample_font_fira,
        sample_font_iosevka_term,
        sample_font_meslo,
    ])

    discover = DiscoverView(repository=repository)
    assert len(discover._category_cards) == 10

    # Verify Featured is first card
    first_cat = list(discover._category_cards.keys())[0]
    assert first_cat == "Featured"

    # Category click
    selected_cats: list[str] = []
    discover.category_selected.connect(selected_cats.append)

    featured_card = discover._category_cards["Featured"]
    QTest.mouseClick(featured_card, Qt.MouseButton.LeftButton)
    assert "Featured" in selected_cats

    code_card = discover._category_cards["Code"]
    QTest.mouseClick(code_card, Qt.MouseButton.LeftButton)
    assert "Code" in selected_cats

    # Refresh counts
    await discover.refresh_stats()
    assert "3 fonts" in discover._category_cards["Featured"]._count_badge.text()
    assert "4 fonts" in discover._category_cards["Code"]._count_badge.text()
    assert "1 fonts" in discover._category_cards["Interface"]._count_badge.text()


# ============================================================================
# SearchView Tests
# ============================================================================


@pytest.mark.asyncio
async def test_search_view_query_and_selection(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    await repository.upsert_fonts([sample_font_jetbrains, sample_font_inter])

    search_view = SearchView(repository=repository)
    await search_view.execute_search_async()

    assert search_view._total_count == 2
    assert "Showing 2 of 2 fonts" in search_view._results_count_label.text()

    # Test filtering by query
    search_view.search_bar.set_text("JetBrains")
    search_view.search_bar._on_debounce_timeout()
    await search_view.execute_search_async()

    assert search_view._total_count == 1
    assert "Showing 1 of 1 fonts" in search_view._results_count_label.text()

    # Font selected signal
    selected_fonts: list[Font] = []
    search_view.font_selected.connect(selected_fonts.append)

    # Click first card
    item = search_view._cards_layout.itemAt(0)
    assert item is not None and isinstance(item.widget(), FontCard)
    item.widget().clicked.emit(sample_font_jetbrains)

    assert len(selected_fonts) == 1
    assert selected_fonts[0].id == "jetbrains-mono"

    # Selection clearing
    search_view.clear_selection()
    assert search_view._selected_card is None


# ============================================================================
# DetailPane Tests
# ============================================================================


def test_detail_pane_interactions(sample_font_jetbrains: Font) -> None:
    pane = DetailPane()
    pane.set_font(sample_font_jetbrains)

    assert pane._title_label.text() == "JetBrains Mono"
    assert pane._provider_badge.text() == "Fontsource"
    cat_texts = [b.text() for b in pane._cat_badges]
    assert "Code" in cat_texts
    assert "Monospace" in cat_texts
    assert not pane.nerd_badge.isHidden()

    # Size slider
    pane._size_slider.setValue(32)
    assert pane._size_val_label.text() == "32 pt"
    assert pane._preview.point_size == 32.0

    # Weight selector
    pane._weight_combo.setCurrentText("Bold (700)")
    assert pane._preview.weight == 700

    # Sample editor
    pane._sample_editor.setPlainText("Custom live preview text")
    assert pane._preview.sample_text == "Custom live preview text"

    # Install action
    installs: list[tuple[Font, str]] = []
    pane.install_requested.connect(lambda f, s, *args: installs.append((f, s)))

    pane._radio_user.setChecked(True)
    pane._install_btn.click()
    assert len(installs) == 1
    assert installs[0][0].id == "jetbrains-mono"
    assert installs[0][1] == "User"

    pane._radio_system.setChecked(True)
    pane._install_btn.click()
    assert installs[1][1] == "System"

    # Close signal
    closed = []
    pane.closed.connect(lambda: closed.append(True))
    pane._close_btn.click()
    assert len(closed) == 1


# ============================================================================
# SystemView Tests
# ============================================================================


@pytest.mark.asyncio
async def test_system_view_display(
    repository: FontRepository,
    sample_font_jetbrains: Font,
) -> None:
    await repository.upsert_fonts([sample_font_jetbrains])
    await repository.record_installation(
        InstalledFont(
            font_id="jetbrains-mono",
            family_name="JetBrains Mono",
            provider="fontsource",
            install_scope="User",
            installed_at=1700000000,
            file_paths=["/home/user/.fonts/JetBrainsMono.ttf"],
        )
    )

    sys_view = SystemView(repository=repository)
    await sys_view.refresh_installed_async()

    assert len(sys_view._installed_fonts) == 1
    assert sys_view._installed_fonts[0].family_name == "JetBrains Mono"
    assert sys_view._empty_label.isHidden()
    await asyncio.sleep(0.01)


# ============================================================================
# MainWindow Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_main_window_navigation_and_signals(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
) -> None:
    await repository.upsert_fonts([sample_font_jetbrains, sample_font_inter])

    window = MainWindow(repository=repository)
    window.show()
    await window._initial_load_async()

    assert window.stack.currentIndex() == 0  # Discover

    # Sidebar page switch
    window.sidebar.page_changed.emit(1)
    assert window.stack.currentIndex() == 1  # Search

    # Discover category selection navigates to Search with category
    window.discover_view.category_selected.emit("Code")
    assert window.stack.currentIndex() == 1
    assert window.search_view._current_filter.curated_categories == ["Code"]

    # Font selection opens Detail Pane
    window.search_view.font_selected.emit(sample_font_jetbrains)
    assert not window.detail_pane.isHidden()
    assert window.detail_pane._title_label.text() == "JetBrains Mono"

    # Detail Pane close
    window.detail_pane.closed.emit()
    assert window.detail_pane.isHidden()

    # Nerd Font counterpart switch in MainWindow
    nf_font = Font(
        id="jetbrainsmono-nerd-font",
        family_name="JetBrainsMono Nerd Font",
        category="monospace",
        curated_category="Code",
        primary_provider="nerd_fonts",
        last_synced_at=1700000000,
    )
    await repository.upsert_fonts([nf_font])
    await window._switch_nerd_font_async("jetbrainsmono-nerd-font", "Mono")
    assert window.detail_pane._title_label.text() == "JetBrainsMono Nerd Font"
    assert window.detail_pane.nerd_badge.get_selected_variant() == "Mono"

    # Stats refresh
    await window.refresh_stats_async()
    assert "3 fonts indexed" in window._status_stats_label.text()
    window.close()


# ============================================================================
# MetaglyphApp Runner Test
# ============================================================================


@pytest.mark.asyncio
async def test_app_initialization(test_config: Config) -> None:
    app_runner = MetaglyphApp()
    await app_runner.initialize()

    window = app_runner.build_ui()
    assert window is not None
    assert isinstance(window, MainWindow)

    await app_runner.shutdown()
