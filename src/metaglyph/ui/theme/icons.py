"""Vector icon generator providing crisp, resolution-independent QIcons for Metaglyph.

All icons sourced from standard open-source icon sets (Lucide Icons) to ensure
consistent 24x24 viewBox, stroke geometry, and aesthetic harmony.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Standard Lucide icon SVGs (viewBox 0 0 24 24, stroke-width 2, stroke-linecap/linejoin round)
ICON_SVGS: dict[str, str] = {
    # Navigation & Actions
    "compass": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" fill="{color}" fill-opacity="0.25"></polygon>
    </svg>""",
    "search": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="8"></circle>
        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </svg>""",
    "folder-check": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"></path>
        <polyline points="9 13 11 15 15 11"></polyline>
    </svg>""",
    "refresh-cw": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path>
        <path d="M21 3v5h-5"></path>
        <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path>
        <path d="M8 16H3v5"></path>
    </svg>""",
    "trash-2": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 6h18"></path>
        <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path>
        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path>
        <line x1="10" y1="11" x2="10" y2="17"></line>
        <line x1="14" y1="11" x2="14" y2="17"></line>
    </svg>""",
    "download": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
        <polyline points="7 10 12 15 17 10"></polyline>
        <line x1="12" y1="15" x2="12" y2="3"></line>
    </svg>""",
    "check": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="20 6 9 17 4 12"></polyline>
    </svg>""",
    "x": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="18" y1="6" x2="6" y2="18"></line>
        <line x1="6" y1="6" x2="18" y2="18"></line>
    </svg>""",
    "chevron-down": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9"></polyline>
    </svg>""",
    "chevron-right": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="9 18 15 12 9 6"></polyline>
    </svg>""",
    "sparkles": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"></path>
    </svg>""",
    "star": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
    </svg>""",

    # Category Cards (Official Lucide icons)
    "layout": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2"></rect>
        <path d="M3 9h18"></path>
        <path d="M9 21V9"></path>
    </svg>""",
    "code": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="16 18 22 12 16 6"></polyline>
        <polyline points="8 6 2 12 8 18"></polyline>
    </svg>""",
    "heading": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 12h12"></path>
        <path d="M6 20V4"></path>
        <path d="M18 20V4"></path>
    </svg>""",
    "book-open": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
        <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
    </svg>""",
    "pen-tool": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m12 19 7-7 3 3-7 7-3-3z"></path>
        <path d="m18 13-1.5-7.5L2 2l3.5 14.5L13 18l5-5z"></path>
        <path d="m2 2 7.586 7.586"></path>
        <circle cx="11" cy="11" r="2"></circle>
    </svg>""",
    "case-lower": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M10 9v7"></path>
        <path d="M14 6v10"></path>
        <circle cx="17.5" cy="12.5" r="3.5"></circle>
        <circle cx="6.5" cy="12.5" r="3.5"></circle>
    </svg>""",
    "type": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 4v16"></path>
        <path d="M4 7V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v2"></path>
        <path d="M9 20h6"></path>
    </svg>""",
    "terminal": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="4 17 10 11 4 5"></polyline>
        <line x1="12" y1="19" x2="20" y2="19"></line>
    </svg>""",
}


from pathlib import Path


def get_brand_asset_path(asset_name: str) -> Path:
    """Resolve path to a brand asset, checking package assets, repo assets, and system locations."""
    # 1. Package bundled assets (src/metaglyph/ui/assets)
    pkg_assets = Path(__file__).resolve().parents[1] / "assets" / asset_name
    if pkg_assets.exists():
        return pkg_assets

    # 2. Repo assets (assets/brand or assets/icons)
    repo_root = Path(__file__).resolve().parents[4]
    for candidate in (
        repo_root / "assets" / "brand" / asset_name,
        repo_root / "assets" / "icons" / asset_name,
        repo_root / "assets" / asset_name,
    ):
        if candidate.exists():
            return candidate

    return pkg_assets


def get_app_icon() -> QIcon:
    """Create a high-fidelity multi-resolution application icon for Metaglyph."""
    icon = QIcon()
    ico_path = get_brand_asset_path("metaglyph.ico")
    if ico_path.exists():
        icon = QIcon(str(ico_path))

    # Add specific size PNG frames if available
    for size in (16, 24, 32, 48, 64, 96, 128, 256, 512):
        png_name = f"metaglyph-{size}.png"
        png_path = get_brand_asset_path(png_name)
        if png_path.exists():
            icon.addFile(str(png_path), QSize(size, size))

    if icon.isNull():
        mark_png = get_brand_asset_path("metaglyph-mark.png")
        if mark_png.exists():
            icon = QIcon(str(mark_png))

    return icon


def get_brand_lockup_pixmap(theme: str = "light", width: int = 172) -> QPixmap:
    """Render the official MetaGlyph horizontal brand lockup into a crisp QPixmap.

    Uses 'light' for dark surfaces (white wordmark + 3D mark) as specified by BRAND_GUIDELINES.md.
    Uses 'dark' for light surfaces (midnight indigo wordmark + 3D mark).
    """
    # 1. Try pre-rendered high-res PNG
    asset_name = f"metaglyph-lockup-horizontal-{theme}.png"
    asset_path = get_brand_asset_path(asset_name)
    if not asset_path.exists():
        asset_name = f"metaglyph-horizontal-{theme}-1000w.png"
        asset_path = get_brand_asset_path(asset_name)

    if asset_path.exists():
        source_px = QPixmap(str(asset_path))
        if not source_px.isNull():
            target_w = width * 2
            target_h = int(target_w * source_px.height() / source_px.width())
            scaled = source_px.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(2.0)
            return scaled

    # 2. Try SVG renderer
    svg_name = f"metaglyph-lockup-horizontal-{theme}.svg"
    svg_path = get_brand_asset_path(svg_name)
    if svg_path.exists():
        renderer = QSvgRenderer(str(svg_path))
        target_w = width * 2
        target_h = int(target_w * 680 / 2836)
        pixmap = QPixmap(target_w, target_h)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer.render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(2.0)
        return pixmap

    empty = QPixmap(width, int(width * 680 / 2836))
    empty.fill(Qt.GlobalColor.transparent)
    return empty


def get_brand_wordmark_pixmap(theme: str = "light", width: int = 160) -> QPixmap:
    """Render the official MetaGlyph standalone wordmark into a crisp QPixmap."""
    asset_name = f"metaglyph-wordmark-{theme}.png"
    asset_path = get_brand_asset_path(asset_name)
    if asset_path.exists():
        source_px = QPixmap(str(asset_path))
        if not source_px.isNull():
            target_w = width * 2
            target_h = int(target_w * source_px.height() / source_px.width())
            scaled = source_px.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(2.0)
            return scaled
    empty = QPixmap(width, int(width * 209 / 1842))
    empty.fill(Qt.GlobalColor.transparent)
    return empty


def get_brand_mark_pixmap(size: int = 64) -> QPixmap:
    """Render the standalone 3D MetaGlyph mark icon into a crisp QPixmap."""
    asset_name = "metaglyph-mark.png"
    asset_path = get_brand_asset_path(asset_name)
    if asset_path.exists():
        source_px = QPixmap(str(asset_path))
        if not source_px.isNull():
            target_size = size * 2
            scaled = source_px.scaled(
                target_size,
                target_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(2.0)
            return scaled
    empty = QPixmap(size, size)
    empty.fill(Qt.GlobalColor.transparent)
    return empty


def render_svg_pixmap(name: str, color: str = "#c4b5d4", size: int = 18) -> QPixmap:
    """Render a named SVG icon into a crisp transparent QPixmap."""
    svg_template = ICON_SVGS.get(name)
    if not svg_template:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap

    svg_content = svg_template.format(color=color)
    svg_bytes = QByteArray(svg_content.encode("utf-8"))

    renderer = QSvgRenderer(svg_bytes)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()

    return pixmap


def create_themed_icon(
    name: str,
    normal_color: str = "#c4b5d4",
    active_color: str = "#e879f9",
    disabled_color: str = "#58446e",
    hover_color: str = "#ffffff",
    size: int = 18,
) -> QIcon:
    """Create a multi-state QIcon with support for Normal, Active/Checked, Hover, and Disabled states."""
    icon = QIcon()

    # Normal / Off
    normal_px = render_svg_pixmap(name, color=normal_color, size=size)
    icon.addPixmap(normal_px, QIcon.Mode.Normal, QIcon.State.Off)

    # Active / Selected / On (Checked state)
    active_px = render_svg_pixmap(name, color=active_color, size=size)
    icon.addPixmap(active_px, QIcon.Mode.Normal, QIcon.State.On)

    # Hover / Active Mode
    hover_px = render_svg_pixmap(name, color=hover_color, size=size)
    icon.addPixmap(hover_px, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(active_px, QIcon.Mode.Active, QIcon.State.On)

    # Disabled
    disabled_px = render_svg_pixmap(name, color=disabled_color, size=size)
    icon.addPixmap(disabled_px, QIcon.Mode.Disabled, QIcon.State.Off)
    icon.addPixmap(disabled_px, QIcon.Mode.Disabled, QIcon.State.On)

    return icon
