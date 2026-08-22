"""Coordinated font uninstallation across User and System scopes."""

from __future__ import annotations

from pathlib import Path

from metaglyph.core.config import Config, get_config
from metaglyph.core.events import EventBus, get_event_bus
from metaglyph.core.logging import get_logger
from metaglyph.db.models import InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import InstallResult, InstallScope
from metaglyph.installer.system_installer import SystemFontInstaller
from metaglyph.installer.user_installer import UserFontInstaller

logger = get_logger("installer.uninstaller")


class FontUninstaller:
    """Coordinates single and batch uninstallation across User and System scopes."""

    def __init__(
        self,
        repository: FontRepository | None = None,
        config: Config | None = None,
        event_bus: EventBus | None = None,
        user_installer: UserFontInstaller | None = None,
        system_installer: SystemFontInstaller | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or get_config()
        self._event_bus = event_bus or get_event_bus()
        self._user_installer = user_installer or UserFontInstaller(
            repository=repository, config=self._config, event_bus=self._event_bus
        )
        self._system_installer = system_installer or SystemFontInstaller(
            repository=repository, config=self._config, event_bus=self._event_bus
        )

    @property
    def user_installer(self) -> UserFontInstaller:
        return self._user_installer

    @property
    def system_installer(self) -> SystemFontInstaller:
        return self._system_installer

    async def uninstall_font(
        self,
        font_id: str,
        family_name: str,
        file_paths: list[Path] | list[str],
        scope: str = "User",
    ) -> InstallResult:
        """Uninstall a single font family by scope."""
        paths = [Path(p) if isinstance(p, str) else p for p in file_paths]

        if scope.lower() == "system":
            return await self._system_installer.uninstall_font(
                font_id=font_id,
                family_name=family_name,
                file_paths=paths,
            )
        else:
            return await self._user_installer.uninstall_font(
                font_id=font_id,
                family_name=family_name,
                file_paths=paths,
            )

    async def uninstall_installed_font(self, installed: InstalledFont) -> InstallResult:
        """Uninstall a font using an InstalledFont database record."""
        return await self.uninstall_font(
            font_id=installed.font_id,
            family_name=installed.family_name,
            file_paths=[Path(p) for p in installed.file_paths],
            scope=installed.install_scope,
        )

    async def batch_uninstall(
        self,
        installed_fonts: list[InstalledFont],
    ) -> list[InstallResult]:
        """Batch uninstall multiple font records across User and System scopes."""
        if not installed_fonts:
            return []

        user_fonts: list[InstalledFont] = []
        system_fonts: list[InstalledFont] = []

        for inst in installed_fonts:
            if inst.install_scope.lower() == "system":
                system_fonts.append(inst)
            else:
                user_fonts.append(inst)

        results: list[InstallResult] = []

        # Process user fonts
        for u_font in user_fonts:
            res = await self._user_installer.uninstall_font(
                font_id=u_font.font_id,
                family_name=u_font.family_name,
                file_paths=[Path(p) for p in u_font.file_paths],
            )
            results.append(res)

        # Process system fonts in a single batch elevation manifest
        if system_fonts:
            batch_tuples = [
                (sf.font_id, sf.family_name, [Path(p) for p in sf.file_paths])
                for sf in system_fonts
            ]
            sys_results = await self._system_installer.uninstall_multiple_fonts(batch_tuples)
            results.extend(sys_results)

        self._event_bus.emit(
            "batch_uninstalled",
            count=len(results),
            results=results,
        )

        return results
