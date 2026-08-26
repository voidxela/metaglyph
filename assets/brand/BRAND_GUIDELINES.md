# MetaGlyph — Brand Identity & Asset Kit Guidelines

Welcome to the official **MetaGlyph** brand asset kit. This package contains the complete set of high-resolution raster, scalable vector, and platform-specific desktop application icons derived from the master design.

---

## 1. Brand Palette & Color Specifications

The MetaGlyph visual identity is built around sophisticated dark neutral/charcoal surfaces, crisp high-contrast typography, and rich electric violet / magenta purple accents.

| Swatch | Color Name | HEX | RGB | HSL | Primary Use |
| :--- | :--- | :--- | :--- | :--- | :--- |
| <img src="https://via.placeholder.com/20/121316/000000?text=+" width="20" height="20" /> | **Deep Charcoal** | `#121316` | `rgb(18, 19, 22)` | `hsl(225°, 10%, 8%)` | Dark Mode Root App Background |
| <img src="https://via.placeholder.com/20/18191E/000000?text=+" width="20" height="20" /> | **Dark Slate Surface** | `#18191E` | `rgb(24, 25, 30)` | `hsl(230°, 11%, 11%)` | Sidebar, Navigation, Card Bases |
| <img src="https://via.placeholder.com/20/1F2127/000000?text=+" width="20" height="20" /> | **Elevated Charcoal** | `#1F2127` | `rgb(31, 33, 39)` | `hsl(225°, 11%, 14%)` | Hover Surfaces, Input Fields, Toolbars |
| <img src="https://via.placeholder.com/20/333742/000000?text=+" width="20" height="20" /> | **Slate Border** | `#333742` | `rgb(51, 55, 66)` | `hsl(224°, 13%, 23%)` | Component Borders & Dividers |
| <img src="https://via.placeholder.com/20/771EBD/000000?text=+" width="20" height="20" /> | **Vibrant Brand Violet** | `#771EBD` | `rgb(119, 30, 189)` | `hsl(274°, 73%, 43%)` | Primary Actions, Focus Rings, Brand Highlights |
| <img src="https://via.placeholder.com/20/8D2CD6/000000?text=+" width="20" height="20" /> | **Electric Violet** | `#8D2CD6` | `rgb(141, 44, 214)` | `hsl(274°, 69%, 51%)` | Button Hovers, Active Navigation States |
| <img src="https://via.placeholder.com/20/E879F9/000000?text=+" width="20" height="20" /> | **Magenta Glow** | `#E879F9` | `rgb(232, 121, 249)` | `hsl(292°, 91%, 73%)` | Nerd Font Badges, Accent Highlights |
| <img src="https://via.placeholder.com/20/E9E9E9/000000?text=+" width="20" height="20" /> | **Chrome Sphere Platinum** | `#E9E9E9` | `rgb(233, 233, 233)` | `hsl(0°, 0%, 91%)` | Metallic Sphere Base Tone |
| <img src="https://via.placeholder.com/20/CBD5E1/000000?text=+" width="20" height="20" /> | **Slate Light** | `#CBD5E1` | `rgb(203, 213, 225)` | `hsl(213°, 27%, 84%)` | Secondary Typography, Subtitles, Chips |
| <img src="https://via.placeholder.com/20/FFFFFF/000000?text=+" width="20" height="20" /> | **Pure White** | `#FFFFFF` | `rgb(255, 255, 255)` | `hsl(0°, 0%, 100%)` | Primary Text, Specular Highlights |

---

## 2. Brand Asset Inventory

### 🎯 Primary Standalone Assets (Root Directory)
- **`metaglyph-mark.png`** / **`metaglyph-mark.svg`**: Standalone 2048×2048 master icon/symbol on transparent background.
- **`metaglyph-wordmark-dark.png`** / **`metaglyph-wordmark-dark.svg`**: Standalone geometric typography in Midnight Indigo (`#290649`) for light backgrounds.
- **`metaglyph-wordmark-light.png`** / **`metaglyph-wordmark-light.svg`**: Standalone geometric typography in Pure White (`#FFFFFF`) for dark backgrounds / dark mode.
- **`metaglyph-lockup-horizontal-dark.png`** / **`.svg`**: Horizontal lockup for light themes (3D Mark + Dark Wordmark).
- **`metaglyph-lockup-horizontal-light.png`** / **`.svg`**: Horizontal lockup for dark themes (3D Mark + White Wordmark).
- **`metaglyph-lockup-vertical-dark.png`** / **`.svg`**: Vertical stacked lockup for light themes.
- **`metaglyph-lockup-vertical-light.png`** / **`.svg`**: Vertical stacked lockup for dark themes.
- **`metaglyph-master-transparent.png`**: Original full-canvas lockup with background cleanly removed.

