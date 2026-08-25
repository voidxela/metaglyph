"""Dynamic application font loader interfacing with PySide6 QFontDatabase."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)


def extract_font_family_name(file_path: Path) -> str:
    """Extract font family name from font binary metadata without requiring Qt."""
    try:
        logger.info("Reading font metadata from %s", file_path)
        with TTFont(file_path, fontNumber=0, lazy=True) as font:
            name_table = font.get("name")
            if name_table:
                # ID 1 is Font Family name, ID 16 is Typographic Family name
                typographic_family = name_table.getDebugName(16)
                if typographic_family:
                    return typographic_family
                font_family = name_table.getDebugName(1)
                if font_family:
                    return font_family
    except Exception as exc:
        logger.warning("Failed to extract font family from %s: %s", file_path, exc)

    return file_path.stem.replace("_", " ").title()


class FontLoader:
    """Dynamically loads and unloads application fonts into Qt's QFontDatabase."""

    def __init__(self, max_loaded_fonts: int = 300) -> None:
        self.max_loaded_fonts = max_loaded_fonts
        # OrderedDict tracking path -> (qt_font_id, family_name) for LRU management
        self._loaded: OrderedDict[Path, tuple[int, str]] = OrderedDict()

    def _is_gui_running(self) -> bool:
        """Check if PySide6 QGuiApplication is initialized."""
        try:
            from PySide6.QtGui import QGuiApplication

            return QGuiApplication.instance() is not None
        except ImportError:
            return False

    def load_font(self, file_path: Path) -> tuple[int, str]:
        """Load a font file dynamically into Qt's QFontDatabase.

        Args:
            file_path: Path to the TTF or OTF font file.

        Returns:
            Tuple of (qt_font_id, family_name).
        """
        file_path = file_path.resolve()

        if file_path in self._loaded:
            # Move to end to mark as recently used
            self._loaded.move_to_end(file_path)
            return self._loaded[file_path]

        qt_font_id = -1
        family_name = ""

        logger.info("Loading application font file into Qt: %s", file_path)
        if self._is_gui_running():
            from PySide6.QtGui import QFontDatabase

            qt_font_id = QFontDatabase.addApplicationFont(str(file_path))
            if qt_font_id != -1:
                families = QFontDatabase.applicationFontFamilies(qt_font_id)
                if families:
                    family_name = families[0]
            else:
                logger.warning("QFontDatabase failed to load font at %s", file_path)

        if not family_name:
            family_name = extract_font_family_name(file_path)

        self._loaded[file_path] = (qt_font_id, family_name)
        self._enforce_capacity()
        return qt_font_id, family_name


    def unload_font(self, file_path: Path) -> bool:
        """Unload a specific font file from QFontDatabase.

        Returns:
            True if font was loaded and removed, False otherwise.
        """
        file_path = file_path.resolve()
        if file_path not in self._loaded:
            return False

        qt_font_id, _ = self._loaded.pop(file_path)
        if qt_font_id >= 0 and self._is_gui_running():
            from PySide6.QtGui import QFontDatabase

            QFontDatabase.removeApplicationFont(qt_font_id)
        return True

    def unload_all(self) -> int:
        """Unload all dynamically registered application fonts.

        Returns:
            Number of unloaded fonts.
        """
        count = len(self._loaded)
        if self._is_gui_running():
            from PySide6.QtGui import QFontDatabase

            for qt_font_id, _ in self._loaded.values():
                if qt_font_id >= 0:
                    QFontDatabase.removeApplicationFont(qt_font_id)

        self._loaded.clear()
        return count

    def get_loaded_count(self) -> int:
        """Number of currently loaded fonts."""
        return len(self._loaded)

    def is_loaded(self, file_path: Path) -> bool:
        """Check if a font file is currently loaded."""
        return file_path.resolve() in self._loaded

    def _enforce_capacity(self) -> None:
        """Evict oldest loaded fonts when exceeding capacity."""
        if self.max_loaded_fonts <= 0:
            return

        while len(self._loaded) > self.max_loaded_fonts:
            oldest_path, (oldest_id, _) = self._loaded.popitem(last=False)
            if oldest_id >= 0 and self._is_gui_running():
                from PySide6.QtGui import QFontDatabase

                QFontDatabase.removeApplicationFont(oldest_id)
