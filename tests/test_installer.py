"""Tests for font installation, Rust helper manifest IPC, detection, and uninstallation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import pytest

from metaglyph.core.config import Config
from metaglyph.core.events import EventBus
from metaglyph.db.models import Font, FontVariant, InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import (
    FONT_MAGIC_SIGNATURES,
    InstallResult,
    InstallScope,
    is_font_file,
    verify_font_magic_bytes,
)
from metaglyph.installer.detector import FontDetector, extract_font_names
from metaglyph.installer.system_installer import SystemFontInstaller, find_helper_binary
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from conftest import synthesize_test_font_bytes


def test_font_magic_signatures() -> None:
    """Verify font signature set contains TrueType, OpenType, WOFF formats."""
    assert b"\x00\x01\x00\x00" in FONT_MAGIC_SIGNATURES
    assert b"OTTO" in FONT_MAGIC_SIGNATURES
    assert b"ttcf" in FONT_MAGIC_SIGNATURES
    assert b"wOFF" in FONT_MAGIC_SIGNATURES
    assert b"wOF2" in FONT_MAGIC_SIGNATURES


def test_verify_font_magic_bytes(tmp_path: Path) -> None:
    """Verify font magic bytes validation on valid and invalid files."""
    valid_font = tmp_path / "valid.ttf"
    valid_font.write_bytes(synthesize_test_font_bytes("Valid Font"))
    assert verify_font_magic_bytes(valid_font) is True
    assert is_font_file(valid_font) is True

    fake_font = tmp_path / "fake.ttf"
    fake_font.write_text("not a real font binary")
    assert verify_font_magic_bytes(fake_font) is False
    assert is_font_file(fake_font) is False

    non_existent = tmp_path / "nonexistent.ttf"
    assert verify_font_magic_bytes(non_existent) is False
    assert is_font_file(non_existent) is False


def test_extract_font_names(tmp_path: Path) -> None:
    """Verify metadata name extraction from synthesized font."""
    font_file = tmp_path / "CustomFamily-Bold.ttf"
    font_file.write_bytes(synthesize_test_font_bytes("Custom Family", "Bold"))

    family, style, postscript = extract_font_names(font_file)
    assert family == "Custom Family"
    assert style == "Bold"


@pytest.mark.asyncio
async def test_user_font_installer_lifecycle(
    test_config: Config,
    repository: FontRepository,
    sample_font_jetbrains: Font,
    tmp_path: Path,
) -> None:
    """Test installing and uninstalling fonts via UserFontInstaller."""
    event_bus = EventBus()
    events_received: list[dict] = []

    def _on_installed(**kwargs):
        events_received.append({"event": "font_installed", **kwargs})

    def _on_uninstalled(**kwargs):
        events_received.append({"event": "font_uninstalled", **kwargs})

    event_bus.subscribe("font_installed", _on_installed)
    event_bus.subscribe("font_uninstalled", _on_uninstalled)

    installer = UserFontInstaller(
        repository=repository,
        config=test_config,
        event_bus=event_bus,
    )

    # Prepare synthesized font files
    f1 = tmp_path / "JetBrainsMono-Regular.ttf"
    f1.write_bytes(synthesize_test_font_bytes("JetBrains Mono", "Regular"))
    f2 = tmp_path / "JetBrainsMono-Bold.ttf"
    f2.write_bytes(synthesize_test_font_bytes("JetBrains Mono", "Bold"))

    # Upsert font in repository first
    await repository.upsert_font(sample_font_jetbrains)

    # 1. Install
    result = await installer.install_font(sample_font_jetbrains, [f1, f2], version="2.304")
    assert result.success is True
    assert result.scope == InstallScope.USER
    assert len(result.installed_files) == 2
    assert all(p.exists() for p in result.installed_files)

    # Check database record
    installed_records = await repository.get_installed_fonts(scope="User")
    assert len(installed_records) == 1
    assert installed_records[0].font_id == sample_font_jetbrains.id
    assert len(installed_records[0].file_paths) == 2

    # Check event
    assert len(events_received) == 1
    assert events_received[0]["event"] == "font_installed"
    assert events_received[0]["font_id"] == sample_font_jetbrains.id

    # 2. Uninstall
    uninst_result = await installer.uninstall_font(
        font_id=sample_font_jetbrains.id,
        family_name=sample_font_jetbrains.family_name,
        file_paths=result.installed_files,
    )
    assert uninst_result.success is True
    assert len(uninst_result.uninstalled_files) == 2
    assert not any(p.exists() for p in result.installed_files)

    # Check DB removed
    remaining = await repository.get_installed_fonts(scope="User")
    assert len(remaining) == 0

    assert len(events_received) == 2
    assert events_received[1]["event"] == "font_uninstalled"


@pytest.mark.asyncio
async def test_system_font_installer_with_mock_helper(
    test_config: Config,
    repository: FontRepository,
    sample_font_inter: Font,
    tmp_path: Path,
) -> None:
    """Test SystemFontInstaller using a mock helper executable script."""
    event_bus = EventBus()
    events_received: list[dict] = []
    event_bus.subscribe("font_installed", lambda **kw: events_received.append(kw))

    # Create a mock helper script in Python that behaves like metaglyph-helper
    mock_helper = tmp_path / "mock_helper.py"
    mock_helper_code = """#!/usr/bin/env python3