---

### 💻 Desktop Application Icons

#### 1. Windows (`.ico`)
- **`metaglyph.ico`** (and `desktop-icons/windows/metaglyph-app.ico`): Multi-resolution Windows application icon containing 16×16, 24×24, 32×32, 48×48, 64×64, 128×128, and 256×256 32-bit RGBA frames.
- **`desktop-icons/windows/metaglyph-mark.ico`**: Multi-resolution frameless mark icon.

#### 2. macOS (`.icns` & `.iconset`)
- **`metaglyph.icns`** (and `desktop-icons/macos/metaglyph.icns`): Modern Apple HIG squircle container icon with midnight gradient backdrop and subtle drop shadow. Contains all 10 Apple standard resolutions (16x16 to 512x512 @2x retina / 1024x1024).
- **`desktop-icons/macos/metaglyph-frameless.icns`**: Frameless floating 3D mark icon.
- **`desktop-icons/macos/metaglyph.iconset/`**: Standard Apple iconset source folder ready for Xcode or `iconutil`.

#### 3. Linux (Freedesktop Hicolor Icon Theme)
- **`desktop-icons/linux/hicolor/{size}/apps/metaglyph.png`**: Standard freedesktop icon hierarchy for 16×16, 24×24, 32×32, 48×48, 64×64, 96×96, 128×128, 256×256, 512×512.
- **`desktop-icons/linux/hicolor/scalable/apps/metaglyph.svg`**: Scalable vector icon.
- **`desktop-icons/linux/metaglyph.desktop`**: Freedesktop application entry definition.

#### 4. Web & Favicons
- **`favicon.ico`** (16×16, 32×32, 48×48)
- **`favicon-16x16.png`**, **`favicon-32x32.png`**, **`favicon-48x48.png`**
- **`apple-touch-icon.png`** (180×180)
- **`web-favicons/android-chrome-192x192.png`**, **`web-favicons/android-chrome-512x512.png`**
- **`web-favicons/site.webmanifest`**

---

## 3. Desktop Application Integration Guide

### 🦀 Tauri (`tauri.conf.json`)
```json
{
  "tauri": {
    "bundle": {
      "icon": [
        "desktop-icons/linux/hicolor/32x32/apps/metaglyph.png",
        "desktop-icons/linux/hicolor/128x128/apps/metaglyph.png",
        "desktop-icons/linux/hicolor/256x256/apps/metaglyph.png",
        "desktop-icons/linux/hicolor/512x512/apps/metaglyph.png",
        "desktop-icons/windows/metaglyph-app.ico",
        "desktop-icons/macos/metaglyph.icns"
      ]
    }
  }
}
```

### ⚡ Electron (`forge.config.js` / `electron-builder`)
```javascript
// electron-builder configuration
module.exports = {
  appId: "com.metaglyph.desktop",
  productName: "MetaGlyph",
  win: {
    icon: "metaglyph.ico"
  },
  mac: {
    icon: "metaglyph.icns"
  },
  linux: {
    icon: "desktop-icons/linux/hicolor"
  }
};
```

### 🐍 PyQt6 / PySide6 / Tkinter
```python
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow

app = QApplication([])
window = QMainWindow()
window.setWindowIcon(QIcon("metaglyph-mark.png")) # or metaglyph.ico on Windows
```

---

## 4. Design & Spacing Rules

- **Clear Space**: Maintain a minimum clear space equal to 25% of the mark's height ($0.25H$) around all lockups and standalone marks.
- **Minimum Size**:
  - Standalone Mark: Minimum 16×16 px for digital icons, 8mm for print.
  - Horizontal Lockup: Minimum 120 px width digital, 25mm print.
  - Vertical Lockup: Minimum 80 px width digital, 20mm print.
- **Background Contrast**:
  - On light surfaces (White, Light Gray `#F0F0F5`): Use `*-dark` assets (`#290649` text).
  - On dark surfaces (Black, Midnight `#120323`, Dark Gray): Use `*-light` assets (`#FFFFFF` text).
