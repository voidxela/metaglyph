"""Category, provider, and feature filter bar component."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metaglyph.db.models import FontFilter

CATEGORIES = [
    ("All", None),
    ("Interface", "Interface"),
    ("Code", "Code"),
    ("Header", "Header"),
    ("Prose", "Prose"),
    ("Display", "Display"),
    ("Handwriting", "Handwriting"),
    ("Sans-Serif", "sans-serif"),
    ("Serif", "serif"),
    ("Monospace", "monospace"),
]

PROVIDERS = [
    ("All", None),
    ("Fontsource", "fontsource"),
    ("Font Squirrel", "fontsquirrel"),
    ("Nerd Fonts", "nerd_fonts"),
]


class FilterBar(QWidget):
    """Filter bar presenting category chips, provider toggles, and feature filters in a clear 2-row layout."""

    filter_changed = Signal(object)  # FontFilter

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("filterBar")

        self._active_category: str | None = None
        self._active_curated_category: str | None = None
        self._active_provider: str | None = None
        self._is_variable_only: bool = False
        self._has_nerd_font_only: bool = False

        self._category_buttons: list[QPushButton] = []
        self._provider_buttons: list[QPushButton] = []

        self._init_ui()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Scroll area allowing smooth horizontal overflow without button clipping
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background-color: transparent;")

        container = QWidget(scroll)
        container.setStyleSheet("background-color: transparent;")
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        # Row 1: Structural Categories
        row1_layout = QHBoxLayout()
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(6)

        cat_label = QLabel("Category:", container)
        cat_label.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; min-width: 56px;")
        row1_layout.addWidget(cat_label)

        self._category_group = QButtonGroup(self)
        self._category_group.setExclusive(True)

        for label, val in CATEGORIES:
            btn = QPushButton(label, container)
            btn.setProperty("class", "filter-chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            if val is None:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked=False, v=val: self._on_category_clicked(v))
            self._category_group.addButton(btn)
            self._category_buttons.append(btn)
            row1_layout.addWidget(btn)

        row1_layout.addStretch(1)
        main_layout.addLayout(row1_layout)

        # Row 2: Providers + Features + Reset
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(6)

        prov_label = QLabel("Provider:", container)
        prov_label.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700; min-width: 56px;")
        row2_layout.addWidget(prov_label)

        self._provider_group = QButtonGroup(self)
        self._provider_group.setExclusive(True)

        for label, val in PROVIDERS:
            btn = QPushButton(label, container)
            btn.setProperty("class", "filter-chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            if val is None:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked=False, v=val: self._on_provider_clicked(v))
            self._provider_group.addButton(btn)
            self._provider_buttons.append(btn)
            row2_layout.addWidget(btn)

        row2_layout.addSpacing(8)

        # Subtle divider between providers and feature toggles
        sep = QFrame(container)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #282e3f; max-height: 16px;")
        row2_layout.addWidget(sep)

        row2_layout.addSpacing(4)

        # Feature toggles
        self._variable_check = QCheckBox("Variable", container)
        self._variable_check.setProperty("class", "filter-toggle")
        self._variable_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._variable_check.toggled.connect(self._on_variable_toggled)
        row2_layout.addWidget(self._variable_check)

        self._nerd_check = QCheckBox("Nerd Font", container)
        self._nerd_check.setProperty("class", "filter-toggle")
        self._nerd_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._nerd_check.toggled.connect(self._on_nerd_toggled)
        row2_layout.addWidget(self._nerd_check)

        row2_layout.addStretch(1)

        # Reset button
        self._reset_btn = QPushButton("Reset Filters", container)
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 11px; color: #64748b; background-color: transparent; border: 1px solid #282e3f; border-radius: 4px; } "
            "QPushButton:hover { color: #f1f5f9; background-color: #1f2433; border-color: #384259; }"
        )
        self._reset_btn.clicked.connect(self.reset_filters)
        row2_layout.addWidget(self._reset_btn)

        main_layout.addLayout(row2_layout)
        scroll.setWidget(container)
        root_layout.addWidget(scroll)
        self.setLayout(root_layout)

    def _on_category_clicked(self, category_val: str | None) -> None:
        curated_names = {"interface", "code", "header", "prose", "display", "handwriting"}
        if category_val and category_val.lower() in curated_names:
            self._active_curated_category = category_val
            self._active_category = None
        else:
            self._active_category = category_val
            self._active_curated_category = None
        self._emit_filter_changed()

    def _on_provider_clicked(self, provider_val: str | None) -> None:
        self._active_provider = provider_val
        self._emit_filter_changed()

    def _on_variable_toggled(self, checked: bool) -> None:
        self._is_variable_only = checked
        self._emit_filter_changed()

    def _on_nerd_toggled(self, checked: bool) -> None:
        self._has_nerd_font_only = checked
        self._emit_filter_changed()

    def _emit_filter_changed(self) -> None:
        filter_obj = self.get_filter()
        self.filter_changed.emit(filter_obj)

    def get_filter(self) -> FontFilter:
        """Construct FontFilter based on current UI state."""
        categories = [self._active_category] if self._active_category else []
        curated = [self._active_curated_category] if self._active_curated_category else []
        providers = [self._active_provider] if self._active_provider else []
        is_var = True if self._is_variable_only else None
        has_nf = True if self._has_nerd_font_only else None

        return FontFilter(
            categories=categories,
            curated_categories=curated,
            providers=providers,
            is_variable=is_var,
            has_nerd_font=has_nf,
            limit=50,
            offset=0,
        )

    def set_category(self, category: str | None) -> None:
        """Programmatically select category filter."""
        curated_names = {"interface", "code", "header", "prose", "display", "handwriting"}
        if category and category.lower() in curated_names:
            self.set_curated_category(category)
            return

        self._active_category = category
        self._active_curated_category = None

        matched = False
        if category:
            clean_cat = category.strip().lower()
            for btn in self._category_buttons:
                for label, val in CATEGORIES:
                    if val and (val.lower() == clean_cat or label.lower() == clean_cat) and btn.text().lower() == label.lower():
                        btn.setChecked(True)
                        matched = True
                        break
                if matched:
                    break

        if not matched and self._category_buttons:
            self._category_buttons[0].setChecked(True)

        self._emit_filter_changed()

    def set_curated_category(self, curated_category: str | None) -> None:
        """Programmatically apply curated category filter."""
        self._active_curated_category = curated_category
        self._active_category = None

        matched = False
        if curated_category:
            clean_cat = curated_category.strip().lower()
            for btn in self._category_buttons:
                for label, val in CATEGORIES:
                    if (label.lower() == clean_cat or (val and val.lower() == clean_cat)) and btn.text().lower() == label.lower():
                        btn.setChecked(True)
                        matched = True
                        break
                if matched:
                    break

        if not matched and self._category_buttons:
            self._category_buttons[0].setChecked(True)

        self._emit_filter_changed()

    def set_provider(self, provider: str | None) -> None:
        """Programmatically select provider filter."""
        self._active_provider = provider

        for btn in self._provider_buttons:
            for label, val in PROVIDERS:
                if val == provider and btn.text() == label:
                    btn.setChecked(True)
                    break
        self._emit_filter_changed()

    def reset_filters(self) -> None:
        """Reset all filters to default state."""
        self._active_category = None
        self._active_curated_category = None
        self._active_provider = None
        self._is_variable_only = False
        self._has_nerd_font_only = False

        widgets_to_block = [
            *self._category_buttons,
            *self._provider_buttons,
            self._variable_check,
            self._nerd_check,
        ]
        for w in widgets_to_block:
            w.blockSignals(True)

        try:
            if self._category_buttons:
                self._category_buttons[0].setChecked(True)
            if self._provider_buttons:
                self._provider_buttons[0].setChecked(True)

            self._variable_check.setChecked(False)
            self._nerd_check.setChecked(False)
        finally:
            for w in widgets_to_block:
                w.blockSignals(False)

        self._emit_filter_changed()
