"""Installed font registry, family grouping, metadata inspector, and batch uninstaller view."""

from __future__ import annotations

import asyncio
import datetime
import logging
from pathlib import Path
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QClipboard, QFontDatabase, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
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
from metaglyph.db.normalizer import normalize_family_name
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector, extract_font_names
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.ui.components.font_preview import FontPreviewWidget
from metaglyph.ui.components.search_bar import SearchBar

logger = logging.getLogger(__name__)


def _variant_to_qfont_weight(style_name: str) -> int:
    """Map typography style name to standard QFont integer weight."""
    s = style_name.lower().strip()
    if "thin" in s or "hairline" in s:
        return 100
    if "extralight" in s or "extra light" in s or "ultralight" in s:
        return 200
    if "light" in s:
        return 300
    if "medium" in s:
        return 500
    if "semibold" in s or "semi bold" in s or "demibold" in s:
        return 600
    if "bold" in s:
        return 700
    if "extrabold" in s or "extra bold" in s or "ultrabold" in s:
        return 800
    if "black" in s or "heavy" in s:
        return 900
    return 400


def _variant_sort_order(style_name: str) -> tuple[int, int, str]:
    """Sort key helper for standard typography variant ordering."""
    order = {
        "thin": 100,
        "hairline": 100,
        "extralight": 200,
        "extra light": 200,
        "ultralight": 200,
        "light": 300,
        "regular": 400,
        "normal": 400,
        "book": 400,
        "medium": 500,
        "semibold": 600,
        "semi bold": 600,
        "demibold": 600,
        "bold": 700,
        "extrabold": 800,
        "extra bold": 800,
        "ultrabold": 800,
        "black": 900,
        "heavy": 900,
    }
    s = style_name.lower().strip()
    is_italic = 1 if ("italic" in s or "oblique" in s) else 0
    clean = s.replace("italic", "").replace("oblique", "").strip()
    weight_score = order.get(clean, 450)
    return (weight_score, is_italic, style_name)


