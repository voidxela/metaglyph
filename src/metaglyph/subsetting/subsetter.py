"""Font micro-subsetting engine using fonttools."""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)

# Suppress harmless OpenType/TrueType table drop notices from fontTools.subset
logging.getLogger("fontTools.subset").setLevel(logging.ERROR)
logging.getLogger("fontTools").setLevel(logging.ERROR)


def create_subset_options() -> Options:
    """Create optimized subsetting options for micro-previews."""
    options = Options()
    # Retain essential hinting and layout tables for accurate rendering
    options.desubroutinize = True
    options.recalc_bounds = True
    options.recalc_timestamp = False
    options.canonical_order = True
    # Strip unnecessary OpenType tables for micro-preview files
    options.drop_tables += [
        "DSIG",
        "BASE",
        "JSTF",
        "MATH",
        "colr",
        "cpal",
        "svg",
        "sbix",
        "CBDT",
        "CBLC",
    ]
    return options


VALID_FONT_MAGICS = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1", b"ttcf")


def subset_font_bytes(font_bytes: bytes, text: str) -> bytes:
    """Create a micro-subset TTF/OTF containing only glyphs in `text`.

    Args:
        font_bytes: Raw font binary (TTF or OTF).
        text: Sample characters to include in the subset.

    Returns:
        Bytes of the subsetted font binary (or raw bytes if subsetting fails).
    """
    if not text:
        text = " "

    try:
        font = TTFont(io.BytesIO(font_bytes))
        options = create_subset_options()
        subsetter = Subsetter(options=options)
        subsetter.populate(text=text)
        subsetter.subset(font)

        out_buffer = io.BytesIO()
        font.save(out_buffer)
        return out_buffer.getvalue()
    except Exception as exc:
        logger.debug("Subset operation failed: %s. Using original font bytes.", exc)
        return font_bytes


async def async_subset_font_bytes(font_bytes: bytes, text: str) -> bytes:
    """Asynchronously offload font subsetting to a background thread."""
    return await asyncio.to_thread(subset_font_bytes, font_bytes, text)


def subset_font_file(source_path: Path, output_path: Path, text: str) -> Path:
    """Read a font file, subset it for `text`, and write to `output_path`.

    Args:
        source_path: Path to source TTF/OTF font file.
        output_path: Destination path for the micro-subset font.
        text: Sample characters to include in the subset.

    Returns:
        The output_path Path object.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Reading font file for subsetting: %s", source_path)
    raw_bytes = source_path.read_bytes()
    subset_bytes = subset_font_bytes(raw_bytes, text)
    logger.debug("Writing subset font file: %s", output_path)
    output_path.write_bytes(subset_bytes)
    return output_path




async def async_subset_font_file(source_path: Path, output_path: Path, text: str) -> Path:
    """Asynchronously subset a font file in a background worker thread."""
    return await asyncio.to_thread(subset_font_file, source_path, output_path, text)
