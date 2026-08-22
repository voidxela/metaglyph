"""OS-level system font scanner, metadata inspector, and registry synchronizer."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from fontTools.ttLib import TTFont

from metaglyph.core.config import Config, get_config
from metaglyph.core.events import EventBus, get_event_bus
from metaglyph.core.logging import get_logger
from metaglyph.db.models import SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import is_font_file

logger = get_logger("installer.detector")


def extract_font_names(file_path: Path) -> tuple[str, str | None]:
    """Extract family name and postscript name from a font file using fontTools."""
    try:
        with TTFont(str(file_path), fontNumber=0, lazy=True) as tt:
            name_table = tt.get("name")
            if not name_table:
                return file_path.stem, None

            family_name: str | None = None
            postscript_name: str | None = None

            # Prefer Typographic Family (Name ID 16) over Font Family (Name ID 1)
            for record in name_table.names:
                try:
                    text = record.toUnicode().strip()
                except Exception:
                    continue

                if not text:
                    continue

                if record.nameID == 16:
                    family_name = text
                elif record.nameID == 1 and family_name is None:
                    family_name = text
                elif record.nameID == 6 and postscript_name is None:
                    postscript_name = text

            return family_name or file_path.stem, postscript_name
    except Exception:
        return file_path.stem, None


class FontDetector:
    """Discovers installed fonts across OS search directories and synchronizes with SQLite."""

    def __init__(
        self,
        config: Config | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()

    def determine_scope(self, file_path: Path) -> str:
        """Determine whether a font file path belongs to User or System scope."""
        user_fonts_dir = self._config.user_fonts_dir.resolve()
        home = Path.home().resolve()
        resolved = file_path.resolve()

        if resolved.is_relative_to(user_fonts_dir) or resolved.is_relative_to(home):
            return "User"

        return "System"

    def scan_directories(self, search_paths: list[Path] | None = None) -> list[SystemFontCacheEntry]:
        """Synchronously scan directory paths for font files and extract metadata."""
        paths = search_paths or self._config.all_system_font_search_paths

        # Also ensure user and system configured dirs are scanned
        all_dirs: list[Path] = list(paths)
        if self._config.user_fonts_dir not in all_dirs and self._config.user_fonts_dir.exists():
            all_dirs.append(self._config.user_fonts_dir)
        if self._config.system_fonts_dir not in all_dirs and self._config.system_fonts_dir.exists():
            all_dirs.append(self._config.system_fonts_dir)

        now = int(time.time())
        discovered: dict[str, SystemFontCacheEntry] = {}

        valid_extensions = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}

        for base_dir in all_dirs:
            if not base_dir.exists():
                continue

            try:
                walk_iter = os.walk(base_dir)
            except Exception as e:
                logger.warning("Error accessing directory %s: %s", base_dir, e)
                continue

            for root, _, files in walk_iter:
                root_path = Path(root)
                for file_name in files:
                    try:
                        p = root_path / file_name
                        if p.suffix.lower() in valid_extensions:
                            abs_path_str = str(p.resolve())
                            if abs_path_str in discovered:
                                continue

                            if not is_font_file(p):
                                continue

                            family_name, postscript = extract_font_names(p)
                            scope = self.determine_scope(p)
                            is_metaglyph = "metaglyph" in str(p).lower()

                            discovered[abs_path_str] = SystemFontCacheEntry(
                                family_name=family_name,
                                postscript_name=postscript,
                                file_path=abs_path_str,
                                scope=scope,
                                is_metaglyph_managed=is_metaglyph,
                                last_scanned_at=now,
                            )
                    except Exception as e:
                        logger.warning("Error processing font file %s/%s: %s", root, file_name, e)

        return list(discovered.values())

    async def scan_system_fonts(
        self, search_paths: list[Path] | None = None
    ) -> list[SystemFontCacheEntry]:
        """Asynchronously scan system fonts without blocking the Qt UI thread."""
        return await asyncio.to_thread(self.scan_directories, search_paths)

    async def scan_and_sync(
        self, repository: FontRepository, search_paths: list[Path] | None = None
    ) -> list[SystemFontCacheEntry]:
        """Scan OS font directories, sync results into SQLite database, and notify via EventBus."""
        entries = await self.scan_system_fonts(search_paths)
        await repository.sync_system_font_cache(entries)

        self._event_bus.emit(
            "system_fonts_scanned",
            count=len(entries),
            entries=entries,
        )

        return entries
