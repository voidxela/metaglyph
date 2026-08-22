"""Nerd Font suggestion banner, variant selector, and quick-switch component."""

from __future__ import annotations

import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from metaglyph.db.models import Font
from metaglyph.db.normalizer import extract_nerd_font_counterpart, is_nerd_font

logger = logging.getLogger(__name__)

NERD_VARIANTS = ["Standard", "Mono", "Propo"]


class NerdFontBadge(QFrame):
    """Interactive banner displaying Nerd Font availability, variant selection, and counterpart switching."""

    switch_requested = Signal(str, str)  # (target_slug_or_id, variant_name)
    variant_changed = Signal(str)        # variant_name ("Standard", "Mono", "Propo")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("nerdBadge")

        self._font: Font | None = None
        self._counterpart_slug: str | None = None
        self._is_already_nerd: bool = False

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(6)

        # Header Row: Icon & Title
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        self._title_label = QLabel("◈ Nerd Font Counterpart Available", self)
        self._title_label.setObjectName("nerdBadgeTitle")
        self._title_label.setStyleSheet("color: #c084fc; font-weight: 700; font-size: 12px;")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch(1)
        main_layout.addLayout(header_layout)

        # Description
        self._desc_label = QLabel(
            "Includes developer icons, glyphs, and ligatures.", self
        )
        self._desc_label.setObjectName("nerdBadgeDesc")
        self._desc_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        self._desc_label.setWordWrap(True)
        main_layout.addWidget(self._desc_label)

        # Controls: Variant Selector + Switch Button
        controls_layout = QHBoxLayout()
        controls_layout.setContentsMargins(0, 4, 0, 0)
        controls_layout.setSpacing(8)

        var_label = QLabel("Variant:", self)
        var_label.setStyleSheet("color: #cbd5e1; font-size: 11px; font-weight: 600;")
        controls_layout.addWidget(var_label)

        self._variant_combo = QComboBox(self)
        self._variant_combo.setObjectName("nerdVariantCombo")
        for v in NERD_VARIANTS:
            self._variant_combo.addItem(v)
        self._variant_combo.setCurrentText("Standard")
        self._variant_combo.setToolTip("Select Nerd Font variant (Standard, Mono, or Propo)")
        self._variant_combo.currentTextChanged.connect(self._on_variant_changed)
        controls_layout.addWidget(self._variant_combo, stretch=1)

        self._switch_btn = QPushButton("Switch to Nerd Font", self)
        self._switch_btn.setObjectName("nerdBadgeBtn")
        self._switch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._switch_btn.setStyleSheet(
            "QPushButton { background-color: #4c1d95; color: #f5d0fe; border: 1px solid #7c3aed; padding: 4px 10px; border-radius: 5px; font-weight: 600; font-size: 11px; } "
            "QPushButton:hover { background-color: #5b21b6; color: #ffffff; border-color: #a855f7; }"
        )
        self._switch_btn.clicked.connect(self._on_switch_clicked)
        controls_layout.addWidget(self._switch_btn, stretch=2)

        main_layout.addLayout(controls_layout)
        self.setLayout(main_layout)

        self.setStyleSheet(
            "QFrame#nerdBadge { background-color: #1c132b; border: 1px solid #3f1e68; border-radius: 8px; }"
        )

    @property
    def variant_combo(self) -> QComboBox:
        return self._variant_combo

    @property
    def action_btn(self) -> QPushButton:
        return self._switch_btn

    def set_font(self, font: Font | None) -> None:
        """Update badge state and visibility based on font properties."""
        self._font = font

        if font is None:
            self.setVisible(False)
            return

        is_nf = font.primary_provider == "nerd_fonts" or is_nerd_font(font.family_name)
        self._is_already_nerd = is_nf

        if is_nf:
            # Viewing a Nerd Font
            base_slug, _ = extract_nerd_font_counterpart(font.family_name)
            self._counterpart_slug = base_slug
            self._title_label.setText("◈ Nerd Font Patched Version")
            self._desc_label.setText("Patched with Devicons, FontAwesome, Octicons & Powerline glyphs.")
            self._switch_btn.setText("Original Standard Font")
            self.setVisible(True)
        elif font.has_nerd_font or font.nerd_font_slug:
            # Viewing a standard font with counterpart
            self._counterpart_slug = font.nerd_font_slug or f"{font.id}-nerd-font"
            self._title_label.setText("◈ Nerd Font Counterpart Available")
            self._desc_label.setText(
                "Includes developer icons, powerline glyphs, and ligatures."
            )
            self._switch_btn.setText("Switch to Nerd Font")
            self.setVisible(True)
        else:
            self._counterpart_slug = None
            self.setVisible(False)

    def get_selected_variant(self) -> str:
        """Return the currently selected Nerd Font variant ('Standard', 'Mono', 'Propo')."""
        return self._variant_combo.currentText()

    def set_selected_variant(self, variant: str) -> None:
        """Set active variant in the combo box."""
        if variant in NERD_VARIANTS:
            self._variant_combo.setCurrentText(variant)

    def _on_variant_changed(self, variant: str) -> None:
        self.variant_changed.emit(variant)

    def _on_switch_clicked(self) -> None:
        if self._counterpart_slug:
            self.switch_requested.emit(self._counterpart_slug, self.get_selected_variant())
