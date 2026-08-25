"""Vector icon generator providing crisp, resolution-independent QIcons for Metaglyph."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Modern Lucide/SVG icon path data (viewBox 0 0 24 24, stroke-width 2, round joins)
ICON_SVGS: dict[str, str] = {
    # Navigation and UI controls
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

    # Category specific icons
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
        <path d="M6 4v16"></path>
        <path d="M18 4v16"></path>
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
    # Clean modern geometric single-story sans-serif lowercase 'a'
    "sans-a": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color}">
        <path d="M12 5C8.13 5 5 8.13 5 12s3.13 7 7 7c1.74 0 3.34-.63 4.6-1.68V19h2.4V7.5h-2.4v1.18C15.34 7.63 13.74 7 12 7zm0 2.4c2.54 0 4.6 2.06 4.6 4.6s-2.06 4.6-4.6 4.6-4.6-2.06-4.6-4.6 2.06-4.6 4.6-4.6z"></path>
    </svg>""",
    # Classical two-story serif lowercase 'a' (Bodoni / Times style with top teardrop terminal and foot serif)
    "serif-a": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color}">
        <path d="M17.5 4.5c-1.3-.7-3.1-1-4.8-1-4.2 0-7.2 2.2-7.2 5.5 0 2.2 1.5 3.9 3.8 4.5-3.5 1-5.8 2.9-5.8 5.8 0 3.3 3 5.7 7.5 5.7 5.1 0 8.3-2.8 8.3-6.8V7c0-1 .7-1.6 1.7-1.6V4.5h-3.5zm-2.5 13.1c0 2.6-2.3 4.4-5.2 4.4-2.8 0-4.6-1.4-4.6-3.4 0-2.3 2-3.5 5.6-4.1l4.2.7v2.4zm0-4.7l-3.5-.5c-1.8-.3-2.8-1.2-2.8-2.6 0-1.8 1.7-3.2 4.2-3.2 1.4 0 2.6.3 3.3.9v5.4z"></path>
    </svg>""",
    "terminal": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="4 17 10 11 4 5"></polyline>
        <line x1="12" y1="19" x2="20" y2="19"></line>
    </svg>""",
}


def render_svg_pixmap(name: str, color: str = "#94a3b8", size: int = 18) -> QPixmap:
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
    normal_color: str = "#94a3b8",
    active_color: str = "#818cf8",
    disabled_color: str = "#475569",
    hover_color: str = "#f8fafc",
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
