"""Pytest fixtures for Metaglyph test suite."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import AsyncGenerator, Generator
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PySide6.QtWidgets import QApplication

from metaglyph.core.config import Config, get_config, set_config
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontVariant, InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository


@pytest.fixture(scope="session", autouse=True)
def qapp_session() -> QApplication:
    """Ensure QApplication is created in offscreen mode for all GUI tests."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def synthesize_test_font_bytes(
    family_name: str = "Test Font",
    style_name: str = "Regular",
    glyphs_chars: list[str] | None = None,
) -> bytes:
    """Synthesize a minimal, valid TrueType font binary for testing."""
    if glyphs_chars is None:
        glyphs_chars = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [" "]

    fb = FontBuilder(1000, isTTF=True)
    glyph_names = [".notdef"] + [
        "space" if c == " " else c for c in glyphs_chars if c != " "
    ]
    if "space" not in glyph_names:
        glyph_names.append("space")

    fb.setupGlyphOrder(glyph_names)

    cmap = {ord(c): ("space" if c == " " else c) for c in glyphs_chars}
    fb.setupCharacterMap(cmap)

    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.lineTo((100, 800))
    pen.lineTo((800, 800))
    pen.lineTo((800, 100))
    pen.closePath()
    box_glyph = pen.glyph()

    blank_pen = TTGlyphPen(None)
    blank_glyph = blank_pen.glyph()

    glyphs_dict = {name: box_glyph for name in glyph_names}
    glyphs_dict[".notdef"] = blank_glyph
    glyphs_dict["space"] = blank_glyph

    fb.setupGlyf(glyphs_dict)
    h_metrics = {name: (1000, 100) for name in glyph_names}
    h_metrics["space"] = (500, 0)
    fb.setupHorizontalMetrics(h_metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family_name, "styleName": style_name})
    fb.setupOS2()
    fb.setupPost()

    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide temporary test directory."""
    return tmp_path


@pytest.fixture
def test_config(temp_dir: Path) -> Generator[Config, None, None]:
    """Provide isolated test Config and restore previous config on teardown."""
    original_cfg = get_config()
    cfg = Config(
        data_dir_override=temp_dir / "data",
        config_dir_override=temp_dir / "config",
        cache_dir_override=temp_dir / "cache",
    )
    cfg.ensure_directories()
    set_config(cfg)
    try:
        yield cfg
    finally:
        set_config(original_cfg)


@pytest.fixture
def test_ttf_bytes() -> bytes:
    """Provide minimal synthesized TrueType font bytes."""
    return synthesize_test_font_bytes("Test Font", "Regular")


@pytest.fixture
def test_ttf_file(temp_dir: Path) -> Path:
    """Provide file path to a synthesized TrueType font."""
    font_path = temp_dir / "TestFont-Regular.ttf"
    font_path.write_bytes(synthesize_test_font_bytes("Test Font", "Regular"))
    return font_path


@pytest.fixture
async def db_manager(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    """Provide an initialized DatabaseManager with an isolated test DB."""
    db_file = tmp_path / "test_mem.db"
    manager = DatabaseManager(db_path=db_file)
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
async def file_db_manager(test_config: Config) -> AsyncGenerator[DatabaseManager, None]:
    """Provide an initialized file-based DatabaseManager."""
    db_file = test_config.data_dir / "test_metaglyph.db"
    manager = DatabaseManager(db_path=db_file)
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def repository(db_manager: DatabaseManager) -> FontRepository:
    """Provide FontRepository instance."""
    return FontRepository(db_manager)


@pytest.fixture
def sample_font_jetbrains() -> Font:
    """Sample JetBrains Mono font."""
    return Font(
        id="jetbrains-mono",
        family_name="JetBrains Mono",
        category="monospace",
        curated_category="Code",
        is_variable=True,
        has_nerd_font=True,
        nerd_font_slug="jetbrainsmono-nerd-font",
        primary_provider="fontsource",
        last_synced_at=1700000000,
        variants=[
            FontVariant(
                font_id="jetbrains-mono",
                provider="fontsource",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://example.com/jetbrains-mono-400.ttf",
                subset_url="https://example.com/subsets/jetbrains-mono-400.ttf",
                filesize=120000,
            ),
            FontVariant(
                font_id="jetbrains-mono",
                provider="fontsource",
                style="normal",
                weight=700,
                file_format="ttf",
                download_url="https://example.com/jetbrains-mono-700.ttf",
                subset_url="https://example.com/subsets/jetbrains-mono-700.ttf",
                filesize=125000,
            ),
        ],
    )


@pytest.fixture
def sample_font_inter() -> Font:
    """Sample Inter font."""
    return Font(
        id="inter",
        family_name="Inter",
        category="sans-serif",
        curated_category="Interface",
        is_variable=True,
        has_nerd_font=False,
        primary_provider="fontsquirrel",
        last_synced_at=1700000000,
        variants=[
            FontVariant(
                font_id="inter",
                provider="fontsquirrel",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://example.com/inter-400.ttf",
                subset_url="https://example.com/subsets/inter-400.ttf",
                filesize=95000,
            )
        ],
    )
