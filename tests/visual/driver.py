"""Programmatic UI driver for Metaglyph visual testing and automated interaction."""

from __future__ import annotations

import asyncio
import time
from typing import Callable
from PySide6.QtCore import QCoreApplication, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QWidget,
)

from metaglyph.db.models import Font
from metaglyph.ui.components.font_card import FontCard
from metaglyph.ui.main_window import MainWindow
from metaglyph.ui.views.detail_pane import DetailPane
from metaglyph.ui.views.discover_view import CategoryCardWidget, DiscoverView
from metaglyph.ui.views.search_view import SearchView
from metaglyph.ui.views.system_view import SystemFontItemWidget, SystemView


class UIDriver:
    """High-level semantic driver for Metaglyph Qt interface."""

    def __init__(self, window: MainWindow) -> None:
        self.window = window

    # =========================================================================
    # Event Loop & Synchronization Helpers
    # =========================================================================

    def pump_events(self, iterations: int = 5) -> None:
        """Process pending Qt events to flush paints, layouts, and signal dispatches."""
        for _ in range(iterations):
            QCoreApplication.processEvents()

    async def wait_for_idle(self, ms: int = 250) -> None:
        """Asynchronously wait while pumping Qt events."""
        elapsed = 0
        step = 25
        while elapsed < ms:
            self.pump_events()
            await asyncio.sleep(step / 1000.0)
            elapsed += step
        self.pump_events()

    async def wait_until(
        self,
        condition: Callable[[], bool],
        timeout_ms: int = 3000,
        poll_interval_ms: int = 50,
    ) -> bool:
        """Wait until a predicate condition returns True or timeout occurs."""
        start_time = time.monotonic()
        timeout_sec = timeout_ms / 1000.0
        step_sec = poll_interval_ms / 1000.0

        while (time.monotonic() - start_time) < timeout_sec:
            self.pump_events()
            try:
                if condition():
                    self.pump_events()
                    return True
            except Exception:
                pass
            await asyncio.sleep(step_sec)

        self.pump_events()
        return condition()

    # =========================================================================
    # Navigation
    # =========================================================================

    async def navigate_to(self, page: str | int) -> None:
        """Switch views via sidebar navigation.

        Args:
            page: 'discover' / 0, 'search' / 1, 'system' / 2
        """
        page_index_map = {
            "discover": 0,
            "search": 1,
            "system": 2,
        }
        idx = page_index_map.get(str(page).lower(), page) if isinstance(page, str) else page
        assert isinstance(idx, int) and 0 <= idx <= 2, f"Invalid page target: {page}"

        # Click the corresponding sidebar button
        btn = self.window.sidebar._nav_buttons[idx]
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        await self.wait_for_idle(150)

    def get_active_page_index(self) -> int:
        """Return index of currently active page in stack."""
        return self.window.stack.currentIndex()

    # =========================================================================
    # Discover View Actions
    # =========================================================================

    async def click_discover_category(self, category_name: str) -> bool:
        """Find and click a curated category card on the Discover page."""
        discover_view = self.window.discover_view
        for card in discover_view.findChildren(CategoryCardWidget):
            if card.category.lower() == category_name.lower():
                QTest.mouseClick(card, Qt.MouseButton.LeftButton)
                await self.wait_for_idle(200)
                return True
        return False

    # =========================================================================
    # Search & Browse View Actions
    # =========================================================================

    async def search(self, query: str, debounce_wait: bool = True) -> None:
        """Enter a query into the search bar."""
        search_view = self.window.search_view
        search_view.search_bar.set_text(query)
        self.pump_events()

        if debounce_wait:
            # Wait longer than the search bar's 200ms debounce
            await self.wait_for_idle(300)
            if search_view.repository:
                await search_view.execute_search_async()
            await self.wait_for_idle(150)

    async def clear_search(self) -> None:
        """Clear active search text."""
        search_view = self.window.search_view
        search_view.search_bar.clear()
        await self.wait_for_idle(200)

    async def reset_search_filters(self) -> None:
        """Reset all search filters to default."""
        search_view = self.window.search_view
        search_view.filter_bar.reset_filters()
        await self.wait_for_idle(200)

    async def set_search_preview_text(self, text: str) -> None:
        """Set preview sample text across all search cards."""
        search_view = self.window.search_view
        search_view._sample_input.setText(text)
        await self.wait_for_idle(100)

    async def toggle_provider_filter(self, provider_key: str, active: bool = True) -> bool:
        """Toggle provider chip in filter bar (e.g. 'fontsquirrel', 'fontsource', 'nerd_fonts')."""
        filter_bar = self.window.search_view.filter_bar
        target_val = provider_key.lower() if active else None
        filter_bar.set_provider(target_val)
        await self.wait_for_idle(200)
        return True

    async def toggle_category_filter(self, category_key: str, active: bool = True) -> bool:
        """Toggle structural category chip (e.g. 'sans-serif', 'serif', 'monospace', 'display', 'handwriting')."""
        filter_bar = self.window.search_view.filter_bar
        target_val = category_key.lower() if active else None
        filter_bar.set_category(target_val)
        await self.wait_for_idle(200)
        return True

    async def toggle_variable_filter(self, active: bool = True) -> None:
        """Toggle variable fonts only filter checkbox."""
        filter_bar = self.window.search_view.filter_bar
        filter_bar._variable_check.setChecked(active)
        await self.wait_for_idle(200)

    async def toggle_nerd_filter(self, active: bool = True) -> None:
        """Toggle nerd fonts only filter checkbox."""
        filter_bar = self.window.search_view.filter_bar
        filter_bar._nerd_check.setChecked(active)
        await self.wait_for_idle(200)

    def get_visible_font_cards(self) -> list[FontCard]:
        """Get all currently loaded FontCard widgets in SearchView."""
        cards_container = self.window.search_view._cards_container
        return [c for c in cards_container.findChildren(FontCard) if c.isVisible()]

    async def select_font_card(self, font_id_or_family: str) -> bool:
        """Find and select a FontCard by family name or ID to open Detail Pane."""
        norm_target = font_id_or_family.lower().replace("-", " ").replace("_", " ")
        cards = self.get_visible_font_cards()
        for card in cards:
            family_norm = card.font.family_name.lower().replace("-", " ").replace("_", " ")
            id_norm = card.font.id.lower().replace("-", " ").replace("_", " ")
            if norm_target in (family_norm, id_norm):
                QTest.mouseClick(card, Qt.MouseButton.LeftButton)
                await self.wait_for_idle(200)
                return True
        return False

    async def select_font_card_at_index(self, index: int) -> bool:
        """Select font card at numerical index."""
        cards = self.get_visible_font_cards()
        if 0 <= index < len(cards):
            QTest.mouseClick(cards[index], Qt.MouseButton.LeftButton)
            await self.wait_for_idle(200)
            return True
        return False

    # =========================================================================
    # Detail Pane Actions
    # =========================================================================

    def is_detail_pane_visible(self) -> bool:
        """Check if detail pane is currently open."""
        return self.window.detail_pane.isVisible()

    async def close_detail_pane(self) -> None:
        """Close the detail pane drawer."""
        detail = self.window.detail_pane
        QTest.mouseClick(detail._close_btn, Qt.MouseButton.LeftButton)
        await self.wait_for_idle(100)

    async def set_detail_point_size(self, size: int) -> None:
        """Set font point size slider in detail pane."""
        detail = self.window.detail_pane
        detail._size_slider.setValue(size)
        await self.wait_for_idle(100)

    async def set_detail_weight(self, weight_label: str) -> bool:
        """Select weight option in detail pane combo box."""
        detail = self.window.detail_pane
        idx = detail._weight_combo.findText(weight_label)
        if idx >= 0:
            detail._weight_combo.setCurrentIndex(idx)
            await self.wait_for_idle(100)
            return True
        return False

    async def toggle_detail_italic(self, italic: bool = True) -> None:
        """Toggle italic preview in detail pane."""
        detail = self.window.detail_pane
        detail._italic_check.setChecked(italic)
        await self.wait_for_idle(100)

    async def set_detail_preset_sample(self, preset_name: str) -> bool:
        """Select a sample text preset in detail pane."""
        detail = self.window.detail_pane
        idx = detail._preset_combo.findText(preset_name)
        if idx >= 0:
            detail._preset_combo.setCurrentIndex(idx)
            await self.wait_for_idle(100)
            return True
        return False

    async def set_detail_sample_text(self, text: str) -> None:
        """Set custom sample text in detail pane editor."""
        detail = self.window.detail_pane
        detail._sample_editor.setPlainText(text)
        await self.wait_for_idle(100)

    async def set_install_scope(self, scope: str = "User") -> None:
        """Select target installation scope ('User' or 'System')."""
        detail = self.window.detail_pane
        if scope.lower() == "user":
            QTest.mouseClick(detail._radio_user, Qt.MouseButton.LeftButton)
        else:
            QTest.mouseClick(detail._radio_system, Qt.MouseButton.LeftButton)
        await self.wait_for_idle(100)

    async def click_detail_install(self) -> None:
        """Click the Install Font Family button in detail pane."""
        detail = self.window.detail_pane
        QTest.mouseClick(detail._install_btn, Qt.MouseButton.LeftButton)
        await self.wait_for_idle(300)

    async def click_detail_uninstall(self) -> None:
        """Click the Uninstall Font Family button in detail pane."""
        detail = self.window.detail_pane
        QTest.mouseClick(detail._uninstall_btn, Qt.MouseButton.LeftButton)
        await self.wait_for_idle(300)

    async def switch_nerd_font_variant(self, variant: str) -> bool:
        """Select Nerd Font variant from the suggestion banner badge."""
        detail = self.window.detail_pane
        badge = detail.nerd_badge
        if not badge.isVisible():
            return False
        idx = badge.variant_combo.findText(variant)
        if idx >= 0:
            badge.variant_combo.setCurrentIndex(idx)
            QTest.mouseClick(badge.action_btn, Qt.MouseButton.LeftButton)
            await self.wait_for_idle(200)
            return True
        return False

    # =========================================================================
    # System View Actions
    # =========================================================================

    async def search_system_fonts(self, query: str) -> None:
        """Filter system view font registry."""
        system_view = self.window.system_view
        system_view._search_bar.set_text(query)
        await self.wait_for_idle(250)

    async def filter_system_scope(self, scope: str = "All") -> None:
        """Filter system registry by scope ('All', 'User', 'System')."""
        system_view = self.window.system_view
        scope_map = {
            "all": None,
            "user": "User",
            "system": "System",
        }
        val = scope_map.get(scope.lower(), scope)
        system_view._on_scope_clicked(val)
        await self.wait_for_idle(150)

    def get_system_font_cards(self, include_collapsed: bool = False) -> list[SystemFontItemWidget]:
        """Get SystemFontItemWidget items in System View."""
        system_view = self.window.system_view
        if include_collapsed:
            return list(system_view.findChildren(SystemFontItemWidget))
        return [c for c in system_view.findChildren(SystemFontItemWidget) if c.isVisible()]

    async def expand_system_font_family(self, family_name: str) -> bool:
        """Expand a specific font family widget by name."""
        system_view = self.window.system_view
        for fam in system_view._family_widgets:
            if fam.family_name.lower() == family_name.lower():
                fam.set_collapsed(False, animated=False)
                await self.wait_for_idle(50)
                return True
        return False

    async def expand_all_system_families(self) -> None:
        """Expand all font families in system view."""
        self.window.system_view.expand_all_families(animated=False)
        await self.wait_for_idle(100)

    async def collapse_all_system_families(self) -> None:
        """Collapse all font families in system view."""
        self.window.system_view.collapse_all_families(animated=False)
        await self.wait_for_idle(100)

    async def toggle_system_font_selection(self, family_name: str, selected: bool = True) -> bool:
        """Toggle checkbox for a specific font in the system registry."""
        await self.expand_system_font_family(family_name)
        cards = self.get_system_font_cards()
        for card in cards:
            if card.item.family_name.lower() == family_name.lower():
                if card.checkbox.isChecked() != selected:
                    QTest.mouseClick(card.checkbox, Qt.MouseButton.LeftButton)
                    await self.wait_for_idle(100)
                return True
        return False

    async def select_all_system_fonts(self, selected: bool = True) -> None:
        """Check or uncheck the Select All box in system view."""
        system_view = self.window.system_view
        if system_view._select_all_check.isChecked() != selected:
            QTest.mouseClick(system_view._select_all_check, Qt.MouseButton.LeftButton)
            await self.wait_for_idle(150)

    async def expand_system_font_details(self, family_name: str) -> bool:
        """Click the row header on a system font card to toggle expanded details."""
        await self.expand_system_font_family(family_name)
        cards = self.get_system_font_cards()
        for card in cards:
            if card.item.family_name.lower() == family_name.lower():
                QTest.mouseClick(card, Qt.MouseButton.LeftButton)
                await self.wait_for_idle(100)
                return True
        return False

    async def click_batch_uninstall(self) -> None:
        """Click the batch uninstall button in the system view action bar."""
        system_view = self.window.system_view
        QTest.mouseClick(system_view._batch_uninstall_btn, Qt.MouseButton.LeftButton)
        await self.wait_for_idle(300)
