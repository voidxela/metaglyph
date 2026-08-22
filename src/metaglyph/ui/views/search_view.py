"""Search & Browse view with debounced search, filter chips, and live font preview cards."""

from __future__ import annotations

import asyncio
import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metaglyph.core.config import get_config
from metaglyph.db.models import Font, FontFilter
from metaglyph.db.repository import FontRepository
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.ui.components.filter_bar import FilterBar
from metaglyph.ui.components.font_card import FontCard
from metaglyph.ui.components.search_bar import SearchBar

logger = logging.getLogger(__name__)


class SearchView(QWidget):
    """Interactive font catalog search, filtering, and live preview browse view."""

    font_selected = Signal(object)  # Font
    sync_requested = Signal()

    def __init__(
        self,
        repository: FontRepository | None = None,
        subset_fetcher: SubsetFetcher | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("searchView")
        self.repository = repository
        self.subset_fetcher = subset_fetcher

        config = get_config()
        self._sample_text = config.default_sample_text
        self._current_filter = FontFilter(limit=40, offset=0)
        self._current_fonts: list[Font] = []
        self._total_count = 0
        self._selected_card: FontCard | None = None
        self._search_task: asyncio.Task | None = None

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 16)
        main_layout.setSpacing(12)

        # Top Control Area: Search Bar & Filter Bar
        controls_container = QWidget(self)
        controls_layout = QVBoxLayout(controls_container)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        # Search Bar
        self.search_bar = SearchBar(
            placeholder_text="Search fonts by family name (e.g. JetBrains Mono, Inter, Fira)...",
            debounce_ms=200,
            parent=controls_container,
        )
        self.search_bar.search_debounced.connect(self._on_search_query_changed)
        self.search_bar.search_cleared.connect(self._on_search_cleared)
        controls_layout.addWidget(self.search_bar)

        # Filter Bar
        self.filter_bar = FilterBar(controls_container)
        self.filter_bar.filter_changed.connect(self._on_filter_changed)
        controls_layout.addWidget(self.filter_bar)

        main_layout.addWidget(controls_container)

        # Results Info & Preview Text Tuning Bar
        info_bar = QWidget(self)
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(2, 4, 2, 4)
        info_layout.setSpacing(12)

        self._results_count_label = QLabel("Searching catalog...", info_bar)
        self._results_count_label.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500;")
        info_layout.addWidget(self._results_count_label)

        info_layout.addStretch(1)

        # Sample text customizer for live card previews
        sample_label = QLabel("Preview Text:", info_bar)
        sample_label.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        info_layout.addWidget(sample_label)

        self._sample_input = QLineEdit(self._sample_text, info_bar)
        self._sample_input.setPlaceholderText("Enter custom sample text...")
        self._sample_input.setStyleSheet(
            "background-color: #161922; border: 1px solid #282e3f; border-radius: 6px; padding: 4px 8px; color: #f1f5f9; font-size: 12px; min-width: 160px; max-width: 320px;"
        )
        self._sample_input.textChanged.connect(self._on_sample_text_changed)
        info_layout.addWidget(self._sample_input)

        main_layout.addWidget(info_bar)

        # Scrollable Font Results List
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cards_container = QWidget(self._scroll_area)
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 4, 0)
        self._cards_layout.setSpacing(8)

        # Empty / Loading State Widget
        self._empty_widget = QWidget(self._cards_container)
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setContentsMargins(32, 48, 32, 48)
        empty_layout.setSpacing(12)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_title = QLabel("No Fonts Found", self._empty_widget)
        self._empty_title.setStyleSheet("font-size: 16px; font-weight: 700; color: #cbd5e1;")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_title)

        self._empty_desc = QLabel(
            "Try adjusting your search query or reset the active category and provider filters.",
            self._empty_widget,
        )
        self._empty_desc.setStyleSheet("color: #64748b; font-size: 12px;")
        self._empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self._empty_desc)

        self._empty_action_btn = QPushButton("Sync Font Catalog", self._empty_widget)
        self._empty_action_btn.setProperty("class", "primary-btn")
        self._empty_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._empty_action_btn.clicked.connect(self.sync_requested.emit)
        empty_layout.addWidget(self._empty_action_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._cards_layout.addWidget(self._empty_widget)
        self._empty_widget.setVisible(False)

        # Pagination: Load More Button
        self._load_more_btn = QPushButton("Load More Fonts", self._cards_container)
        self._load_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_more_btn.setStyleSheet(
            "QPushButton { background-color: #1e1e28; border: 1px solid #2d2d3c; color: #818cf8; padding: 10px; border-radius: 8px; font-weight: 600; } QPushButton:hover { background-color: #262634; border-color: #6366f1; }"
        )
        self._load_more_btn.clicked.connect(self._on_load_more_clicked)
        self._load_more_btn.setVisible(False)
        self._cards_layout.addWidget(self._load_more_btn)

        self._scroll_area.setWidget(self._cards_container)
        main_layout.addWidget(self._scroll_area, stretch=1)

        self.setLayout(main_layout)

    def _on_search_query_changed(self, query: str) -> None:
        self._current_filter.query = query if query else None
        self._current_filter.offset = 0
        self.trigger_search()

    def _on_search_cleared(self) -> None:
        self._current_filter.query = None
        self._current_filter.offset = 0
        self.trigger_search()

    def _on_filter_changed(self, filter_obj: FontFilter) -> None:
        # Retain current query & pagination size
        filter_obj.query = self._current_filter.query
        filter_obj.limit = self._current_filter.limit
        filter_obj.offset = 0
        self._current_filter = filter_obj
        self.trigger_search()

    def _on_sample_text_changed(self, text: str) -> None:
        self._sample_text = text if text.strip() else get_config().default_sample_text
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), FontCard):
                item.widget().set_sample_text(self._sample_text)

    def _on_load_more_clicked(self) -> None:
        self._current_filter.offset += self._current_filter.limit
        self.trigger_search(append=True)

    def set_curated_category(self, curated_category: str | None) -> None:
        """Apply curated category filter and update filter bar UI."""
        self.filter_bar.set_curated_category(curated_category)

    def set_query(self, query: str) -> None:
        """Set search query and update search bar UI."""
        self.search_bar.set_text(query)

    def trigger_search(self, append: bool = False) -> None:
        """Asynchronously execute database query."""
        try:
            loop = asyncio.get_running_loop()
            self._search_task = loop.create_task(self.execute_search_async(append=append))
        except RuntimeError:
            pass

    async def execute_search_async(self, append: bool = False) -> None:
        """Async worker fetching fonts from FontRepository and rendering cards."""
        if not self.repository:
            return

        try:
            self._results_count_label.setText("Searching catalog...")
            fonts, total = await self.repository.search_fonts(self._current_filter)
            self._total_count = total

            if append:
                self._current_fonts.extend(fonts)
            else:
                self._current_fonts = fonts
                self._clear_cards()

            self._render_font_cards(fonts)

            # Update count label
            shown = len(self._current_fonts)
            if total == 0:
                self._results_count_label.setText("0 fonts found")
                self._empty_widget.setVisible(True)
                self._load_more_btn.setVisible(False)
            else:
                self._results_count_label.setText(f"Showing {shown:,} of {total:,} fonts")
                self._empty_widget.setVisible(False)
                self._load_more_btn.setVisible(shown < total)

            # Background prefetch for new batch
            if self.subset_fetcher and fonts:
                asyncio.create_task(
                    self.subset_fetcher.prefetch_subsets(fonts, self._sample_text, limit=15)
                )

        except Exception as exc:
            logger.error("Search query failed: %s", exc)
            self._results_count_label.setText("Error querying catalog")

    def _clear_cards(self) -> None:
        """Remove all existing font card widgets from layout."""
        # Keep empty_widget and load_more_btn, remove other widgets
        for i in reversed(range(self._cards_layout.count())):
            item = self._cards_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if widget not in (self._empty_widget, self._load_more_btn):
                    self._cards_layout.removeWidget(widget)
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()

    def _render_font_cards(self, fonts: list[Font]) -> None:
        """Create and add FontCard widgets to layout."""
        insert_idx = max(0, self._cards_layout.count() - 2)

        for font in fonts:
            card = FontCard(
                font=font,
                subset_fetcher=self.subset_fetcher,
                sample_text=self._sample_text,
                parent=self._cards_container,
            )
            card.clicked.connect(self._on_card_clicked)
            self._cards_layout.insertWidget(insert_idx, card)
            insert_idx += 1

    def _on_card_clicked(self, font: Font) -> None:
        # Update selection state
        sender = self.sender()
        if isinstance(sender, FontCard):
            if self._selected_card and self._selected_card != sender:
                self._selected_card.set_selected(False)
            self._selected_card = sender
            sender.set_selected(True)

        self.font_selected.emit(font)