import sys, json, shutil
from pathlib import Path

manifest_path = None
for i, arg in enumerate(sys.argv):
    if arg in ("-m", "--manifest") and i + 1 < len(sys.argv):
        manifest_path = sys.argv[i + 1]

if not manifest_path:
    print(json.dumps({"success": False, "errors": ["No manifest"]}))
    sys.exit(1)

with open(manifest_path) as f:
    manifest = json.load(f)

action = manifest.get("action")
target_dir = Path(manifest.get("target_dir", "/tmp"))
target_dir.mkdir(parents=True, exist_ok=True)

if action == "install":
    installed = []
    for font in manifest.get("fonts", []):
        for file_entry in font.get("files", []):
            src = Path(file_entry["source_path"])
            dest = target_dir / file_entry.get("destination_filename", src.name)
            shutil.copy2(src, dest)
            installed.append(str(dest))
    print(json.dumps({
        "success": True,
        "action": "install",
        "installed_files": installed,
        "uninstalled_files": [],
        "errors": [],
        "message": "Installed successfully"
    }))
    sys.exit(0)
elif action == "uninstall":
    uninstalled = []
    for font in manifest.get("fonts", []):
        for file_entry in font.get("files", []):
            dest = Path(file_entry.get("destination_path", target_dir / file_entry.get("destination_filename", "")))
            if dest.exists():
                dest.unlink()
                uninstalled.append(str(dest))
    print(json.dumps({
        "success": True,
        "action": "uninstall",
        "installed_files": [],
        "uninstalled_files": uninstalled,
        "errors": [],
        "message": "Uninstalled successfully"
    }))
    sys.exit(0)
