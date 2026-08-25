"""Native Qt QLabel font sample renderer with dynamic font styling."""

from __future__ import annotations

import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

from metaglyph.core.config import get_config

logger = logging.getLogger(__name__)


class FontPreviewWidget(QFrame):
    """Native Qt widget for live previewing rendered fonts at custom sizes and weights."""

    def __init__(
        self,
        font_family: str | None = None,
        sample_text: str | None = None,
        point_size: float = 20.0,
        weight: int = QFont.Weight.Normal,
        italic: bool = False,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("fontPreviewWidget")

        config = get_config()
        self._sample_text = sample_text or config.default_sample_text
        self._font_family = font_family
        self._point_size = point_size
        self._weight = weight
        self._italic = italic
        self._is_loading = False

        self._init_ui()
        self._apply_font()

    def _init_ui(self) -> None:
        """Initialize widget layout and child label."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        self._label = QLabel(self._sample_text, self)
        self._label.setObjectName("fontPreviewLabel")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._label.setWordWrap(True)

        layout.addWidget(self._label)
        self.setLayout(layout)

    def _apply_font(self) -> None:
        """Update QFont properties on preview label."""
        qfont = QFont()
        if self._font_family:
            qfont.setFamily(self._font_family)
            self._label.setStyleSheet(
                f'#fontPreviewLabel {{ font-family: "{self._font_family}", sans-serif; }}'
            )
        else:
            qfont.setStyleHint(QFont.StyleHint.SansSerif)
            self._label.setStyleSheet("")

        qfont.setPointSizeF(self._point_size)
        qfont.setWeight(QFont.Weight(self._weight))
        qfont.setItalic(self._italic)

        self._label.setFont(qfont)

    @property
    def sample_text(self) -> str:
        """Current sample text string."""
        return self._sample_text

    def set_sample_text(self, text: str) -> None:
        """Update preview text."""
        self._sample_text = text
        self._label.setText(text)

    @property
    def font_family(self) -> str | None:
        """Currently applied font family."""
        return self._font_family

    def set_font_family(self, family_name: str | None) -> None:
        """Update font family name."""
        self._font_family = family_name
        self._apply_font()

    @property
    def point_size(self) -> float:
        """Current font point size."""
        return self._point_size

    def set_font_size(self, size: float) -> None:
        """Update font size in points."""
        self._point_size = max(6.0, min(128.0, size))
        self._apply_font()

    @property
    def weight(self) -> int:
        """Current font weight."""
        return self._weight

    def set_font_weight(self, weight: int) -> None:
        """Update font weight (100 to 900 or QFont.Weight enum)."""
        self._weight = weight
        self._apply_font()

    @property
    def italic(self) -> bool:
        """Whether font is styled italic."""
        return self._italic

    def set_italic(self, italic: bool) -> None:
        """Update font italic property."""
        self._italic = italic
        self._apply_font()

    def set_loading(self, loading: bool) -> None:
        """Toggle loading opacity / state."""
        self._is_loading = loading
        if loading:
            self._label.setStyleSheet("color: #64748b;")
        else:
            self._label.setStyleSheet("")
