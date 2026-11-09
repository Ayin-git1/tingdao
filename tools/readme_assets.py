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

PAPER, INK, MUTED, RULE, EDGE, DEEP = "#F7F6F2", "#243C31", "#6E7E72", "#DADFD7", "#E3E5DE", "#567764"
# 竹青 晴蓝 青莲 松石 橘红 胭脂 —— HSL presets from the app, with a deeper ink of each hue for numerals.
SWATCHES = [("竹青", "#CBEBDB", "#416C57"), ("晴蓝", "#C9DFF2", "#395974"), ("青莲", "#DFD4F2", "#503C71"),
            ("松石", "#C8EAE5", "#416C66"), ("橘红", "#F8D9C3", "#7D4F31"), ("胭脂", "#F5D1D9", "#763846")]
SERIF = "'Songti SC','STSong','Noto Serif CJK SC','Noto Serif SC','Source Han Serif SC',serif"
LATIN = "Georgia,'Times New Roman',serif"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif"

# Pinyon Script "Folio" outline at 100 units, baseline y=0 (from the font embedded in index.html).
FOLIO_PATH = (ROOT / "assets" / "readme" / "folio-path.txt").read_text().split("\n", 1)[1].strip()


def hero():
    rows = [
        ("00:30", "点右下角的 ＋ 新建录音。", None, None),
        ("01:04", "录音来源有三种：系统、麦克风或混合。", ("mark", 8, 17), SWATCHES[0][1]),
        ("01:16", "录到一半也能换来源，录音不会断。", ("line", 11, 16), "#D9A3AF"),
    ]
    x0, size = 752, 20
    body = []
    for i, (stamp, text, deco, color) in enumerate(rows):
        y = 186 + i * 50
        if deco and deco[0] == "mark":
            body.append(f'<rect x="{x0 + deco[1] * size - 2}" y="{y - 19}" width="{(deco[2] - deco[1]) * size + 4}" height="26" rx="3" fill="{color}"/>')
        if deco and deco[0] == "line":
            body.append(f'<path d="M{x0 + deco[1] * size} {y + 6}H{x0 + deco[2] * size}" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
        body.append(f'<text x="676" y="{y}" font-family="{LATIN}" font-size="17" fill="{MUTED}" letter-spacing=".5">{stamp}</text>')
        body.append(f'<text x="{x0}" y="{y}" font-family="{SERIF}" font-size="{size}" fill="{INK}">{text}</text>')
    chips = []
    for i, (name, fill, _) in enumerate(SWATCHES):
        x = 56 + i * 76
        chips.append(f'<rect x="{x}" y="356" width="14" height="14" rx="3" fill="{fill}" stroke="#00000014"/>'
                     f'<text x="{x + 22}" y="368" font-family="{SERIF}" font-size="15" fill="{MUTED}">{name}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="420" viewBox="0 0 1200 420" role="img" aria-labelledby="title desc">
  <title id="title">听道 Folio</title>
  <desc id="desc">听道 Folio：本地优先的录音、转写与笔记工具，把声音留成文字。右侧是一段带时间戳、划线和时间线笔记的文稿样张。</desc>
  <rect x=".5" y=".5" width="1199" height="419" rx="18" fill="{PAPER}" stroke="{EDGE}"/>
  <text x="56" y="56" font-family="{SANS}" font-size="14" font-weight="600" letter-spacing="3" fill="{MUTED}">LOCAL-FIRST AUDIO NOTEBOOK</text>
  <text x="1144" y="56" text-anchor="end" font-family="{SANS}" font-size="14" font-weight="600" letter-spacing="3" fill="{MUTED}">MACOS · WINDOWS</text>
  <path d="M56 76H1144" stroke="{INK}" stroke-opacity=".75" stroke-width="1.2"/>
  <path d="M56 80H1144" stroke="{RULE}"/>
  <text x="52" y="206" font-family="{SERIF}" font-size="104" font-weight="600" fill="{INK}" letter-spacing="2">听道</text>
  <path transform="translate(284 204) scale(.86)" fill="{DEEP}" d="{FOLIO_PATH}"/>
  <text x="58" y="268" font-family="{SERIF}" font-size="32" fill="{INK}">把声音，留成文字。</text>
  <text x="58" y="314" font-family="{SANS}" font-size="19" fill="{MUTED}">录音 · 转写 · 摘要目录 · 时间线笔记 · 复习</text>
  {"".join(chips)}
  <path d="M636 112V384" stroke="{RULE}"/>
  <text x="676" y="128" font-family="{SANS}" font-size="13" font-weight="600" letter-spacing="2.5" fill="{MUTED}">SPECIMEN · 文稿样张</text>
  {"".join(body)}
  <rect x="752.5" y="306.5" width="391" height="70" rx="10" fill="#FFFFFF" stroke="{RULE}"/>
  <rect x="752.5" y="306.5" width="4" height="70" rx="2" fill="{SWATCHES[5][1]}"/>
  <text x="774" y="332" font-family="{SANS}" font-size="13" font-weight="600" letter-spacing="1.5" fill="{MUTED}">时间线笔记 · 01:16</text>
  <text x="774" y="362" font-family="{SERIF}" font-size="19" fill="{INK}">中途换成麦克风，记得戴上耳机。</text>
</svg>
'''


SECTIONS = ["overview:概览", "download:下载与安装", "features:核心功能", "privacy:隐私与数据", "first-use:首次使用",
            "guide:使用说明", "models:推荐模型组合", "dependencies:运行依赖", "windows-setup:Windows 安装步骤",
            "workflow:工作方式", "data:文件与数据", "limitations:已知限制", "license:许可", f"updates:v{VERSION} 更新"]


def text_width(text, size):
    return sum(size if ord(c) > 0x2E80 else (size * .3 if c == " " else size * .56) for c in text)


def badge(index, title):
    _, fill, deep = SWATCHES[index % len(SWATCHES)]
    width = round(74 + text_width(title, 22) + 22)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="52" viewBox="0 0 {width} 52" role="img" aria-labelledby="title">
  <title id="title">{title}</title>
  <rect x=".5" y=".5" width="{width - 1}" height="51" rx="12" fill="{PAPER}" stroke="{RULE}"/>
  <rect x="18" y="22" width="9" height="9" rx="2" fill="{fill}" stroke="{deep}" stroke-opacity=".35"/>
  <text x="34" y="32" font-family="{LATIN}" font-size="15" font-style="italic" fill="{deep}">{index + 1:02d}</text>
  <path d="M61 15V37" stroke="{RULE}"/>
  <text x="74" y="34" font-family="{SERIF}" font-size="22" font-weight="600" fill="{INK}">{title}</text>
</svg>
'''


(OUT / "hero.svg").write_text(hero(), encoding="utf-8")
for i, item in enumerate(SECTIONS):
    slug, title = item.split(":", 1)
    (OUT / "badges" / f"{slug}.svg").write_text(badge(i, title), encoding="utf-8")
print("wrote hero.svg and", len(SECTIONS), "headers")
