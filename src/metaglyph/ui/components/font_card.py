"""Font card widget with metadata badges and live native sample preview."""

from __future__ import annotations

import asyncio
import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from metaglyph.db.models import Font
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.ui.components.font_preview import FontPreviewWidget

logger = logging.getLogger(__name__)


class FontCard(QFrame):
    """Card item displaying font family metadata and live micro-subset preview."""

    clicked = Signal(object)  # Font

    def __init__(
        self,
        font: Font,
        subset_fetcher: SubsetFetcher | None = None,
        sample_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.font = font
        self.subset_fetcher = subset_fetcher
        self._sample_text = sample_text
        self._is_selected = False
        self._fetch_task: asyncio.Task | None = None

        self.setObjectName("fontCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._init_ui()
        self._start_subset_load()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(8)

        # Header Row: Family name & Badges
        header_widget = QWidget(self)
        header_widget.setObjectName("fontCardHeader")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        # Family Name
        self._name_label = QLabel(self.font.family_name, header_widget)
        self._name_label.setObjectName("fontFamilyLabel")
        header_layout.addWidget(self._name_label)

        # Provider Badge
        prov_name = self.font.primary_provider.replace("_", " ").title()
        self._provider_badge = QLabel(prov_name, header_widget)
        self._provider_badge.setObjectName("fontProviderBadge")
        header_layout.addWidget(self._provider_badge)

        # Category Badge (support multiple categories)
        cats = []
        raw_cat = (self.font.category or "").strip()
        raw_display = "Sans-Serif" if raw_cat.lower() in ("sans-serif", "sans_serif", "sansserif") else raw_cat.title()
        if raw_display:
            cats.append(raw_display)

        curated = self.font.curated_category.strip().title() if self.font.curated_category else None
        if curated and curated.lower() != raw_display.lower() and curated not in cats:
            cats.append(curated)

        cat_name = " • ".join(cats) if cats else "Sans-Serif"
        self._cat_badge = QLabel(cat_name, header_widget)
        self._cat_badge.setObjectName("fontCategoryBadge")
        header_layout.addWidget(self._cat_badge)

        # Styles Count
        styles_count = len(self.font.variants) if self.font.variants else 1
        styles_text = f"{styles_count} {'Style' if styles_count == 1 else 'Styles'}"
        self._styles_badge = QLabel(styles_text, header_widget)
        self._styles_badge.setObjectName("fontStylesBadge")
        header_layout.addWidget(self._styles_badge)

        # Nerd Font Badge if available
        if self.font.has_nerd_font:
            self._nerd_badge = QLabel("◈ Nerd Font", header_widget)
            self._nerd_badge.setObjectName("fontNerdBadge")
            header_layout.addWidget(self._nerd_badge)

        # Variable Font Badge if variable
        if self.font.is_variable:
            self._var_badge = QLabel("Variable", header_widget)
            self._var_badge.setObjectName("fontVariableBadge")
            header_layout.addWidget(self._var_badge)

        header_layout.addStretch(1)
        main_layout.addWidget(header_widget)

        # Font Preview Row
        self.preview_widget = FontPreviewWidget(
            font_family=None,  # Fallback initially
            sample_text=self._sample_text,
            point_size=20.0,
            parent=self,
        )
        main_layout.addWidget(self.preview_widget)

        self.setLayout(main_layout)

    def cleanup(self) -> None:
        """Cancel in-flight async tasks before widget destruction."""
        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()
            self._fetch_task = None

    def _start_subset_load(self) -> None:
        """Asynchronously trigger micro-subset fetching without blocking UI thread."""
        if not self.subset_fetcher:
            return

        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()

        try:
            loop = asyncio.get_running_loop()
            self._fetch_task = loop.create_task(self._fetch_subset_coro())
        except RuntimeError:
            # No running loop in synchronous contexts / tests
            pass

    async def _fetch_subset_coro(self) -> None:
        """Coroutine fetching subset and updating preview widget."""
        if not self.subset_fetcher:
            return

        try:
            sample = self.preview_widget.sample_text
            _, family_name = await self.subset_fetcher.get_or_fetch_subset(self.font, sample)
            if family_name:
                self.preview_widget.set_font_family(family_name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Failed to load subset preview for '%s': %s", self.font.family_name, exc)

    def set_sample_text(self, text: str) -> None:
        """Update sample text displayed on preview."""
        self._sample_text = text
        self.preview_widget.set_sample_text(text)
        # Refresh subset for new sample text
        self._start_subset_load()

    def set_selected(self, selected: bool) -> None:
        """Toggle selected highlight state."""
        self._is_selected = selected
        if selected:
            self.setProperty("class", "selected")
            self.setStyleSheet(
                "#fontCard { border: 1.5px solid #6366f1; background-color: #1f1f2a; }"
            )
        else:
            self.setProperty("class", "")
            self.setStyleSheet("")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse click and emit clicked signal."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.font)
        super().mousePressEvent(event)
