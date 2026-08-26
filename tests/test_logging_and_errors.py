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
async def test_user_actions_logged_at_info_and_subsets_at_debug(
    tmp_path: Path,
    test_ttf_bytes: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify direct user actions are logged at INFO while micro-subset operations log at DEBUG."""
    # 1. Micro-subset operations produce DEBUG logs (not INFO)
    caplog.set_level(logging.DEBUG, logger="metaglyph")
    cache_dir = tmp_path / "subset_cache"
    cache = SubsetCache(cache_dir=cache_dir)

    subset_path = cache.save_subset("test-font", "ABC", test_ttf_bytes, 400, "normal")
    assert subset_path.exists()
    assert any("Writing temporary subset file" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)
    assert not any("Writing temporary subset file" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)

    got = cache.get_subset("test-font", "ABC", 400, "normal")
    assert got is not None
    assert any("Updating access timestamp on cached subset" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)

    cache.clear()
    assert any("Clearing cached subset file" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)

    # Subsetter & FontLoader
    font_file = tmp_path / "TestFont.ttf"
    font_file.write_bytes(test_ttf_bytes)
    out_subset = tmp_path / "subsets" / "sub.ttf"
    subset_font_file(font_file, out_subset, "Hello")
    assert any("Reading font file for subsetting" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)
    assert any("Writing subset font file" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)

    extract_font_family_name(font_file)
    assert any("Reading font metadata from" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)

    loader = FontLoader()
    loader.load_font(font_file)
    assert any("Loading application font file into Qt" in rec.message and rec.levelno == logging.DEBUG for rec in caplog.records)

    # 2. Scanning summary & Direct User Install / Uninstall are logged at INFO
    caplog.set_level(logging.INFO, logger="metaglyph")
    caplog.clear()

    cfg = Config(
        data_dir_override=tmp_path / "data",
        cache_dir_override=tmp_path / "cache",
        user_fonts_dir_override=tmp_path / "fonts",
    )
    detector = FontDetector(config=cfg)
    detector.scan_directories([tmp_path])
    assert any("Scanning" in rec.message and "font directories" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)
    assert any("Discovered" in rec.message and "installed fonts" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)

    # User font installation
    db_file = tmp_path / "db" / "test.db"
    db_mgr = DatabaseManager(db_file)
    await db_mgr.initialize()
    repo = FontRepository(db_mgr)
    user_target = tmp_path / "user_installed_fonts"
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
    assert any("Copying font file from" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)
    assert any("Moving temporary file from" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)

    # User font uninstallation
    uninst_res = await installer.uninstall_font(sample_font.id, sample_font.family_name, res.installed_files)
    assert uninst_res.success is True
    assert any("Deleting user font file" in rec.message and rec.levelno == logging.INFO for rec in caplog.records)
    await db_mgr.close()



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


@pytest.mark.asyncio
async def test_installer_logs_warnings_on_invalid_files(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify that user installer and system installer log WARNING for missing or invalid font files."""
    caplog.set_level(logging.WARNING, logger="metaglyph")
    caplog.clear()

    db_file = tmp_path / "db" / "test_warn.db"
    db_mgr = DatabaseManager(db_file)
    await db_mgr.initialize()
    repo = FontRepository(db_mgr)

    user_target = tmp_path / "user_fonts"
    user_installer = UserFontInstaller(repository=repo, target_dir_override=user_target)

    # 1. Non-existent file
    missing_file = tmp_path / "Missing.ttf"
    # 2. Corrupt/non-font file
    corrupt_file = tmp_path / "Corrupt.ttf"
    corrupt_file.write_text("not a font binary")

    sample_font = Font(
        id="test-font",
        family_name="Test Font",
        category="sans-serif",
        primary_provider="fontsource",
        last_synced_at=1700000000,
    )

    res = await user_installer.install_font(sample_font, [missing_file, corrupt_file])
    assert res.success is False
    assert any("Source file does not exist" in rec.message and rec.levelno == logging.WARNING for rec in caplog.records)
    assert any("is not a valid TTF/OTF font" in rec.message and rec.levelno == logging.WARNING for rec in caplog.records)

    await db_mgr.close()