class SystemFontItemWidget(QFrame):
    """Condensed single-line widget representing a single installed or system font variant."""

    selection_changed = Signal(object, bool)  # (item, is_selected)
    uninstall_requested = Signal(object)       # (InstalledFont or SystemFontCacheEntry)
    expand_requested = Signal(object)          # (SystemFontItemWidget)

    def __init__(
        self,
        item: InstalledFont | SystemFontCacheEntry,
        family_name: str | None = None,
        style_name: str | None = None,
        file_path: str | None = None,
        is_managed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("systemFontCard")
        self.item = item
        self.family_name = family_name or item.family_name
        self.style_name = style_name or getattr(item, "style_name", "Regular") or "Regular"
        self.file_path = file_path or (item.file_paths[0] if isinstance(item, InstalledFont) and item.file_paths else getattr(item, "file_path", ""))
        self.is_managed = is_managed
        self._is_expanded: bool = False

        self._init_ui()
        self._details_anim = QPropertyAnimation(self.details_box, b"maximumHeight", self)
        self._details_anim.setDuration(200)
        self._details_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._details_anim.finished.connect(self._on_details_anim_finished)

    def _init_ui(self) -> None:
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 6, 8, 6)
        main_layout.setSpacing(4)

        # Primary Single-Line Row
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        # 1. Selection Checkbox
        self.checkbox = QCheckBox(self)
        self.checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.checkbox.toggled.connect(self._on_toggled)
        row_layout.addWidget(self.checkbox)

        # 2. Font Display Title (Family — Variant)
        display_name = f"{self.family_name} — {self.style_name}"
        self.name_label = QLabel(display_name, self)
        self.name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.name_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #f8fafc;")
        row_layout.addWidget(self.name_label)

        # Subtle sub label (kept for backwards compatibility)
        if isinstance(self.item, InstalledFont):
            provider_title = self.item.provider.replace("_", " ").title()
            installed_date = datetime.datetime.fromtimestamp(self.item.installed_at).strftime("%Y-%m-%d")
            sub_text = f"{provider_title} • {installed_date}"
        else:
            sub_text = Path(self.file_path).name if self.file_path else ""
        self.sub_label = QLabel(sub_text, self)
        self.sub_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.sub_label.setStyleSheet("color: #64748b; font-size: 11px;")
        row_layout.addWidget(self.sub_label)

        row_layout.addStretch(1)

        # 3. Format tag
        fmt = Path(self.file_path).suffix.lstrip(".").upper() if self.file_path else "TTF"
        if fmt:
            format_badge = QLabel(fmt, self)
            format_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            format_badge.setStyleSheet(
                "background-color: #1e2230; color: #94a3b8; font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 3px;"
            )
            row_layout.addWidget(format_badge)

        # 4. Scope Badge
        scope = self.item.install_scope if isinstance(self.item, InstalledFont) else getattr(self.item, "scope", "System")
        scope_badge = QLabel(scope, self)
        scope_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        scope_color = "#38bdf8" if scope == "User" else "#f59e0b"
        scope_badge.setStyleSheet(
            f"background-color: #1c2438; color: {scope_color}; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;"
        )
        row_layout.addWidget(scope_badge)

        # 5. Managed Badge
        if self.is_managed:
            mgmt_badge = QLabel("Managed", self)
            mgmt_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            mgmt_badge.setStyleSheet(
                "background-color: #064e3b; color: #34d399; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;"
            )
            row_layout.addWidget(mgmt_badge)

        # 6. Uninstall Button
        self.uninstall_btn = QPushButton("Uninstall", self)
        self.uninstall_btn.setObjectName("uninstallItemBtn")
        self.uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_btn.setStyleSheet(
            "QPushButton { background-color: #7f1d1d; color: #fecaca; border: 1px solid #991b1b; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; } "
            "QPushButton:hover { background-color: #991b1b; color: #ffffff; }"
        )
        self.uninstall_btn.clicked.connect(self._on_uninstall_clicked)
        row_layout.addWidget(self.uninstall_btn)

        main_layout.addLayout(row_layout)

        # Details Context Drawer (shown when row is selected / expanded)
        self.details_box = QFrame(self)
        self.details_box.setObjectName("systemFontDetailsBox")
        details_layout = QVBoxLayout(self.details_box)
        details_layout.setContentsMargins(12, 10, 12, 10)
        details_layout.setSpacing(8)

        # Load font into Qt application font database if file exists on disk
        if self.file_path and Path(self.file_path).exists():
            try:
                QFontDatabase.addApplicationFont(self.file_path)
            except Exception:
                pass

        # Live Font Preview in Details Box
        is_italic = "italic" in self.style_name.lower() or "oblique" in self.style_name.lower()
        self.preview_widget = FontPreviewWidget(
            font_family=self.family_name,
            sample_text="The quick brown fox jumps over the lazy dog 1234567890",
            point_size=15.0,
            weight=_variant_to_qfont_weight(self.style_name),
            italic=is_italic,
            parent=self.details_box,
        )
        self.preview_widget.setObjectName("systemFontPreview")
        self.preview_widget.setStyleSheet(
            "background-color: #12141c; border: 1px solid #1e2433; border-radius: 4px; padding: 6px 10px; color: #f1f5f9;"
        )
        details_layout.addWidget(self.preview_widget)

        # Detailed metadata (with first line removed as info is present in header)
        if isinstance(self.item, InstalledFont):
            paths_str = "\n".join(f"  • {p}" for p in self.item.file_paths)
            d_text = (
                f"Font ID: {self.item.font_id}   |   Provider: {self.item.provider}\n"
                f"Installed At: {datetime.datetime.fromtimestamp(self.item.installed_at).strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Files:\n{paths_str}"
            )
        else:
            ps_name = getattr(self.item, "postscript_name", None) or "N/A"
            d_text = (
                f"PostScript: {ps_name}\n"
                f"Path: {self.file_path}"
            )

        details_lbl = QLabel(d_text, self.details_box)
        details_lbl.setObjectName("systemFontPath")
        details_lbl.setWordWrap(True)
        details_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details_layout.addWidget(details_lbl)

        # Context action buttons
        actions_layout = QHBoxLayout()
        actions_layout.setContentsMargins(0, 4, 0, 0)
        actions_layout.setSpacing(8)

        self.copy_path_btn = QPushButton("📋 Copy Path", self.details_box)
        self.copy_path_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_path_btn.setStyleSheet(
            "QPushButton { background-color: #22222f; color: #cbd5e1; border: 1px solid #333346; padding: 4px 10px; border-radius: 4px; font-size: 11px; } "
            "QPushButton:hover { background-color: #2c2c3d; color: #ffffff; }"
        )
        self.copy_path_btn.clicked.connect(self._copy_path_to_clipboard)
        actions_layout.addWidget(self.copy_path_btn)

        actions_layout.addStretch(1)
        details_layout.addLayout(actions_layout)

        main_layout.addWidget(self.details_box)
        self.details_box.setVisible(False)
        self.details_box.setMaximumHeight(0)

        self.setLayout(main_layout)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Clicking on row header toggles expansion."""
        if event.button() == Qt.MouseButton.LeftButton:
            pt = event.position().toPoint()
            child = self.childAt(pt)
            interactive = (self.checkbox, self.uninstall_btn, self.copy_path_btn)
            if child not in interactive and (
                not self.details_box.isVisible() or not self.details_box.geometry().contains(pt)
            ):
                self.expand_requested.emit(self)
                return
        super().mousePressEvent(event)

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()

    def set_selected(self, selected: bool) -> None:
        self.checkbox.setChecked(selected)

    def is_expanded(self) -> bool:
        return self._is_expanded

    def _on_details_anim_finished(self) -> None:
        if not self._is_expanded:
            self.details_box.setVisible(False)
        else:
            self.details_box.setMaximumHeight(16777215)

    def set_expanded(self, expanded: bool, animated: bool = True) -> None:
        if self._is_expanded == expanded:
            return
        self._is_expanded = expanded
        self.setProperty("selected", expanded)
        self.style().unpolish(self)
        self.style().polish(self)

        if not animated:
            self._details_anim.stop()
            if expanded:
                self.details_box.setVisible(True)
                self.details_box.setMaximumHeight(16777215)
            else:
                self.details_box.setMaximumHeight(0)
                self.details_box.setVisible(False)
            return

        self._details_anim.stop()
        if expanded:
            self.details_box.setVisible(True)
            self.details_box.setMaximumHeight(16777215)
            target_h = self.details_box.layout().sizeHint().height()
            start_h = self.details_box.height() if self.details_box.isVisible() else 0
            self.details_box.setMaximumHeight(start_h)
            self._details_anim.setStartValue(start_h)
            self._details_anim.setEndValue(target_h)
            self._details_anim.start()
        else:
            start_h = self.details_box.height()
            self.details_box.setMaximumHeight(start_h)
            self._details_anim.setStartValue(start_h)
            self._details_anim.setEndValue(0)
            self._details_anim.start()

    def toggle_expand(self) -> None:
        self.expand_requested.emit(self)

    def set_row_selected(self, selected: bool) -> None:
        self.set_expanded(selected, animated=False)

    def _on_toggled(self, checked: bool) -> None:
        self.selection_changed.emit(self.item, checked)

    def _copy_path_to_clipboard(self) -> None:
        if self.file_path:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(self.file_path)
                self.copy_path_btn.setText("✓ Copied!")
                self.copy_path_btn.setEnabled(False)
                try:
                    asyncio.get_running_loop().call_later(1.5, self._reset_copy_btn)
                except RuntimeError:
                    pass

    def _reset_copy_btn(self) -> None:
        self.copy_path_btn.setText("📋 Copy Path")
        self.copy_path_btn.setEnabled(True)

    def _on_uninstall_clicked(self) -> None:
        self.uninstall_requested.emit(self.item)


class SystemFontFamilyHeader(QFrame):
    """Header row frame for SystemFontFamilyWidget."""

    header_clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pt = event.position().toPoint()
            child = self.childAt(pt)
            if not isinstance(child, QCheckBox):
                self.header_clicked.emit()
                return
        super().mousePressEvent(event)


class SystemFontFamilyWidget(QFrame):
    """Card grouping font variants belonging to the same font family."""

    def __init__(
        self,
        family_name: str,
        initially_collapsed: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("systemFontFamilyGroup")
        self.family_name = family_name
        self.cards: list[SystemFontItemWidget] = []
        self._is_collapsed: bool = initially_collapsed

        self._init_ui()
        self._anim = QPropertyAnimation(self.cards_container, b"maximumHeight", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.finished.connect(self._on_animation_finished)

        if self._is_collapsed:
            self.cards_container.setVisible(False)
            self.cards_container.setMaximumHeight(0)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header Frame
        self.header_frame = SystemFontFamilyHeader(self)
        self.header_frame.setObjectName("systemFontFamilyHeader")
        self.header_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_frame.header_clicked.connect(self._on_header_clicked)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        self.chevron_label = QLabel("▶" if self._is_collapsed else "▼", self.header_frame)
        self.chevron_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.chevron_label.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700;")
        header_layout.addWidget(self.chevron_label)

        self.family_checkbox = QCheckBox(self.header_frame)
        self.family_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.family_checkbox.toggled.connect(self._on_family_checkbox_toggled)
        header_layout.addWidget(self.family_checkbox)

        self.title_label = QLabel(self.family_name, self.header_frame)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #f8fafc;")
        header_layout.addWidget(self.title_label)

        self.count_badge = QLabel("0 variants", self.header_frame)
        self.count_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.count_badge.setStyleSheet(
            "background-color: #22222e; color: #94a3b8; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px;"
        )
        header_layout.addWidget(self.count_badge)

        header_layout.addStretch(1)

        self.scope_container = QHBoxLayout()
        self.scope_container.setSpacing(6)
        header_layout.addLayout(self.scope_container)

        main_layout.addWidget(self.header_frame)

        # Cards Container
        self.cards_container = QWidget(self)
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(6, 4, 6, 6)
        self.cards_layout.setSpacing(2)
        main_layout.addWidget(self.cards_container)

        self.setLayout(main_layout)

    def _on_header_clicked(self) -> None:
        self.set_collapsed(not self._is_collapsed)

    def _on_animation_finished(self) -> None:
        if self._is_collapsed:
            self.cards_container.setVisible(False)
        else:
            self.cards_container.setMaximumHeight(16777215)

    def set_collapsed(self, collapsed: bool, animated: bool = True) -> None:
        if self._is_collapsed == collapsed:
            return
        self._is_collapsed = collapsed
        self.chevron_label.setText("▶" if collapsed else "▼")

        if not animated:
            self._anim.stop()
            if collapsed:
                self.cards_container.setMaximumHeight(0)
                self.cards_container.setVisible(False)
            else:
                self.cards_container.setVisible(True)
                self.cards_container.setMaximumHeight(16777215)
            return

        self._anim.stop()
        if collapsed:
            start_h = self.cards_container.height()
            self.cards_container.setMaximumHeight(start_h)
            self._anim.setStartValue(start_h)
            self._anim.setEndValue(0)
            self._anim.start()
        else:
            self.cards_container.setVisible(True)
            self.cards_container.setMaximumHeight(16777215)
            target_h = self.cards_layout.sizeHint().height()
            start_h = self.cards_container.height() if self.cards_container.isVisible() else 0
            self.cards_container.setMaximumHeight(start_h)
            self._anim.setStartValue(start_h)
            self._anim.setEndValue(target_h)
            self._anim.start()

    def add_card(self, card: SystemFontItemWidget) -> None:
        self.cards.append(card)
        self.cards_layout.addWidget(card)
        card.selection_changed.connect(self._on_card_selection_changed)
        self._update_header_meta()

    def _on_card_selection_changed(self, item: object, is_selected: bool) -> None:
        self._update_family_checkbox()

    def _on_family_checkbox_toggled(self, checked: bool) -> None:
        for card in self.cards:
            card.checkbox.blockSignals(True)
            card.set_selected(checked)
            card.checkbox.blockSignals(False)
            card.selection_changed.emit(card.item, checked)

    def _update_family_checkbox(self) -> None:
        selected_count = sum(1 for c in self.cards if c.is_selected())
        total = len(self.cards)

        self.family_checkbox.blockSignals(True)
        if selected_count == total and total > 0:
            self.family_checkbox.setCheckState(Qt.CheckState.Checked)
        elif selected_count > 0:
            self.family_checkbox.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.family_checkbox.setCheckState(Qt.CheckState.Unchecked)
        self.family_checkbox.blockSignals(False)

    def _update_header_meta(self) -> None:
        count = len(self.cards)
        self.count_badge.setText(f"{count} variant" if count == 1 else f"{count} variants")

        # Clear existing scope badges
        for i in reversed(range(self.scope_container.count())):
            item = self.scope_container.itemAt(i)
            if item and item.widget():
                w = item.widget()
                self.scope_container.removeWidget(w)
                w.deleteLater()

        scopes = {c.item.install_scope if isinstance(c.item, InstalledFont) else getattr(c.item, "scope", "System") for c in self.cards}
        if "User" in scopes:
            b = QLabel("User", self.header_frame)
            b.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            b.setStyleSheet("background-color: #1c2438; color: #38bdf8; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;")
            self.scope_container.addWidget(b)
        if "System" in scopes:
            b = QLabel("System", self.header_frame)
            b.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            b.setStyleSheet("background-color: #1c2438; color: #f59e0b; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;")
            self.scope_container.addWidget(b)

        if any(c.is_managed for c in self.cards):
            mb = QLabel("Managed", self.header_frame)
            mb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            mb.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 4px;")
            self.scope_container.addWidget(mb)


class SystemView(QWidget):
    """Local OS and Metaglyph-installed font registry view with family grouping and batch uninstallation."""

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
        self._family_widgets: list[SystemFontFamilyWidget] = []
        self._expanded_card: SystemFontItemWidget | None = None
        self._rendered_signature: tuple | None = None
        self._is_scanning: bool = False
        self._is_uninstalling: bool = False
        self._has_scanned_on_open: bool = False

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

        title_label = QLabel("Installed Fonts", self)
        title_label.setStyleSheet("font-size: 18px; font-weight: 800; color: #f8fafc;")
        title_layout.addWidget(title_label)

        sub_label = QLabel(
            "Inspect local user and system fonts, and manage installations.",
            self,
        )
        sub_label.setStyleSheet("color: #64748b; font-size: 12px;")
        title_layout.addWidget(sub_label)

        header_layout.addLayout(title_layout)
        header_layout.addStretch(1)

        self._header_scan_indicator = QLabel("⟳ Scanning fonts...", self)
        self._header_scan_indicator.setObjectName("headerScanIndicator")
        self._header_scan_indicator.setVisible(False)
        header_layout.addWidget(self._header_scan_indicator)

        main_layout.addLayout(header_layout)

        # 2. Search Bar & Filter Chips
        filter_layout = QHBoxLayout()
        filter_layout.setContentsMargins(0, 4, 0, 4)
        filter_layout.setSpacing(8)

        self._search_bar = SearchBar(
            placeholder_text="Filter installed fonts by family, variant, or path...",
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

        self._expand_all_btn = QPushButton("▼ Expand All", self._batch_bar)
        self._expand_all_btn.setObjectName("expandAllBtn")
        self._expand_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._expand_all_btn.clicked.connect(lambda: self.expand_all_families(animated=True))
        batch_layout.addWidget(self._expand_all_btn)

        self._collapse_all_btn = QPushButton("▶ Collapse All", self._batch_bar)
        self._collapse_all_btn.setObjectName("collapseAllBtn")
        self._collapse_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_all_btn.clicked.connect(lambda: self.collapse_all_families(animated=True))
        batch_layout.addWidget(self._collapse_all_btn)

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
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_container = QWidget(self._scroll_area)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(10)

        # Scanning / Loading indicator label
        self._loading_label = QLabel("Scanning system fonts...", self._list_container)
        self._loading_label.setObjectName("systemLoadingLabel")
        self._loading_label.setStyleSheet("color: #818cf8; font-size: 13px; font-weight: 600; padding: 32px;")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setVisible(False)
        self._list_layout.addWidget(self._loading_label)

        # Empty state label
        self._empty_label = QLabel("No installed fonts found.", self._list_container)
        self._empty_label.setStyleSheet("color: #64748b; font-size: 13px; padding: 32px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        self._list_layout.addWidget(self._empty_label)

        self._scroll_area.setWidget(self._list_container)
        main_layout.addWidget(self._scroll_area, stretch=1)

        self.setLayout(main_layout)

    def showEvent(self, event) -> None:
        """Auto-scan local fonts when the Installed Fonts tab is opened."""
        super().showEvent(event)
        if not self._has_scanned_on_open:
            self._has_scanned_on_open = True
            self.trigger_scan_and_sync()

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

    def _on_select_all_toggled(self, checked: bool) -> None:
        self.set_all_selected(checked)

    def set_all_selected(self, selected: bool) -> None:
        for card in self._card_widgets:
            card.set_selected(selected)
        for family_widget in self._family_widgets:
            family_widget._update_family_checkbox()
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

    def _on_card_expand_requested(self, card: SystemFontItemWidget) -> None:
        """Handle single row detail expansion across the registry view."""
        if self._expanded_card == card:
            # Clicking currently expanded row collapses it
            card.set_expanded(False)
            self._expanded_card = None
        else:
            # Collapse previous expanded card without refreshing or touching family states
            if self._expanded_card is not None and self._expanded_card != card:
                self._expanded_card.set_expanded(False)
            card.set_expanded(True)
            self._expanded_card = card

    def expand_all_families(self, animated: bool = True) -> None:
        """Expand all font family groups."""
        for fam in self._family_widgets:
            fam.set_collapsed(False, animated=animated)

    def collapse_all_families(self, animated: bool = True) -> None:
        """Collapse all font family groups."""
        for fam in self._family_widgets:
            fam.set_collapsed(True, animated=animated)

    def trigger_refresh(self) -> None:
        """Schedule background database refresh."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_installed_async())
        except RuntimeError:
            pass

    def trigger_scan_and_sync(self) -> None:
        """Run system font scan and database update asynchronously."""
        self._is_scanning = True
        has_existing = len(self._family_widgets) > 0
        self._header_scan_indicator.setVisible(has_existing)
        self._loading_label.setVisible(not has_existing)
        self._empty_label.setVisible(False)
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
            has_existing = len(self._family_widgets) > 0
            self._header_scan_indicator.setVisible(has_existing)
            self._loading_label.setVisible(not has_existing)
            self._empty_label.setVisible(False)

            await self.detector.scan_and_sync(self.repository)
            await self.refresh_installed_async()
        except Exception as exc:
            logger.error("Failed to scan system fonts: %s", exc)
        finally:
            self._is_scanning = False
            self._header_scan_indicator.setVisible(False)
            self._loading_label.setVisible(False)
            total_items = sum(len(f.cards) for f in self._family_widgets)
            self._empty_label.setVisible(total_items == 0)

    async def refresh_installed_async(self) -> None:
        """Retrieve installed and system fonts from SQLite repository with family grouping."""
        if not self.repository:
            return

        try:
            installed = await self.repository.get_installed_fonts(scope=self._filter_scope)
            system_fonts = await self.repository.get_system_fonts(
                scope=self._filter_scope, metaglyph_only=self._metaglyph_only
            )

            # Filter by search query if any
            if self._query:
                installed = [
                    f for f in installed
                    if self._query in f.family_name.lower() or any(self._query in p.lower() for p in f.file_paths)
                ]
                system_fonts = [
                    f for f in system_fonts
                    if self._query in f.family_name.lower() or self._query in getattr(f, "style_name", "").lower() or self._query in f.file_path.lower()
                ]

            self._installed_fonts = installed
            self._system_fonts = system_fonts

            # Group items by normalized family name
            # key: normalized_family -> {"display_name": str, "items": list[dict]}
            families: dict[str, dict] = {}

            # 1. Process Metaglyph-installed fonts
            installed_paths: set[str] = set()
            for inst in installed:
                norm_fam = normalize_family_name(inst.family_name)
                if norm_fam not in families:
                    families[norm_fam] = {"display_name": inst.family_name, "items": []}

                if inst.file_paths:
                    for p_str in inst.file_paths:
                        installed_paths.add(p_str)
                        fam, style, _ = extract_font_names(Path(p_str))
                        families[norm_fam]["items"].append({
                            "item": inst,
                            "family_name": inst.family_name,
                            "style_name": style,
                            "file_path": p_str,
                            "is_managed": True,
                        })
                else:
                    families[norm_fam]["items"].append({
                        "item": inst,
                        "family_name": inst.family_name,
                        "style_name": "Regular",
                        "file_path": "",
                        "is_managed": True,
                    })

            # 2. Process cached system fonts (skipping paths already accounted for in installed)
            if not self._metaglyph_only:
                for sf in system_fonts:
                    if sf.file_path in installed_paths:
                        continue
                    norm_fam = normalize_family_name(sf.family_name)
                    if norm_fam not in families:
                        families[norm_fam] = {"display_name": sf.family_name, "items": []}

                    families[norm_fam]["items"].append({
                        "item": sf,
                        "family_name": sf.family_name,
                        "style_name": getattr(sf, "style_name", "Regular") or "Regular",
                        "file_path": sf.file_path,
                        "is_managed": sf.is_metaglyph_managed,
                    })

            # Clean up empty families (where all files might have been removed)
            families = {k: v for k, v in families.items() if v["items"]}

            total_items = sum(len(f["items"]) for f in families.values())
            has_existing = len(self._family_widgets) > 0

            if self._is_scanning:
                self._loading_label.setVisible(not has_existing)
                self._empty_label.setVisible(False)
            else:
                self._loading_label.setVisible(False)
                self._empty_label.setVisible(total_items == 0)

            # Sort families alphabetically
            sorted_family_keys = sorted(families.keys(), key=lambda k: families[k]["display_name"].lower())

            # Build data signature for content change detection
            new_sig_list = []
            for norm_key in sorted_family_keys:
                fam_info = families[norm_key]
                sorted_items = sorted(fam_info["items"], key=lambda it: _variant_sort_order(it["style_name"]))
                fam_sig = (
                    fam_info["display_name"],
                    tuple((it["style_name"], it["file_path"], it["is_managed"]) for it in sorted_items),
                )
                new_sig_list.append(fam_sig)
            new_signature = tuple(new_sig_list)

            # If content has not changed and list is already populated, skip rebuilding DOM to avoid reset and flicker
            if self._rendered_signature == new_signature and len(self._family_widgets) > 0:
                return

            # Capture existing UI state before updating
            expanded_families = {fam.family_name for fam in self._family_widgets if not fam._is_collapsed}
            expanded_card_key = (self._expanded_card.family_name, self._expanded_card.style_name) if self._expanded_card else None
            selected_card_keys = {(c.family_name, c.style_name) for c in self._card_widgets if c.is_selected()}
            scroll_pos = self._scroll_area.verticalScrollBar().value()

            # Clear existing widgets and spacers
            for i in reversed(range(self._list_layout.count())):
                item = self._list_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if widget and widget not in (self._empty_label, self._loading_label):
                        self._list_layout.removeWidget(widget)
                        widget.hide()
                        widget.setParent(None)
                        widget.deleteLater()
                    elif not widget:
                        self._list_layout.removeItem(item)

            self._card_widgets.clear()
            self._family_widgets.clear()
            self._expanded_card = None

            for norm_key in sorted_family_keys:
                fam_info = families[norm_key]
                # Preserve previously expanded state or default to collapsed
                is_collapsed = fam_info["display_name"] not in expanded_families
                family_widget = SystemFontFamilyWidget(
                    family_name=fam_info["display_name"],
                    initially_collapsed=is_collapsed,
                    parent=self._list_container,
                )

                # Sort variants within family logically
                sorted_items = sorted(fam_info["items"], key=lambda it: _variant_sort_order(it["style_name"]))

                for item_dict in sorted_items:
                    card = SystemFontItemWidget(
                        item=item_dict["item"],
                        family_name=item_dict["family_name"],
                        style_name=item_dict["style_name"],
                        file_path=item_dict["file_path"],
                        is_managed=item_dict["is_managed"],
                        parent=family_widget.cards_container,
                    )
                    card.selection_changed.connect(self._on_card_selection_changed)
                    card.uninstall_requested.connect(self._on_single_uninstall_requested)
                    card.expand_requested.connect(self._on_card_expand_requested)

                    card_key = (item_dict["family_name"], item_dict["style_name"])
                    if card_key in selected_card_keys:
                        card.set_selected(True)
                    if card_key == expanded_card_key:
                        card.set_expanded(True, animated=False)
                        self._expanded_card = card

                    family_widget.add_card(card)
                    self._card_widgets.append(card)

                self._list_layout.addWidget(family_widget)
                self._family_widgets.append(family_widget)

            if self._family_widgets:
                self._list_layout.addStretch(1)

            self._scroll_area.verticalScrollBar().setValue(scroll_pos)
            self._rendered_signature = new_signature
            self._update_selection_state()

        except Exception as exc:
            logger.error("Failed to refresh system view: %s", exc)

    def _on_single_uninstall_requested(self, item: object) -> None:
        """Handle individual font uninstall button click with confirmation."""
        family_name = getattr(item, "family_name", "Font")
        msg = f"Are you sure you want to uninstall '{family_name}'?\nThis will remove the font file(s) from your system."

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
                if self.repository:
                    await self.repository.delete_system_font_cache_by_paths(item.file_paths)
                self.font_uninstalled.emit(item.font_id, item.install_scope)
            elif isinstance(item, SystemFontCacheEntry):
                norm_id = normalize_family_name(item.family_name)
                res = await self.uninstaller.uninstall_font(
                    font_id=norm_id,
                    family_name=item.family_name,
                    file_paths=[Path(item.file_path)],
                    scope=item.scope,
                )
                if self.repository:
                    await self.repository.delete_system_font_cache_by_paths([item.file_path])
                self.font_uninstalled.emit(norm_id, item.scope)

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
            seen_ids: set[tuple[str, str]] = set()
            all_paths: list[str] = []

            for item in items:
                if isinstance(item, InstalledFont):
                    key = (item.font_id, item.install_scope)
                    all_paths.extend(item.file_paths)
                    if key not in seen_ids:
                        seen_ids.add(key)
                        installed_records.append(item)
                elif isinstance(item, SystemFontCacheEntry):
                    norm_id = normalize_family_name(item.family_name)
                    key = (norm_id, item.scope)
                    all_paths.append(item.file_path)
                    if key not in seen_ids:
                        seen_ids.add(key)
                        installed_records.append(
                            InstalledFont(
                                font_id=norm_id,
                                family_name=item.family_name,
                                provider="system",
                                install_scope=item.scope,
                                installed_at=item.last_scanned_at,
                                file_paths=[item.file_path],
                            )
                        )

            results = await self.uninstaller.batch_uninstall(installed_records)
            if self.repository:
                await self.repository.delete_system_font_cache_by_paths(all_paths)
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