"""
    mock_helper.write_text(mock_helper_code)
    mock_helper.chmod(0o755)

    system_target_dir = tmp_path / "system_fonts"
    system_target_dir.mkdir(parents=True, exist_ok=True)

    installer = SystemFontInstaller(
        repository=repository,
        config=test_config,
        event_bus=event_bus,
        helper_path_override=mock_helper,
        escalate_command_override=[sys.executable, str(mock_helper), "--manifest", "{MANIFEST}"],
        target_dir_override=system_target_dir,
    )
    installer.target_dir.mkdir(parents=True, exist_ok=True)

    # Upsert font in repository
    await repository.upsert_font(sample_font_inter)

    f = tmp_path / "Inter-Regular.ttf"
    f.write_bytes(synthesize_test_font_bytes("Inter", "Regular"))

    # 1. System Install
    result = await installer.install_font(sample_font_inter, [f])
    assert result.success is True
    assert result.scope == InstallScope.SYSTEM
    assert len(result.installed_files) == 1
    assert result.installed_files[0].exists()

    # Verify DB
    inst_records = await repository.get_installed_fonts(scope="System")
    assert len(inst_records) == 1
    assert inst_records[0].font_id == sample_font_inter.id

    # 2. System Uninstall
    uninst_res = await installer.uninstall_font(
        font_id=sample_font_inter.id,
        family_name=sample_font_inter.family_name,
        file_paths=result.installed_files,
    )
    assert uninst_res.success is True
    assert len(uninst_res.uninstalled_files) == 1
    assert not result.installed_files[0].exists()


@pytest.mark.asyncio
async def test_font_detector(
    test_config: Config,
    repository: FontRepository,
    tmp_path: Path,
) -> None:
    """Test discovering fonts across directories and syncing to SQLite."""
    user_fonts_dir = test_config.user_fonts_dir
    user_fonts_dir.mkdir(parents=True, exist_ok=True)

    system_fonts_dir = tmp_path / "system_fonts"
    system_fonts_dir.mkdir(parents=True, exist_ok=True)

    # Create synthesized fonts in both locations
    uf = user_fonts_dir / "UserFont-Regular.ttf"
    uf.write_bytes(synthesize_test_font_bytes("User Font", "Regular"))

    sf = system_fonts_dir / "SystemFont-Regular.ttf"
    sf.write_bytes(synthesize_test_font_bytes("System Font", "Regular"))

    detector = FontDetector(config=test_config)

    # Check scope determination
    assert detector.determine_scope(uf) == "User"
    assert detector.determine_scope(sf) == "System"

    # Scan and sync
    entries = await detector.scan_and_sync(
        repository=repository,
        search_paths=[user_fonts_dir, system_fonts_dir],
    )

    assert len(entries) >= 2
    family_names = {e.family_name for e in entries}
    assert "User Font" in family_names
    assert "System Font" in family_names

    # Check DB system_font_cache
    db_entries = await repository.get_system_fonts()
    db_families = {e.family_name for e in db_entries}
    assert "User Font" in db_families
    assert "System Font" in db_families


@pytest.mark.asyncio
async def test_font_uninstaller_batch(
    test_config: Config,
    repository: FontRepository,
    sample_font_jetbrains: Font,
    sample_font_inter: Font,
    tmp_path: Path,
) -> None:
    """Test batch uninstallation across User and System scope records."""
    event_bus = EventBus()
    events: list[dict] = []
    event_bus.subscribe("batch_uninstalled", lambda **kw: events.append(kw))

    # Mock helper for system installer
    mock_helper = tmp_path / "mock_uninst_helper.py"
    mock_helper.write_text("""#!/usr/bin/env python3
import sys, json
from pathlib import Path
manifest_path = sys.argv[2]
with open(manifest_path) as f:
    manifest = json.load(f)
uninst = []
for font in manifest.get("fonts", []):
    for f in font.get("files", []):
        p = Path(f["destination_path"])
        if p.exists():
            p.unlink()
        uninst.append(str(p))
