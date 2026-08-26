"""Application startup, dependency container, and qasync event loop integration."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
import qasync

from metaglyph.core.config import get_config
from metaglyph.core.logging import setup_logging
from metaglyph.db.database import DatabaseManager
from metaglyph.db.repository import FontRepository
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.cache import SubsetCache
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.subsetting.loader import FontLoader
from metaglyph.ui.main_window import MainWindow
from metaglyph.ui.theme.icons import get_app_icon
from metaglyph.ui.theme.qss_builder import apply_theme

logger = logging.getLogger("metaglyph.ui.app")


def set_process_name(name: str = "metaglyph") -> None:
    """Set Linux process comm name and title for desktop taskbars and system monitors."""
    if sys.platform.startswith("linux"):
        try:
            import ctypes
            import ctypes.util

            libc_name = ctypes.util.find_library("c")
            if libc_name:
                libc = ctypes.CDLL(libc_name)
                # PR_SET_NAME = 15
                libc.prctl(15, name.encode("utf-8"), 0, 0, 0)
        except Exception:
            pass


def create_application() -> QApplication:
    """Create or retrieve QApplication instance configured for Metaglyph."""
    set_process_name("metaglyph")

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName("metaglyph")
    app.setApplicationDisplayName("Metaglyph")
    app.setOrganizationName("Metaglyph")
    app.setOrganizationDomain("metaglyph.app")
    app.setApplicationVersion("0.1.0")

    # Set desktop file name for Wayland app_id and FreeDesktop taskbar matching
    app.setDesktopFileName("metaglyph.desktop")

    # Set official MetaGlyph desktop window icon
    app.setWindowIcon(get_app_icon())

    # Apply modern cross-platform Fusion style and dark theme
    app.setStyle("Fusion")
    apply_theme(app, "dark")

    return app


class MetaglyphApp:
    """Application runner orchestrating GUI components, database connection, and async runtime."""

    def __init__(self) -> None:
        self.config = get_config()
        self.config.ensure_directories()

        self.db_manager = DatabaseManager(self.config.database_path)
        self.repository = FontRepository(self.db_manager)
        self.provider_manager = ProviderManager()
        self.subset_cache = SubsetCache(self.config.subsets_cache_dir)
        self.font_loader = FontLoader()
        self.subset_fetcher = SubsetFetcher(
            cache=self.subset_cache,
            loader=self.font_loader,
            provider_manager=self.provider_manager,
        )

        self.qapp: QApplication | None = None
        self.main_window: MainWindow | None = None

    async def initialize(self) -> None:
        """Initialize database tables and schema."""
        await self.db_manager.initialize()

    def build_ui(self) -> MainWindow:
        """Create and configure MainWindow."""
        self.qapp = create_application()
        self.main_window = MainWindow(
            repository=self.repository,
            subset_fetcher=self.subset_fetcher,
            provider_manager=self.provider_manager,
        )
        return self.main_window

    async def run_async(self) -> int:
        """Run application event loop asynchronously with qasync."""
        await self.initialize()

        window = self.build_ui()
        assert self.qapp is not None
        self.qapp.setQuitOnLastWindowClosed(False)
        window.show()

        # Connect application close to cleanup
        exit_future: asyncio.Future[int] = asyncio.get_running_loop().create_future()

        def on_app_exit():
            if not exit_future.done():
                exit_future.set_result(0)

        window.closed.connect(on_app_exit)
        self.qapp.aboutToQuit.connect(on_app_exit)

        try:
            return await exit_future
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully release database and network provider resources."""
        current_task = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current_task and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        try:
            await self.provider_manager.close()
        except Exception as exc:
            logger.warning("Error closing provider manager: %s", exc)

        try:
            await self.db_manager.close()
        except Exception as exc:
            logger.warning("Error closing database manager: %s", exc)

        if self.qapp is not None:
            self.qapp.quit()


def run_app() -> int:
    """Main synchronous entry point executing qasync event loop."""
    setup_logging()
    app_instance = MetaglyphApp()
    qapp = create_application()

    # Install SIGINT handler for graceful termination
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    try:
        return qasync.run(app_instance.run_async())
    except (KeyboardInterrupt, SystemExit):
        return 0
    except Exception as exc:
        logger.error("Application error: %s", exc, exc_info=True)
        try:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(None, "Application Error", f"Metaglyph encountered an unexpected error:\n{exc}")
        except Exception:
            pass
        return 1

