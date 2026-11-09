#!/usr/bin/env python3
"""Generate the README hero and section headers.

Palette follows the app's built-in bright Morandi swatches (THEME_PRESETS in
index.html); the Folio wordmark is the app's Pinyon Script, converted to paths
so GitHub needs no web font. Run: python3 tools/readme_assets.py VERSION
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "readme"
VERSION = sys.argv[1] if len(sys.argv) > 1 else "3.1.10.3"

PAPER, DEEP = "#F7F6F2", "#567764"
# 竹青 晴蓝 青莲 松石 橘红 胭脂 —— HSL presets from the app, with a deeper ink of each hue for numerals.
SWATCHES = [("竹青", "#CBEBDB", "#416C57"), ("晴蓝", "#C9DFF2", "#395974"), ("青莲", "#DFD4F2", "#503C71"),
            ("松石", "#C8EAE5", "#416C66"), ("橘红", "#F8D9C3", "#7D4F31"), ("胭脂", "#F5D1D9", "#763846")]
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"

# Pinyon Script "Folio" outline at 100 units, baseline y=0 (from the font embedded in index.html).
FOLIO_PATH = (ROOT / "assets" / "readme" / "folio-path.txt").read_text().split("\n", 1)[1].strip()


def hero():
    """Product-style hero: centred icon and wordmark over soft swatch light, features as pills."""
    import base64
    icon = base64.b64encode((OUT / "app-icon-192.png").read_bytes()).decode()
    pills = []
    items = [("本地转写", 0), ("AI 摘要目录", 1), ("时间线笔记", 5), ("间隔复习", 2)]
    widths = [round(text_width(t, 18) + 52) for t, _ in items]
    x = 600 - (sum(widths) + 12 * (len(items) - 1)) / 2
    for (label, sw), w in zip(items, widths):
        pills.append(f'<rect x="{x:.1f}" y="310" width="{w}" height="38" rx="19" fill="#FFFFFF" fill-opacity=".78" stroke="#1C2A22" stroke-opacity=".08"/>'
                     f'<circle cx="{x + 20:.1f}" cy="329" r="5" fill="{SWATCHES[sw][1]}" stroke="{SWATCHES[sw][2]}" stroke-opacity=".45"/>'
                     f'<text x="{x + 33:.1f}" y="336" font-family="{SANS}" font-size="18" font-weight="500" fill="#2E3A33">{label}</text>')
        x += w + 12
    folio_w = 179.2 * .62
    title_w = 2 * 64 + 14 + folio_w
    tx = 600 - title_w / 2
    return f'''<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1200" height="420" viewBox="0 0 1200 420" role="img" aria-labelledby="title desc">
  <title id="title">听道 Folio</title>
  <desc id="desc">听道 Folio：本地优先的录音、转写与笔记工具，把声音留成文字。支持本地转写、AI 摘要目录、时间线笔记与间隔复习，适用于 macOS 和 Windows。</desc>
  <defs>
    <clipPath id="card"><rect width="1200" height="420" rx="24"/></clipPath>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="70"/></filter>
    <linearGradient id="base" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="{PAPER}"/></linearGradient>
  </defs>
  <g clip-path="url(#card)">
    <rect width="1200" height="420" fill="url(#base)"/>
    <g filter="url(#soft)" opacity=".9">
      <circle cx="250" cy="90" r="170" fill="{SWATCHES[0][1]}"/>
      <circle cx="980" cy="70" r="160" fill="{SWATCHES[1][1]}"/>
      <circle cx="1040" cy="400" r="150" fill="{SWATCHES[5][1]}"/>
      <circle cx="140" cy="420" r="130" fill="{SWATCHES[2][1]}"/>
    </g>
  </g>
  <rect x=".5" y=".5" width="1199" height="419" rx="24" fill="none" stroke="#1C2A22" stroke-opacity=".07"/>
  <image x="556" y="44" width="88" height="88" href="data:image/png;base64,{icon}" xlink:href="data:image/png;base64,{icon}"/>
  <text x="{tx:.1f}" y="222" font-family="{SANS}" font-size="64" font-weight="700" letter-spacing="1" fill="#1C2A22">听道</text>
  <path transform="translate({tx + 128 + 14:.1f} 220) scale(.62)" fill="{DEEP}" d="{FOLIO_PATH}"/>
  <text x="600" y="272" text-anchor="middle" font-family="{SANS}" font-size="24" font-weight="400" fill="#55625A">把声音，留成文字。本地优先的录音、转写与笔记。</text>
  {"".join(pills)}
  <text x="600" y="392" text-anchor="middle" font-family="{SANS}" font-size="14" font-weight="500" letter-spacing="2" fill="#8A968E">MACOS · WINDOWS</text>
</svg>
'''


SECTIONS = ["overview:概览", "download:下载与安装", "features:核心功能", "privacy:隐私与数据", "first-use:首次使用",
            "guide:使用说明", "models:推荐模型组合", "dependencies:运行依赖", "windows-setup:Windows 安装步骤",
            "workflow:工作方式", "data:文件与数据", "limitations:已知限制", "license:许可", f"updates:v{VERSION} 更新"]


def text_width(text, size):
    return sum(size if ord(c) > 0x2E80 else (size * .3 if c == " " else size * .56) for c in text)


def badge(index, title):
    _, fill, deep = SWATCHES[index % len(SWATCHES)]
    width = round(46 + text_width(title, 21) + 24)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="52" viewBox="0 0 {width} 52" role="img" aria-labelledby="title">
  <title id="title">{title}</title>
  <rect x=".5" y=".5" width="{width - 1}" height="51" rx="25.5" fill="#FFFFFF" stroke="#1C2A22" stroke-opacity=".1"/>
  <circle cx="26" cy="26" r="6" fill="{fill}" stroke="{deep}" stroke-opacity=".45"/>
  <text x="44" y="33" font-family="{SANS}" font-size="21" font-weight="600" fill="#1C2A22">{title}</text>
</svg>
'''


(OUT / "hero.svg").write_text(hero(), encoding="utf-8")
for i, item in enumerate(SECTIONS):
    slug, title = item.split(":", 1)
    (OUT / "badges" / f"{slug}.svg").write_text(badge(i, title), encoding="utf-8")
print("wrote hero.svg and", len(SECTIONS), "headers")
