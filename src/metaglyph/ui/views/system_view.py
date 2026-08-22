"""System font registry and management view."""

from __future__ import annotations

import asyncio
import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from metaglyph.db.models import InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector
from metaglyph.ui.components.search_bar import SearchBar

logger = logging.getLogger(__name__)


class SystemView(QWidget):
    """Local OS and Metaglyph-installed font registry view."""

    scan_requested = Signal()
    batch_uninstall_requested = Signal(list)  # list of InstalledFont or font IDs

    def __init__(
        self,
        repository: FontRepository | None = None,
        detector: FontDetector | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("systemView")
        self.repository = repository
        self.detector = detector or FontDetector()

        self._filter_scope: str | None = None
        self._metaglyph_only: bool = False
        self._query: str = ""
        self._installed_fonts: list[InstalledFont] = []
        self._system_fonts: list[SystemFontCacheEntry] = []

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 16)
        main_layout.setSpacing(12)

        # Header section
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        title_label = QLabel("System Font Registry", self)
        title_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #f8fafc;")
        title_layout.addWidget(title_label)

        sub_label = QLabel(
            "Scan OS font directories, inspect local fonts, and manage installations.",
            self,
        )
        sub_label.setStyleSheet("color: #64748b; font-size: 12px;")
        title_layout.addWidget(sub_label)

        header_layout.addLayout(title_layout)
        header_layout.addStretch(1)

        # Scan OS Fonts Button
        self._scan_btn = QPushButton("🔍  Scan Local Fonts", self)
        self._scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_btn.setStyleSheet(
            "QPushButton { background-color: #22222c; border: 1px solid #313140; color: #cbd5e1; padding: 8px 14px; border-radius: 6px; font-weight: 600; } QPushButton:hover { background-color: #2b2b38; border-color: #6366f1; color: #ffffff; }"
        )
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        header_layout.addWidget(self._scan_btn)

        main_layout.addLayout(header_layout)

        # Search Bar & Filter Chips
        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 4, 0, 4)
        filter_layout.setSpacing(8)

        self._search_bar = SearchBar(
            placeholder_text="Filter installed fonts by family name...",
            debounce_ms=150,
            parent=self,
        )
        self._search_bar.search_debounced.connect(self._on_search_query_changed)
        self._search_bar.search_cleared.connect(self._on_search_cleared)
        filter_layout.addWidget(self._search_bar, stretch=1)

        # Scope buttons
        self._scope_group = QButtonGroup(self)
        self._scope_group.setExclusive(True)

        scopes = [
            ("All Local", None),
            ("User Scope", "User"),
            ("System Scope", "System"),
        ]

        for label, val in scopes:
            btn = QPushButton(label, self)
            btn.setProperty("class", "filter-chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if val is None:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked=False, v=val: self._on_scope_clicked(v))
            self._scope_group.addButton(btn)
            filter_layout.addWidget(btn)

        main_layout.addLayout(filter_layout)

        # Content List / Scroll Area
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self._list_container = QWidget(self._scroll_area)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 8, 0)
        self._list_layout.setSpacing(6)

        # Empty state label
        self._empty_label = QLabel("No installed fonts found.", self._list_container)
        self._empty_label.setStyleSheet("color: #64748b; font-size: 13px; padding: 32px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_layout.addWidget(self._empty_label)

        self._scroll_area.setWidget(self._list_container)
        main_layout.addWidget(self._scroll_area, stretch=1)

        self.setLayout(main_layout)

    def _on_search_query_changed(self, query: str) -> None:
        self._query = query.strip().lower()
        self.trigger_refresh()

    def _on_search_cleared(self) -> None:
        self._query = ""
        self.trigger_refresh()

    def _on_scope_clicked(self, scope: str | None) -> None:
        self._filter_scope = scope
        self.trigger_refresh()

    def _on_scan_clicked(self) -> None:
        self.scan_requested.emit()
        self.trigger_scan_and_sync()

    def trigger_refresh(self) -> None:
        """Schedule background database refresh."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_installed_async())
        except RuntimeError:
            pass

    def trigger_scan_and_sync(self) -> None:
        """Run system font scan and database update asynchronously."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._scan_and_sync_async())
        except RuntimeError:
            pass

    async def _scan_and_sync_async(self) -> None:
        if not self.repository:
            return

        try:
            self._scan_btn.setEnabled(False)
            self._scan_btn.setText("⏳ Scanning...")
            await self.detector.scan_and_sync(self.repository)
            await self.refresh_installed_async()
        except Exception as exc:
            logger.error("Failed to scan system fonts: %s", exc)
        finally:
            self._scan_btn.setEnabled(True)
            self._scan_btn.setText("🔍 Scan Local Fonts")

    async def refresh_installed_async(self) -> None:
        """Retrieve installed and system fonts from SQLite repository."""
        if not self.repository:
            return

        try:
            installed = await self.repository.get_installed_fonts(scope=self._filter_scope)
            system_fonts = await self.repository.get_system_fonts(
                scope=self._filter_scope, metaglyph_only=self._metaglyph_only
            )

            # Filter by search query if any
            if self._query:
                installed = [f for f in installed if self._query in f.family_name.lower()]
                system_fonts = [f for f in system_fonts if self._query in f.family_name.lower()]

            self._installed_fonts = installed
            self._system_fonts = system_fonts

            # Clear list items
            for i in reversed(range(self._list_layout.count())):
                item = self._list_layout.itemAt(i)
                if item and item.widget() and item.widget() != self._empty_label:
                    w = item.widget()
                    self._list_layout.removeWidget(w)
                    w.deleteLater()

            total_items = len(installed) + len(system_fonts)
            self._empty_label.setVisible(total_items == 0)

            # Render Metaglyph-installed items first
            for inst in installed:
                card = self._create_font_item(
                    title=inst.family_name,
                    subtitle=f"Installed via Metaglyph ({inst.provider})",
                    scope=inst.install_scope,
                    is_managed=True,
                )
                self._list_layout.addWidget(card)

            # Render cached system fonts
            for sf in system_fonts:
                if any(inst.family_name == sf.family_name for inst in installed):
                    continue
                card = self._create_font_item(
                    title=sf.family_name,
                    subtitle=sf.file_path,
                    scope=sf.scope,
                    is_managed=sf.is_metaglyph_managed,
                )
                self._list_layout.addWidget(card)

        except Exception as exc:
            logger.error("Failed to refresh system view: %s", exc)

    def _create_font_item(
        self, title: str, subtitle: str, scope: str, is_managed: bool
    ) -> QFrame:
        item = QFrame(self._list_container)
        item.setStyleSheet(
            "QFrame { background-color: #17171d; border: 1px solid #252530; border-radius: 8px; padding: 10px; } QFrame:hover { background-color: #1d1d26; border-color: #383848; }"
        )
        layout = QHBoxLayout(item)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        name_lbl = QLabel(title, item)
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        info_layout.addWidget(name_lbl)

        sub_lbl = QLabel(subtitle, item)
        sub_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        info_layout.addWidget(sub_lbl)

        layout.addLayout(info_layout, stretch=1)

        # Badges
        scope_badge = QLabel(scope, item)
        scope_color = "#38bdf8" if scope == "User" else "#f59e0b"
        scope_badge.setStyleSheet(
            f"background-color: #1c2438; color: {scope_color}; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px;"
        )
        layout.addWidget(scope_badge)

        if is_managed:
            mgmt_badge = QLabel("Managed", item)
            mgmt_badge.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px;"
            )
            layout.addWidget(mgmt_badge)

        return item