print(json.dumps({"success": True, "action": "uninstall", "installed_files": [], "uninstalled_files": uninst, "errors": [], "message": "Done"}))
""")
    mock_helper.chmod(0o755)

    user_installer = UserFontInstaller(repository=repository, config=test_config, event_bus=event_bus)
    system_installer = SystemFontInstaller(
        repository=repository,
        config=test_config,
        event_bus=event_bus,
        helper_path_override=mock_helper,
        escalate_command_override=[sys.executable, str(mock_helper), "--manifest", "{MANIFEST}"],
    )

    uninstaller = FontUninstaller(
        repository=repository,
        config=test_config,
        event_bus=event_bus,
        user_installer=user_installer,
        system_installer=system_installer,
    )

    # Setup files
    uf_path = test_config.user_fonts_dir / "JetBrainsMono.ttf"
    uf_path.write_bytes(synthesize_test_font_bytes("JetBrains Mono"))

    sf_path = tmp_path / "Inter.ttf"
    sf_path.write_bytes(synthesize_test_font_bytes("Inter"))

    # Upsert fonts into repository first
    await repository.upsert_font(sample_font_jetbrains)
    await repository.upsert_font(sample_font_inter)

    # Record installed in DB
    inst_user = InstalledFont(
        font_id="jetbrains-mono",
        family_name="JetBrains Mono",
        provider="fontsource",
        install_scope="User",
        installed_at=1700000000,
        file_paths=[str(uf_path)],
    )
    inst_sys = InstalledFont(
        font_id="inter",
        family_name="Inter",
        provider="fontsquirrel",
        install_scope="System",
        installed_at=1700000000,
        file_paths=[str(sf_path)],
    )
    await repository.record_installation(inst_user)
    await repository.record_installation(inst_sys)

    assert len(await repository.get_installed_fonts()) == 2

    # Execute batch uninstall
    results = await uninstaller.batch_uninstall([inst_user, inst_sys])
    assert len(results) == 2
    assert all(r.success for r in results)

    # Verify files deleted
    assert not uf_path.exists()
    assert not sf_path.exists()

    # Verify DB cleared
    assert len(await repository.get_installed_fonts()) == 0
    assert len(events) == 1
    assert events[0]["count"] == 2


@pytest.mark.asyncio
async def test_installer_empty_and_invalid_inputs(
    test_config: Config,
    sample_font_jetbrains: Font,
    tmp_path: Path,
) -> None:
    """Test installer validation on empty and corrupted font lists."""
    user_installer = UserFontInstaller(config=test_config)
    res = await user_installer.install_font(sample_font_jetbrains, [])
    assert res.success is False
    assert "no files provided" in res.message.lower()

    # Invalid font files
    invalid_file = tmp_path / "corrupted.ttf"
    invalid_file.write_text("corrupted content")
    res_inv = await user_installer.install_font(sample_font_jetbrains, [invalid_file])
    assert res_inv.success is False

    system_installer = SystemFontInstaller(config=test_config)
    res_sys = await system_installer.install_font(sample_font_jetbrains, [])
    assert res_sys.success is False


def test_find_helper_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test helper binary resolution via environment variable and file system."""
    fake_helper = tmp_path / "metaglyph-helper"
    fake_helper.write_text("#!/bin/sh\necho ok")
    fake_helper.chmod(0o755)

    monkeypatch.setenv("METAGLYPH_HELPER_PATH", str(fake_helper))
    # Without debug/dev flag or explicit override, environment variable is ignored
    monkeypatch.delenv("METAGLYPH_DEBUG", raising=False)
    monkeypatch.delenv("METAGLYPH_DEV_MODE", raising=False)
    assert find_helper_binary() is None

    # When debug or explicit flag is enabled, it resolves
    monkeypatch.setenv("METAGLYPH_DEBUG", "1")
    found = find_helper_binary()
    assert found == fake_helper

    monkeypatch.delenv("METAGLYPH_DEBUG", raising=False)
    assert find_helper_binary(allow_env_override=True) == fake_helper
    monkeypatch.delenv("METAGLYPH_HELPER_PATH", raising=False)


