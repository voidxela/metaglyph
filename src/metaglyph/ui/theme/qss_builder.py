"""Theme manager and stylesheet compiler for Metaglyph PySide6 UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# Core brand palette tokens specified by BRAND_GUIDELINES.md
DARK_PALETTE: dict[str, str] = {
    # Surfaces & Backgrounds (Deep Obsidian brand foundation)
    "bg_root": "#120323",
    "bg_surface": "#16072b",
    "bg_elevated": "#1b0a33",
    "bg_card": "#1a0933",
    "bg_card_hover": "#240d47",
    "bg_card_selected": "#2f105c",
    "bg_dark": "#0c0217",

    # Borders
    "border_subtle": "#2a104f",
    "border_default": "#371666",
    "border_highlight": "#5c24a3",
    "border_accent": "#771ebd",

    # Typography (Pure White & Chrome Sphere Platinum)
    "text_primary": "#ffffff",
    "text_secondary": "#c4b5d4",
    "text_muted": "#8a769f",
    "text_platinum": "#e9e9e9",

    # Brand Violet Accents (Vibrant Magenta Violet, Electric Violet, Midnight Indigo)
    "accent_primary": "#771ebd",
    "accent_hover": "#8d2cd6",
    "accent_active": "#49107f",
    "accent_midnight": "#290649",
    "accent_platinum": "#e9e9e9",

    # Functional State Accents
    "accent_emerald": "#10b981",
    "accent_amber": "#f59e0b",
    "accent_rose": "#f43f5e",
    "accent_sky": "#38bdf8",
    "accent_purple": "#e879f9",
}


class ThemeManager:
    """Manages application stylesheet loading, caching, and theme injection."""

    def __init__(self, theme_dir: Path | None = None) -> None:
        if theme_dir is None:
            self.theme_dir = Path(__file__).parent
        else:
            self.theme_dir = theme_dir
        self._cache: dict[str, str] = {}

    def get_stylesheet(self, theme_name: str = "dark") -> str:
        """Load and return the QSS stylesheet for a given theme name."""
        if theme_name in self._cache:
            return self._cache[theme_name]

        theme_file = self.theme_dir / f"{theme_name}.qss"
        if not theme_file.exists():
            logger.warning("Theme file %s does not exist; falling back to dark.qss", theme_file)
            theme_file = self.theme_dir / "dark.qss"

        if not theme_file.exists():
            logger.error("No valid QSS theme file found at %s", theme_file)
            return ""

        try:
            logger.debug("Reading stylesheet from %s", theme_file)
            content = theme_file.read_text(encoding="utf-8")
            self._cache[theme_name] = content
            return content

        except Exception as exc:
            logger.error("Failed to read theme file %s: %s", theme_file, exc)
            return ""

    def apply_theme(self, target: QApplication | QWidget, theme_name: str = "dark") -> bool:
        """Apply theme stylesheet and palette to a QApplication or QWidget."""
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication

        if isinstance(target, QApplication):
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor("#120323"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#120323"))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#16072b"))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1b0a33"))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#1b0a33"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
            palette.setColor(QPalette.ColorRole.Highlight, QColor("#771ebd"))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
            target.setPalette(palette)

        stylesheet = self.get_stylesheet(theme_name)
        if not stylesheet:
            return False

        try:
            target.setStyleSheet(stylesheet)
            return True
        except Exception as exc:
            logger.error("Failed to apply stylesheet to %s: %s", target, exc)
            return False

    def clear_cache(self) -> None:
        """Clear cached stylesheets."""
        self._cache.clear()


_global_theme_manager: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    """Retrieve the global ThemeManager singleton."""
    global _global_theme_manager
    if _global_theme_manager is None:
        _global_theme_manager = ThemeManager()
    return _global_theme_manager


def apply_theme(target: QApplication | QWidget, theme_name: str = "dark") -> bool:
    """Convenience helper to apply theme stylesheet."""
    return get_theme_manager().apply_theme(target, theme_name)
