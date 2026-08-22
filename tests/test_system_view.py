"""Unit and integration tests for SystemView registry and batch uninstaller."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel

from metaglyph.db.models import Font, InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import InstallResult
from metaglyph.installer.detector import FontDetector
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.ui.views.system_view import SystemFontItemWidget, SystemView


@pytest.mark.asyncio
async def test_system_view_render_installed_and_cached(
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
            file_paths=["/home/user/.local/share/fonts/JetBrainsMono.ttf"],
        )
    )

    await repository.sync_system_font_cache([
        SystemFontCacheEntry(
            family_name="Ubuntu",
            postscript_name="Ubuntu-Regular",
            file_path="/usr/share/fonts/TTF/Ubuntu-R.ttf",
            scope="System",
            is_metaglyph_managed=False,
            last_scanned_at=1700000000,
        )
    ])

    view = SystemView(repository=repository)
    await view.refresh_installed_async()

    assert len(view._card_widgets) == 2
    assert view._empty_label.isHidden()
    assert "0 of 2 selected" in view._batch_count_label.text()
    assert not view._batch_uninstall_btn.isEnabled()


@pytest.mark.asyncio
async def test_system_view_search_and_scope_filtering(
    repository: FontRepository,
) -> None:
    await repository.upsert_fonts([
        Font(
            id="fira-code",
            family_name="Fira Code",
            category="monospace",
            primary_provider="fontsource",
            last_synced_at=1700000000,
        ),
        Font(
            id="roboto",
            family_name="Roboto",
            category="sans-serif",
            primary_provider="google",
            last_synced_at=1700000000,
        ),
    ])

    await repository.record_installation(
        InstalledFont(
            font_id="fira-code",
            family_name="Fira Code",
            provider="fontsource",
            install_scope="User",
            installed_at=1700000000,
            file_paths=["/home/user/.fonts/FiraCode.ttf"],
        )
    )
    await repository.record_installation(
        InstalledFont(
            font_id="roboto",
            family_name="Roboto",
            provider="google",
            install_scope="System",
            installed_at=1700000000,
            file_paths=["/usr/share/fonts/Roboto.ttf"],
        )
    )

    view = SystemView(repository=repository)
    await view.refresh_installed_async()
    assert len(view._card_widgets) == 2

    # Filter by search
    view._search_bar.set_text("Fira")
    view._search_bar._on_debounce_timeout()
    await view.refresh_installed_async()
    assert len(view._card_widgets) == 1
    assert "Fira Code" in view._card_widgets[0].name_label.text()
    assert "Regular" in view._card_widgets[0].name_label.text()

    # Reset search
    view._search_bar.clear()
    await view.refresh_installed_async()
    assert len(view._card_widgets) == 2

    # Filter by User Scope
    view._on_scope_clicked("User")
    await view.refresh_installed_async()
    assert len(view._card_widgets) == 1
    assert "Fira Code" in view._card_widgets[0].name_label.text()

    # Filter by System Scope
    view._on_scope_clicked("System")
    await view.refresh_installed_async()
    assert len(view._card_widgets) == 1
    assert "Roboto" in view._card_widgets[0].name_label.text()


@pytest.mark.asyncio
async def test_system_view_card_details_toggle(
    repository: FontRepository,
) -> None:
    inst = InstalledFont(
        font_id="jetbrains-mono",
        family_name="JetBrains Mono",
        provider="fontsource",
        install_scope="User",
        installed_at=1700000000,
        file_paths=["/path/to/JetBrainsMono.ttf"],
    )

    card = SystemFontItemWidget(item=inst, style_name="Bold Italic", is_managed=True)
    assert card.details_box.isHidden()
    assert not hasattr(card, "expand_btn")

    # Font preview widget should exist in details box
    assert hasattr(card, "preview_widget")
    assert card.preview_widget.font_family == "JetBrains Mono"
    assert card.preview_widget.weight == 700
    assert card.preview_widget.italic is True

    # Details label should NOT have the redundant first line ("Family: JetBrains Mono ...")
    details_lbl = card.details_box.findChild(QLabel, "systemFontPath")
    assert details_lbl is not None
    assert "Family: JetBrains Mono" not in details_lbl.text()
    assert "Font ID: jetbrains-mono" in details_lbl.text()
    assert "Provider: fontsource" in details_lbl.text()

    # Expand card
    card.set_expanded(True)
    assert not card.details_box.isHidden()
    assert card.is_expanded() is True

    # Collapse card
    card.set_expanded(False)
    assert card.details_box.isHidden()
    assert card.is_expanded() is False

    # Row click selection method
    card.set_row_selected(True)
    assert not card.details_box.isHidden()
    card.set_row_selected(False)
    assert card.details_box.isHidden()


@pytest.mark.asyncio
async def test_system_view_batch_selection_and_uninstall(
    repository: FontRepository,
    tmp_path: Path,
    test_ttf_bytes: bytes,
) -> None:
    user_fonts_dir = tmp_path / "user_fonts"
    user_fonts_dir.mkdir(parents=True, exist_ok=True)

    f1 = user_fonts_dir / "FontA.ttf"
    f2 = user_fonts_dir / "FontB.ttf"
    f1.write_bytes(test_ttf_bytes)
    f2.write_bytes(test_ttf_bytes)

    await repository.upsert_fonts([
        Font(
            id="font-a",
            family_name="Font A",
            category="sans-serif",
            primary_provider="fontsource",
            last_synced_at=1700000000,
        ),
        Font(
            id="font-b",
            family_name="Font B",
            category="sans-serif",
            primary_provider="google",
            last_synced_at=1700000000,
        ),
    ])

    await repository.record_installation(
        InstalledFont(
            font_id="font-a",
            family_name="Font A",
            provider="fontsource",
            install_scope="User",
            installed_at=1700000000,
            file_paths=[str(f1)],
        )
    )
    await repository.record_installation(
        InstalledFont(
            font_id="font-b",
            family_name="Font B",
            provider="google",
            install_scope="User",
            installed_at=1700000000,
            file_paths=[str(f2)],
        )
    )

    user_installer = UserFontInstaller(
        repository=repository,
        target_dir_override=user_fonts_dir,
    )
    uninstaller = FontUninstaller(
        repository=repository,
        user_installer=user_installer,
    )

    view = SystemView(
        repository=repository,
        uninstaller=uninstaller,
    )
    await view.refresh_installed_async()
    assert len(view._card_widgets) == 2

    # Select all
    view.set_all_selected(True)
    assert "2 of 2 selected" in view._batch_count_label.text()
    assert view._batch_uninstall_btn.isEnabled()

    selected_items = view.get_selected_items()
    assert len(selected_items) == 2

    # Execute batch uninstall async
    results = await view.batch_uninstall_async(selected_items)
    assert len(results) == 2
    assert all(r.success for r in results)

    # Files should be deleted
    assert not f1.exists()
    assert not f2.exists()

    # DB records should be gone
    assert await repository.get_installed_font("font-a") is None
    assert await repository.get_installed_font("font-b") is None

    # View should show empty
    assert len(view._card_widgets) == 0
    assert not view._empty_label.isHidden()


@pytest.mark.asyncio
async def test_system_view_batch_uninstall_cache_entries_complex_name(
    repository: FontRepository,
    tmp_path: Path,
    test_ttf_bytes: bytes,
) -> None:
    """Verify batch uninstall with SystemFontCacheEntry items and complex family names."""
    user_fonts_dir = tmp_path / "user_fonts"
    user_fonts_dir.mkdir(parents=True, exist_ok=True)
    f = user_fonts_dir / "AdobeGaramondPro.ttf"
    f.write_bytes(test_ttf_bytes)

    user_installer = UserFontInstaller(
        repository=repository,
        target_dir_override=user_fonts_dir,
    )
    uninstaller = FontUninstaller(
        repository=repository,
        user_installer=user_installer,
    )

    view = SystemView(repository=repository, uninstaller=uninstaller)
    cache_entry = SystemFontCacheEntry(
        family_name="Adobe Garamond Pro",
        postscript_name="AGaramondPro-Regular",
        file_path=str(f),
        scope="User",
        is_metaglyph_managed=True,
        last_scanned_at=1700000000,
    )

    results = await view.batch_uninstall_async([cache_entry])
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].font_id == "garamond-pro"
    assert not f.exists()


@pytest.mark.asyncio
async def test_system_view_family_grouping_and_variant_names(
    repository: FontRepository,
) -> None:
    """Verify multiple variants of the same font family are grouped under a single family widget."""
    now = 1700000000
    await repository.sync_system_font_cache([
        SystemFontCacheEntry(
            family_name="Roboto",
            style_name="Regular",
            postscript_name="Roboto-Regular",
            file_path="/usr/share/fonts/Roboto-Regular.ttf",
            scope="System",
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="Roboto",
            style_name="Bold",
            postscript_name="Roboto-Bold",
            file_path="/usr/share/fonts/Roboto-Bold.ttf",
            scope="System",
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="Roboto",
            style_name="Italic",
            postscript_name="Roboto-Italic",
            file_path="/usr/share/fonts/Roboto-Italic.ttf",
            scope="System",
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="Fira Code",
            style_name="Regular",
            postscript_name="FiraCode-Regular",
            file_path="/usr/share/fonts/FiraCode-Regular.ttf",
            scope="System",
            last_scanned_at=now,
        ),
    ])

    view = SystemView(repository=repository)
    await view.refresh_installed_async()

    # Total variants = 4
    assert len(view._card_widgets) == 4
    # Total family groups = 2 (Fira Code and Roboto)
    assert len(view._family_widgets) == 2

    # Check first family is Fira Code with 1 variant
    assert view._family_widgets[0].family_name == "Fira Code"
    assert len(view._family_widgets[0].cards) == 1
    assert "Fira Code — Regular" in view._family_widgets[0].cards[0].name_label.text()

    # Check second family is Roboto with 3 variants
    assert view._family_widgets[1].family_name == "Roboto"
    assert len(view._family_widgets[1].cards) == 3
    variant_titles = [c.name_label.text() for c in view._family_widgets[1].cards]
    assert "Roboto — Regular" in variant_titles
    assert "Roboto — Bold" in variant_titles
    assert "Roboto — Italic" in variant_titles

    # Test family checkbox toggles all variants in that family
    view._family_widgets[1].family_checkbox.setChecked(True)
    assert all(c.is_selected() for c in view._family_widgets[1].cards)
    assert not view._family_widgets[0].cards[0].is_selected()
    assert "3 of 4 selected" in view._batch_count_label.text()


@pytest.mark.asyncio
async def test_system_view_auto_scan_on_open(
    repository: FontRepository,
) -> None:
    """Verify local font scan is automatically scheduled when view is shown."""
    detector = FontDetector()
    view = SystemView(repository=repository, detector=detector)
    assert view._has_scanned_on_open is False

    # Simulate tab open / show
    view.show()
    assert view._has_scanned_on_open is True


@pytest.mark.asyncio
async def test_system_view_single_row_expansion(
    repository: FontRepository,
) -> None:
    """Verify only one row is expanded across the entire view, clicking current row collapses it, and family states are preserved."""
    now = 1700000000
    await repository.sync_system_font_cache([
        SystemFontCacheEntry(
            family_name="Roboto",
            style_name="Regular",
            postscript_name="Roboto-Regular",
            file_path="/usr/share/fonts/Roboto-Regular.ttf",
            scope="System",
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="Roboto",
            style_name="Bold",
            postscript_name="Roboto-Bold",
            file_path="/usr/share/fonts/Roboto-Bold.ttf",
            scope="System",
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="Fira Code",
            style_name="Regular",
            postscript_name="FiraCode-Regular",
            file_path="/usr/share/fonts/FiraCode-Regular.ttf",
            scope="System",
            last_scanned_at=now,
        ),
    ])

    view = SystemView(repository=repository)
    await view.refresh_installed_async()

    assert len(view._card_widgets) == 3
    card0 = view._card_widgets[0]  # Fira Code Regular
    card1 = view._card_widgets[1]  # Roboto Bold
    card2 = view._card_widgets[2]  # Roboto Regular

    # Initially no card is expanded
    assert not card0.is_expanded()
    assert not card1.is_expanded()
    assert not card2.is_expanded()
    assert view._expanded_card is None

    # Expand card0
    card0.expand_requested.emit(card0)
    assert card0.is_expanded() is True
    assert card1.is_expanded() is False
    assert card2.is_expanded() is False
    assert view._expanded_card == card0

    # Expand card1 -> card0 should automatically collapse
    card1.expand_requested.emit(card1)
    assert card0.is_expanded() is False
    assert card1.is_expanded() is True
    assert card2.is_expanded() is False
    assert view._expanded_card == card1

    # Clicking currently expanded card1 header collapses it
    card1.expand_requested.emit(card1)
    assert card0.is_expanded() is False
    assert card1.is_expanded() is False
    assert card2.is_expanded() is False
    assert view._expanded_card is None


@pytest.mark.asyncio
async def test_system_view_loading_indicator_and_empty_state_flow(
    repository: FontRepository,
) -> None:
    """Verify loading indicator is shown during scanning and empty state is not reported prematurely."""
    view = SystemView(repository=repository)

    # Initial state before scan
    assert view._loading_label.isHidden()
    assert view._empty_label.isHidden()

    # When scanning starts
    view._is_scanning = True
    await view.refresh_installed_async()
    assert not view._loading_label.isHidden()
    assert view._empty_label.isHidden()

    # When scanning finishes with no fonts found
    view._is_scanning = False
    await view.refresh_installed_async()
    assert view._loading_label.isHidden()
    assert not view._empty_label.isHidden()


@pytest.mark.asyncio
async def test_system_family_widget_slide_animation() -> None:
    """Verify SystemFontFamilyWidget collapse/expand state and animation properties."""
    from metaglyph.ui.views.system_view import SystemFontFamilyWidget

    fam = SystemFontFamilyWidget(family_name="Inter", initially_collapsed=True)
    assert fam._is_collapsed is True
    assert fam.chevron_label.text() == "▶"
    assert fam.cards_container.isHidden()
    assert fam._anim.duration() == 220

    # Non-animated expand
    fam.set_collapsed(False, animated=False)
    assert fam._is_collapsed is False
    assert fam.chevron_label.text() == "▼"
    assert not fam.cards_container.isHidden()

    # Non-animated collapse
    fam.set_collapsed(True, animated=False)
    assert fam._is_collapsed is True
    assert fam.chevron_label.text() == "▶"
    assert fam.cards_container.isHidden()

    # Animated expand initiation
    fam.set_collapsed(False, animated=True)
    assert fam._is_collapsed is False
    assert fam.chevron_label.text() == "▼"


@pytest.mark.asyncio
async def test_system_view_expand_and_collapse_all_actions(
    repository: FontRepository,
) -> None:
    """Verify all family groups start collapsed and Expand/Collapse All actions update all family widgets."""
    now = 1700000000
    await repository.sync_system_font_cache([
        SystemFontCacheEntry(
            family_name="Roboto",
            style_name="Regular",
            postscript_name="Roboto-Regular",
            file_path="/usr/share/fonts/Roboto-Regular.ttf",
            scope="System",
            last_scanned_at=now,
        ),
        SystemFontCacheEntry(
            family_name="Fira Code",
            style_name="Regular",
            postscript_name="FiraCode-Regular",
            file_path="/usr/share/fonts/FiraCode-Regular.ttf",
            scope="System",
            last_scanned_at=now,
        ),
    ])

    view = SystemView(repository=repository)
    await view.refresh_installed_async()

    assert len(view._family_widgets) == 2
    # Verify all family widgets start collapsed by default
    assert all(fam._is_collapsed for fam in view._family_widgets)
    assert all(fam.cards_container.isHidden() for fam in view._family_widgets)

    # Click Expand All action
    view.expand_all_families(animated=False)
    assert all(not fam._is_collapsed for fam in view._family_widgets)
    assert all(not fam.cards_container.isHidden() for fam in view._family_widgets)

    # Click Collapse All action
    view.collapse_all_families(animated=False)
    assert all(fam._is_collapsed for fam in view._family_widgets)
    assert all(fam.cards_container.isHidden() for fam in view._family_widgets)


