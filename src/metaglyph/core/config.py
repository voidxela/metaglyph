"""Application configuration and cross-platform path resolution."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from pydantic import BaseModel, Field


class Config(BaseModel):
    """Metaglyph runtime and path configuration."""

    app_name: str = "metaglyph"
    data_dir_override: Path | None = None
    config_dir_override: Path | None = None
    cache_dir_override: Path | None = None
    user_fonts_dir_override: Path | None = None
    system_fonts_dir_override: Path | None = None
    system_font_search_paths_override: list[Path] | None = None
    platform_override: str | None = None

    default_sample_text: str = "The quick brown fox jumps over the lazy dog."
    default_font_size: float = 24.0
    curated_categories: list[str] = Field(
        default_factory=lambda: [
            "Interface",
            "Code",
            "Header",
            "Prose",
            "Display",
            "Handwriting",
        ]
    )

    # Provider priorities: lower number = higher priority
    provider_priorities: dict[str, int] = Field(
        default_factory=lambda: {
            "fontsource": 1,
            "google": 2,
            "nerd_fonts": 3,
        }
    )

    @property
    def platform_name(self) -> str:
        """Normalized OS platform name ('linux', 'darwin', 'windows')."""
        if self.platform_override:
            return self.platform_override
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform == "darwin":
            return "darwin"
        if sys.platform in ("win32", "cygwin"):
            return "windows"
        return sys.platform

    @property
    def data_dir(self) -> Path:
        """Application data directory for database and persistent state."""
        if self.data_dir_override:
            return self.data_dir_override
        if env_val := os.environ.get("METAGLYPH_DATA_DIR"):
            return Path(env_val)

        home = Path.home()
        match self.platform_name:
            case "linux":
                xdg_data = os.environ.get("XDG_DATA_HOME")
                base = Path(xdg_data) if xdg_data else home / ".local" / "share"
                return base / self.app_name
            case "darwin":
                return home / "Library" / "Application Support" / self.app_name
            case "windows":
                app_data = os.environ.get("LOCALAPPDATA")
                base = Path(app_data) if app_data else home / "AppData" / "Local"
                return base / self.app_name
            case _:
                return home / f".{self.app_name}"

    @property
    def config_dir(self) -> Path:
        """Application configuration directory."""
        if self.config_dir_override:
            return self.config_dir_override
        if env_val := os.environ.get("METAGLYPH_CONFIG_DIR"):
            return Path(env_val)

        home = Path.home()
        match self.platform_name:
            case "linux":
                xdg_config = os.environ.get("XDG_CONFIG_HOME")
                base = Path(xdg_config) if xdg_config else home / ".config"
                return base / self.app_name
            case "darwin":
                return home / "Library" / "Application Support" / self.app_name
            case "windows":
                app_data = os.environ.get("APPDATA")
                base = Path(app_data) if app_data else home / "AppData" / "Roaming"
                return base / self.app_name
            case _:
                return home / f".{self.app_name}"

    @property
    def cache_dir(self) -> Path:
        """Application cache directory for temporary micro-subsets and downloads."""
        if self.cache_dir_override:
            return self.cache_dir_override
        if env_val := os.environ.get("METAGLYPH_CACHE_DIR"):
            return Path(env_val)

        home = Path.home()
        match self.platform_name:
            case "linux":
                xdg_cache = os.environ.get("XDG_CACHE_HOME")
                base = Path(xdg_cache) if xdg_cache else home / ".cache"
                return base / self.app_name
            case "darwin":
                return home / "Library" / "Caches" / self.app_name
            case "windows":
                local_app_data = os.environ.get("LOCALAPPDATA")
                base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
                return base / self.app_name / "cache"
            case _:
                return home / f".{self.app_name}" / "cache"

    @property
    def subsets_cache_dir(self) -> Path:
        """Directory for micro-subset TTF font previews."""
        return self.cache_dir / "subsets"

    @property
    def downloads_cache_dir(self) -> Path:
        """Directory for staging downloaded full font files."""
        return self.cache_dir / "downloads"

    @property
    def database_path(self) -> Path:
        """SQLite database file path."""
        if env_val := os.environ.get("METAGLYPH_DB_PATH"):
            return Path(env_val)
        return self.data_dir / "metaglyph.db"

    @property
    def user_fonts_dir(self) -> Path:
        """Primary OS font installation directory for the current user."""
        if self.user_fonts_dir_override:
            return self.user_fonts_dir_override
        home = Path.home()
        match self.platform_name:
            case "linux":
                xdg_data = os.environ.get("XDG_DATA_HOME")
                base = Path(xdg_data) if xdg_data else home / ".local" / "share"
                return base / "fonts" / self.app_name
            case "darwin":
                return home / "Library" / "Fonts"
            case "windows":
                local_app_data = os.environ.get("LOCALAPPDATA")
                base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
                return base / "Microsoft" / "Windows" / "Fonts"
            case _:
                return home / ".fonts" / self.app_name

    @property
    def system_fonts_dir(self) -> Path:
        """Primary OS font installation directory requiring system privileges."""
        if self.system_fonts_dir_override:
            return self.system_fonts_dir_override
        match self.platform_name:
            case "linux":
                return Path("/usr/local/share/fonts") / self.app_name
            case "darwin":
                return Path("/Library/Fonts")
            case "windows":
                win_dir = os.environ.get("WINDIR", r"C:\Windows")
                return Path(win_dir) / "Fonts"
            case _:
                return Path("/usr/share/fonts") / self.app_name

    @property
    def all_system_font_search_paths(self) -> list[Path]:
        """All search paths where OS fonts might reside."""
        if self.system_font_search_paths_override is not None:
            return [p for p in self.system_font_search_paths_override if p.exists()]

        paths: list[Path] = []
        home = Path.home()

        match self.platform_name:
            case "linux":
                paths.extend([
                    home / ".local" / "share" / "fonts",
                    home / ".fonts",
                    Path("/usr/local/share/fonts"),
                    Path("/usr/share/fonts"),
                ])
            case "darwin":
                paths.extend([
                    home / "Library" / "Fonts",
                    Path("/Library/Fonts"),
                    Path("/System/Library/Fonts"),
                ])
            case "windows":
                win_dir = os.environ.get("WINDIR", r"C:\Windows")
                local_app_data = os.environ.get("LOCALAPPDATA")
                if local_app_data:
                    paths.append(Path(local_app_data) / "Microsoft" / "Windows" / "Fonts")
                paths.append(Path(win_dir) / "Fonts")

        return [p for p in paths if p.exists()]

    def ensure_directories(self) -> None:
        """Ensure core application runtime directories exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.subsets_cache_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_fonts_dir.mkdir(parents=True, exist_ok=True)


_global_config: Config | None = None


def get_config() -> Config:
    """Retrieve the global Config singleton."""
    global _global_config
    if _global_config is None:
        _global_config = Config()
    return _global_config


def set_config(config: Config) -> None:
    """Set the global Config singleton (primarily for testing)."""
    global _global_config
    _global_config = config
