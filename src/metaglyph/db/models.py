"""Data models and schemas for Metaglyph font database."""

from __future__ import annotations

import json
from typing import Literal
from pydantic import BaseModel, Field


class FontVariant(BaseModel):
    """Specific variant/style of a font from a provider."""

    id: int | None = None
    font_id: str
    provider: Literal["google", "fontsource", "nerd_fonts"] | str
    style: Literal["normal", "italic"] | str = "normal"
    weight: int = 400
    file_format: Literal["ttf", "otf", "woff2"] | str = "ttf"
    download_url: str
    subset_url: str | None = None
    filesize: int = 0


class Font(BaseModel):
    """Unified font family entry."""

    id: str
    family_name: str
    category: str
    curated_category: str | None = None
    is_variable: bool = False
    has_nerd_font: bool = False
    nerd_font_slug: str | None = None
    primary_provider: Literal["google", "fontsource", "nerd_fonts"] | str
    last_synced_at: int
    variants: list[FontVariant] = Field(default_factory=list)


class InstalledFont(BaseModel):
    """Record of a font family or variant installed on the local system."""

    id: int | None = None
    font_id: str
    family_name: str
    provider: str
    version: str | None = None
    install_scope: Literal["User", "System"] | str = "User"
    installed_at: int
    file_paths: list[str] = Field(default_factory=list)

    def file_paths_json(self) -> str:
        """Serialize file_paths list to JSON string for SQLite storage."""
        return json.dumps(self.file_paths)

    @classmethod
    def from_db_row(
        cls,
        id: int,
        font_id: str,
        family_name: str,
        provider: str,
        version: str | None,
        install_scope: str,
        installed_at: int,
        file_paths_str: str,
    ) -> InstalledFont:
        """Create instance from raw database columns."""
        paths = json.loads(file_paths_str) if file_paths_str else []
        return cls(
            id=id,
            font_id=font_id,
            family_name=family_name,
            provider=provider,
            version=version,
            install_scope=install_scope,
            installed_at=installed_at,
            file_paths=paths,
        )


class SystemFontCacheEntry(BaseModel):
    """OS font index item discovered during system scan."""

    family_name: str
    postscript_name: str | None = None
    file_path: str
    scope: Literal["User", "System"] | str = "System"
    is_metaglyph_managed: bool = False
    last_scanned_at: int


class FontFilter(BaseModel):
    """Query and filter parameters for searching the font catalog."""

    query: str | None = None
    categories: list[str] = Field(default_factory=list)
    curated_categories: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    is_variable: bool | None = None
    has_nerd_font: bool | None = None
    limit: int = 50
    offset: int = 0
