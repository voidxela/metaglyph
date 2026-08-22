"""Theme manager and stylesheet compiler for Metaglyph PySide6 UI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# Core palette tokens
DARK_PALETTE: dict[str, str] = {
    "bg_root": "#121215",
    "bg_surface": "#18181c",
    "bg_elevated": "#1e1e24",
    "bg_card": "#18181d",
    "bg_card_hover": "#1d1d24",
    "border_subtle": "#23232a",
    "border_default": "#282832",
    "border_highlight": "#383848",
    "text_primary": "#f8fafc",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",
    "accent_primary": "#6366f1",
    "accent_hover": "#818cf8",
    "accent_active": "#4f46e5",
    "accent_emerald": "#10b981",
    "accent_amber": "#f59e0b",
    "accent_rose": "#f43f5e",
    "accent_sky": "#38bdf8",
    "accent_purple": "#c084fc",
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
            content = theme_file.read_text(encoding="utf-8")
            self._cache[theme_name] = content
            return content
        except Exception as exc:
            logger.error("Failed to read theme file %s: %s", theme_file, exc)
            return ""

    def apply_theme(self, target: QApplication | QWidget, theme_name: str = "dark") -> bool:
        """Apply theme stylesheet to a QApplication or QWidget."""
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
