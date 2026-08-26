#!/usr/bin/env python3
"""
MetaGlyph Brand Kit Asset Generator
Generates full set of brand assets for desktop applications, web, and marketing.
"""

import os
import re
import sys
import io
import json
import base64
import subprocess
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import cairosvg
import icnsutil

ROOT_DIR = Path("/home/alex/Develop/metaglyph-assets")

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def step1_extract_master_and_mark():
    print("=== Step 1: Extracting Master Assets and High-Precision Alpha Matting ===")
    master_path = ROOT_DIR / "logo-master.jpeg"
    img_bgr = cv2.imread(str(master_path))
    h, w, _ = img_bgr.shape
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    img_f = img_rgb.astype(np.float32)

    # 1. Fit smooth background model
    mask_bg = np.ones((h, w), dtype=bool)
    mask_bg[250:950, 1000:1800] = False
    mask_bg[1000:1300, 600:2200] = False

    y_coords, x_coords = np.where(mask_bg)
    sample_rgb = img_f[y_coords, x_coords]

    nx = (x_coords - w/2) / (w/2)
    ny = (y_coords - h/2) / (h/2)
    X = np.stack([np.ones_like(nx), nx, ny, nx**2, ny**2, nx*ny, nx**3, ny**3], axis=1)

    grid_y, grid_x = np.indices((h, w))
    gnx = (grid_x - w/2) / (w/2)
    gny = (grid_y - h/2) / (h/2)
    grid_X = np.stack([np.ones_like(gnx), gnx, gny, gnx**2, gny**2, gnx*gny, gnx**3, gny**3], axis=-1)

    bg_model = np.zeros((h, w, 3), dtype=np.float32)
    for ch in range(3):
        coeffs, _, _, _ = np.linalg.lstsq(X, sample_rgb[:, ch], rcond=None)
        bg_model[:, :, ch] = np.tensordot(grid_X, coeffs, axes=([-1], [0]))

    diff = np.sqrt(np.sum((img_f - bg_model)**2, axis=2))

    # 2. Base Alpha from ISNet
    isnet_png = Image.open(ROOT_DIR / "test_isnet.png")
    alpha = np.array(isnet_png)[:, :, 3].astype(np.float32) / 255.0

    # 3. Clean alpha for Symbol ROI (rows 280:910, cols 1050:1770)
    sym_mask = np.zeros((h, w), dtype=bool)
    sym_mask[280:910, 1050:1770] = True

    # Exact Sphere Protection at (1409, 679) radius 52.0
    y_grid, x_grid = np.ogrid[:h, :w]
    sphere_dist = np.sqrt((x_grid - 1409)**2 + (y_grid - 679)**2)
    sphere_mask = sphere_dist <= 52.5

    sym_bg_clear = sym_mask & (~sphere_mask)
    alpha[sym_bg_clear & (diff < 5.0)] = 0.0
    alpha[sym_bg_clear & (alpha < 0.35) & (diff < 16.0)] = 0.0

    # Sphere alpha
    alpha[sphere_dist <= 51.5] = 1.0
    sphere_anti_alias = (sphere_dist > 51.5) & (sphere_dist <= 53.0)
    alpha[sphere_anti_alias] = np.maximum(alpha[sphere_anti_alias], (53.0 - sphere_dist[sphere_anti_alias]) / 1.5)

    # 4. Color Unmixing
    unmixed = np.zeros_like(img_f)
    alpha_3d = np.dstack([alpha, alpha, alpha])
    pos = alpha > 0.01

    unmixed[pos] = (img_f[pos] - (1.0 - alpha_3d[pos]) * bg_model[pos]) / np.maximum(alpha_3d[pos], 0.05)
    unmixed = np.clip(unmixed, 0, 255)

    # Tight crop of standalone mark
    sym_y, sym_x = np.where((alpha > 0.05) & sym_mask)
    y_min, y_max, x_min, x_max = sym_y.min(), sym_y.max(), sym_x.min(), sym_x.max()
    sym_w = x_max - x_min + 1
    sym_h = y_max - y_min + 1

    sym_rgba = np.dstack([
        unmixed[y_min:y_max+1, x_min:x_max+1].astype(np.uint8),
        (alpha[y_min:y_max+1, x_min:x_max+1] * 255).astype(np.uint8)
    ])
    isolated_mark = Image.fromarray(sym_rgba)

    # Square master 2048x2048 mark with 82% fill
    max_dim = max(sym_w, sym_h)
    target_canvas = int(max_dim / 0.82)
    sq_canvas = Image.new('RGBA', (target_canvas, target_canvas), (0, 0, 0, 0))
    offset_x = (target_canvas - sym_w) // 2
    offset_y = (target_canvas - sym_h) // 2
    sq_canvas.paste(isolated_mark, (offset_x, offset_y))
    master_mark_2048 = sq_canvas.resize((2048, 2048), Image.Resampling.LANCZOS)

    return isolated_mark, master_mark_2048, unmixed, alpha, (offset_x, offset_y, sym_w, sym_h)

