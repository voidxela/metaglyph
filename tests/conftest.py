"""Pytest fixtures for Metaglyph test suite."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator
import pytest

from metaglyph.core.config import Config, set_config
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontVariant, InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide temporary test directory."""
    return tmp_path


@pytest.fixture
def test_config(temp_dir: Path) -> Config:
    """Provide isolated test Config."""
    cfg = Config(
        data_dir_override=temp_dir / "data",
        config_dir_override=temp_dir / "config",
        cache_dir_override=temp_dir / "cache",
    )
    cfg.ensure_directories()
    set_config(cfg)
    return cfg


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
        primary_provider="google",
        last_synced_at=1700000000,
        variants=[
            FontVariant(
                font_id="inter",
                provider="google",
                style="normal",
                weight=400,
                file_format="ttf",
                download_url="https://example.com/inter-400.ttf",
                subset_url="https://example.com/subsets/inter-400.ttf",
                filesize=95000,
            )
        ],
    )
