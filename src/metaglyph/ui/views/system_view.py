"""System font registry, metadata inspector, and batch font uninstaller view."""

from __future__ import annotations

import asyncio
import datetime
import logging
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from metaglyph.db.models import InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.ui.components.search_bar import SearchBar

logger = logging.getLogger(__name__)


class SystemFontItemWidget(QFrame):
    """Card widget representing a single installed or system font in the registry."""

    selection_changed = Signal(object, bool)  # (item, is_selected)
    uninstall_requested = Signal(object)       # (InstalledFont or SystemFontCacheEntry)

    def __init__(
        self,
        item: InstalledFont | SystemFontCacheEntry,
        is_managed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("systemFontCard")
        self.item = item
        self.is_managed = is_managed
        self._is_expanded: bool = False

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(6)

        # Primary Row
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        # 1. Selection Checkbox
        self.checkbox = QCheckBox(self)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox.toggled.connect(self._on_toggled)
        row_layout.addWidget(self.checkbox)

        # 2. Font info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.name_label = QLabel(self.item.family_name, self)
        self.name_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        info_layout.addWidget(self.name_label)

        if isinstance(self.item, InstalledFont):
            provider_title = self.item.provider.replace("_", " ").title()
            installed_date = datetime.datetime.fromtimestamp(self.item.installed_at).strftime("%Y-%m-%d %H:%M")
            sub_text = f"Installed via {provider_title} • {installed_date} • {len(self.item.file_paths)} file(s)"
        else:
            sub_text = str(self.item.file_path)

        self.sub_label = QLabel(sub_text, self)
        self.sub_label.setStyleSheet("color: #64748b; font-size: 11px;")
        info_layout.addWidget(self.sub_label)

        row_layout.addLayout(info_layout, stretch=1)

        # 3. Badges
        scope = self.item.install_scope if isinstance(self.item, InstalledFont) else self.item.scope
        scope_badge = QLabel(scope, self)
        scope_color = "#38bdf8" if scope == "User" else "#f59e0b"
        scope_badge.setStyleSheet(
            f"background-color: #1c2438; color: {scope_color}; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px;"
        )
        row_layout.addWidget(scope_badge)

        if self.is_managed:
            mgmt_badge = QLabel("Managed", self)
            mgmt_badge.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px;"
            )
            row_layout.addWidget(mgmt_badge)

        # 4. Expand / Details Button
        self.expand_btn = QPushButton("Details", self)
        self.expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_btn.setStyleSheet(
            "background-color: #252533; color: #94a3b8; border: 1px solid #333345; padding: 4px 10px; border-radius: 4px; font-size: 11px;"
        )
        self.expand_btn.clicked.connect(self._toggle_expand)
        row_layout.addWidget(self.expand_btn)

        # 5. Uninstall Button
        self.uninstall_btn = QPushButton("Uninstall", self)
        self.uninstall_btn.setObjectName("uninstallItemBtn")
        self.uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_btn.setStyleSheet(
            "QPushButton { background-color: #7f1d1d; color: #fecaca; border: 1px solid #991b1b; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; } QPushButton:hover { background-color: #991b1b; color: #ffffff; }"
        )
        self.uninstall_btn.clicked.connect(self._on_uninstall_clicked)
        row_layout.addWidget(self.uninstall_btn)

        main_layout.addLayout(row_layout)

        # Details Box (hidden by default)
        self.details_box = QFrame(self)
        self.details_box.setObjectName("systemFontDetailsBox")
        details_layout = QVBoxLayout(self.details_box)
        details_layout.setContentsMargins(8, 8, 8, 8)
        details_layout.setSpacing(4)

        if isinstance(self.item, InstalledFont):
            paths_str = "\n".join(f"• {p}" for p in self.item.file_paths)
            d_text = (
                f"Font ID: {self.item.font_id}\n"
                f"Provider: {self.item.provider}\n"
                f"Scope: {self.item.install_scope}\n"
                f"Installed At: {datetime.datetime.fromtimestamp(self.item.installed_at).strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Files:\n{paths_str}"
            )
        else:
            d_text = (
                f"Family: {self.item.family_name}\n"
                f"PostScript: {self.item.postscript_name or 'N/A'}\n"
                f"Scope: {self.item.scope}\n"
                f"Path: {self.item.file_path}"
            )

        details_lbl = QLabel(d_text, self.details_box)
        details_lbl.setObjectName("systemFontPath")
        details_lbl.setWordWrap(True)
        details_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(details_lbl)

        main_layout.addWidget(self.details_box)
        self.details_box.setVisible(False)

        self.setLayout(main_layout)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def set_selected(self, selected: bool) -> None:
        self.checkbox.setChecked(selected)

    def _on_toggled(self, checked: bool) -> None:
        self.selection_changed.emit(self.item, checked)

    def _toggle_expand(self) -> None:
        self._is_expanded = not self._is_expanded
        self.details_box.setVisible(self._is_expanded)
        self.expand_btn.setText("Hide" if self._is_expanded else "Details")

    def _on_uninstall_clicked(self) -> None:
        self.uninstall_requested.emit(self.item)


