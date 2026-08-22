"""System-level font installer leveraging the standalone Rust helper binary via IPC."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from metaglyph.core.config import Config, get_config
from metaglyph.core.events import EventBus, get_event_bus
from metaglyph.core.logging import get_logger
from metaglyph.db.models import Font, InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import (
    BaseInstaller,
    InstallResult,
    InstallScope,
    verify_font_magic_bytes,
)

logger = get_logger("installer.system")


def find_helper_binary(allow_env_override: bool = False) -> Path | None:
    """Locate the compiled metaglyph-helper Rust binary on the filesystem."""
    # 1. Environment variable override (gated to explicit debug/dev mode)
    if allow_env_override or os.environ.get("METAGLYPH_DEBUG") == "1" or os.environ.get("METAGLYPH_DEV_MODE") == "1":
        if env_path := os.environ.get("METAGLYPH_HELPER_PATH"):
            p = Path(env_path)
            if p.is_file() and os.access(p, os.X_OK):
                logger.info("Using development override for helper binary: %s", p)
                return p

    binary_name = "metaglyph-helper.exe" if sys.platform in ("win32", "cygwin") else "metaglyph-helper"

    # 2. Project repository target directories
    repo_root = Path(__file__).resolve().parents[3]
    candidate_paths = [
        repo_root / "helper" / "target" / "release" / binary_name,
        repo_root / "helper" / "target" / "debug" / binary_name,
        repo_root / "bin" / binary_name,
        Path(sys.prefix) / "bin" / binary_name,
        Path.home() / ".local" / "bin" / binary_name,
    ]

    for candidate in candidate_paths:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    # 3. System PATH lookup
    if found := shutil.which(binary_name):
        return Path(found)

    return None


class SystemFontInstaller(BaseInstaller):
    """Installs font files into system directories using the elevated Rust helper binary."""

    def __init__(
        self,
        repository: FontRepository | None = None,
        config: Config | None = None,
        event_bus: EventBus | None = None,
        helper_path_override: Path | None = None,
        escalate_command_override: list[str] | None = None,
        target_dir_override: Path | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()
        self._helper_path_override = helper_path_override
        self._escalate_command_override = escalate_command_override
        self._target_dir_override = target_dir_override

    @property
    def helper_path(self) -> Path | None:
        """Resolve path to the metaglyph-helper binary."""
        if self._helper_path_override:
            return self._helper_path_override
        return find_helper_binary()

    @property
    def target_dir(self) -> Path:
        """System font installation directory."""
        if self._target_dir_override is not None:
            return self._target_dir_override
        return self._config.system_fonts_dir

    def _build_elevation_command(self, helper_path: Path, manifest_path: Path) -> list[str]:
        """Build OS-specific privilege escalation command to invoke metaglyph-helper."""
        if self._escalate_command_override:
            cmd = []
            for token in self._escalate_command_override:
                cmd.append(
                    token.replace("{HELPER}", str(helper_path)).replace("{MANIFEST}", str(manifest_path))
                )
            return cmd

        platform_name = self._config.platform_name

        if platform_name == "linux":
            # If already running as root (e.g. in container/testing), invoke directly
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                return [str(helper_path), "--manifest", str(manifest_path)]
            # Standard Linux GUI escalation
            return ["pkexec", str(helper_path), "--manifest", str(manifest_path)]

        elif platform_name == "darwin":
            # macOS AppleScript escalation with shlex quoting against /bin/sh injection
            inner_cmd = f"{shlex.quote(str(helper_path))} --manifest {shlex.quote(str(manifest_path))}"
            as_escaped = inner_cmd.replace("\\", "\\\\").replace('"', '\\"')
            script = f'do shell script "{as_escaped}" with administrator privileges'
            return ["osascript", "-e", script]

        elif platform_name == "windows":
            # Windows PowerShell RunAs elevation encoded in UTF-16LE Base64 to prevent injection
            ps_helper = str(helper_path).replace("'", "''")
            ps_manifest = str(manifest_path).replace("'", "''")
            ps_script = f"Start-Process -FilePath '{ps_helper}' -ArgumentList '--manifest \"\"{ps_manifest}\"\"' -Verb RunAs -Wait"
            encoded_cmd = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
            return [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded_cmd,
            ]

        return [str(helper_path), "--manifest", str(manifest_path)]

    async def _invoke_helper(self, manifest_data: dict) -> tuple[bool, dict, list[str]]:
        """Write temporary manifest, invoke elevated Rust helper asynchronously, and parse output."""
        helper = self.helper_path
        if helper is None:
            err = "metaglyph-helper binary could not be found. Please build the helper via Cargo."
            logger.error(err)
            return False, {}, [err]

        # Create temporary manifest file
        temp_dir = tempfile.mkdtemp(prefix="metaglyph_manifest_")
        manifest_file = Path(temp_dir) / "install_manifest.json"

        try:
            with manifest_file.open("w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

            cmd = self._build_elevation_command(helper, manifest_file)
            logger.info("Executing helper elevation command: %s", cmd)

            def _run_subprocess() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

            proc = await asyncio.to_thread(_run_subprocess)

            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()

            if proc.returncode != 0:
                err_msg = f"Helper failed with returncode {proc.returncode}."
                if stderr:
                    err_msg += f" Stderr: {stderr}"
                if stdout:
                    err_msg += f" Stdout: {stdout}"
                logger.error(err_msg)
                return False, {}, [err_msg]

            # Parse JSON status report from stdout
            try:
                result_json = json.loads(stdout)
                success = result_json.get("success", False)
                errors = result_json.get("errors", [])
                return success, result_json, errors
            except json.JSONDecodeError:
                # If stdout is empty or non-JSON (e.g. from some elevation wrappers)
                if proc.returncode == 0:
                    return True, {"success": True, "installed_files": [], "uninstalled_files": []}, []
                return False, {}, [f"Helper produced invalid output: {stdout}"]

        except Exception as exc:
            logger.error("Exception invoking helper: %s", exc)
            return False, {}, [str(exc)]
        finally:
            # Clean up temp manifest
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def install_font(
        self,
        font: Font,
        font_files: list[Path],
        version: str | None = None,
    ) -> InstallResult:
        """Generate manifest, invoke Rust helper with privilege escalation, and update repository."""
        if not font_files:
            return InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=InstallScope.SYSTEM,
                errors=["No font files provided for installation"],
                message="Installation failed: no files provided",
            )

        # Validate source files
        valid_files: list[dict[str, str]] = []
        errors: list[str] = []

        for src in font_files:
            if not src.exists():
                errors.append(f"Source file does not exist: {src}")
                continue
            if not verify_font_magic_bytes(src):
                errors.append(f"File {src.name} is not a valid TTF/OTF font")
                continue

            valid_files.append({
                "source_path": str(src.resolve()),
                "destination_filename": src.name,
            })

        if not valid_files:
            return InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=InstallScope.SYSTEM,
                errors=errors,
                message="Installation failed: no valid font files",
            )

        manifest = {
            "version": 1,
            "action": "install",
            "target_scope": "system",
            "target_dir": str(self.target_dir),
            "fonts": [
                {
                    "family_name": font.family_name,
                    "files": valid_files,
                }
            ],
        }

        success, result_data, helper_errors = await self._invoke_helper(manifest)
        errors.extend(helper_errors)

        if not success:
            return InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=InstallScope.SYSTEM,
                errors=errors,
                message=f"System installation failed for {font.family_name}",
            )

        installed_files = [Path(p) for p in result_data.get("installed_files", [])]
        if not installed_files:
            # Fallback to anticipated destinations if helper did not report file list
            installed_files = [self.target_dir / item["destination_filename"] for item in valid_files]

        # Record in database if repository is available
        if self._repository is not None:
            installed_record = InstalledFont(
                font_id=font.id,
                family_name=font.family_name,
                provider=font.primary_provider,
                version=version,
                install_scope=InstallScope.SYSTEM,
                installed_at=int(time.time()),
                file_paths=[str(p.resolve()) for p in installed_files],
            )
            try:
                await self._repository.record_installation(installed_record)
            except Exception as e:
                logger.error("Failed to record system font installation in DB: %s", e)

        # Emit event
        self._event_bus.emit(
            "font_installed",
            font_id=font.id,
            family_name=font.family_name,
            scope=InstallScope.SYSTEM,
            files=installed_files,
        )

        return InstallResult(
            success=True,
            font_id=font.id,
            family_name=font.family_name,
            scope=InstallScope.SYSTEM,
            installed_files=installed_files,
            errors=errors,
            message=f"Successfully installed {len(installed_files)} system font file(s)",
        )

    async def uninstall_font(
        self,
        font_id: str,
        family_name: str,
        file_paths: list[Path],
    ) -> InstallResult:
        """Generate uninstall manifest, invoke Rust helper with privilege escalation, and update DB."""
        files_entries = [{"destination_path": str(p.resolve())} for p in file_paths]

        manifest = {
            "version": 1,
            "action": "uninstall",
            "target_scope": "system",
            "target_dir": str(self.target_dir),
            "fonts": [
                {
                    "family_name": family_name,
                    "files": files_entries,
                }
            ],
        }

        success, result_data, helper_errors = await self._invoke_helper(manifest)

        if not success:
            return InstallResult(
                success=False,
                font_id=font_id,
                family_name=family_name,
                scope=InstallScope.SYSTEM,
                errors=helper_errors,
                message=f"System uninstallation failed for {family_name}",
            )

        uninstalled_files = [Path(p) for p in result_data.get("uninstalled_files", [])]
        if not uninstalled_files:
            uninstalled_files = file_paths

        # Remove from database
        if self._repository is not None:
            try:
                await self._repository.remove_installation(font_id, scope=InstallScope.SYSTEM)
            except Exception as e:
                logger.error("Failed to remove system font installation record from DB: %s", e)

        # Emit event
        self._event_bus.emit(
            "font_uninstalled",
            font_id=font_id,
            family_name=family_name,
            scope=InstallScope.SYSTEM,
            files=uninstalled_files,
        )

        return InstallResult(
            success=True,
            font_id=font_id,
            family_name=family_name,
            scope=InstallScope.SYSTEM,
            uninstalled_files=uninstalled_files,
            errors=helper_errors,
            message=f"Successfully uninstalled {len(uninstalled_files)} system font file(s)",
        )

    async def uninstall_multiple_fonts(
        self,
        fonts_to_uninstall: list[tuple[str, str, list[Path]]],
    ) -> list[InstallResult]:
        """Uninstall multiple font families in a single elevated helper invocation."""
        if not fonts_to_uninstall:
            return []

        fonts_manifest: list[dict] = []
        for font_id, family_name, file_paths in fonts_to_uninstall:
            fonts_manifest.append({
                "family_name": family_name,
                "files": [{"destination_path": str(p.resolve())} for p in file_paths],
            })

        manifest = {
            "version": 1,
            "action": "uninstall",
            "target_scope": "system",
            "target_dir": str(self.target_dir),
            "fonts": fonts_manifest,
        }

        success, result_data, helper_errors = await self._invoke_helper(manifest)

        results: list[InstallResult] = []
        all_uninstalled = {Path(p).resolve() for p in result_data.get("uninstalled_files", [])}

        for font_id, family_name, file_paths in fonts_to_uninstall:
            removed_for_font = [p for p in file_paths if p.resolve() in all_uninstalled or not p.exists()]
            if not removed_for_font and success:
                removed_for_font = file_paths

            if self._repository is not None and success:
                try:
                    await self._repository.remove_installation(font_id, scope=InstallScope.SYSTEM)
                except Exception as e:
                    logger.error("Failed to remove record for %s from DB: %s", font_id, e)

            self._event_bus.emit(
                "font_uninstalled",
                font_id=font_id,
                family_name=family_name,
                scope=InstallScope.SYSTEM,
                files=removed_for_font,
            )

            results.append(
                InstallResult(
                    success=success,
                    font_id=font_id,
                    family_name=family_name,
                    scope=InstallScope.SYSTEM,
                    uninstalled_files=removed_for_font,
                    errors=helper_errors,
                    message=f"Batch uninstalled {len(removed_for_font)} file(s)" if success else "Failed to uninstall",
                )
            )

        return results

