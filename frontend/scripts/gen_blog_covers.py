#!/usr/bin/env python3
"""生成博客封面 —— 真实摄影底图 + 品牌处理叠加,自包含本地资源,不依赖外部图床。

每篇文章:一张深色抽象摄影底图(Unsplash,免费可商用) → 压暗 + 品牌色斜向渐变罩
+ 左侧加深(保证文字可读) + 暗角 → 叠加主题线性图标 + 角标 + Vigilath 放大镜字标。
跨三套站点主题(极简/浅色/深色)都在卡片图区独立成图,稳定显示。

底图放在 frontend/scripts/assets/bg/<file>.jpg(随仓库,离线可复跑)。
输出 frontend/public/image/blog/<slug>.jpg
依赖:pip install pillow cairosvg
"""
import io
import math
import os

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
import cairosvg

HERE = os.path.dirname(__file__)
BG_DIR = os.path.join(HERE, "assets", "bg")
OUT = os.path.join(HERE, "..", "public", "image", "blog")
W, H = 1200, 675

FONT_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_LAT = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"

# slug, 底图文件, 主色(RGB), 副色, 角标文字, 图标 id
COVERS = [
    ("what-is-geo",                "hQo6Uyo4nBg", (34, 211, 238),  (123, 97, 255),  "GEO 基础", "bubble"),
    ("how-ai-picks-sources",       "BV9vbI8ZkZM", (167, 139, 250), (34, 211, 238),  "信源机制", "network"),
    ("geo-for-global-brands",      "6-rgE3WSEio", (45, 212, 191),  (56, 189, 248),  "多引擎",   "globe"),
    ("geo-vs-aeo",                 "VzfIPiKsg68", (251, 191, 36),  (251, 113, 133), "概念辨析", "venn"),
    ("monitor-brand-in-ai-answers","x9vo_Z6G8xY", (56, 189, 248),  (123, 97, 255),  "持续监控", "chart"),
    ("wikipedia-and-ai-visibility","Lh9Jqm2-z7Y", (129, 140, 248), (34, 211, 238),  "权威信源", "book"),
    ("make-content-ai-crawlable",  "QTPagUbFT1g", (52, 211, 153),  (34, 211, 238),  "收录侧",   "crawl"),
    ("ai-hallucination-brand-risk","UVPRU8HSdS8", (251, 113, 133), (245, 158, 11),  "舆情风险", "warning"),
]


def hx(c):
    return "#%02x%02x%02x" % c


# ---- 主题线性图标(透明底 SVG,白色描边 + 副色点缀)----
def icon_svg(kind, c2):
    cx, cy = 0, 0
    W2 = "white"
    s = f'stroke="{W2}" stroke-width="13" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    sa = f'stroke="{hx(c2)}" stroke-width="13" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    body = ""
    if kind == "bubble":
        body = f'''<rect x="-150" y="-120" width="300" height="200" rx="36" {s}/>
        <path d="M -60 80 L -30 140 L 10 80" {s}/>
        <path d="M 0 -70 L 14 -22 L 62 -8 L 14 6 L 0 54 L -14 6 L -62 -8 L -14 -22 Z" fill="{hx(c2)}" stroke="none"/>
        <line x1="-100" y1="20" x2="-26" y2="20" {sa}/>'''
    elif kind == "network":
        sat = [(-165, -92), (172, -72), (140, 112), (-150, 104)]
        body = "".join(f'<line x1="0" y1="0" x2="{dx}" y2="{dy}" {sa}/>' for dx, dy in sat)
        body += f'<circle cx="0" cy="0" r="52" {s}/>'
        for i, (dx, dy) in enumerate(sat):
            fill = hx(c2) if i == 1 else "none"
            body += f'<circle cx="{dx}" cy="{dy}" r="34" fill="{fill}" stroke="{W2}" stroke-width="13"/>'
    elif kind == "globe":
        body = f'''<circle cx="0" cy="0" r="150" {s}/>
        <line x1="-150" y1="0" x2="150" y2="0" {s}/>
        <ellipse cx="0" cy="0" rx="64" ry="150" {s}/>
        <path d="M -140 -58 Q 0 -30 140 -58" {sa}/>
        <path d="M -140 58 Q 0 30 140 58" {sa}/>
        <circle cx="150" cy="-150" r="20" fill="{hx(c2)}" stroke="none"/>'''
    elif kind == "venn":
        body = f'''<circle cx="-60" cy="0" r="125" {s}/>
        <circle cx="60" cy="0" r="125" {sa}/>'''
    elif kind == "chart":
        pts = [(-185, 72), (-105, 22), (-32, 52), (52, -42), (135, -10), (195, -92)]
        poly = " ".join(f"{x},{y}" for x, y in pts)
        body = f'<line x1="-195" y1="-112" x2="-195" y2="112" {s} opacity="0.55"/>'
        body += f'<line x1="-195" y1="112" x2="205" y2="112" {s} opacity="0.55"/>'
        body += f'<polyline points="{poly}" {s}/>'
        body += "".join(f'<circle cx="{x}" cy="{y}" r="13" fill="{hx(c2)}" stroke="none"/>' for x, y in pts)
    elif kind == "book":
        body = f'''<path d="M 0 -110 C -60 -140 -150 -130 -180 -110 L -180 110 C -150 90 -60 80 0 110" {s}/>
        <path d="M 0 -110 C 60 -140 150 -130 180 -110 L 180 110 C 150 90 60 80 0 110" {s}/>
        <line x1="0" y1="-110" x2="0" y2="110" {s}/>
        <line x1="-145" y1="-78" x2="-45" y2="-90" {sa}/>
        <line x1="-145" y1="-30" x2="-45" y2="-42" {sa}/>
        <line x1="45" y1="-90" x2="145" y2="-78" {sa}/>'''
    elif kind == "crawl":
        body = f'''<rect x="-150" y="-130" width="232" height="260" rx="24" {s}/>
        <line x1="-110" y1="-80" x2="36" y2="-80" {sa}/>
        <line x1="-110" y1="-30" x2="46" y2="-30" {sa}/>
        <line x1="-110" y1="20" x2="6" y2="20" {sa}/>
        <circle cx="116" cy="70" r="56" {s}/>
        <line x1="156" y1="110" x2="201" y2="155" {s}/>
        <path d="M 92 70 L 110 88 L 142 50" {sa}/>'''
    elif kind == "warning":
        body = f'''<path d="M 0 -132 L 162 122 L -162 122 Z" {s}/>
        <line x1="0" y1="-44" x2="0" y2="40" {sa}/>
        <circle cx="0" cy="84" r="9" fill="{hx(c2)}" stroke="none"/>'''
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-260 -200 520 400" width="520" height="400">{body}</svg>'


