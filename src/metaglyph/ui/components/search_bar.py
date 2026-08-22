"""Debounced live search input component."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class SearchBar(QWidget):
    """Search input bar with 200ms debounce timer and clear action."""

    # Emitted immediately on keystrokes
    text_changed = Signal(str)
    # Emitted after debounce delay (default 200ms)
    search_debounced = Signal(str)
    # Emitted when search is cleared
    search_cleared = Signal()
    # Emitted when Enter/Return is pressed
    return_pressed = Signal()

    def __init__(
        self,
        placeholder_text: str = "Search fonts by name, style, or family...",
        debounce_ms: int = 200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("searchBar")
        self._debounce_ms = debounce_ms

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        self._init_ui(placeholder_text)

    def _init_ui(self, placeholder_text: str) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Search container box
        self._container = QWidget(self)
        self._container.setObjectName("searchBarContainer")
        container_layout = QHBoxLayout(self._container)
        container_layout.setContentsMargins(10, 4, 8, 4)
        container_layout.setSpacing(8)

        # Search icon label
        self._icon_label = QLabel("🔍", self._container)
        self._icon_label.setStyleSheet("color: #64748b; font-size: 13px;")

        # Search line edit
        self._line_edit = QLineEdit(self._container)
        self._line_edit.setObjectName("searchLineEdit")
        self._line_edit.setPlaceholderText(placeholder_text)
        self._line_edit.textChanged.connect(self._on_text_changed)
        self._line_edit.returnPressed.connect(self._on_return_pressed)

        # Clear button
        self._clear_btn = QPushButton("✕", self._container)
        self._clear_btn.setObjectName("searchClearButton")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(self.clear)

        container_layout.addWidget(self._icon_label)
        container_layout.addWidget(self._line_edit, stretch=1)
        container_layout.addWidget(self._clear_btn)

        main_layout.addWidget(self._container)
        self.setLayout(main_layout)

    def _on_text_changed(self, text: str) -> None:
        self._clear_btn.setVisible(bool(text))
        self.text_changed.emit(text)
        # Restart debounce timer
        self._debounce_timer.start(self._debounce_ms)

    def _on_debounce_timeout(self) -> None:
        query = self._line_edit.text().strip()
        self.search_debounced.emit(query)

    def _on_return_pressed(self) -> None:
        self._debounce_timer.stop()
        query = self._line_edit.text().strip()
        self.search_debounced.emit(query)
        self.return_pressed.emit()

    def text(self) -> str:
        """Get current text query."""
        return self._line_edit.text().strip()

    def set_text(self, text: str) -> None:
        """Set query text programmatically."""
        self._line_edit.setText(text)

    def clear(self) -> None:
        """Clear query text and emit search_cleared."""
        self._line_edit.clear()
        self._debounce_timer.stop()
        self.search_cleared.emit()
        self.search_debounced.emit("")

    def set_placeholder_text(self, text: str) -> None:
        """Update placeholder text."""
        self._line_edit.setPlaceholderText(text)

    def set_debounce_interval(self, ms: int) -> None:
        """Update debounce interval in milliseconds."""
        self._debounce_ms = ms

    def setFocus(self) -> None:
        """Focus the inner text field."""
        self._line_edit.setFocus()
