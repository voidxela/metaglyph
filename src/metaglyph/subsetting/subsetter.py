"""Font micro-subsetting engine using fonttools."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)


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


def subset_font_bytes(font_bytes: bytes, text: str) -> bytes:
    """Create a micro-subset TTF/OTF containing only glyphs in `text`.

    Args:
        font_bytes: Raw font binary (TTF or OTF).
        text: Sample characters to include in the subset.

    Returns:
        Bytes of the subsetted font binary.
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
        logger.warning("Failed to subset font bytes: %s. Returning original font.", exc)
        return font_bytes


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
    raw_bytes = source_path.read_bytes()
    subset_bytes = subset_font_bytes(raw_bytes, text)
    output_path.write_bytes(subset_bytes)
    return output_path