def step2_extract_vector_wordmark():
    print("=== Step 2: Extracting Vector Typography (Wordmark) ===")
    img = cv2.imread(str(ROOT_DIR / "logo-master.jpeg"))
    text_roi = img[1020:1260, 650:2180]
    gray = cv2.cvtColor(text_roi, cv2.COLOR_BGR2GRAY)

    bg_val = np.median(gray[:10, :])
    norm = np.clip((bg_val - gray.astype(np.float32)) / (bg_val - 40.0), 0, 1)

    # 4x supersampling for high-precision potrace vectorization
    high_res = cv2.resize(norm, (norm.shape[1]*4, norm.shape[0]*4), interpolation=cv2.INTER_LANCZOS4)
    binary = (high_res > 0.45).astype(np.uint8)

    h_pbm, w_pbm = binary.shape
    pbm_path = ROOT_DIR / "temp_text_letters.pbm"
    with open(pbm_path, 'wb') as f:
        f.write(f'P4\n{w_pbm} {h_pbm}\n'.encode('ascii'))
        f.write(np.packbits(binary, axis=1).tobytes())

    svg_out_path = ROOT_DIR / "temp_text_letters.svg"
    subprocess.run([
        'potrace', str(pbm_path), '-s', '-o', str(svg_out_path),
        '--opttolerance', '0.2', '--alphamax', '1.0'
    ], check=True)

    with open(svg_out_path, 'r') as f:
        raw_svg = f.read()

    pbm_path.unlink(missing_ok=True)
    svg_out_path.unlink(missing_ok=True)

    paths = re.findall(r'd=\"([^\"]+)\"', raw_svg)
    vb_match = re.search(r'viewBox=\"([^\"]+)\"', raw_svg)
    vb = vb_match.group(1) if vb_match else '0 0 6120 960'

    return paths, vb

def make_wordmark_svg_string(paths, vb, fill_color):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="100%" height="100%">
  <g transform="translate(0.000000,960.000000) scale(0.100000,-0.100000)" fill="{fill_color}" stroke="none">
    {' '.join(f'<path d="{p}"/>' for p in paths)}
  </g>
