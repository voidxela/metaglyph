"""Dynamic font micro-subsetting and caching subsystem."""

from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader, extract_font_family_name
from metaglyph.subsetting.subsetter import (
    create_subset_options,
    subset_font_bytes,
    subset_font_file,
)

__all__ = [
    "FontLoader",
    "SubsetCache",
    "SubsetFetcher",
    "create_subset_options",
    "extract_font_family_name",
    "subset_font_bytes",
    "subset_font_file",
]
