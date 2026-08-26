"""Direct user-space font installer for unprivileged font deployment."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
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

logger = get_logger("installer.user")


async def refresh_user_font_cache(target_dir: Path | None = None) -> bool:
    """Trigger OS-specific user font cache refresh without blocking the event loop."""
    config = get_config()
    target = target_dir or config.user_fonts_dir

    if config.platform_name == "linux":
        try:
            def _run_fc_cache() -> bool:
                result = subprocess.run(
                    ["fc-cache", "-f", str(target)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=15,
                )
                return result.returncode == 0

            return await asyncio.to_thread(_run_fc_cache)
        except FileNotFoundError:
            logger.warning("fc-cache command not found in PATH; font cache refresh skipped.")
            return True
        except Exception as exc:
            logger.warning("Failed to refresh user font cache via fc-cache: %s", exc)
            return False
    elif config.platform_name == "windows":
        # Windows handles user font installations natively when placed in AppData Fonts
        return True
    elif config.platform_name == "darwin":
        # macOS fontd monitors ~/Library/Fonts automatically
        return True

    return True


class UserFontInstaller(BaseInstaller):
    """Installs font files directly into the user's font directory without root privileges."""

    def __init__(
        self,
        repository: FontRepository | None = None,
        config: Config | None = None,
        event_bus: EventBus | None = None,
        target_dir_override: Path | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()
        self._target_dir_override = target_dir_override

    @property
    def target_dir(self) -> Path:
        """Target user font directory."""
        if self._target_dir_override is not None:
            return self._target_dir_override
        return self._config.user_fonts_dir

    async def install_font(
        self,
        font: Font,
        font_files: list[Path],
        version: str | None = None,
    ) -> InstallResult:
        """Copy font files into user fonts directory, rebuild user cache, and update repository."""
        if not font_files:
            return InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=InstallScope.USER,
                errors=["No font files provided for installation"],
                message="Installation failed: no files provided",
            )

        target_dir = self.target_dir
        logger.info("Ensuring user fonts directory exists: %s", target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        installed_paths: list[Path] = []
        errors: list[str] = []

        def _do_copy() -> tuple[list[Path], list[str]]:
            copied: list[Path] = []
            errs: list[str] = []

            for src in font_files:
                if not src.exists():
                    msg = f"Source file does not exist: {src}"
                    logger.warning(msg)
                    errs.append(msg)
                    continue

                if not verify_font_magic_bytes(src):
                    msg = f"File {src.name} is not a valid TTF/OTF font"
                    logger.warning(msg)
                    errs.append(msg)
                    continue

                dest = target_dir / src.name
                temp_dest = target_dir / f".metaglyph_tmp_{os.getpid()}_{src.name}"

                try:
                    logger.info("Copying font file from %s to %s", src, temp_dest)
                    shutil.copy2(src, temp_dest)
                    # Set standard file permissions (0644 on Unix)
                    if hasattr(os, "chmod"):
                        os.chmod(temp_dest, 0o644)
                    logger.info("Moving temporary file from %s to %s", temp_dest, dest)
                    temp_dest.replace(dest)
                    copied.append(dest)
                except Exception as e:
                    msg = f"Failed to copy {src.name}: {e}"
                    logger.warning(msg)
                    errs.append(msg)
                    if temp_dest.exists():
                        try:
                            logger.info("Removing temporary file: %s", temp_dest)
                            temp_dest.unlink()
                        except Exception as ue:
                            logger.warning("Failed to remove temporary file %s: %s", temp_dest, ue)

            return copied, errs

        installed_paths, errors = await asyncio.to_thread(_do_copy)

        if not installed_paths:
            return InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=InstallScope.USER,
                errors=errors,
                message=f"Failed to install font {font.family_name}",
            )

        # Refresh user font cache
        await refresh_user_font_cache(target_dir)

        # Record in database if repository is available
        if self._repository is not None:
            installed_record = InstalledFont(
                font_id=font.id,
                family_name=font.family_name,
                provider=font.primary_provider,
                version=version,
                install_scope=InstallScope.USER,
                installed_at=int(time.time()),
                file_paths=[str(p.resolve()) for p in installed_paths],
            )
            try:
                await self._repository.record_installation(installed_record)
            except Exception as e:
                logger.error("Failed to record font installation in DB: %s", e)
                errors.append(f"Database error: {e}")

        # Emit event
        self._event_bus.emit(
            "font_installed",
            font_id=font.id,
            family_name=font.family_name,
            scope=InstallScope.USER,
            files=installed_paths,
        )

        msg = f"Successfully installed {len(installed_paths)} file(s) for {font.family_name}"
        if errors:
            msg += f" with {len(errors)} warning(s)"

        return InstallResult(
            success=True,
            font_id=font.id,
            family_name=font.family_name,
            scope=InstallScope.USER,
            installed_files=installed_paths,
            errors=errors,
            message=msg,
        )

    async def uninstall_font(
        self,
        font_id: str,
        family_name: str,
        file_paths: list[Path],
    ) -> InstallResult:
        """Delete user font files, rebuild user cache, and update repository."""
        uninstalled_paths: list[Path] = []
        errors: list[str] = []

        def _do_delete() -> tuple[list[Path], list[str]]:
            removed: list[Path] = []
            errs: list[str] = []

            for path in file_paths:
                try:
                    if path.exists():
                        logger.info("Deleting user font file: %s", path)
                        path.unlink()
                        removed.append(path)
                    else:
                        # File might already be gone
                        logger.info("User font file already deleted or not found: %s", path)
                        removed.append(path)
                except Exception as e:
                    errs.append(f"Failed to delete {path}: {e}")

            return removed, errs

        uninstalled_paths, errors = await asyncio.to_thread(_do_delete)

        # Refresh user font cache
        await refresh_user_font_cache(self.target_dir)

        # Remove from database
        if self._repository is not None:
            try:
                await self._repository.remove_installation(font_id, scope=InstallScope.USER)
            except Exception as e:
                logger.error("Failed to remove font installation record from DB: %s", e)
                errors.append(f"Database error: {e}")

        # Emit event
        self._event_bus.emit(
            "font_uninstalled",
            font_id=font_id,
            family_name=family_name,
            scope=InstallScope.USER,
            files=uninstalled_paths,
        )

        return InstallResult(
            success=len(errors) == 0 or len(uninstalled_paths) > 0,
            font_id=font_id,
            family_name=family_name,
            scope=InstallScope.USER,
            uninstalled_files=uninstalled_paths,
            errors=errors,
            message=f"Uninstalled {len(uninstalled_paths)} file(s) for {family_name}",
        )

