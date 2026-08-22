"""Detail pane font inspector, size/weight tuner, Nerd Font switcher, and installation controller."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from metaglyph.core.config import get_config
from metaglyph.db.models import Font, FontVariant, InstalledFont
from metaglyph.db.repository import FontRepository
from metaglyph.installer.base import InstallResult, InstallScope
from metaglyph.installer.system_installer import SystemFontInstaller
from metaglyph.installer.uninstaller import FontUninstaller
from metaglyph.installer.user_installer import UserFontInstaller
from metaglyph.providers.manager import ProviderManager
from metaglyph.subsetting.fetcher import SubsetFetcher
from metaglyph.ui.components.font_preview import FontPreviewWidget
from metaglyph.ui.components.nerd_badge import NerdFontBadge

logger = logging.getLogger(__name__)

WEIGHT_MAP: dict[str, int] = {
    "Thin (100)": 100,
    "Extra Light (200)": 200,
    "Light (300)": 300,
    "Regular (400)": 400,
    "Medium (500)": 500,
    "SemiBold (600)": 600,
    "Bold (700)": 700,
    "ExtraBold (800)": 800,
    "Black (900)": 900,
}

SAMPLE_PRESETS: dict[str, str] = {
    "Quick Brown Fox": "The quick brown fox jumps over the lazy dog.",
    "Alphabet": "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz",
    "Numerals & Symbols": "0123456789 !@#$%^&*()_+=-`~[]\\{}|;':\",./<>?",
    "Programming Ligatures": "const fn = (x) => x !== null ? x : 0; // === >= <= -> != <!--",
    "Pangram (Sphinx)": "Sphinx of black quartz, judge my vow.",
}


class DetailPane(QFrame):
    """Sliding or docked side inspector for fine-tuning font preview, variant selection, and installation."""

    install_requested = Signal(object, str, str)  # (Font, "User" | "System", variant_filter)
    uninstall_requested = Signal(object, str)     # (Font, "User" | "System")
    nerd_switch_requested = Signal(str, str)      # (target_slug, variant)
    closed = Signal()
    install_completed = Signal(object)            # InstallResult
    uninstall_completed = Signal(object)          # InstallResult

    def __init__(
        self,
        repository: FontRepository | None = None,
        provider_manager: ProviderManager | None = None,
        user_installer: UserFontInstaller | None = None,
        system_installer: SystemFontInstaller | None = None,
        uninstaller: FontUninstaller | None = None,
        subset_fetcher: SubsetFetcher | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailPane")
        self.repository = repository
        self.provider_manager = provider_manager or ProviderManager()
        self.user_installer = user_installer or UserFontInstaller(repository=repository)
        self.system_installer = system_installer or SystemFontInstaller(repository=repository)
        self.uninstaller = uninstaller or FontUninstaller(
            repository=repository,
            user_installer=self.user_installer,
            system_installer=self.system_installer,
        )
        self.subset_fetcher = subset_fetcher or SubsetFetcher(
            provider_manager=self.provider_manager
        )

        self._font: Font | None = None
        self._installed_record: InstalledFont | None = None
        self._is_busy: bool = False
        self._subset_task: asyncio.Task | None = None
        self._check_installed_task: asyncio.Task | None = None

        self._init_ui()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Scroll area to comfortably handle smaller display heights
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget(scroll_area)
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 1. Header Row: Title & Close Button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self._title_label = QLabel("Font Inspector", container)
        self._title_label.setObjectName("detailPaneTitle")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch(1)

        self._close_btn = QPushButton("✕", container)
        self._close_btn.setStyleSheet(
            "background-color: transparent; color: #64748b; font-size: 14px; font-weight: bold; border: none; padding: 2px 6px;"
        )
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.closed.emit)
        header_layout.addWidget(self._close_btn)

        main_layout.addLayout(header_layout)

        # Subtitle & Badges
        self._subtitle_label = QLabel("Select a font to view details", container)
        self._subtitle_label.setObjectName("detailPaneSubtitle")
        main_layout.addWidget(self._subtitle_label)

        # Badges row
        self._badges_widget = QWidget(container)
        badges_layout = QHBoxLayout(self._badges_widget)
        badges_layout.setContentsMargins(0, 0, 0, 0)
        badges_layout.setSpacing(6)

        self._provider_badge = QLabel("Provider", self._badges_widget)
        self._provider_badge.setObjectName("fontProviderBadge")
        badges_layout.addWidget(self._provider_badge)

        self._cat_badge = QLabel("Category", self._badges_widget)
        self._cat_badge.setObjectName("fontCategoryBadge")
        badges_layout.addWidget(self._cat_badge)

        self._styles_badge = QLabel("Styles", self._badges_widget)
        self._styles_badge.setObjectName("fontStylesBadge")
        badges_layout.addWidget(self._styles_badge)

        badges_layout.addStretch(1)
        main_layout.addWidget(self._badges_widget)

        # 2. Nerd Font Counterpart Banner (Dedicated NerdFontBadge component)
        self.nerd_badge = NerdFontBadge(container)
        self.nerd_badge.switch_requested.connect(self._on_nerd_switch_requested)
        main_layout.addWidget(self.nerd_badge)
        self.nerd_badge.setVisible(False)

        # Separator line
        sep1 = QFrame(container)
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet("color: #262632;")
        main_layout.addWidget(sep1)

        # 3. Size Slider Section
        size_header_layout = QHBoxLayout()
        size_label = QLabel("Point Size", container)
        size_label.setObjectName("detailSectionHeader")
        size_header_layout.addWidget(size_label)
        size_header_layout.addStretch(1)

        self._size_val_label = QLabel("24 pt", container)
        self._size_val_label.setStyleSheet("color: #818cf8; font-weight: 600; font-size: 11px;")
        size_header_layout.addWidget(self._size_val_label)
        main_layout.addLayout(size_header_layout)

        self._size_slider = QSlider(Qt.Orientation.Horizontal, container)
        self._size_slider.setRange(10, 72)
        self._size_slider.setValue(24)
        self._size_slider.valueChanged.connect(self._on_size_changed)
        main_layout.addWidget(self._size_slider)

        # 4. Weight & Style Controls
        style_controls_layout = QHBoxLayout()
        style_controls_layout.setSpacing(8)

        # Weight Selector
        weight_box = QVBoxLayout()
        weight_label = QLabel("Weight", container)
        weight_label.setObjectName("detailSectionHeader")
        weight_box.addWidget(weight_label)

        self._weight_combo = QComboBox(container)
        for label in WEIGHT_MAP.keys():
            self._weight_combo.addItem(label)
        self._weight_combo.setCurrentText("Regular (400)")
        self._weight_combo.currentTextChanged.connect(self._on_weight_changed)
        weight_box.addWidget(self._weight_combo)
        style_controls_layout.addLayout(weight_box, stretch=2)

        # Italic Checkbox
        italic_box = QVBoxLayout()
        italic_label = QLabel("Style", container)
        italic_label.setObjectName("detailSectionHeader")
        italic_box.addWidget(italic_label)

        self._italic_check = QCheckBox("Italic", container)
        self._italic_check.setProperty("class", "filter-toggle")
        self._italic_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._italic_check.toggled.connect(self._on_italic_toggled)
        italic_box.addWidget(self._italic_check)
        style_controls_layout.addLayout(italic_box, stretch=1)

        main_layout.addLayout(style_controls_layout)

        # 5. Interactive Sample Text & Presets
        sample_header_layout = QHBoxLayout()
        sample_header = QLabel("Sample Text", container)
        sample_header.setObjectName("detailSectionHeader")
        sample_header_layout.addWidget(sample_header)
        sample_header_layout.addStretch(1)

        self._preset_combo = QComboBox(container)
        self._preset_combo.addItem("Presets...")
        for name in SAMPLE_PRESETS.keys():
            self._preset_combo.addItem(name)
        self._preset_combo.currentTextChanged.connect(self._on_preset_selected)
        sample_header_layout.addWidget(self._preset_combo)
        main_layout.addLayout(sample_header_layout)

        self._sample_editor = QPlainTextEdit(container)
        self._sample_editor.setObjectName("detailSampleEditor")
        self._sample_editor.setMaximumHeight(70)
        self._sample_editor.setPlainText(get_config().default_sample_text)
        self._sample_editor.textChanged.connect(self._on_sample_text_changed)
        main_layout.addWidget(self._sample_editor)

        # 6. Live Preview Box
        preview_header = QLabel("Live Rendering", container)
        preview_header.setObjectName("detailSectionHeader")
        main_layout.addWidget(preview_header)

        self._preview = FontPreviewWidget(
            font_family=None,
            sample_text=self._sample_editor.toPlainText(),
            point_size=24.0,
            parent=container,
        )
        main_layout.addWidget(self._preview)

        # 7. Installation State Banner
        self._install_status_label = QLabel("", container)
        self._install_status_label.setObjectName("installStatusBadge")
        self._install_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._install_status_label.setVisible(False)
        main_layout.addWidget(self._install_status_label)

        # Feedback notification label (success/error messages)
        self._feedback_label = QLabel("", container)
        self._feedback_label.setWordWrap(True)
        self._feedback_label.setVisible(False)
        main_layout.addWidget(self._feedback_label)

        # 8. Installation Scope Section
        scope_header = QLabel("Install Target Scope", container)
        scope_header.setObjectName("detailSectionHeader")
        main_layout.addWidget(scope_header)

        scope_group = QButtonGroup(container)
        self._radio_user = QRadioButton("User (~/.local/share/fonts) - No Sudo", container)
        self._radio_user.setChecked(True)
        self._radio_user.setCursor(Qt.CursorShape.PointingHandCursor)
        scope_group.addButton(self._radio_user)
        main_layout.addWidget(self._radio_user)

        self._radio_system = QRadioButton("System (/usr/local/share/fonts) - Helper", container)
        self._radio_system.setCursor(Qt.CursorShape.PointingHandCursor)
        scope_group.addButton(self._radio_system)
        main_layout.addWidget(self._radio_system)

        # 9. Action Buttons Row (Install & Uninstall)
        self._actions_layout = QVBoxLayout()
        self._actions_layout.setSpacing(6)

        self._install_btn = QPushButton("Install Font Family", container)
        self._install_btn.setProperty("class", "primary-btn")
        self._install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_btn.setStyleSheet("padding: 10px; font-size: 13px; font-weight: 700;")
        self._install_btn.clicked.connect(self._on_install_clicked)
        self._actions_layout.addWidget(self._install_btn)

        self._uninstall_btn = QPushButton("Uninstall Font Family", container)
        self._uninstall_btn.setProperty("class", "danger-btn")
        self._uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._uninstall_btn.setStyleSheet(
            "QPushButton { background-color: #991b1b; color: #ffffff; border: 1px solid #dc2626; padding: 8px; font-weight: 700; border-radius: 6px; } QPushButton:hover { background-color: #b91c1c; }"
        )
        self._uninstall_btn.clicked.connect(self._on_uninstall_clicked)
        self._uninstall_btn.setVisible(False)
        self._actions_layout.addWidget(self._uninstall_btn)

        main_layout.addLayout(self._actions_layout)

        scroll_area.setWidget(container)
        root_layout.addWidget(scroll_area)
        self.setLayout(root_layout)

    def set_font(self, font: Font) -> None:
        """Populate inspector with font model data and refresh installation state."""
        self._font = font
        self._title_label.setText(font.family_name)

        prov = font.primary_provider.replace("_", " ").title()
        self._subtitle_label.setText(f"Provided via {prov}")
        self._provider_badge.setText(prov)

        cat = (font.curated_category or font.category).title()
        self._cat_badge.setText(cat)

        styles_count = len(font.variants) if font.variants else 1
        self._styles_badge.setText(f"{styles_count} {'Style' if styles_count == 1 else 'Styles'}")

        # Update Nerd Font banner
        self.nerd_badge.set_font(font)

        # Update preview family
        self._preview.set_font_family(font.family_name)

        # Clear feedback
        self._feedback_label.setVisible(False)

        # Trigger subset fetch for current variant and check installation status
        self._trigger_subset_load()
        self._trigger_check_installed()

    def cleanup(self) -> None:
        """Cancel in-flight async tasks."""
        if self._subset_task and not self._subset_task.done():
            self._subset_task.cancel()
            self._subset_task = None
        if self._check_installed_task and not self._check_installed_task.done():
            self._check_installed_task.cancel()
            self._check_installed_task = None

    def _trigger_subset_load(self) -> None:
        """Trigger async subset fetch for active font variant."""
        if not self._font or not self.subset_fetcher:
            return

        if self._subset_task and not self._subset_task.done():
            self._subset_task.cancel()

        try:
            loop = asyncio.get_running_loop()
            self._subset_task = loop.create_task(self._load_subset_async())
        except RuntimeError:
            pass

    async def _load_subset_async(self) -> None:
        """Fetch and register authentic variant subset in QFontDatabase."""
        if not self._font or not self.subset_fetcher:
            return

        font = self._font
        weight_text = self._weight_combo.currentText()
        weight_val = WEIGHT_MAP.get(weight_text, 400)
        is_italic = self._italic_check.isChecked()
        style_val = "italic" if is_italic else "normal"
        sample = self._preview.sample_text or self._sample_editor.toPlainText() or get_config().default_sample_text

        target_variant: FontVariant | None = None
        if font.variants:
            for v in font.variants:
                if v.weight == weight_val and v.style == style_val:
                    target_variant = v
                    break

        if target_variant is None:
            target_variant = FontVariant(
                font_id=font.id,
                provider=font.primary_provider,
                style=style_val,
                weight=weight_val,
                file_format="ttf",
                download_url="",
            )

        try:
            _, family_name = await self.subset_fetcher.get_or_fetch_subset(
                font=font,
                sample_text=sample,
                variant=target_variant,
            )
            if family_name and self._font and self._font.id == font.id:
                self._preview.set_font_family(family_name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug(
                "Failed to fetch variant subset for %s (%d %s): %s",
                font.family_name,
                weight_val,
                style_val,
                exc,
            )

    def _trigger_check_installed(self) -> None:
        if self._check_installed_task and not self._check_installed_task.done():
            self._check_installed_task.cancel()
        try:
            loop = asyncio.get_running_loop()
            self._check_installed_task = loop.create_task(self._check_installed_async())
        except RuntimeError:
            pass

    async def _check_installed_async(self) -> None:
        if not self.repository or not self._font:
            return

        try:
            installed = await self.repository.get_installed_font(self._font.id)
            self._installed_record = installed

            if installed:
                self._install_status_label.setText(f"✓ Installed ({installed.install_scope} Scope)")
                self._install_status_label.setVisible(True)
                self._uninstall_btn.setVisible(True)
                self._install_btn.setText("Reinstall Font Family")
                if installed.install_scope.lower() == "system":
                    self._radio_system.setChecked(True)
                else:
                    self._radio_user.setChecked(True)
            else:
                self._install_status_label.setVisible(False)
                self._uninstall_btn.setVisible(False)
                self._install_btn.setText("Install Font Family")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Failed to check font installation status: %s", exc)

    def _on_size_changed(self, value: int) -> None:
        self._size_val_label.setText(f"{value} pt")
        self._preview.set_font_size(float(value))

    def _on_weight_changed(self, text: str) -> None:
        weight_val = WEIGHT_MAP.get(text, 400)
        self._preview.set_font_weight(weight_val)
        self._trigger_subset_load()

    def _on_italic_toggled(self, checked: bool) -> None:
        self._preview.set_italic(checked)
        self._trigger_subset_load()

    def _on_preset_selected(self, preset_name: str) -> None:
        if preset_name in SAMPLE_PRESETS:
            self._sample_editor.setPlainText(SAMPLE_PRESETS[preset_name])

    def _on_sample_text_changed(self) -> None:
        text = self._sample_editor.toPlainText().strip()
        self._preview.set_sample_text(text if text else get_config().default_sample_text)
        self._trigger_subset_load()

    def _on_nerd_switch_requested(self, slug: str, variant: str) -> None:
        self.nerd_switch_requested.emit(slug, variant)

    def _on_install_clicked(self) -> None:
        if not self._font or self._is_busy:
            return

        scope = "User" if self._radio_user.isChecked() else "System"
        variant_filter = self.nerd_badge.get_selected_variant() if self.nerd_badge.isVisible() else "Standard"

        self.install_requested.emit(self._font, scope, variant_filter)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.install_font_async(scope=scope, variant_filter=variant_filter))
        except RuntimeError:
            pass

    def _on_uninstall_clicked(self) -> None:
        if not self._font or self._is_busy:
            return

        scope = "User" if self._radio_user.isChecked() else "System"
        self.uninstall_requested.emit(self._font, scope)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.uninstall_font_async(scope=scope))
        except RuntimeError:
            pass

    async def install_font_async(self, scope: str = "User", variant_filter: str | None = None) -> InstallResult:
        """Download and install the active font family."""
        if not self._font:
            return InstallResult(
                success=False,
                font_id="",
                family_name="",
                errors=["No font selected"],
            )

        font = self._font
        self._is_busy = True
        self._install_btn.setEnabled(False)
        self._uninstall_btn.setEnabled(False)
        self._install_btn.setText("⏳ Downloading & Installing...")
        self._feedback_label.setVisible(False)

        temp_dir = Path(tempfile.mkdtemp(prefix=f"metaglyph_dl_{font.id}_"))

        try:
            # 1. Download font files
            if font.primary_provider == "nerd_fonts":
                nerd_prov = self.provider_manager.get_provider("nerd_fonts")
                downloaded_files = await nerd_prov.download_font_family(
                    font, temp_dir, variant_filter=variant_filter
                )
            else:
                downloaded_files = await self.provider_manager.download_font_family(font, temp_dir)

            if not downloaded_files:
                raise ValueError("No font files could be downloaded from provider")

            # 2. Dispatch to appropriate installer
            if scope.lower() == "system":
                result = await self.system_installer.install_font(font, downloaded_files)
            else:
                result = await self.user_installer.install_font(font, downloaded_files)

            # 3. Present UI feedback
            if result.success:
                self._feedback_label.setObjectName("installFeedbackSuccess")
                self._feedback_label.setStyleSheet(
                    "background-color: #064e3b; color: #a7f3d0; border: 1px solid #059669; border-radius: 6px; padding: 8px;"
                )
                self._feedback_label.setText(f"✓ {result.message}")
                self._feedback_label.setVisible(True)
                await self._check_installed_async()
            else:
                err = "; ".join(result.errors) if result.errors else result.message
                self._feedback_label.setObjectName("installFeedbackError")
                self._feedback_label.setStyleSheet(
                    "background-color: #450a0a; color: #fecaca; border: 1px solid #dc2626; border-radius: 6px; padding: 8px;"
                )
                self._feedback_label.setText(f"Installation failed: {err}")
                self._feedback_label.setVisible(True)

            self.install_completed.emit(result)
            return result

        except Exception as exc:
            logger.error("Error during font installation: %s", exc)
            self._feedback_label.setObjectName("installFeedbackError")
            self._feedback_label.setStyleSheet(
                "background-color: #450a0a; color: #fecaca; border: 1px solid #dc2626; border-radius: 6px; padding: 8px;"
            )
            self._feedback_label.setText(f"Installation error: {exc}")
            self._feedback_label.setVisible(True)

            fail_res = InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=scope,
                errors=[str(exc)],
                message=str(exc),
            )
            self.install_completed.emit(fail_res)
            return fail_res

        finally:
            self._is_busy = False
            self._install_btn.setEnabled(True)
            self._uninstall_btn.setEnabled(True)
            if self._installed_record:
                self._install_btn.setText("Reinstall Font Family")
            else:
                self._install_btn.setText("Install Font Family")
            # Clean up temp download directory
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    async def uninstall_font_async(self, scope: str = "User") -> InstallResult:
        """Uninstall the active font family."""
        if not self._font:
            return InstallResult(
                success=False,
                font_id="",
                family_name="",
                errors=["No font selected"],
            )

        font = self._font
        self._is_busy = True
        self._install_btn.setEnabled(False)
        self._uninstall_btn.setEnabled(False)
        self._uninstall_btn.setText("⏳ Uninstalling...")
        self._feedback_label.setVisible(False)

        try:
            # Look up file paths from installed record
            file_paths = []
            if self._installed_record:
                file_paths = [Path(p) for p in self._installed_record.file_paths]

            result = await self.uninstaller.uninstall_font(
                font_id=font.id,
                family_name=font.family_name,
                file_paths=file_paths,
                scope=scope,
            )

            if result.success:
                self._feedback_label.setObjectName("installFeedbackSuccess")
                self._feedback_label.setStyleSheet(
                    "background-color: #064e3b; color: #a7f3d0; border: 1px solid #059669; border-radius: 6px; padding: 8px;"
                )
                self._feedback_label.setText(f"✓ {result.message}")
                self._feedback_label.setVisible(True)
                await self._check_installed_async()
            else:
                err = "; ".join(result.errors) if result.errors else result.message
                self._feedback_label.setObjectName("installFeedbackError")
                self._feedback_label.setStyleSheet(
                    "background-color: #450a0a; color: #fecaca; border: 1px solid #dc2626; border-radius: 6px; padding: 8px;"
                )
                self._feedback_label.setText(f"Uninstall failed: {err}")
                self._feedback_label.setVisible(True)

            self.uninstall_completed.emit(result)
            return result

        except Exception as exc:
            logger.error("Error during font uninstallation: %s", exc)
            self._feedback_label.setObjectName("installFeedbackError")
            self._feedback_label.setStyleSheet(
                "background-color: #450a0a; color: #fecaca; border: 1px solid #dc2626; border-radius: 6px; padding: 8px;"
            )
            self._feedback_label.setText(f"Uninstall error: {exc}")
            self._feedback_label.setVisible(True)

            fail_res = InstallResult(
                success=False,
                font_id=font.id,
                family_name=font.family_name,
                scope=scope,
                errors=[str(exc)],
                message=str(exc),
            )
            self.uninstall_completed.emit(fail_res)
            return fail_res

        finally:
            self._is_busy = False
            self._install_btn.setEnabled(True)
            self._uninstall_btn.setEnabled(True)
            self._uninstall_btn.setText("Uninstall Font Family")
