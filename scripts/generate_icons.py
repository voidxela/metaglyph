#!/usr/bin/env python3
"""Generate crisp vector SVG and rendered PNG icons for Metaglyph."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

SVG_ICON_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e1b4b"/>
    </linearGradient>
    <linearGradient id="glyphGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="50%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#c084fc"/>
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="10" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <!-- Background rounded rectangle -->
  <rect width="512" height="512" rx="112" fill="url(#bgGrad)"/>
  <rect width="508" height="508" x="2" y="2" rx="110" fill="none" stroke="#334155" stroke-width="4" stroke-opacity="0.6"/>

  <!-- Subtle grid typography guidelines -->
  <line x1="96" y1="136" x2="416" y2="136" stroke="#334155" stroke-width="2" stroke-dasharray="8 8" opacity="0.4"/>
  <line x1="96" y1="256" x2="416" y2="256" stroke="#334155" stroke-width="2" stroke-dasharray="8 8" opacity="0.4"/>
  <line x1="96" y1="376" x2="416" y2="376" stroke="#334155" stroke-width="2" stroke-dasharray="8 8" opacity="0.4"/>

  <!-- Stylized Metaglyph 'M' Character with Bezier curves -->
  <path d="M 128 376 L 128 148 L 256 276 L 384 148 L 384 376" 
        fill="none" 
        stroke="url(#glyphGrad)" 
        stroke-width="44" 
        stroke-linecap="round" 
        stroke-linejoin="round"
        filter="url(#glow)"/>

  <!-- Vector Anchor Nodes (Font design theme) -->
  <circle cx="128" cy="148" r="14" fill="#38bdf8" stroke="#0f172a" stroke-width="4"/>
  <circle cx="256" cy="276" r="16" fill="#818cf8" stroke="#0f172a" stroke-width="4"/>
  <circle cx="384" cy="148" r="14" fill="#c084fc" stroke="#0f172a" stroke-width="4"/>
  <circle cx="128" cy="376" r="14" fill="#38bdf8" stroke="#0f172a" stroke-width="4"/>
  <circle cx="384" cy="376" r="14" fill="#c084fc" stroke="#0f172a" stroke-width="4"/>

  <!-- Sparkle Accent in top right -->
  <path d="M 416 88 L 421 104 L 437 109 L 421 114 L 416 130 L 411 114 L 395 109 L 411 104 Z" fill="#38bdf8"/>
</svg>
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    icons_dir = repo_root / "assets" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    svg_file = icons_dir / "metaglyph.svg"
    svg_file.write_text(SVG_ICON_CONTENT, encoding="utf-8")
    print(f"Wrote SVG icon to {svg_file}")

    # Initialize headless Qt Application if needed
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _ = QApplication.instance() or QApplication([])

    renderer = QSvgRenderer(QByteArray(SVG_ICON_CONTENT.encode("utf-8")))

    for size in (64, 128, 256, 512):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        renderer.render(painter)
        painter.end()

        target_png = icons_dir / f"metaglyph-{size}.png"
        pixmap.save(str(target_png))
        print(f"Generated {target_png}")
        if size == 256:
            default_png = icons_dir / "metaglyph.png"
            pixmap.save(str(default_png))
            print(f"Generated default PNG {default_png}")


if __name__ == "__main__":
    main()
