"""Visual testing harness and environment orchestrator for Metaglyph."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from metaglyph.core.config import Config, set_config
from metaglyph.db.database import DatabaseManager
from metaglyph.db.models import Font, FontVariant, InstalledFont, SystemFontCacheEntry
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector
from metaglyph.installer.system_installer import SystemFontInstaller
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader
from metaglyph.ui.app import create_application
from metaglyph.ui.main_window import MainWindow
from .driver import UIDriver


@dataclass
class VisualSnapshot:
    """Captured screenshot metadata and file location."""

    scenario_name: str
    image_path: Path
    viewport_size: tuple[int, int]
    description: str = ""
    timestamp: float = 0.0


def synthesize_valid_ttf(
    family_name: str = "Metaglyph Test Font",
    style_name: str = "Regular",
    sample_text: str | None = None,
) -> bytes:
    """Synthesize a valid, renderable TrueType font binary with real glyph outlines."""
    if sample_text is None:
        chars = [chr(c) for c in range(32, 127)]
    else:
        chars = list(set(sample_text + " ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"))

    fb = FontBuilder(1000, isTTF=True)
    glyph_names = [".notdef"] + [f"uni{ord(c):04X}" if c != " " else "space" for c in chars]
    if "space" not in glyph_names:
        glyph_names.append("space")

    fb.setupGlyphOrder(glyph_names)

    cmap = {ord(c): ("space" if c == " " else f"uni{ord(c):04X}") for c in chars}
    fb.setupCharacterMap(cmap)

    pen = TTGlyphPen(None)
    pen.moveTo((100, 100))
    pen.lineTo((100, 800))
    pen.lineTo((750, 800))
    pen.lineTo((750, 100))
    pen.closePath()
    box_glyph = pen.glyph()

    blank_pen = TTGlyphPen(None)
    blank_glyph = blank_pen.glyph()

    glyphs_dict = {name: box_glyph for name in glyph_names}
    glyphs_dict[".notdef"] = blank_glyph
    glyphs_dict["space"] = blank_glyph

    fb.setupGlyf(glyphs_dict)
    h_metrics = {name: (900, 50) for name in glyph_names}
    h_metrics["space"] = (450, 0)
    fb.setupHorizontalMetrics(h_metrics)
    fb.setupHorizontalHeader(ascent=850, descent=-150)
    fb.setupNameTable({"familyName": family_name, "styleName": style_name})
    fb.setupOS2()
    fb.setupPost()

    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


class VisualHarness:
    """Context manager and orchestrator for running headless visual UI tests."""

    def __init__(
        self,
        output_dir: str | Path | None = None,
        viewport_size: tuple[int, int] = (1280, 820),
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="metaglyph_visual_"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.viewport_size = viewport_size

        self._temp_dir = Path(tempfile.mkdtemp(prefix="metaglyph_harness_env_"))
        self.qapp: QApplication | None = None
        self.window: MainWindow | None = None
        self.driver: UIDriver | None = None

        self.db_manager: DatabaseManager | None = None
        self.repository: FontRepository | None = None
        self.provider_manager: MagicMock | None = None
        self.detector: MagicMock | None = None
        self.subset_fetcher: SubsetFetcher | None = None
        self.font_loader: FontLoader | None = None

        self.test_ttf_path: Path | None = None
        self.snapshots: list[VisualSnapshot] = []

    async def __aenter__(self) -> VisualHarness:
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.teardown()

    async def setup(self) -> None:
        """Initialize offscreen Qt environment, mock database, and seed font catalog."""
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        self.qapp = create_application()

        # 1. Setup isolated test config
        config_dir = self._temp_dir / "config"
        data_dir = self._temp_dir / "data"
        cache_dir = self._temp_dir / "cache"
        user_fonts_dir = self._temp_dir / "user_fonts"
        system_fonts_dir = self._temp_dir / "system_fonts"
        subsets_cache_dir = self._temp_dir / "subsets"
        db_path = data_dir / "visual_test.db"

        for d in (config_dir, data_dir, cache_dir, user_fonts_dir, system_fonts_dir, subsets_cache_dir):
            d.mkdir(parents=True, exist_ok=True)

        config = Config(
            app_name="metaglyph-visual-test",
            config_dir=config_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
            user_fonts_dir=user_fonts_dir,
            system_fonts_dir=system_fonts_dir,
            subsets_cache_dir=subsets_cache_dir,
            database_path=db_path,
        )
        set_config(config)

        # 2. Synthesize test font binary
        self.test_ttf_path = cache_dir / "TestFont-Regular.ttf"
        self.test_ttf_path.write_bytes(synthesize_valid_ttf("Metaglyph Preview Font", "Regular"))

        # 3. Database initialization & seed catalog
        self.db_manager = DatabaseManager(db_path)
        await self.db_manager.initialize()
        self.repository = FontRepository(self.db_manager)
        await self._seed_catalog()

        # 4. Mock Providers and Loaders
        self.font_loader = FontLoader()
        subset_cache = SubsetCache(subsets_cache_dir)

        self.provider_manager = MagicMock(spec=ProviderManager)
        self.provider_manager.fetch_sample_subset = AsyncMock(return_value=self.test_ttf_path)
        self.provider_manager.download_font_family = AsyncMock(return_value=[self.test_ttf_path])
        self.provider_manager.sync_all = AsyncMock(return_value={"google": 5, "fontsource": 3, "nerd_fonts": 2})

        self.subset_fetcher = SubsetFetcher(
            cache=subset_cache,
            loader=self.font_loader,
            provider_manager=self.provider_manager,
        )

        # 5. Mock Detectors & Installers
        self.detector = MagicMock(spec=FontDetector)
        self.detector.scan_all_fonts = AsyncMock(
            return_value=[
                SystemFontCacheEntry(
                    family_name="DejaVu Sans",
                    postscript_name="DejaVuSans",
                    scope="System",
                    file_path="/usr/share/fonts/dejavu/DejaVuSans.ttf",
                    last_scanned_at=1700000000,
                ),
                SystemFontCacheEntry(
                    family_name="Liberation Mono",
                    postscript_name="LiberationMono-Regular",
                    scope="System",
                    file_path="/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
                    last_scanned_at=1700000000,
                ),
                SystemFontCacheEntry(
                    family_name="Inter",
                    postscript_name="Inter-Regular",
                    scope="User",
                    file_path=str(user_fonts_dir / "Inter-Regular.ttf"),
                    is_metaglyph_managed=True,
                    last_scanned_at=1700000000,
                ),
            ]
        )

        user_installer = UserFontInstaller(repository=self.repository)
        system_installer = SystemFontInstaller(repository=self.repository)
        uninstaller = FontUninstaller(
            repository=self.repository,
            user_installer=user_installer,
            system_installer=system_installer,
        )

        # 6. Build Main Window
        self.window = MainWindow(
            repository=self.repository,
            subset_fetcher=self.subset_fetcher,
            provider_manager=self.provider_manager,
            user_installer=user_installer,
            system_installer=system_installer,
            uninstaller=uninstaller,
            detector=self.detector,
        )
        self.window.resize(self.viewport_size[0], self.viewport_size[1])
        self.window.show()

        self.driver = UIDriver(self.window)
        self.driver.pump_events(10)
        await self.driver.wait_for_idle(200)

    async def _seed_catalog(self) -> None:
        """Seed a rich, realistic catalog of fonts across all categories and providers."""
        seed_fonts = [
            Font(
                id="inter",
                family_name="Inter",
                category="sans-serif",
                curated_category="Interface",
                is_variable=True,
                has_nerd_font=False,
                primary_provider="google",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="inter",
                        provider="google",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/inter-400.ttf",
                    ),
                    FontVariant(
                        font_id="inter",
                        provider="google",
                        style="normal",
                        weight=700,
                        file_format="ttf",
                        download_url="https://example.com/inter-700.ttf",
                    ),
                ],
            ),
            Font(
                id="jetbrains-mono",
                family_name="JetBrains Mono",
                category="monospace",
                curated_category="Code",
                is_variable=True,
                has_nerd_font=True,
                nerd_font_slug="jetbrainsmono-nerd-font",
                primary_provider="fontsource",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="jetbrains-mono",
                        provider="fontsource",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/jb-400.ttf",
                    ),
                    FontVariant(
                        font_id="jetbrains-mono",
                        provider="fontsource",
                        style="normal",
                        weight=700,
                        file_format="ttf",
                        download_url="https://example.com/jb-700.ttf",
                    ),
                ],
            ),
            Font(
                id="jetbrainsmono-nerd-font",
                family_name="JetBrainsMono Nerd Font",
                category="monospace",
                curated_category="Code",
                is_variable=False,
                has_nerd_font=False,
                primary_provider="nerd_fonts",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="jetbrainsmono-nerd-font",
                        provider="nerd_fonts",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/jb-nf-400.ttf",
                    )
                ],
            ),
            Font(
                id="fira-code",
                family_name="Fira Code",
                category="monospace",
                curated_category="Code",
                is_variable=True,
                has_nerd_font=True,
                nerd_font_slug="firacode-nerd-font",
                primary_provider="fontsource",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="fira-code",
                        provider="fontsource",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/fira-400.ttf",
                    )
                ],
            ),
            Font(
                id="firacode-nerd-font",
                family_name="FiraCode Nerd Font",
                category="monospace",
                curated_category="Code",
                is_variable=False,
                has_nerd_font=False,
                primary_provider="nerd_fonts",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="firacode-nerd-font",
                        provider="nerd_fonts",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/fira-nf-400.ttf",
                    )
                ],
            ),
            Font(
                id="playfair-display",
                family_name="Playfair Display",
                category="serif",
                curated_category="Prose",
                is_variable=True,
                has_nerd_font=False,
                primary_provider="google",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="playfair-display",
                        provider="google",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/playfair-400.ttf",
                    )
                ],
            ),
            Font(
                id="montserrat",
                family_name="Montserrat",
                category="sans-serif",
                curated_category="Header",
                is_variable=True,
                has_nerd_font=False,
                primary_provider="google",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="montserrat",
                        provider="google",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/montserrat-400.ttf",
                    )
                ],
            ),
            Font(
                id="caveat",
                family_name="Caveat",
                category="handwriting",
                curated_category="Handwriting",
                is_variable=True,
                has_nerd_font=False,
                primary_provider="google",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="caveat",
                        provider="google",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/caveat-400.ttf",
                    )
                ],
            ),
            Font(
                id="bebas-neue",
                family_name="Bebas Neue",
                category="display",
                curated_category="Display",
                is_variable=False,
                has_nerd_font=False,
                primary_provider="google",
                last_synced_at=1700000000,
                variants=[
                    FontVariant(
                        font_id="bebas-neue",
                        provider="google",
                        style="normal",
                        weight=400,
                        file_format="ttf",
                        download_url="https://example.com/bebas-400.ttf",
                    )
                ],
            ),
        ]
        assert self.repository is not None
        await self.repository.upsert_fonts(seed_fonts)

        # Seed installed font record (Inter installed by user)
        installed_inter = InstalledFont(
            font_id="inter",
            family_name="Inter",
            provider="google",
            install_scope="User",
            installed_at=1700000000,
            file_paths=["/home/user/.local/share/fonts/Inter-Regular.ttf"],
        )
        await self.repository.record_installation(installed_inter)

    # =========================================================================
    # Screenshot Capture Methods
    # =========================================================================

    def resize_viewport(self, width: int, height: int) -> None:
        """Resize main window to specific viewport resolution."""
        if self.window:
            self.viewport_size = (width, height)
            self.window.resize(width, height)
            if self.driver:
                self.driver.pump_events(5)

    def capture_window(self, filename: str) -> Path:
        """Capture pixel-perfect screenshot of the active MainWindow."""
        assert self.window is not None, "Window is not initialized"
        if self.driver:
            self.driver.pump_events(5)

        target_path = self.output_dir / filename
        pixmap: QPixmap = self.window.grab()
        pixmap.save(str(target_path), "PNG")
        return target_path

    def capture_widget(self, widget: QWidget, filename: str) -> Path:
        """Capture screenshot of a specific isolated child widget."""
        if self.driver:
            self.driver.pump_events(5)

        target_path = self.output_dir / filename
        pixmap: QPixmap = widget.grab()
        pixmap.save(str(target_path), "PNG")
        return target_path

    def capture_snapshot(self, scenario_name: str, description: str = "") -> VisualSnapshot:
        """Capture and record a named scenario snapshot."""
        safe_name = scenario_name.lower().replace(" ", "_").replace("/", "_")
        filename = f"{safe_name}.png"
        path = self.capture_window(filename)

        snapshot = VisualSnapshot(
            scenario_name=scenario_name,
            image_path=path,
            viewport_size=self.viewport_size,
            description=description,
        )
        self.snapshots.append(snapshot)
        return snapshot

    async def teardown(self) -> None:
        """Clean up database, windows, and temp files."""
        if self.window:
            self.window.close()
            self.window = None

        if self.db_manager:
            await self.db_manager.close()

        if self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