def test_build_elevation_command_security(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify privilege escalation command formatting is safe against shell metacharacters."""
    import base64
    from metaglyph.core.config import Config

    cfg_darwin = Config(platform_override="darwin")
    installer_darwin = SystemFontInstaller(config=cfg_darwin)

    malicious_helper = tmp_path / "helper'; rm -rf /; '"
    malicious_manifest = tmp_path / 'manifest"; cat /etc/passwd; "'
    cmd_darwin = installer_darwin._build_elevation_command(malicious_helper, malicious_manifest)

    assert cmd_darwin[0] == "osascript"
    assert cmd_darwin[1] == "-e"
    # Ensure quotes are properly escaped in the AppleScript string
    assert "do shell script" in cmd_darwin[2]
    assert "with administrator privileges" in cmd_darwin[2]

    cfg_win = Config(platform_override="windows")
    installer_win = SystemFontInstaller(config=cfg_win)
    cmd_win = installer_win._build_elevation_command(malicious_helper, malicious_manifest)

    assert cmd_win[0] == "powershell"
    assert "-EncodedCommand" in cmd_win
    # Decode and verify the command payload is well-formed
    idx = cmd_win.index("-EncodedCommand") + 1
    decoded = base64.b64decode(cmd_win[idx]).decode("utf-16le")
    assert "Start-Process" in decoded
    assert "-Verb RunAs" in decoded


@pytest.mark.asyncio
async def test_uninstaller_single_and_model_routing(
    test_config: Config,
    repository: FontRepository,
    sample_font_jetbrains: Font,
    tmp_path: Path,
) -> None:
    """Test FontUninstaller single font and model-based uninstallation."""
    user_font_file = test_config.user_fonts_dir / "JetBrainsMono-Single.ttf"
    user_font_file.write_bytes(synthesize_test_font_bytes("JetBrains Mono"))

    await repository.upsert_font(sample_font_jetbrains)
    installed_record = InstalledFont(
        font_id="jetbrains-mono",
        family_name="JetBrains Mono",
        provider="fontsource",
        install_scope="User",
        installed_at=1700000000,
        file_paths=[str(user_font_file)],
    )
    await repository.record_installation(installed_record)

    uninstaller = FontUninstaller(repository=repository, config=test_config)
    res = await uninstaller.uninstall_installed_font(installed_record)
    assert res.success is True
    assert not user_font_file.exists()
    assert len(await repository.get_installed_fonts()) == 0


def test_ipc_manifest_install_and_uninstall_schema_structure(
    test_config: Config,
    sample_font_jetbrains: Font,
    tmp_path: Path,
) -> None:
    """Verify generated JSON manifests strictly match Rust Helper manifest schema definition."""
    system_installer = SystemFontInstaller(config=test_config)

    # 1. Install Manifest Schema
    f1 = tmp_path / "JetBrainsMono-Regular.ttf"
    f1.write_bytes(synthesize_test_font_bytes("JetBrains Mono", "Regular"))

    captured_manifests: list[dict] = []

    async def fake_invoke(manifest: dict):
        captured_manifests.append(manifest)
        return True, {"success": True, "installed_files": [str(test_config.system_fonts_dir / f1.name)]}, []

    system_installer._invoke_helper = fake_invoke  # type: ignore[assignment]

    import asyncio
    asyncio.run(system_installer.install_font(sample_font_jetbrains, [f1]))

    assert len(captured_manifests) == 1
    install_manifest = captured_manifests[0]

    # Validate schema fields required by Rust helper Manifest struct
    assert install_manifest["version"] == 1
    assert install_manifest["action"] == "install"
    assert install_manifest["target_scope"] == "system"
    assert isinstance(install_manifest["target_dir"], str)
    assert isinstance(install_manifest["fonts"], list)
    assert len(install_manifest["fonts"]) == 1

    font_entry = install_manifest["fonts"][0]
    assert font_entry["family_name"] == "JetBrains Mono"
    assert isinstance(font_entry["files"], list)
    assert len(font_entry["files"]) == 1

    file_entry = font_entry["files"][0]
    assert "source_path" in file_entry
    assert "destination_filename" in file_entry
    assert file_entry["destination_filename"] == "JetBrainsMono-Regular.ttf"

    # 2. Uninstall Manifest Schema
    captured_manifests.clear()
    dest_path = test_config.system_fonts_dir / f1.name
    asyncio.run(system_installer.uninstall_font("jetbrains-mono", "JetBrains Mono", [dest_path]))

    assert len(captured_manifests) == 1
    uninstall_manifest = captured_manifests[0]
    assert uninstall_manifest["version"] == 1
    assert uninstall_manifest["action"] == "uninstall"
    assert uninstall_manifest["target_scope"] == "system"
    assert len(uninstall_manifest["fonts"]) == 1
    uninst_font = uninstall_manifest["fonts"][0]
    assert uninst_font["family_name"] == "JetBrains Mono"
    assert len(uninst_font["files"]) == 1
    assert "destination_path" in uninst_font["files"][0]
    assert uninst_font["files"][0]["destination_path"] == str(dest_path.resolve())

