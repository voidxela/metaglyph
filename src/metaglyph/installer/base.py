"""Base definitions, contracts, and validation utilities for font installation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

from metaglyph.db.models import Font


class InstallScope(StrEnum):
    """Scope target for font installation."""

    USER = "User"
    SYSTEM = "System"


class InstallResult(BaseModel):
    """Result of a font installation or uninstallation operation."""

    success: bool
    font_id: str
    family_name: str
    scope: Literal["User", "System"] | str = "User"
    installed_files: list[Path] = Field(default_factory=list)
    uninstalled_files: list[Path] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    message: str = ""


# Recognized font binary header magic bytes
FONT_MAGIC_SIGNATURES: set[bytes] = {
    b"\x00\x01\x00\x00",  # TrueType (TTF)
    b"OTTO",              # OpenType with CFF (OTF)
    b"ttcf",              # TrueType / OpenType Collection (TTC)
    b"true",              # Mac TrueType
    b"typ1",              # PostScript Type 1
    b"wOFF",              # WOFF 1.0
    b"wOF2",              # WOFF 2.0
}


import logging

logger = logging.getLogger("metaglyph.installer.base")


def verify_font_magic_bytes(file_path: Path) -> bool:
    """Verify that a file on disk starts with valid font header magic bytes."""
    if not file_path.is_file():
        return False

    try:
        logger.debug("Reading font header magic bytes: %s", file_path)
        with file_path.open("rb") as f:
            header = f.read(4)
            return header in FONT_MAGIC_SIGNATURES
    except Exception as exc:
        logger.warning("Failed to read header from %s: %s", file_path, exc)
        return False




def is_font_file(file_path: Path) -> bool:
    """Check if file extension and header match a recognized font."""
    valid_exts = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}
    if file_path.suffix.lower() not in valid_exts:
        return False
    return verify_font_magic_bytes(file_path)


class BaseInstaller(ABC):
    """Abstract contract for font installers across scopes."""

    @abstractmethod
    async def install_font(
        self,
        font: Font,
        font_files: list[Path],
        version: str | None = None,
    ) -> InstallResult:
        """Install font files to the target scope."""
        pass

    @abstractmethod
    async def uninstall_font(
        self,
        font_id: str,
        family_name: str,
        file_paths: list[Path],
    ) -> InstallResult:
        """Uninstall font files from the target scope."""
        pass
