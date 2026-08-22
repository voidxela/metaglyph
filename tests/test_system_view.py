"""Unit and integration tests for SystemView registry and batch uninstaller."""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

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

    card = SystemFontItemWidget(item=inst, is_managed=True)
    assert card.details_box.isHidden()
    assert card.expand_btn.text() == "Details"

    # Click details button
    card.expand_btn.click()
    assert not card.details_box.isHidden()
    assert card.expand_btn.text() == "Hide"

    card.expand_btn.click()
    assert card.details_box.isHidden()
    assert card.expand_btn.text() == "Details"

    # Row click selection
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
