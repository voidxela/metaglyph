"""Root QMainWindow and view coordinator for Metaglyph."""

from __future__ import annotations

import asyncio
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from metaglyph.core.events import get_event_bus
from metaglyph.db.models import Font
from metaglyph.db.repository import FontRepository
from metaglyph.installer.detector import FontDetector
from metaglyph.installer.system_installer import SystemFontInstaller
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.ui.components.sidebar import SidebarWidget
from metaglyph.ui.views.detail_pane import DetailPane
from metaglyph.ui.views.discover_view import DiscoverView
from metaglyph.ui.views.search_view import SearchView
from metaglyph.ui.views.system_view import SystemView

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Metaglyph primary desktop window hosting navigation, views, and detail drawer."""

    def __init__(
        self,
        repository: FontRepository | None = None,
        subset_fetcher: SubsetFetcher | None = None,
        provider_manager: ProviderManager | None = None,
        user_installer: UserFontInstaller | None = None,
        system_installer: SystemFontInstaller | None = None,
        uninstaller: FontUninstaller | None = None,
        detector: FontDetector | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.subset_fetcher = subset_fetcher
        self.provider_manager = provider_manager or ProviderManager()
        self.user_installer = user_installer or UserFontInstaller(repository=repository)
        self.system_installer = system_installer or SystemFontInstaller(repository=repository)
        self.uninstaller = uninstaller or FontUninstaller(
            repository=repository,
            user_installer=self.user_installer,
            system_installer=self.system_installer,
        )
        self.detector = detector or FontDetector()

        self._sync_task: asyncio.Task | None = None

        self._init_window()
        self._init_ui()
        self._connect_signals()
        self._subscribe_events()
        self._initial_load()

    def _init_window(self) -> None:
        self.setWindowTitle("Metaglyph - Modern Font Browser & Installer")
        self.resize(1280, 820)
        self.setMinimumSize(960, 600)

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        central_layout = QHBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # 1. Left Sidebar Navigation
        self.sidebar = SidebarWidget(central_widget)
        central_layout.addWidget(self.sidebar)

        # 2. Central Views (QStackedWidget)
        self.stack = QStackedWidget(central_widget)

        self.discover_view = DiscoverView(
            repository=self.repository,
            subset_fetcher=self.subset_fetcher,
            parent=self.stack,
        )
        self.search_view = SearchView(
            repository=self.repository,
            subset_fetcher=self.subset_fetcher,
            parent=self.stack,
        )
        self.system_view = SystemView(
            repository=self.repository,
            detector=self.detector,
            uninstaller=self.uninstaller,
            parent=self.stack,
        )

        self.stack.addWidget(self.discover_view)  # index 0
        self.stack.addWidget(self.search_view)    # index 1
        self.stack.addWidget(self.system_view)    # index 2

        central_layout.addWidget(self.stack, stretch=1)

        # 3. Right Detail Pane Inspector (initially hidden until a font is selected)
        self.detail_pane = DetailPane(
            repository=self.repository,
            provider_manager=self.provider_manager,
            user_installer=self.user_installer,
            system_installer=self.system_installer,
            uninstaller=self.uninstaller,
            subset_fetcher=self.subset_fetcher,
            parent=central_widget,
        )
        self.detail_pane.setVisible(False)
        central_layout.addWidget(self.detail_pane)

        self.setCentralWidget(central_widget)

        # 4. Status Bar
        self._status_bar = QStatusBar(self)
        self._status_bar.setObjectName("statusBar")

        self._status_msg_label = QLabel("Status: Ready", self._status_bar)
        self._status_msg_label.setObjectName("statusLabel")
        self._status_bar.addWidget(self._status_msg_label, stretch=1)

        self._status_progress = QProgressBar(self._status_bar)
        self._status_progress.setMaximumWidth(140)
        self._status_progress.setVisible(False)
        self._status_bar.addPermanentWidget(self._status_progress)

        self._status_stats_label = QLabel("0 fonts indexed | 0 installed", self._status_bar)
        self._status_stats_label.setObjectName("statusLabel")
        self._status_bar.addPermanentWidget(self._status_stats_label)

        self._status_version_label = QLabel("v0.1.0", self._status_bar)
        self._status_version_label.setStyleSheet("color: #475569; font-weight: 600;")
        self._status_bar.addPermanentWidget(self._status_version_label)

        self.setStatusBar(self._status_bar)

    def _connect_signals(self) -> None:
        # Sidebar navigation
        self.sidebar.page_changed.connect(self._on_sidebar_page_changed)
        self.sidebar.sync_requested.connect(self.start_catalog_sync)

        # Discover View navigation
        self.discover_view.category_selected.connect(self._on_discover_category_selected)
        self.discover_view.font_selected.connect(self._on_font_selected)
        self.discover_view.sync_requested.connect(self.start_catalog_sync)

        # Search View navigation
        self.search_view.font_selected.connect(self._on_font_selected)
        self.search_view.sync_requested.connect(self.start_catalog_sync)

        # Detail Pane
        self.detail_pane.closed.connect(lambda: self.detail_pane.setVisible(False))
        self.detail_pane.nerd_switch_requested.connect(self._on_nerd_switch_requested)
        self.detail_pane.install_completed.connect(self._on_install_completed)
        self.detail_pane.uninstall_completed.connect(self._on_uninstall_completed)

        # System View
        self.system_view.batch_uninstall_completed.connect(self._on_batch_uninstall_completed)
        self.system_view.font_uninstalled.connect(self._on_single_font_uninstalled)

    def _subscribe_events(self) -> None:
        bus = get_event_bus()
        bus.subscribe("catalog_synced", self._on_catalog_synced_event)
        bus.subscribe("font_installed", self._on_install_state_changed_event)
        bus.subscribe("font_uninstalled", self._on_install_state_changed_event)
        bus.subscribe("system_fonts_scanned", self._on_system_fonts_scanned_event)

    def _initial_load(self) -> None:
        """Schedule initial async data load."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._initial_load_async())
        except RuntimeError:
            pass

    async def _initial_load_async(self) -> None:
        """Perform non-blocking startup database query."""
        await self.refresh_stats_async()
        if self.discover_view:
            await self.discover_view.refresh_stats()
        if self.search_view:
            await self.search_view.execute_search_async()

    def _on_sidebar_page_changed(self, page_index: int) -> None:
        self.stack.setCurrentIndex(page_index)
        if page_index == 0:
            self.discover_view.trigger_async_refresh()
        elif page_index == 1:
            self.search_view.trigger_search()
        elif page_index == 2:
            self.system_view.trigger_scan_and_sync()

    def _on_discover_category_selected(self, category: str) -> None:
        """Switch to search view with curated category pre-filtered."""
        self.sidebar.set_current_page(1)
        self.stack.setCurrentIndex(1)
        self.search_view.set_curated_category(category)

    def _on_font_selected(self, font: Font) -> None:
        """Display font details in the right inspector drawer."""
        self.detail_pane.set_font(font)
        self.detail_pane.setVisible(True)

    def _on_nerd_switch_requested(self, target_slug: str, variant: str) -> None:
        """Switch Detail Pane to target counterpart font (standard or Nerd Font)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._switch_nerd_font_async(target_slug, variant))
        except RuntimeError:
            pass

    async def _switch_nerd_font_async(self, target_slug: str, variant: str) -> None:
        if not self.repository:
            return

        try:
            target_font = await self.repository.get_font_by_slug_or_family(target_slug)
            if target_font:
                self.detail_pane.set_font(target_font)
                self.detail_pane.nerd_badge.set_selected_variant(variant)
            else:
                logger.info("Counterpart font '%s' not indexed in local catalog", target_slug)
        except Exception as exc:
            logger.warning("Failed to switch to counterpart font %s: %s", target_slug, exc)

    def _on_install_completed(self, result: object) -> None:
        msg = getattr(result, "message", "Font installation completed")
        self._status_msg_label.setText(f"Status: {msg}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
            self.system_view.trigger_refresh()
        except RuntimeError:
            pass

    def _on_uninstall_completed(self, result: object) -> None:
        msg = getattr(result, "message", "Font uninstallation completed")
        self._status_msg_label.setText(f"Status: {msg}")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
            self.system_view.trigger_refresh()
        except RuntimeError:
            pass

    def _on_batch_uninstall_completed(self, results: list) -> None:
        count = len(results)
        self._status_msg_label.setText(f"Status: Batch uninstalled {count} font(s)")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
            self.detail_pane._trigger_check_installed()
        except RuntimeError:
            pass

    def _on_single_font_uninstalled(self, font_id: str, scope: str) -> None:
        self._status_msg_label.setText(f"Status: Uninstalled {font_id} ({scope} Scope)")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
            self.detail_pane._trigger_check_installed()
        except RuntimeError:
            pass

    def start_catalog_sync(self) -> None:
        """Trigger background catalog sync across all providers."""
        if not self.repository or not self.provider_manager:
            return

        try:
            loop = asyncio.get_running_loop()
            self._sync_task = loop.create_task(self._sync_catalog_async())
        except RuntimeError:
            pass

    async def _sync_catalog_async(self) -> None:
        if not self.repository:
            return

        self._status_msg_label.setText("Status: Syncing font catalogs from providers...")
        self._status_progress.setVisible(True)
        self._status_progress.setRange(0, 0)  # Indeterminate
        self.sidebar.set_syncing(True, "Syncing...")

        try:
            results = await self.provider_manager.sync_all(self.repository)
            total = sum(results.values())
            self._status_msg_label.setText(f"Status: Sync complete ({total:,} fonts updated)")
            await self.refresh_stats_async()
            await self.discover_view.refresh_stats()
            await self.search_view.execute_search_async()
        except Exception as exc:
            logger.error("Catalog sync failed: %s", exc)
            self._status_msg_label.setText(f"Status: Sync error ({exc})")
        finally:
            self._status_progress.setVisible(False)
            self.sidebar.set_syncing(False)

    async def refresh_stats_async(self) -> None:
        """Update metrics across sidebar and status bar."""
        if not self.repository:
            return

        try:
            stats = await self.repository.get_stats()
            total_fonts = stats.get("total_fonts", 0)
            total_inst = stats.get("total_installed", 0)

            self.sidebar.update_stats(total_fonts, total_inst)
            self._status_stats_label.setText(
                f"{total_fonts:,} fonts indexed | {total_inst} installed"
            )
        except Exception as exc:
            logger.debug("Failed to query stats: %s", exc)

    def _on_catalog_synced_event(self, **kwargs) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
        except RuntimeError:
            pass

    def _on_install_state_changed_event(self, **kwargs) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
            self.system_view.trigger_refresh()
            self.detail_pane._trigger_check_installed()
        except RuntimeError:
            pass

    def _on_system_fonts_scanned_event(self, **kwargs) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.refresh_stats_async())
            self.system_view.trigger_refresh()
        except RuntimeError:
            pass
