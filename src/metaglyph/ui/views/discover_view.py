"""Discover view dashboard displaying curated font category cards and spotlight collections."""

from __future__ import annotations

import asyncio
import logging
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from metaglyph.db.models import Font
from metaglyph.db.repository import FontRepository
from metaglyph.subsetting.fetcher import SubsetFetcher

logger = logging.getLogger(__name__)

CURATED_CATEGORY_METADATA = [
    {
        "category": "Interface",
        "icon": "◈",
        "title": "Interface",
        "description": "Clean, highly readable sans-serif typefaces engineered for modern UI design and application workflows.",
        "examples": ["Inter", "Roboto", "Plus Jakarta Sans"],
    },
    {
        "category": "Code",
        "icon": "⟨/⟩",
        "title": "Code",
        "description": "Monospaced fonts optimized for syntax clarity, coding ligatures, and developer terminal ergonomics.",
        "examples": ["JetBrains Mono", "Fira Code", "Hack"],
    },
    {
        "category": "Header",
        "icon": "¶",
        "title": "Header",
        "description": "Punchy, expressive display and headline fonts designed for high visual impact and titles.",
        "examples": ["Montserrat", "Syne", "Cabinet Grotesk"],
    },
    {
        "category": "Prose",
        "icon": "§",
        "title": "Prose",
        "description": "Refined serif and editorial typefaces tailored for sustained, effortless long-form reading.",
        "examples": ["Merriweather", "Playfair Display", "Lora"],
    },
    {
        "category": "Display",
        "icon": "★",
        "title": "Display",
        "description": "Distinctive, bold, artistic letterforms for branding, posters, creative typography, and logos.",
        "examples": ["Bebas Neue", "Righteous", "Orbitron"],
    },
    {
        "category": "Handwriting",
        "icon": "✎",
        "title": "Handwriting",
        "description": "Organic, brush, and cursive handwritten scripts for personal, casual, or signature styles.",
        "examples": ["Caveat", "Pacifico", "Dancing Script"],
    },
    {
        "category": "Sans-Serif",
        "icon": "Aa",
        "title": "Sans-Serif",
        "description": "Modernist typefaces without serifs, engineered for clarity and visual consistency across all screen resolutions.",
        "examples": ["Inter", "Roboto", "Open Sans"],
    },
    {
        "category": "Serif",
        "icon": "Tt",
        "title": "Serif",
        "description": "Classic typefaces with decorative serifs, designed for elegant literary publishing and comfortable editorial reading.",
        "examples": ["Merriweather", "Lora", "PT Serif"],
    },
    {
        "category": "Monospace",
        "icon": "⌨",
        "title": "Monospace",
        "description": "Fixed-width character grid typefaces designed for code editors, developer terminals, and technical data.",
        "examples": ["JetBrains Mono", "Space Mono", "Fira Code"],
    },
]


class CategoryCardWidget(QFrame):
    """Clickable curated category card with title, icon, description, and font count."""

    clicked = Signal(str)  # category name

    def __init__(
        self,
        category: str,
        icon: str,
        title: str,
        description: str,
        examples: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.category = category
        self.setObjectName("categoryCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._init_ui(icon, title, description, examples)

    def _init_ui(
        self,
        icon: str,
        title: str,
        description: str,
        examples: list[str],
    ) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(8)

        # Top Header: Icon Badge, Title, and Count Badge
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)

        icon_label = QLabel(icon, self)
        icon_label.setObjectName("categoryCardIcon")
        icon_label.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #818cf8; background-color: #1f2436; padding: 3px 6px; border-radius: 4px; border: 1px solid #2d344d;"
        )
        header_layout.addWidget(icon_label)

        title_label = QLabel(title, self)
        title_label.setObjectName("categoryCardTitle")
        header_layout.addWidget(title_label)

        header_layout.addStretch(1)

        self._count_badge = QLabel("Browsing...", self)
        self._count_badge.setObjectName("categoryCardCount")
        header_layout.addWidget(self._count_badge)

        main_layout.addLayout(header_layout)

        # Description
        desc_label = QLabel(description, self)
        desc_label.setObjectName("categoryCardDesc")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)

        # Example tags row
        examples_layout = QHBoxLayout()
        examples_layout.setContentsMargins(0, 2, 0, 0)
        examples_layout.setSpacing(5)

        ex_prefix = QLabel("Examples:", self)
        ex_prefix.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        examples_layout.addWidget(ex_prefix)

        for ex in examples:
            tag = QLabel(ex, self)
            tag.setStyleSheet(
                "background-color: #1c202d; color: #cbd5e1; font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid #282e3f;"
            )
            examples_layout.addWidget(tag)

        examples_layout.addStretch(1)
        main_layout.addLayout(examples_layout)

        self.setLayout(main_layout)

    def set_font_count(self, count: int) -> None:
        """Update category font count label."""
        self._count_badge.setText(f"{count:,} fonts")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.category)
        super().mousePressEvent(event)


