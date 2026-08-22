"""Font installation, privilege escalation, and font cache management."""

from metaglyph.installer.base import (
    BaseInstaller,
    InstallResult,
    InstallScope,
    is_font_file,
    verify_font_magic_bytes,
)
from metaglyph.installer.detector import FontDetector, extract_font_names
from metaglyph.installer.system_installer import SystemFontInstaller, find_helper_binary
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller, refresh_user_font_cache

__all__ = [
    "BaseInstaller",
    "InstallScope",
    "InstallResult",
    "verify_font_magic_bytes",
    "is_font_file",
    "UserFontInstaller",
    "refresh_user_font_cache",
    "SystemFontInstaller",
    "find_helper_binary",
    "FontDetector",
    "extract_font_names",
    "FontUninstaller",
]