</svg>'''

def render_wordmark(paths, vb, fill_color, target_height):
    svg_content = make_wordmark_svg_string(paths, vb, fill_color)
    png_bytes = cairosvg.svg2png(bytestring=svg_content.encode('utf-8'), output_height=target_height)
    wm_img = Image.open(io.BytesIO(png_bytes))
    arr = np.array(wm_img)
    y_idx, x_idx = np.where(arr[:, :, 3] > 10)
    return wm_img.crop((x_idx.min(), y_idx.min(), x_idx.max()+1, y_idx.max()+1))

def make_macos_container_app_icon(master_mark_2048, size=1024):
    scale = 4
    s_full = size * scale
    sq_size = int(size * 0.824)
    pad = (size - sq_size) // 2
    s_sq = sq_size * scale
    s_pad = pad * scale

    mask = Image.new('L', (s_full, s_full), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(s_sq * 0.2237)
    draw.rounded_rectangle([s_pad, s_pad, s_pad + s_sq, s_pad + s_sq], radius=radius, fill=255)
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)

    shadow_mask = Image.new('L', (size, size), 0)
    sdraw = ImageDraw.Draw(shadow_mask)
    sdraw.rounded_rectangle([pad, pad + 14, pad + sq_size, pad + sq_size + 14], radius=int(sq_size * 0.2237), fill=130)
    shadow = shadow_mask.filter(ImageFilter.GaussianBlur(18))

    gradient = np.zeros((size, size, 4), dtype=np.uint8)
    for y in range(size):
        r_val = y / size
        gradient[y, :, 0] = int(36 * (1 - r_val) + 16 * r_val)
        gradient[y, :, 1] = int(8 * (1 - r_val) + 2 * r_val)
        gradient[y, :, 2] = int(68 * (1 - r_val) + 32 * r_val)
        gradient[y, :, 3] = 255
    grad_img = Image.fromarray(gradient)

    border_mask = Image.new('L', (s_full, s_full), 0)
    bdraw = ImageDraw.Draw(border_mask)
    bdraw.rounded_rectangle([s_pad, s_pad, s_pad + s_sq, s_pad + s_sq], radius=radius, outline=255, width=scale*2)
    border = border_mask.resize((size, size), Image.Resampling.LANCZOS)

    container = Image.new('RGBA', (size, size), (0,0,0,0))
    shadow_layer = Image.new('RGBA', (size, size), (0,0,0,0))
    shadow_layer.paste((0,0,0,85), (0,0), shadow)
    container = Image.alpha_composite(container, shadow_layer)
    container.paste(grad_img, (0,0), mask)

    highlight = Image.new('RGBA', (size, size), (255, 255, 255, 40))
    container.paste(highlight, (0,0), border)

    mark_size = int(sq_size * 0.74)
    mark_scaled = master_mark_2048.resize((mark_size, mark_size), Image.Resampling.LANCZOS)
    
    mark_shadow_layer = Image.new('RGBA', (size, size), (0,0,0,0))
    m_alpha = mark_scaled.split()[3].filter(ImageFilter.GaussianBlur(10))
    m_shadow_color = Image.new('RGBA', (mark_size, mark_size), (0,0,0,150))
    
    pos_x = (size - mark_size) // 2
    pos_y = (size - mark_size) // 2
    mark_shadow_layer.paste(m_shadow_color, (pos_x, pos_y + 6), m_alpha)

    app_icon = Image.alpha_composite(container, mark_shadow_layer)
    app_icon.paste(mark_scaled, (pos_x, pos_y), mark_scaled)
    return app_icon

def make_frameless_app_icon(master_mark_2048, size=1024):
    icon_canvas = Image.new('RGBA', (size, size), (0,0,0,0))
    mark_size = int(size * 0.88)
    mark_scaled = master_mark_2048.resize((mark_size, mark_size), Image.Resampling.LANCZOS)
    
    shadow_layer = Image.new('RGBA', (size, size), (0,0,0,0))
    m_alpha = mark_scaled.split()[3].filter(ImageFilter.GaussianBlur(12))
    m_shadow_color = Image.new('RGBA', (mark_size, mark_size), (0,0,0,130))
    
    pos_x = (size - mark_size) // 2
    pos_y = (size - mark_size) // 2
    shadow_layer.paste(m_shadow_color, (pos_x, pos_y + 8), m_alpha)
    
    icon_canvas = Image.alpha_composite(icon_canvas, shadow_layer)
    icon_canvas.paste(mark_scaled, (pos_x, pos_y), mark_scaled)
    return icon_canvas

def main():
    print("Starting full brand kit build for MetaGlyph...")
    
    dirs = {
        'root': ROOT_DIR,
        'logo_mark': ROOT_DIR / "logo-mark",
        'wordmark': ROOT_DIR / "wordmark",
        'lockups_h': ROOT_DIR / "lockups" / "horizontal",
        'lockups_v': ROOT_DIR / "lockups" / "vertical",
        'icons_win': ROOT_DIR / "desktop-icons" / "windows",
        'icons_mac': ROOT_DIR / "desktop-icons" / "macos",
        'icons_mac_set': ROOT_DIR / "desktop-icons" / "macos" / "metaglyph.iconset",
        'icons_linux': ROOT_DIR / "desktop-icons" / "linux",
        'web': ROOT_DIR / "web-favicons",
    }
    for d in dirs.values():
        ensure_dir(d)

    isolated_mark, master_mark_2048, unmixed, alpha, (offset_x, offset_y, sym_w, sym_h) = step1_extract_master_and_mark()
    paths, vb = step2_extract_vector_wordmark()

    print("=== Step 3: Generating Standalone Logo Mark Assets ===")
    master_mark_2048.save(dirs['root'] / "metaglyph-mark.png", "PNG")
    master_mark_2048.save(dirs['logo_mark'] / "metaglyph-mark-2048x2048.png", "PNG")
    isolated_mark.save(dirs['logo_mark'] / "metaglyph-mark-tight.png", "PNG")

    mark_sizes = [16, 24, 32, 48, 64, 96, 128, 256, 512, 1024, 2048]
    for s in mark_sizes:
        resized = master_mark_2048.resize((s, s), Image.Resampling.LANCZOS)
        resized.save(dirs['logo_mark'] / f"metaglyph-mark-{s}x{s}.png", "PNG")
        if s in [256, 512, 1024, 2048]:
            resized.save(dirs['logo_mark'] / f"metaglyph-mark-{s}x{s}.webp", "WEBP")

    with open(dirs['root'] / "metaglyph-mark.png", "rb") as f:
        mark_b64 = base64.b64encode(f.read()).decode('ascii')
    
    mark_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2048 2048" width="100%" height="100%">
  <image href="data:image/png;base64,{mark_b64}" width="2048" height="2048" preserveAspectRatio="xMidYMid meet"/>
</svg>'''
    with open(dirs['root'] / "metaglyph-mark.svg", "w") as f:
        f.write(mark_svg)
    with open(dirs['logo_mark'] / "metaglyph-mark.svg", "w") as f:
        f.write(mark_svg)

    m_alpha = master_mark_2048.split()[3]
    mono_white_mark = Image.new('RGBA', (2048, 2048), (255, 255, 255, 0))
    mono_white_mark.paste((255, 255, 255, 255), (0, 0), m_alpha)
    mono_white_mark.save(dirs['logo_mark'] / "metaglyph-mark-mono-white.png", "PNG")

    mono_black_mark = Image.new('RGBA', (2048, 2048), (0, 0, 0, 0))
    mono_black_mark.paste((0, 0, 0, 255), (0, 0), m_alpha)
    mono_black_mark.save(dirs['logo_mark'] / "metaglyph-mark-mono-black.png", "PNG")

    print("=== Step 4: Generating Standalone Wordmark Assets ===")
    color_schemes = [
        ('dark', '#290649'),
        ('light', '#FFFFFF'),
        ('violet', '#49107F'),
        ('black', '#000000')
    ]

    for name, hex_code in color_schemes:
        svg_content = make_wordmark_svg_string(paths, vb, hex_code)
        with open(dirs['wordmark'] / f"metaglyph-wordmark-{name}.svg", "w") as f:
            f.write(svg_content)
        if name in ['dark', 'light']:
            with open(dirs['root'] / f"metaglyph-wordmark-{name}.svg", "w") as f:
                f.write(svg_content)

        for w_target in [500, 1000, 2000, 4000]:
            h_target = int(w_target * (960 / 6120))
            png_bytes = cairosvg.svg2png(bytestring=svg_content.encode('utf-8'), output_width=w_target, output_height=h_target)
            wm_img = Image.open(io.BytesIO(png_bytes))
            arr = np.array(wm_img)
            y_i, x_i = np.where(arr[:, :, 3] > 5)
            wm_crop = wm_img.crop((x_i.min(), y_i.min(), x_i.max()+1, y_i.max()+1))
            wm_crop.save(dirs['wordmark'] / f"metaglyph-wordmark-{name}-{w_target}w.png", "PNG")
            if w_target == 2000 and name in ['dark', 'light']:
                wm_crop.save(dirs['root'] / f"metaglyph-wordmark-{name}.png", "PNG")

    print("=== Step 5: Generating Horizontal & Vertical Lockups ===")
    target_mark_h = 560
    scale_mark = target_mark_h / sym_h
    target_mark_w = int(sym_w * scale_mark)
    mark_resized = isolated_mark.resize((target_mark_w, target_mark_h), Image.Resampling.LANCZOS)

    wm_dark_base = render_wordmark(paths, vb, '#290649', 240)
    scale_wm = 210 / wm_dark_base.size[1]
    wm_w_scaled = int(wm_dark_base.size[0] * scale_wm)
    wm_h_scaled = 210

    gap_h = 160
    pad_x = 80
    pad_y = 60
    canvas_w = pad_x * 2 + target_mark_w + gap_h + wm_w_scaled
    canvas_h = pad_y * 2 + max(target_mark_h, wm_h_scaled)

    mark_y = pad_y + (max(target_mark_h, wm_h_scaled) - target_mark_h) // 2
    text_x = pad_x + target_mark_w + gap_h
    text_y = pad_y + (max(target_mark_h, wm_h_scaled) - wm_h_scaled) // 2

    h_variants = [
        ('dark', '#290649', isolated_mark),
        ('light', '#FFFFFF', isolated_mark),
        ('mono-black', '#000000', mono_black_mark.crop((offset_x, offset_y, offset_x+sym_w, offset_y+sym_h))),
        ('mono-white', '#FFFFFF', mono_white_mark.crop((offset_x, offset_y, offset_x+sym_w, offset_y+sym_h))),
    ]

    t_svg_paths = ' '.join(f'<path d="{p}"/>' for p in paths)

    for name, text_color, mark_src in h_variants:
        m_img = mark_src.resize((target_mark_w, target_mark_h), Image.Resampling.LANCZOS)
        t_img = render_wordmark(paths, vb, text_color, 240).resize((wm_w_scaled, wm_h_scaled), Image.Resampling.LANCZOS)
        
        lockup_img = Image.new('RGBA', (canvas_w, canvas_h), (0,0,0,0))
        lockup_img.paste(m_img, (pad_x, mark_y), m_img)
        lockup_img.paste(t_img, (text_x, text_y), t_img)
        
        lockup_img.save(dirs['lockups_h'] / f"metaglyph-horizontal-{name}.png", "PNG")
        lockup_img.resize((canvas_w // 2, canvas_h // 2), Image.Resampling.LANCZOS).save(dirs['lockups_h'] / f"metaglyph-horizontal-{name}-1000w.png", "PNG")
        
        if name in ['dark', 'light']:
            lockup_img.save(dirs['root'] / f"metaglyph-lockup-horizontal-{name}.png", "PNG")

        with io.BytesIO() as buf:
            m_img.save(buf, format='PNG')
            m_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        
        h_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {canvas_w} {canvas_h}" width="100%" height="100%">
  <image href="data:image/png;base64,{m_b64}" x="{pad_x}" y="{mark_y}" width="{target_mark_w}" height="{target_mark_h}"/>
  <g transform="translate({text_x},{text_y + wm_h_scaled}) scale(0.100000,-0.100000) scale({wm_w_scaled/6120.0 * 10},{wm_h_scaled/960.0 * 10})" fill="{text_color}" stroke="none">
    {t_svg_paths}
  </g>
</svg>'''
        with open(dirs['lockups_h'] / f"metaglyph-horizontal-{name}.svg", "w") as f:
            f.write(h_svg)
        if name in ['dark', 'light']:
            with open(dirs['root'] / f"metaglyph-lockup-horizontal-{name}.svg", "w") as f:
                f.write(h_svg)

    # Vertical Lockups
    target_vmark_w = 700
    scale_vmark = target_vmark_w / sym_w
    target_vmark_h = int(sym_h * scale_vmark)

    scale_vwm = 1100 / wm_dark_base.size[0]
    vwm_w = 1100
    vwm_h = int(wm_dark_base.size[1] * scale_vwm)

    gap_v = 110
    pad_vx = 80
    pad_vy = 80
    vcanvas_w = pad_vx * 2 + max(target_vmark_w, vwm_w)
    vcanvas_h = pad_vy * 2 + target_vmark_h + gap_v + vwm_h

    vmark_x = pad_vx + (max(target_vmark_w, vwm_w) - target_vmark_w) // 2
    vtext_x = pad_vx + (max(target_vmark_w, vwm_w) - vwm_w) // 2
    vtext_y = pad_vy + target_vmark_h + gap_v

    v_variants = [
        ('dark', '#290649', isolated_mark),
        ('light', '#FFFFFF', isolated_mark),
        ('mono-black', '#000000', mono_black_mark.crop((offset_x, offset_y, offset_x+sym_w, offset_y+sym_h))),
        ('mono-white', '#FFFFFF', mono_white_mark.crop((offset_x, offset_y, offset_x+sym_w, offset_y+sym_h))),
    ]

    for name, text_color, mark_src in v_variants:
        m_img = mark_src.resize((target_vmark_w, target_vmark_h), Image.Resampling.LANCZOS)
        t_img = render_wordmark(paths, vb, text_color, 300).resize((vwm_w, vwm_h), Image.Resampling.LANCZOS)
        
        vlockup_img = Image.new('RGBA', (vcanvas_w, vcanvas_h), (0,0,0,0))
        vlockup_img.paste(m_img, (vmark_x, pad_vy), m_img)
        vlockup_img.paste(t_img, (vtext_x, vtext_y), t_img)
        
        vlockup_img.save(dirs['lockups_v'] / f"metaglyph-vertical-{name}.png", "PNG")
        vlockup_img.resize((vcanvas_w // 2, vcanvas_h // 2), Image.Resampling.LANCZOS).save(dirs['lockups_v'] / f"metaglyph-vertical-{name}-800w.png", "PNG")
        
        if name in ['dark', 'light']:
            vlockup_img.save(dirs['root'] / f"metaglyph-lockup-vertical-{name}.png", "PNG")

        with io.BytesIO() as buf:
            m_img.save(buf, format='PNG')
            m_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
        
        v_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vcanvas_w} {vcanvas_h}" width="100%" height="100%">
  <image href="data:image/png;base64,{m_b64}" x="{vmark_x}" y="{pad_vy}" width="{target_vmark_w}" height="{target_vmark_h}"/>
  <g transform="translate({vtext_x},{vtext_y + vwm_h}) scale(0.100000,-0.100000) scale({vwm_w/6120.0 * 10},{vwm_h/960.0 * 10})" fill="{text_color}" stroke="none">
    {t_svg_paths}
  </g>
</svg>'''
        with open(dirs['lockups_v'] / f"metaglyph-vertical-{name}.svg", "w") as f:
            f.write(v_svg)
        if name in ['dark', 'light']:
            with open(dirs['root'] / f"metaglyph-lockup-vertical-{name}.svg", "w") as f:
                f.write(v_svg)

    print("=== Step 6: Generating Desktop Application Icons (Windows, macOS, Linux, Web) ===")
    app_icon_container = make_macos_container_app_icon(master_mark_2048, 1024)
    app_icon_frameless = make_frameless_app_icon(master_mark_2048, 1024)

    app_icon_container.save(dirs['root'] / "metaglyph-app-icon.png", "PNG")
    app_icon_frameless.save(dirs['root'] / "metaglyph-app-icon-frameless.png", "PNG")
    app_icon_container.save(dirs['icons_mac'] / "metaglyph-app-icon-1024x1024.png", "PNG")
    app_icon_frameless.save(dirs['icons_mac'] / "metaglyph-frameless-1024x1024.png", "PNG")

    apple_iconset_specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    icns_file = icnsutil.IcnsFile()
    for fname, size in apple_iconset_specs:
        resized_icon = app_icon_container.resize((size, size), Image.Resampling.LANCZOS)
        out_path = dirs['icons_mac_set'] / fname
        resized_icon.save(out_path, "PNG")
        icns_file.add_media(file=str(out_path))

    icns_file.write(str(dirs['root'] / "metaglyph.icns"))
    icns_file.write(str(dirs['icons_mac'] / "metaglyph.icns"))

    icns_frameless = icnsutil.IcnsFile()
    for fname, size in apple_iconset_specs:
        resized_fl = app_icon_frameless.resize((size, size), Image.Resampling.LANCZOS)
        tmp_p = dirs['icons_mac'] / f"temp_{fname}"
        resized_fl.save(tmp_p, "PNG")
        icns_frameless.add_media(file=str(tmp_p))
        tmp_p.unlink()

    icns_frameless.write(str(dirs['icons_mac'] / "metaglyph-frameless.icns"))

    win_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    app_icon_container.save(str(dirs['root'] / "metaglyph.ico"), format='ICO', sizes=win_sizes)
    app_icon_container.save(str(dirs['icons_win'] / "metaglyph-app.ico"), format='ICO', sizes=win_sizes)
    master_mark_2048.save(str(dirs['icons_win'] / "metaglyph-mark.ico"), format='ICO', sizes=win_sizes)

    linux_sizes = [16, 24, 32, 48, 64, 96, 128, 256, 512]
    for s in linux_sizes:
        hicolor_dir = dirs['icons_linux'] / "hicolor" / f"{s}x{s}" / "apps"
        ensure_dir(hicolor_dir)
        icon_res = app_icon_container.resize((s, s), Image.Resampling.LANCZOS)
        icon_res.save(hicolor_dir / "metaglyph.png", "PNG")
        icon_res.save(dirs['icons_linux'] / f"metaglyph-{s}x{s}.png", "PNG")

    hicolor_scalable = dirs['icons_linux'] / "hicolor" / "scalable" / "apps"
    ensure_dir(hicolor_scalable)
    with open(dirs['root'] / "metaglyph-mark.svg", "r") as f:
        svg_content = f.read()
    with open(hicolor_scalable / "metaglyph.svg", "w") as f:
        f.write(svg_content)

    desktop_entry = """[Desktop Entry]
Name=MetaGlyph
Comment=MetaGlyph Desktop Application
Exec=metaglyph %U
Icon=metaglyph
Terminal=false
Type=Application
Categories=Graphics;Development;Utility;
StartupWMClass=metaglyph
"""
    with open(dirs['icons_linux'] / "metaglyph.desktop", "w") as f:
        f.write(desktop_entry)

    fav_sizes = [(16, 16), (32, 32), (48, 48)]
    master_mark_2048.save(dirs['root'] / "favicon.ico", format='ICO', sizes=fav_sizes)
    master_mark_2048.save(dirs['web'] / "favicon.ico", format='ICO', sizes=fav_sizes)

    master_mark_2048.resize((16, 16), Image.Resampling.LANCZOS).save(dirs['root'] / "favicon-16x16.png", "PNG")
    master_mark_2048.resize((32, 32), Image.Resampling.LANCZOS).save(dirs['root'] / "favicon-32x32.png", "PNG")
    master_mark_2048.resize((16, 16), Image.Resampling.LANCZOS).save(dirs['web'] / "favicon-16x16.png", "PNG")
    master_mark_2048.resize((32, 32), Image.Resampling.LANCZOS).save(dirs['web'] / "favicon-32x32.png", "PNG")
    master_mark_2048.resize((48, 48), Image.Resampling.LANCZOS).save(dirs['web'] / "favicon-48x48.png", "PNG")

    app_icon_container.resize((180, 180), Image.Resampling.LANCZOS).save(dirs['root'] / "apple-touch-icon.png", "PNG")
    app_icon_container.resize((180, 180), Image.Resampling.LANCZOS).save(dirs['web'] / "apple-touch-icon.png", "PNG")
    app_icon_container.resize((192, 192), Image.Resampling.LANCZOS).save(dirs['web'] / "android-chrome-192x192.png", "PNG")
    app_icon_container.resize((512, 512), Image.Resampling.LANCZOS).save(dirs['web'] / "android-chrome-512x512.png", "PNG")

    manifest = {
        "name": "MetaGlyph",
        "short_name": "MetaGlyph",
        "icons": [
            {"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"}
        ],
        "theme_color": "#290649",
        "background_color": "#120323",
        "display": "standalone"
    }
    with open(dirs['web'] / "site.webmanifest", "w") as f:
        json.dump(manifest, f, indent=2)

    master_full_rgba = np.dstack([unmixed.astype(np.uint8), (alpha * 255).astype(np.uint8)])
    Image.fromarray(master_full_rgba).save(dirs['root'] / "metaglyph-master-transparent.png", "PNG")

    print("=== Brand Kit Generation Complete! ===")

if __name__ == '__main__':
    main()
