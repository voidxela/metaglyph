"""Tests verifying INFO-level filesystem logging and user-facing error handling."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from metaglyph.core.config import Config
from metaglyph.core.logging import setup_logging
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontVariant, InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import InstallResult, verify_font_magic_bytes
from metaglyph.installer.detector import FontDetector, extract_font_names
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.loader import FontLoader, extract_font_family_name
from metaglyph.subsetting.subsetter import subset_font_file
from metaglyph.ui.main_window import MainWindow
from metaglyph.ui.theme.qss_builder import ThemeManager
from metaglyph.ui.views.detail_pane import DetailPane
from metaglyph.ui.views.discover_view import DiscoverView
from metaglyph.ui.views.search_view import SearchView
from metaglyph.ui.views.system_view import SystemView


@pytest.mark.asyncio
async def test_filesystem_actions_logged_at_info(
    tmp_path: Path,
    test_ttf_bytes: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that every filesystem operation produces INFO logs in the metaglyph logger."""
    caplog.set_level(logging.INFO, logger="metaglyph")

    # 1. Config ensure directories
    data_dir = tmp_path / "data"
    cfg = Config(
        data_dir_override=data_dir,
        cache_dir_override=tmp_path / "cache",
        user_fonts_dir_override=tmp_path / "fonts",
    )
    cfg.ensure_directories()
    assert any("Ensuring directory exists" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)

    # 2. Database manager initialize & connection
    db_file = tmp_path / "db" / "test.db"
    db_mgr = DatabaseManager(db_file)
    await db_mgr.initialize()
    assert any("Initializing database schema" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)
    assert any("Opening database connection" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)
    await db_mgr.close()

    # 3. SubsetCache operations
    cache_dir = tmp_path / "subset_cache"
    cache = SubsetCache(cache_dir=cache_dir)
    assert any("Ensuring subset cache directory exists" in rec.message for rec in caplog.records)

    subset_path = cache.save_subset("test-font", "ABC", test_ttf_bytes, 400, "normal")
    assert subset_path.exists()
    assert any("Writing temporary subset file" in rec.message for rec in caplog.records)
    assert any("Moving temporary subset" in rec.message for rec in caplog.records)

    # Get cached subset (touch)
    got = cache.get_subset("test-font", "ABC", 400, "normal")
    assert got is not None
    assert any("Updating access timestamp on cached subset" in rec.message for rec in caplog.records)

    # Clear cache
    cache.clear()
    assert any("Clearing cached subset file" in rec.message for rec in caplog.records)

    # 4. Subsetter & Loader
    font_file = tmp_path / "TestFont.ttf"
    font_file.write_bytes(test_ttf_bytes)
    out_subset = tmp_path / "subsets" / "sub.ttf"
    subset_font_file(font_file, out_subset, "Hello")
    assert any("Reading font file for subsetting" in rec.message for rec in caplog.records)
    assert any("Writing subset font file" in rec.message for rec in caplog.records)

    extract_font_family_name(font_file)
    assert any("Reading font metadata from" in rec.message for rec in caplog.records)

    loader = FontLoader()
    loader.load_font(font_file)
    assert any("Loading application font file into Qt" in rec.message for rec in caplog.records)

    # 5. Magic bytes & Detector
    verify_font_magic_bytes(font_file)
    assert any("Reading font header magic bytes" in rec.message for rec in caplog.records)

    extract_font_names(font_file)
    assert any("Reading font names from file" in rec.message for rec in caplog.records)

    detector = FontDetector(config=cfg)
    detector.scan_directories([tmp_path])
    assert any("Scanning directory for fonts" in rec.message for rec in caplog.records)

    # 6. UserFontInstaller
    user_target = tmp_path / "user_installed_fonts"
    repo = FontRepository(db_mgr)
    await db_mgr.initialize()
    installer = UserFontInstaller(repository=repo, target_dir_override=user_target)
    sample_font = Font(
        id="test-font",
        family_name="Test Font",
        category="sans-serif",
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )
    res = await installer.install_font(sample_font, [font_file])
    assert res.success is True
    assert any("Copying font file from" in rec.message for rec in caplog.records)
    assert any("Moving temporary file from" in rec.message for rec in caplog.records)

    # Uninstall
    uninst_res = await installer.uninstall_font(sample_font.id, sample_font.family_name, res.installed_files)
    assert uninst_res.success is True
    assert any("Deleting user font file" in rec.message for rec in caplog.records)

    # 7. ThemeManager stylesheet reading
    theme_mgr = ThemeManager()
    theme_mgr.get_stylesheet("dark")
    assert any("Reading stylesheet from" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_system_view_single_uninstall_error_modal(repository: FontRepository) -> None:
    """Verify that single uninstallation failures display a critical error dialog to the user."""
    mock_uninstaller = MagicMock(spec=FontUninstaller)
    mock_uninstaller.uninstall_installed_font = AsyncMock(
        return_value=InstallResult(
            success=False,
            font_id="broken-font",
            family_name="Broken Font",
            scope="User",
            errors=["Permission denied on font file"],
            message="Uninstallation failed: Permission denied",
        )
    )

    view = SystemView(repository=repository, uninstaller=mock_uninstaller)
    item = InstalledFont(
        font_id="broken-font",
        family_name="Broken Font",
        provider="fontsource",
        install_scope="User",
        installed_at=1700000000,
        file_paths=["/root/fonts/Broken.ttf"],
    )

    with patch.object(QMessageBox, "critical") as mock_crit:
        await view.uninstall_single_async(item)
        assert mock_crit.called
        assert "Uninstallation Failed" in mock_crit.call_args[0][1]
        assert "Broken Font" in mock_crit.call_args[0][2]
        assert "Permission denied on font file" in mock_crit.call_args[0][2]


@pytest.mark.asyncio
async def test_system_view_batch_uninstall_error_modal(repository: FontRepository) -> None:
    """Verify that batch uninstallation failures display a warning dialog with failure details."""
    mock_uninstaller = MagicMock(spec=FontUninstaller)
    mock_uninstaller.batch_uninstall = AsyncMock(
        return_value=[
            InstallResult(
                success=False,
                font_id="fail-1",
                family_name="Fail Font 1",
                scope="System",
                errors=["Elevation was denied by user"],
                message="Elevation rejected",
            ),
            InstallResult(
                success=True,
                font_id="ok-1",
                family_name="OK Font",
                scope="User",
                uninstalled_files=[Path("/tmp/ok.ttf")],
            ),
        ]
    )

    view = SystemView(repository=repository, uninstaller=mock_uninstaller)
    items = [
        InstalledFont(
            font_id="fail-1",
            family_name="Fail Font 1",
            provider="system",
            install_scope="System",
            installed_at=1700000000,
            file_paths=["/usr/share/fonts/Fail.ttf"],
        ),
        InstalledFont(
            font_id="ok-1",
            family_name="OK Font",
            provider="fontsource",
            install_scope="User",
            installed_at=1700000000,
            file_paths=["/tmp/ok.ttf"],
        ),
    ]

    with patch.object(QMessageBox, "warning") as mock_warn:
        results = await view.batch_uninstall_async(items)
        assert len(results) == 2
        assert mock_warn.called
        assert "Batch Uninstallation Incomplete" in mock_warn.call_args[0][1]
        assert "Fail Font 1" in mock_warn.call_args[0][2]
        assert "Elevation was denied by user" in mock_warn.call_args[0][2]


@pytest.mark.asyncio
async def test_detail_pane_install_error_feedback(
    repository: FontRepository,
    sample_font_jetbrains: Font,
) -> None:
    """Verify that installation failure presents clear error feedback in DetailPane UI banner."""
    pane = DetailPane(repository=repository)
    pane.set_font(sample_font_jetbrains)

    # Mock user_installer to simulate failure
    pane.user_installer.install_font = AsyncMock(
        return_value=InstallResult(
            success=False,
            font_id=sample_font_jetbrains.id,
            family_name=sample_font_jetbrains.family_name,
            scope="User",
            errors=["Disk quota exceeded"],
            message="No space left on device",
        )
    )

    # Also mock provider manager download
    pane.provider_manager.download_font_family = AsyncMock(return_value=[Path("/tmp/dummy.ttf")])

    res = await pane.install_font_async(scope="User")
    assert res.success is False
    assert not pane._feedback_label.isHidden()
    assert "Disk quota exceeded" in pane._feedback_label.text() or "No space left" in pane._feedback_label.text()
    assert pane._feedback_label.objectName() == "installFeedbackError"


@pytest.mark.asyncio
async def test_search_view_query_error_state(repository: FontRepository) -> None:
    """Verify that database search failure updates UI empty state with error details."""
    view = SearchView(repository=repository)

    # Mock repository.search_fonts to raise exception
    view.repository.search_fonts = AsyncMock(side_effect=RuntimeError("Database lock conflict"))

    await view.execute_search_async()
    assert not view._empty_widget.isHidden()
    assert view._empty_title.text() == "Search Error"
    assert "Database lock conflict" in view._empty_desc.text()
    assert "Database lock conflict" in view._results_count_label.text()


@pytest.mark.asyncio
async def test_main_window_catalog_sync_error_dialog(repository: FontRepository) -> None:
    """Verify that catalog sync errors trigger a warning dialog and update status bar."""
    win = MainWindow(repository=repository)
    win.provider_manager.sync_all = AsyncMock(side_effect=ConnectionError("Failed to connect to Fontsource CDN"))

    with patch.object(QMessageBox, "warning") as mock_warn:
        await win._sync_catalog_async()
        assert "Sync error" in win._status_msg_label.text()
        assert mock_warn.called
        assert "Sync Failed" in mock_warn.call_args[0][1]
        assert "Failed to connect to Fontsource CDN" in mock_warn.call_args[0][2]
