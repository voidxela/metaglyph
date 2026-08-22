"""Database access layer and data models."""

from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import (
    Font,
    FontFilter,
    FontVariant,
    InstalledFont,
    SystemFontCacheEntry,
)
from metaglyph.db.normalizer import (
    curate_category,
    extract_nerd_font_counterpart,
    is_nerd_font,
    normalize_family_name,
    should_replace_primary_provider,
)
from metaglyph.db.repository import FontRepository

__all__ = [
    "DatabaseManager",
    "Font",
    "FontVariant",
    "InstalledFont",
    "SystemFontCacheEntry",
    "FontFilter",
    "FontRepository",
    "normalize_family_name",
    "is_nerd_font",
    "extract_nerd_font_counterpart",
    "curate_category",
    "should_replace_primary_provider",
]