class DiscoverView(QWidget):
    """Discover view containing curated category dashboard and featured collections."""

    category_selected = Signal(str)  # Curated category name
    font_selected = Signal(object)  # Font model
    sync_requested = Signal()

    def __init__(
        self,
        repository: FontRepository | None = None,
        subset_fetcher: SubsetFetcher | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("discoverView")
        self.repository = repository
        self.subset_fetcher = subset_fetcher

        self._category_cards: dict[str, CategoryCardWidget] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll Area for responsive dashboard
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget(scroll)
        container.setObjectName("discoverContainer")
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(24, 20, 24, 24)
        content_layout.setSpacing(20)

        # Banner / Spotlight Card
        spotlight = QFrame(container)
        spotlight.setObjectName("spotlightCard")
        spotlight_layout = QVBoxLayout(spotlight)
        spotlight_layout.setContentsMargins(20, 18, 20, 18)
        spotlight_layout.setSpacing(8)

        spotlight_title = QLabel("Explore Beautiful Typography", spotlight)
        spotlight_title.setObjectName("spotlightTitle")
        spotlight_layout.addWidget(spotlight_title)

        spotlight_subtitle = QLabel(
            "Browse thousands of open-source fonts from Fontsource, Google Fonts, and Nerd Fonts with live native previews.",
            spotlight,
        )
        spotlight_subtitle.setObjectName("spotlightSubtitle")
        spotlight_subtitle.setWordWrap(True)
        spotlight_layout.addWidget(spotlight_subtitle)

        # Sync Banner helper (shown if catalog is empty)
        self._empty_notice = QWidget(spotlight)
        empty_layout = QHBoxLayout(self._empty_notice)
        empty_layout.setContentsMargins(0, 8, 0, 0)
        empty_layout.setSpacing(12)

        empty_label = QLabel("Catalog is currently empty. Sync to download metadata.", self._empty_notice)
        empty_label.setStyleSheet("color: #f59e0b; font-weight: 500;")
        empty_layout.addWidget(empty_label)

        sync_btn = QPushButton("Sync Font Catalog", self._empty_notice)
        sync_btn.setProperty("class", "primary-btn")
        sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sync_btn.clicked.connect(self.sync_requested.emit)
        empty_layout.addWidget(sync_btn)
        empty_layout.addStretch(1)

        spotlight_layout.addWidget(self._empty_notice)
        content_layout.addWidget(spotlight)

        # Section Header
        section_label = QLabel("Browse Categories", container)
        section_label.setStyleSheet("font-size: 15px; font-weight: 700; color: #f8fafc;")
        content_layout.addWidget(section_label)

        # 2-Column Responsive Category Grid
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(12)

        for idx, item in enumerate(CURATED_CATEGORY_METADATA):
            card = CategoryCardWidget(
                category=item["category"],
                icon=item["icon"],
                title=item["title"],
                description=item["description"],
                examples=item["examples"],
                parent=container,
            )
            card.clicked.connect(self._on_category_clicked)
            self._category_cards[item["category"]] = card

            row = idx // 2
            col = idx % 2
            grid_layout.addWidget(card, row, col)

        content_layout.addLayout(grid_layout)
        content_layout.addStretch(1)

        scroll.setWidget(container)
        root_layout.addWidget(scroll)
        self.setLayout(root_layout)

    def _on_category_clicked(self, category: str) -> None:
        self.category_selected.emit(category)

    async def refresh_stats(self) -> None:
        """Asynchronously load category counts from SQLite repository."""
        if not self.repository:
            return

        try:
            counts = await self.repository.get_curated_category_counts()
            total_fonts = sum(counts.values())

            # Update notice visibility
            self._empty_notice.setVisible(total_fonts == 0)

            for cat_name, card in self._category_cards.items():
                cnt = counts.get(cat_name, 0)
                card.set_font_count(cnt)
        except Exception as exc:
            logger.error("Failed to load curated category counts: %s", exc)

    def trigger_async_refresh(self) -> None:
        """Schedule background stats refresh."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats())
        except RuntimeError:
            pass
