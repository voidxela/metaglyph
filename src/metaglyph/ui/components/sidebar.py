"""Sidebar navigation component for Metaglyph main window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SidebarWidget(QWidget):
    """Left navigation sidebar containing app brand, page tabs, sync button, and catalog stats."""

    page_changed = Signal(int)  # 0: Discover, 1: Search, 2: System
    sync_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")

        self._nav_buttons: list[QPushButton] = []
        self._is_syncing = False

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header / Brand Section
        header_widget = QWidget(self)
        header_widget.setObjectName("sidebarHeader")
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 20, 16, 16)
        header_layout.setSpacing(4)

        logo_label = QLabel("METAGLYPH", header_widget)
        logo_label.setObjectName("sidebarLogo")
        header_layout.addWidget(logo_label)

        sub_label = QLabel("Font Manager & Browser", header_widget)
        sub_label.setObjectName("sidebarSubtitle")
        header_layout.addWidget(sub_label)

        main_layout.addWidget(header_widget)

        # Navigation Buttons Group
        nav_group_widget = QWidget(self)
        nav_group_widget.setObjectName("sidebarNavGroup")
        nav_layout = QVBoxLayout(nav_group_widget)
        nav_layout.setContentsMargins(10, 8, 10, 8)
        nav_layout.setSpacing(4)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        nav_items = [
            ("✦  Discover", 0),
            ("🔍  Search && Browse", 1),
            ("💻  Installed Fonts", 2),
        ]

        for text, page_idx in nav_items:
            btn = QPushButton(text, nav_group_widget)
            btn.setProperty("class", "nav-btn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, idx=page_idx: self._on_nav_clicked(idx))
            self._button_group.addButton(btn)
            self._nav_buttons.append(btn)
            nav_layout.addWidget(btn)

        # Default active item: Discover (0)
        self._nav_buttons[0].setChecked(True)

        main_layout.addWidget(nav_group_widget)
        main_layout.addStretch(1)

        # Sync Action Section
        sync_container = QWidget(self)
        sync_layout = QVBoxLayout(sync_container)
        sync_layout.setContentsMargins(12, 8, 12, 12)

        self._sync_btn = QPushButton("🔄  Sync Catalog", sync_container)
        self._sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_btn.setStyleSheet(
            "QPushButton { background-color: #22222c; border: 1px solid #313140; color: #94a3b8; padding: 8px 12px; border-radius: 6px; font-weight: 600; text-align: center; } QPushButton:hover { background-color: #2b2b38; color: #f1f5f9; border-color: #444458; }"
        )
        self._sync_btn.clicked.connect(self._on_sync_clicked)
        sync_layout.addWidget(self._sync_btn)

        main_layout.addWidget(sync_container)

        # Footer Section (Stats & Version)
        footer_widget = QWidget(self)
        footer_widget.setObjectName("sidebarFooter")
        footer_layout = QVBoxLayout(footer_widget)
        footer_layout.setContentsMargins(16, 12, 16, 16)
        footer_layout.setSpacing(4)

        self._stats_label = QLabel("0 fonts indexed\n0 installed", footer_widget)
        self._stats_label.setObjectName("sidebarStatsLabel")
        footer_layout.addWidget(self._stats_label)

        version_layout = QHBoxLayout()
        version_layout.setContentsMargins(0, 4, 0, 0)
        self._version_label = QLabel("v0.1.0", footer_widget)
        self._version_label.setObjectName("sidebarVersionLabel")
        version_layout.addWidget(self._version_label)
        version_layout.addStretch(1)

        footer_layout.addLayout(version_layout)
        main_layout.addWidget(footer_widget)

        self.setLayout(main_layout)

    def _on_nav_clicked(self, page_index: int) -> None:
        self.page_changed.emit(page_index)

    def _on_sync_clicked(self) -> None:
        if not self._is_syncing:
            self.sync_requested.emit()

    def set_current_page(self, page_index: int) -> None:
        """Update active navigation button state."""
        if 0 <= page_index < len(self._nav_buttons):
            self._nav_buttons[page_index].setChecked(True)

    def update_stats(self, total_fonts: int, installed_count: int) -> None:
        """Update catalog and installed font metrics in footer."""
        fonts_text = f"{total_fonts:,} fonts indexed" if total_fonts > 0 else "No fonts indexed"
        inst_text = f"{installed_count} installed"
        self._stats_label.setText(f"{fonts_text}\n{inst_text}")

    def set_syncing(self, is_syncing: bool, message: str = "Syncing Catalog...") -> None:
        """Update sync button state and label during active sync."""
        self._is_syncing = is_syncing
        if is_syncing:
            self._sync_btn.setEnabled(False)
            self._sync_btn.setText(f"⏳  {message}")
        else:
            self._sync_btn.setEnabled(True)
            self._sync_btn.setText("🔄  Sync Catalog")