def svg_to_img(svg, scale=2):
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=520 * scale, output_height=400 * scale)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def cover_base(path):
    im = Image.open(path).convert("RGB")
    iw, ih = im.size
    tr = W / H
    if iw / ih > tr:
        nw = int(ih * tr); im = im.crop(((iw - nw) // 2, 0, (iw - nw) // 2 + nw, ih))
    else:
        nh = int(iw / tr); im = im.crop((0, (ih - nh) // 2, iw, (ih - nh) // 2 + nh))
    return im.resize((W, H), Image.LANCZOS)


def vgrad(size, c1, c2, horizontal=False):
    """两端 RGBA 线性渐变图层。"""
    w, h = size
    base = Image.new("RGBA", (1, h) if not horizontal else (w, 1))
    px = base.load()
    n = h if not horizontal else w
    for i in range(n):
        t = i / max(1, n - 1)
        px[0, i] if not horizontal else None
        col = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(4))
        if horizontal:
            px[i, 0] = col
        else:
            px[0, i] = col
    return base.resize(size)


def vignette(size, strength=140):
    w, h = size
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.18, -h * 0.18, w * 1.18, h * 1.18], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(120))
    dark = Image.new("RGBA", size, (5, 7, 16, strength))
    inv = Image.eval(mask, lambda x: 255 - x)
    dark.putalpha(inv)
    return dark


def build(slug, bgfile, c, c2, kicker, kind):
    im = cover_base(os.path.join(BG_DIR, bgfile + ".jpg")).convert("RGBA")
    im = ImageEnhance.Brightness(im).enhance(0.62)
    im = ImageEnhance.Color(im).enhance(0.9)

    # 品牌色斜向渐变罩(主色左上 → 透明 → 副色右下),adds 品牌统一色调
    wash = vgrad((W, H), (*c, 150), (*c, 0))
    im = Image.alpha_composite(im, wash.rotate(0))
    wash2 = vgrad((W, H), (*c2, 0), (*c2, 90))
    im = Image.alpha_composite(im, wash2)

    # 左侧加深,保证角标/字标可读
    left = vgrad((W, H), (4, 6, 16, 175), (4, 6, 16, 0), horizontal=True)
    im = Image.alpha_composite(im, left)
    # 底部加深
    bottom = vgrad((W, H), (4, 6, 16, 0), (4, 6, 16, 130))
    im = Image.alpha_composite(im, bottom)
    # 暗角
    im = Image.alpha_composite(im, vignette((W, H)))

    # 主题图标(右侧),带轻微发光
    icon = svg_to_img(icon_svg(kind, c2), scale=2).resize((520, 400), Image.LANCZOS)
    glow = icon.filter(ImageFilter.GaussianBlur(14))
    ix, iy = 600, 150
    im.alpha_composite(glow, (ix, iy))
    im.alpha_composite(icon, (ix, iy))

    # 文字/角标画在透明层再合成(ImageDraw 直接画半透明填充不会做 alpha 合成)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # 角标 chip:半透明主色底 + 主色描边 + 白字
    fk = ImageFont.truetype(FONT_CJK, 30)
    tb = d.textbbox((0, 0), kicker, font=fk)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    px0, py0 = 64, 68
    chip_w, chip_h = tw + 48, 58
    d.rounded_rectangle([px0, py0, px0 + chip_w, py0 + chip_h], radius=29,
                        fill=(*c, 48), outline=(*c, 210), width=2)
    d.text((px0 + 24, py0 + chip_h / 2 - th / 2 - tb[1]), kicker, font=fk, fill=(245, 250, 252, 255))

    # Vigilath 放大镜字标
    bx, by = 64, H - 76
    d.ellipse([bx, by, bx + 30, by + 30], outline=(*c, 255), width=5)
    d.line([bx + 26, by + 26, bx + 44, by + 44], fill=(*c, 255), width=5)
    fb = ImageFont.truetype(FONT_LAT, 30)
    d.text((bx + 58, by - 2), "VIGILATH", font=fb, fill=(248, 250, 252, 255))

    im = Image.alpha_composite(im, overlay)
    rgb = im.convert("RGB")
    out = os.path.join(OUT, slug + ".jpg")
    rgb.save(out, "JPEG", quality=84, optimize=True, progressive=True)
    return out, os.path.getsize(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    for slug, bgfile, c, c2, kicker, kind in COVERS:
        out, sz = build(slug, bgfile, c, c2, kicker, kind)
        print(f"wrote {os.path.relpath(out)}  {sz//1024}KB")


if __name__ == "__main__":
    main()
