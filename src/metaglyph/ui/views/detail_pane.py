"""Detail pane font inspector, size/weight tuner, and installation controller."""

from __future__ import annotations

import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from metaglyph.core.config import get_config
from metaglyph.db.models import Font
from metaglyph.installer.base import InstallScope
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.ui.components.font_preview import FontPreviewWidget

logger = logging.getLogger(__name__)

WEIGHT_MAP: dict[str, int] = {
    "Thin (100)": 100,
    "Extra Light (200)": 200,
    "Light (300)": 300,
    "Regular (400)": 400,
    "Medium (500)": 500,
    "SemiBold (600)": 600,
    "Bold (700)": 700,
    "ExtraBold (800)": 800,
    "Black (900)": 900,
}


class DetailPane(QFrame):
    """Sliding or docked side inspector for fine-tuning font preview, variant selection, and installation."""

    install_requested = Signal(object, str)  # (Font, "User" | "System")
    closed = Signal()

    def __init__(
        self,
        subset_fetcher: SubsetFetcher | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailPane")
        self.subset_fetcher = subset_fetcher
        self._font: Font | None = None

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Row: Title & Close Button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel("Font Inspector", self)
        self._title_label.setObjectName("detailPaneTitle")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch(1)

        self._close_btn = QPushButton("✕", self)
        self._close_btn.setStyleSheet(
            "background-color: transparent; color: #64748b; font-size: 14px; font-weight: bold; border: none; padding: 2px 6px;"
        )
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.closed.emit)
        header_layout.addWidget(self._close_btn)

        main_layout.addLayout(header_layout)

        # Subtitle & Badges
        self._subtitle_label = QLabel("Select a font to view details", self)
        self._subtitle_label.setObjectName("detailPaneSubtitle")
        main_layout.addWidget(self._subtitle_label)

        # Badges row
        self._badges_widget = QWidget(self)
        badges_layout = QHBoxLayout(self._badges_widget)
        badges_layout.setContentsMargins(0, 0, 0, 0)
        badges_layout.setSpacing(6)

        self._provider_badge = QLabel("Provider", self._badges_widget)
        self._provider_badge.setObjectName("fontProviderBadge")
        badges_layout.addWidget(self._provider_badge)

        self._cat_badge = QLabel("Category", self._badges_widget)
        self._cat_badge.setObjectName("fontCategoryBadge")
        badges_layout.addWidget(self._cat_badge)

        self._styles_badge = QLabel("Styles", self._badges_widget)
        self._styles_badge.setObjectName("fontStylesBadge")
        badges_layout.addWidget(self._styles_badge)

        badges_layout.addStretch(1)
        main_layout.addWidget(self._badges_widget)

        # Nerd Font Counterpart Banner (if applicable)
        self._nf_banner = QFrame(self)
        self._nf_banner.setStyleSheet(
            "background-color: #241442; border: 1px solid #4c1d95; border-radius: 8px; padding: 10px;"
        )
        nf_layout = QVBoxLayout(self._nf_banner)
        nf_layout.setContentsMargins(8, 8, 8, 8)
        nf_layout.setSpacing(4)

        nf_title = QLabel("󰊤 Nerd Font Counterpart Available", self._nf_banner)
        nf_title.setStyleSheet("color: #c084fc; font-weight: 700; font-size: 12px;")
        nf_layout.addWidget(nf_title)

        self._nf_desc = QLabel("Includes developer icons, glyphs, and ligatures.", self._nf_banner)
        self._nf_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self._nf_desc.setWordWrap(True)
        nf_layout.addWidget(self._nf_desc)

        main_layout.addWidget(self._nf_banner)
        self._nf_banner.setVisible(False)

        # Separator line
        sep1 = QFrame(self)
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #262632;")
        main_layout.addWidget(sep1)

        # Size Slider Section
        size_header_layout = QHBoxLayout()
        size_label = QLabel("Point Size", self)
        size_label.setObjectName("detailSectionHeader")
        size_header_layout.addWidget(size_label)
        size_header_layout.addStretch(1)

        self._size_val_label = QLabel("24 pt", self)
        self._size_val_label.setStyleSheet("color: #818cf8; font-weight: 600; font-size: 11px;")
        size_header_layout.addWidget(self._size_val_label)
        main_layout.addLayout(size_header_layout)

        self._size_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._size_slider.setRange(10, 72)
        self._size_slider.setValue(24)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        main_layout.addWidget(self._size_slider)

        # Weight Selector Section
        weight_label = QLabel("Weight", self)
        weight_label.setObjectName("detailSectionHeader")
        main_layout.addWidget(weight_label)

        self._weight_combo = QComboBox(self)
        for label in WEIGHT_MAP.keys():
            self._weight_combo.addItem(label)
        self._weight_combo.setCurrentText("Regular (400)")
        self._weight_combo.currentTextChanged.connect(self._on_weight_changed)
        main_layout.addWidget(self._weight_combo)

        # Interactive Sample Text Editor
        sample_header = QLabel("Sample Text", self)
        sample_header.setObjectName("detailSectionHeader")
        main_layout.addWidget(sample_header)

        self._sample_editor = QPlainTextEdit(self)
        self._sample_editor.setObjectName("detailSampleEditor")
        self._sample_editor.setMaximumHeight(80)
        self._sample_editor.setPlainText(get_config().default_sample_text)
        self._sample_editor.textChanged.connect(self._on_sample_text_changed)
        main_layout.addWidget(self._sample_editor)

        # Live Preview Box
        preview_header = QLabel("Live Rendering", self)
        preview_header.setObjectName("detailSectionHeader")
        main_layout.addWidget(preview_header)

        self._preview = FontPreviewWidget(
            font_family=None,
            sample_text=self._sample_editor.toPlainText(),
            point_size=24.0,
            parent=self,
        )
        main_layout.addWidget(self._preview)

        main_layout.addStretch(1)

        # Installation Scope Section
        scope_header = QLabel("Install Target Scope", self)
        scope_header.setObjectName("detailSectionHeader")
        main_layout.addWidget(scope_header)

        scope_group = QButtonGroup(self)
        self._radio_user = QRadioButton("User (No Admin / Sudo)", self)
        self._radio_user.setChecked(True)
        self._radio_user.setCursor(Qt.CursorShape.PointingHandCursor)
        scope_group.addButton(self._radio_user)
        main_layout.addWidget(self._radio_user)

        self._radio_system = QRadioButton("System-wide (Elevated Helper)", self)
        self._radio_system.setCursor(Qt.CursorShape.PointingHandCursor)
        scope_group.addButton(self._radio_system)
        main_layout.addWidget(self._radio_system)

        # Install Action Button
        self._install_btn = QPushButton("Install Font Family", self)
        self._install_btn.setProperty("class", "primary-btn")
        self._install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_btn.setStyleSheet("padding: 10px; font-size: 13px; font-weight: 700;")
        self._install_btn.clicked.connect(self._on_install_clicked)
        main_layout.addWidget(self._install_btn)

        self.setLayout(main_layout)

    def set_font(self, font: Font) -> None:
        """Populate inspector with font model data."""
        self._font = font
        self._title_label.setText(font.family_name)

        prov = font.primary_provider.replace("_", " ").title()
        self._subtitle_label.setText(f"Provided via {prov}")
        self._provider_badge.setText(prov)

        cat = (font.curated_category or font.category).title()
        self._cat_badge.setText(cat)

        styles_count = len(font.variants) if font.variants else 1
        self._styles_badge.setText(f"{styles_count} {'Style' if styles_count == 1 else 'Styles'}")

        self._nf_banner.setVisible(bool(font.has_nerd_font or font.nerd_font_slug))

        # Update preview family
        self._preview.set_font_family(font.family_name)

    def _on_size_changed(self, value: int) -> None:
        self._size_val_label.setText(f"{value} pt")
        self._preview.set_font_size(float(value))

    def _on_weight_changed(self, text: str) -> None:
        weight_val = WEIGHT_MAP.get(text, 400)
        self._preview.set_font_weight(weight_val)

    def _on_sample_text_changed(self) -> None:
        text = self._sample_editor.toPlainText().strip()
        self._preview.set_sample_text(text if text else get_config().default_sample_text)

    def _on_install_clicked(self) -> None:
        if not self._font:
            return
        scope = "User" if self._radio_user.isChecked() else "System"
        self.install_requested.emit(self._font, scope)
