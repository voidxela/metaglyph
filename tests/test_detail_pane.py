"""Unit and integration tests for DetailPane inspector and installation controller."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from PySide6.QtCore import Qt

from metaglyph.db.models import Font, FontVariant, InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import InstallResult, InstallScope
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.providers.manager import ProviderManager
from metaglyph.ui.views.detail_pane import DetailPane


def test_detail_pane_set_font(sample_font_jetbrains: Font) -> None:
    pane = DetailPane()
    pane.set_font(sample_font_jetbrains)

    assert pane._title_label.text() == "JetBrains Mono"
    assert pane._provider_badge.text() == "Fontsource"
    assert pane._cat_badge.text() == "Code"
    assert pane._styles_badge.text() == "2 Styles"
    assert not pane.nerd_badge.isHidden()
    assert pane._preview.font_family == "JetBrains Mono"


def test_detail_pane_live_controls(sample_font_jetbrains: Font) -> None:
    pane = DetailPane()
    pane.set_font(sample_font_jetbrains)

    # Point size
    pane._size_slider.setValue(48)
    assert pane._size_val_label.text() == "48 pt"
    assert pane._preview.point_size == 48.0

    # Weight
    pane._weight_combo.setCurrentText("Bold (700)")
    assert pane._preview.weight == 700

    # Italic toggle
    pane._italic_check.setChecked(True)
    assert pane._preview.italic is True
    pane._italic_check.setChecked(False)
    assert pane._preview.italic is False

    # Preset selection
    pane._preset_combo.setCurrentText("Programming Ligatures")
    assert "const fn" in pane._sample_editor.toPlainText()
    assert "const fn" in pane._preview.sample_text


@pytest.mark.asyncio
async def test_detail_pane_installed_status_check(
    repository: FontRepository,
    sample_font_jetbrains: Font,
) -> None:
    await repository.upsert_fonts([sample_font_jetbrains])
    await repository.record_installation(
        InstalledFont(
            font_id="jetbrains-mono",
            family_name="JetBrains Mono",
            provider="fontsource",
            install_scope="User",
            installed_at=1700000000,
            file_paths=["/path/to/JetBrainsMono-Regular.ttf"],
        )
    )

    pane = DetailPane(repository=repository)
    pane.set_font(sample_font_jetbrains)
    await pane._check_installed_async()

    assert not pane._install_status_label.isHidden()
    assert "Installed (User Scope)" in pane._install_status_label.text()
    assert not pane._uninstall_btn.isHidden()
    assert pane._install_btn.text() == "Reinstall Font Family"
    assert pane._radio_user.isChecked()


@pytest.mark.asyncio
async def test_detail_pane_install_async_flow(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    tmp_path: Path,
    test_ttf_bytes: bytes,
) -> None:
    await repository.upsert_fonts([sample_font_jetbrains])

    user_fonts_dir = tmp_path / "user_fonts"
    user_fonts_dir.mkdir(parents=True, exist_ok=True)

    user_installer = UserFontInstaller(
        repository=repository,
        target_dir_override=user_fonts_dir,
    )

    prov_mgr = ProviderManager([])

    # Mock download_font_family
    async def mock_download(font: Font, target_dir: Path, **kwargs) -> list[Path]:
        f1 = target_dir / "JetBrainsMono-Regular.ttf"
        f1.write_bytes(test_ttf_bytes)
        return [f1]

    prov_mgr.download_font_family = AsyncMock(side_effect=mock_download)

    pane = DetailPane(
        repository=repository,
        provider_manager=prov_mgr,
        user_installer=user_installer,
    )
    pane.set_font(sample_font_jetbrains)

    completed_results: list[InstallResult] = []
    pane.install_completed.connect(completed_results.append)

    # Perform async install
    result = await pane.install_font_async(scope="User")

    assert result.success is True
    assert len(completed_results) == 1
    assert completed_results[0].success is True
    assert (user_fonts_dir / "JetBrainsMono-Regular.ttf").exists()

    # DB record verified
    installed_in_db = await repository.get_installed_font("jetbrains-mono")
    assert installed_in_db is not None
    assert installed_in_db.install_scope == "User"

    # UI state updated
    assert not pane._install_status_label.isHidden()
    assert "Installed (User Scope)" in pane._install_status_label.text()


@pytest.mark.asyncio
async def test_detail_pane_uninstall_async_flow(
    repository: FontRepository,
    sample_font_jetbrains: Font,
    tmp_path: Path,
    test_ttf_bytes: bytes,
) -> None:
    user_fonts_dir = tmp_path / "user_fonts"
    user_fonts_dir.mkdir(parents=True, exist_ok=True)
    installed_file = user_fonts_dir / "JetBrainsMono-Regular.ttf"
    installed_file.write_bytes(test_ttf_bytes)

    await repository.upsert_fonts([sample_font_jetbrains])
    await repository.record_installation(
        InstalledFont(
            font_id="jetbrains-mono",
            family_name="JetBrains Mono",
            provider="fontsource",
            install_scope="User",
            installed_at=1700000000,
            file_paths=[str(installed_file)],
        )
    )

    user_installer = UserFontInstaller(
        repository=repository,
        target_dir_override=user_fonts_dir,
    )
    uninstaller = FontUninstaller(
        repository=repository,
        user_installer=user_installer,
    )

    pane = DetailPane(
        repository=repository,
        user_installer=user_installer,
        uninstaller=uninstaller,
    )
    pane.set_font(sample_font_jetbrains)
    await pane._check_installed_async()

    completed_uninstalls: list[InstallResult] = []
    pane.uninstall_completed.connect(completed_uninstalls.append)

    # Perform uninstall
    result = await pane.uninstall_font_async(scope="User")

    assert result.success is True
    assert len(completed_uninstalls) == 1
    assert not installed_file.exists()

    # Verify DB removed
    assert await repository.get_installed_font("jetbrains-mono") is None


@pytest.mark.asyncio
async def test_detail_pane_install_error_handling(
    repository: FontRepository,
    sample_font_jetbrains: Font,
) -> None:
    prov_mgr = ProviderManager([])
    prov_mgr.download_font_family = AsyncMock(side_effect=RuntimeError("Network error"))

    pane = DetailPane(
        repository=repository,
        provider_manager=prov_mgr,
    )
    pane.set_font(sample_font_jetbrains)

    result = await pane.install_font_async(scope="User")
    assert result.success is False
    assert not pane._feedback_label.isHidden()
    assert "Installation error" in pane._feedback_label.text()