class SystemView(QWidget):
    """Local OS and Metaglyph-installed font registry view with batch uninstallation."""

    scan_requested = Signal()
    batch_uninstall_requested = Signal(list)  # list of InstalledFont or SystemFontCacheEntry
    batch_uninstall_completed = Signal(list)  # list of InstallResult
    font_uninstalled = Signal(str, str)       # (font_id, scope)

    def __init__(
        self,
        repository: FontRepository | None = None,
        detector: FontDetector | None = None,
        uninstaller: FontUninstaller | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("systemView")
        self.repository = repository
        self.detector = detector or FontDetector()
        self.uninstaller = uninstaller or FontUninstaller(repository=repository)

        self._filter_scope: str | None = None
        self._metaglyph_only: bool = False
        self._query: str = ""
        self._installed_fonts: list[InstalledFont] = []
        self._system_fonts: list[SystemFontCacheEntry] = []
        self._card_widgets: list[SystemFontItemWidget] = []
        self._is_scanning: bool = False
        self._is_uninstalling: bool = False

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 16)
        main_layout.setSpacing(12)

        # 1. Header section
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
            "QPushButton { background-color: #22222c; border: 1px solid #313140; color: #cbd5e1; padding: 8px 14px; border-radius: 6px; font-weight: 600; } "
            "QPushButton:hover { background-color: #2b2b38; border-color: #6366f1; color: #ffffff; }"
        )
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        header_layout.addWidget(self._scan_btn)

        main_layout.addLayout(header_layout)

        # 2. Search Bar & Filter Chips
        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 4, 0, 4)
        filter_layout.setSpacing(8)

        self._search_bar = SearchBar(
            placeholder_text="Filter installed fonts by family name or path...",
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

        # Managed only toggle
        self._managed_toggle = QPushButton("Metaglyph Managed", self)
        self._managed_toggle.setProperty("class", "filter-chip")
        self._managed_toggle.setCheckable(True)
        self._managed_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._managed_toggle.clicked.connect(self._on_managed_toggled)
        filter_layout.addWidget(self._managed_toggle)

        main_layout.addLayout(filter_layout)

        # 3. Batch Actions Bar
        self._batch_bar = QFrame(self)
        self._batch_bar.setObjectName("batchBar")
        batch_layout = QHBoxLayout(self._batch_bar)
        batch_layout.setContentsMargins(8, 6, 8, 6)
        batch_layout.setSpacing(12)

        self._select_all_check = QCheckBox("Select All", self._batch_bar)
        self._select_all_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_all_check.toggled.connect(self._on_select_all_toggled)
        batch_layout.addWidget(self._select_all_check)

        self._deselect_all_btn = QPushButton("Deselect All", self._batch_bar)
        self._deselect_all_btn.setStyleSheet(
            "background-color: transparent; color: #94a3b8; font-size: 11px; font-weight: 500; border: none; padding: 2px 6px;"
        )
        self._deselect_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._deselect_all_btn.clicked.connect(lambda: self.set_all_selected(False))
        batch_layout.addWidget(self._deselect_all_btn)

        self._batch_count_label = QLabel("0 fonts selected", self._batch_bar)
        self._batch_count_label.setObjectName("batchSelectedLabel")
        batch_layout.addWidget(self._batch_count_label)

        batch_layout.addStretch(1)

        self._batch_uninstall_btn = QPushButton("🗑️ Batch Uninstall", self._batch_bar)
        self._batch_uninstall_btn.setObjectName("batchUninstallBtn")
        self._batch_uninstall_btn.setEnabled(False)
        self._batch_uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._batch_uninstall_btn.clicked.connect(self._on_batch_uninstall_clicked)
        batch_layout.addWidget(self._batch_uninstall_btn)

        main_layout.addWidget(self._batch_bar)

        # 4. Content List / Scroll Area
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self._list_container = QWidget(self._scroll_area)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 8, 0)
        self._list_layout.setSpacing(8)

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

    def _on_managed_toggled(self, checked: bool) -> None:
        self._metaglyph_only = checked
        self.trigger_refresh()

    def _on_scan_clicked(self) -> None:
        self.scan_requested.emit()
        self.trigger_scan_and_sync()

    def _on_select_all_toggled(self, checked: bool) -> None:
        self.set_all_selected(checked)

    def set_all_selected(self, selected: bool) -> None:
        for card in self._card_widgets:
            card.set_selected(selected)
        self._update_selection_state()

    def get_selected_items(self) -> list[InstalledFont | SystemFontCacheEntry]:
        return [card.item for card in self._card_widgets if card.is_selected()]

    def _update_selection_state(self) -> None:
        selected_count = sum(1 for card in self._card_widgets if card.is_selected())
        total_count = len(self._card_widgets)

        self._batch_count_label.setText(f"{selected_count} of {total_count} selected")
        self._batch_uninstall_btn.setEnabled(selected_count > 0 and not self._is_uninstalling)

        # Update select all checkbox state without re-triggering signal
        self._select_all_check.blockSignals(True)
        self._select_all_check.setChecked(selected_count > 0 and selected_count == total_count)
        self._select_all_check.blockSignals(False)

    def _on_card_selection_changed(self, item: object, is_selected: bool) -> None:
        self._update_selection_state()

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
            self._is_scanning = True
            self._scan_btn.setEnabled(False)
            self._scan_btn.setText("⏳ Scanning...")
            await self.detector.scan_and_sync(self.repository)
            await self.refresh_installed_async()
        except Exception as exc:
            logger.error("Failed to scan system fonts: %s", exc)
        finally:
            self._is_scanning = False
            self._scan_btn.setEnabled(True)
            self._scan_btn.setText("🔍  Scan Local Fonts")

    async def refresh_installed_async(self) -> None:
        """Retrieve installed and system fonts from SQLite repository."""
        if not self.repository:
            return

        try:
            installed = await self.repository.get_installed_fonts(scope=self._filter_scope)
            system_fonts = await self.repository.get_system_fonts(
                scope=self._filter_scope, metaglyph_only=self._metaglyph_only
            )

            # Apply Metaglyph Only filter to installed if set
            if self._metaglyph_only:
                system_fonts = [f for f in system_fonts if f.is_metaglyph_managed]

            # Filter by search query if any
            if self._query:
                installed = [
                    f for f in installed
                    if self._query in f.family_name.lower() or any(self._query in p.lower() for p in f.file_paths)
                ]
                system_fonts = [
                    f for f in system_fonts
                    if self._query in f.family_name.lower() or self._query in f.file_path.lower()
                ]

            self._installed_fonts = installed
            self._system_fonts = system_fonts

            # Clear existing cards
            for card in self._card_widgets:
                self._list_layout.removeWidget(card)
                card.hide()
                card.setParent(None)
                card.deleteLater()
            self._card_widgets.clear()

            total_items = len(installed) + (0 if self._metaglyph_only else len(system_fonts))
            self._empty_label.setVisible(total_items == 0)

            # Render Metaglyph-installed items first
            installed_families = set()
            for inst in installed:
                installed_families.add(inst.family_name)
                card = SystemFontItemWidget(item=inst, is_managed=True, parent=self._list_container)
                card.selection_changed.connect(self._on_card_selection_changed)
                card.uninstall_requested.connect(self._on_single_uninstall_requested)
                self._list_layout.addWidget(card)
                self._card_widgets.append(card)

            # Render cached system fonts if not metaglyph-only
            if not self._metaglyph_only:
                for sf in system_fonts:
                    if sf.family_name in installed_families:
                        continue
                    card = SystemFontItemWidget(
                        item=sf, is_managed=sf.is_metaglyph_managed, parent=self._list_container
                    )
                    card.selection_changed.connect(self._on_card_selection_changed)
                    card.uninstall_requested.connect(self._on_single_uninstall_requested)
                    self._list_layout.addWidget(card)
                    self._card_widgets.append(card)

            self._update_selection_state()

        except Exception as exc:
            logger.error("Failed to refresh system view: %s", exc)

    def _on_single_uninstall_requested(self, item: object) -> None:
        """Handle individual font uninstall button click with confirmation."""
        family_name = item.family_name
        msg = f"Are you sure you want to uninstall '{family_name}'?\nThis will remove the font files from your system."

        reply = QMessageBox.question(
            self,
            "Confirm Font Uninstallation",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.uninstall_single_async(item))
            except RuntimeError:
                pass

    async def uninstall_single_async(self, item: object) -> None:
        """Asynchronously uninstall a single font item."""
        try:
            if isinstance(item, InstalledFont):
                res = await self.uninstaller.uninstall_installed_font(item)
                self.font_uninstalled.emit(item.font_id, item.install_scope)
            elif isinstance(item, SystemFontCacheEntry):
                res = await self.uninstaller.uninstall_font(
                    font_id=item.family_name.lower().replace(" ", "-"),
                    family_name=item.family_name,
                    file_paths=[Path(item.file_path)],
                    scope=item.scope,
                )
                self.font_uninstalled.emit(item.family_name, item.scope)

            await self.refresh_installed_async()
        except Exception as exc:
            logger.error("Failed to uninstall font %s: %s", getattr(item, "family_name", ""), exc)

    def _on_batch_uninstall_clicked(self) -> None:
        """Handle batch uninstall button click with confirmation modal."""
        selected_items = self.get_selected_items()
        if not selected_items:
            return

        count = len(selected_items)
        msg = (
            f"Are you sure you want to batch uninstall {count} selected font(s)?\n"
            "This will remove the font files from your local user/system directories."
        )

        reply = QMessageBox.question(
            self,
            "Confirm Batch Uninstallation",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.batch_uninstall_requested.emit(selected_items)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.batch_uninstall_async(selected_items))
            except RuntimeError:
                pass

    async def batch_uninstall_async(
        self, items: list[InstalledFont | SystemFontCacheEntry]
    ) -> list:
        """Execute batch uninstallation across selected fonts."""
        if not items:
            return []

        self._is_uninstalling = True
        self._batch_uninstall_btn.setEnabled(False)
        self._batch_uninstall_btn.setText("⏳ Uninstalling...")

        try:
            installed_records: list[InstalledFont] = []
            for item in items:
                if isinstance(item, InstalledFont):
                    installed_records.append(item)
                elif isinstance(item, SystemFontCacheEntry):
                    # Convert cache entry to temporary InstalledFont record for uninstaller
                    installed_records.append(
                        InstalledFont(
                            font_id=item.family_name.lower().replace(" ", "-"),
                            family_name=item.family_name,
                            provider="system",
                            install_scope=item.scope,
                            installed_at=item.last_scanned_at,
                            file_paths=[item.file_path],
                        )
                    )

            results = await self.uninstaller.batch_uninstall(installed_records)
            self.batch_uninstall_completed.emit(results)
            await self.refresh_installed_async()
            return results

        except Exception as exc:
            logger.error("Failed batch uninstallation: %s", exc)
            return []
        finally:
            self._is_uninstalling = False
            self._batch_uninstall_btn.setText("🗑️ Batch Uninstall")
            self._update_selection_state()
