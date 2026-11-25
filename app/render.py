"""Designed slides, thumbnails and carousel cards rendered with Pillow (no GPU)."""
from __future__ import annotations

import hashlib
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIRS = (
    Path("/usr/share/fonts/opentype/noto"),
    Path("/Library/Fonts"),
    Path.home() / "Library" / "Fonts",
)


def _font_file(weight: str) -> Path:
    for folder in FONT_DIRS:
        for name in (f"NotoSansCJK-{weight}.ttc", "NotoSansCJK.ttc"):
            if (folder / name).exists():
                return folder / name
    raise FileNotFoundError(f"找不到 Noto Sans CJK（{weight}），已找：{', '.join(map(str, FONT_DIRS))}")


@lru_cache(maxsize=64)
def font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    path = str(_font_file(weight))
    fallback = None
    for idx in range(40):  # pick the Traditional Chinese face of this weight inside the collection
        try:
            f = ImageFont.truetype(path, size, index=idx)
        except OSError:
            break
        family, style = f.getname()
        if "TC" in family and style == weight:
            return f
        if "TC" in family and fallback is None:
            fallback = f
    return fallback or ImageFont.truetype(path, size)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if draw.textlength(cur + ch, font=f) <= width:
            cur += ch
        else:
            # prefer breaking at a space (between words / mixed CJK-latin)
            sp = cur.rstrip().rfind(" ")
            if sp > 0:
                lines.append(cur[:sp])
                cur = cur[sp + 1:] + ch
                continue
            # keep latin words together
            if ch.isascii() and ch.isalnum() and cur and cur[-1].isascii() and cur[-1].isalnum():
                cut = len(cur.rstrip("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))
                if 0 < cut < len(cur):
                    lines.append(cur[:cut])
                    cur = cur[cut:] + ch
                    continue
            lines.append(cur)
            cur = ch.lstrip()
    if cur:
        lines.append(cur)
    return lines


def fit_lines(draw, text, max_size, min_size, width, max_lines, weight="Black", balanced=False):
    size = max_size
    while size >= min_size:
        f = font(size, weight)
        lines = wrap(draw, text, f, width)
        if len(lines) <= max_lines:
            # balanced: avoid a lone orphan character on the last line
            if not balanced or len(lines) == 1 or len(lines[-1].strip()) >= max(2, len(lines[0]) * 0.35):
                return f, lines
        size -= 4
    f = font(min_size, weight)
    return f, wrap(draw, text, f, width)[:max_lines]


def draw_block(draw, xy, lines, f, fill, spacing=1.2, anchor_center=False, width=0):
    x, y = xy
    lh = int(f.size * spacing)
    for ln in lines:
        if anchor_center:
            w = draw.textlength(ln, font=f)
            draw.text((x + (width - w) / 2, y), ln, font=f, fill=fill)
        else:
            draw.text((x, y), ln, font=f, fill=fill)
        y += lh
    return y


def _rng(seed: str) -> random.Random:
    return random.Random(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16))


PALETTES = [
    ((20, 22, 28), (255, 214, 0), (245, 245, 240)),
    ((16, 40, 72), (255, 120, 80), (240, 244, 250)),
    ((34, 24, 48), (120, 230, 180), (245, 240, 255)),
]


def _text_block(d, head, bullets, width, vertical, head_scale, bullet_scale, prefix, W):
    """Lay out headline + bullets; returns (head_font, head_lines, bullet_font, bullet_lines, height)."""
    fh, hl = fit_lines(d, head, int(W * head_scale), 44, width, 4 if vertical else 3)
    fb = font(int(W * bullet_scale), "Bold")
    bl = [[prefix + ln if k == 0 else "   " + ln for k, ln in enumerate(wrap(d, b, fb, width - int(fb.size * 1.2)))] for b in bullets]
    h = len(hl) * int(fh.size * 1.18) + (int(fb.size * 0.9) if bl else 0) + sum(len(x) for x in bl) * int(fb.size * 1.45) + len(bl) * int(fb.size * 0.35)
    return fh, hl, fb, bl, h


def _draw_text_block(d, x, y, fh, hl, fb, bl, head_fill, body_fill, bullet_fill=None):
    for ln in hl:
        d.text((x, y), ln, font=fh, fill=head_fill)
        y += int(fh.size * 1.18)
    if bl:
        y += int(fb.size * 0.9)
    for lines in bl:
        for ln in lines:
            d.text((x, y), ln, font=fb, fill=body_fill)
            y += int(fb.size * 1.45)
        y += int(fb.size * 0.35)
    return y


def slide(scene: dict, size: tuple[int, int], out: Path, channel: str = "", index: int = 0, total: int = 0) -> Path:
    W, H = size
    style = scene.get("style") or "clean"
    rng = _rng(scene.get("headline", "") + str(index))
    head = scene.get("headline") or ""
    bullets = [b for b in (scene.get("bullets") or []) if b][:3]
    vertical = H > W
    sub_zone = int(H * (0.24 if vertical else 0.2))  # keep bottom clear for subtitles
    margin = int(W * 0.08)
    top = int(H * 0.06)
    area_h = H - sub_zone - top  # content is centred inside [top, H - sub_zone]
    hs, bs = (0.15, 0.062) if vertical else (0.085, 0.034)

    if style == "bigtype":
        bg, accent, ink = PALETTES[index % len(PALETTES)]
        img = Image.new("RGB", size, bg)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, int(W * 0.03), H], fill=accent)
        fh, hl, fb, bl, h = _text_block(d, head, bullets, W - 2 * margin, vertical, hs * 1.1, bs, "— ", W)
        _draw_text_block(d, margin, top + max(0, (area_h - h) // 2), fh, hl, fb, bl, accent, ink)

    elif style == "papercut":
        paper = [(250, 228, 196), (196, 228, 214), (214, 206, 240), (248, 206, 206)]
        img = Image.new("RGB", size, (252, 248, 238))
        d = ImageDraw.Draw(img)
        for _ in range(8):
            c = rng.choice(paper)
            x, y = rng.randint(-200, W), rng.randint(-200, H)
            r = rng.randint(int(W * 0.1), int(W * 0.28))
            d.polygon([(x + rng.randint(-r, r), y + rng.randint(-r, r)) for _ in range(6)], fill=c)
        pad = int(W * 0.06)
        cw = W - 2 * margin
        fh, hl, fb, bl, h = _text_block(d, head, bullets, cw - 2 * pad, vertical, hs * 0.85, bs, "✂ ", W)
        card = Image.new("RGBA", (cw, h + 2 * pad), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, card.width - 1, card.height - 1], 30, fill=(255, 250, 240, 255), outline=(60, 50, 40), width=6)
        _draw_text_block(cd, pad, pad, fh, hl, fb, bl, (60, 40, 30), (90, 70, 60))
        card = card.rotate(rng.uniform(-2.5, 2.5), expand=True, resample=Image.BICUBIC)
        shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 70), mask=card.split()[3])
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))
        y0 = top + max(0, (area_h - card.height) // 2)
        img.paste(shadow, (margin + 14, y0 + 18), shadow)
        img.paste(card, (margin, y0), card)

    elif style == "corkboard":
        img = Image.new("RGB", size, (176, 132, 88))
        d = ImageDraw.Draw(img)
        for _ in range(int(W * H / 900)):
            d.point((rng.randint(0, W), rng.randint(0, H)), fill=rng.choice([(150, 108, 70), (196, 152, 106), (164, 120, 80)]))
        img = img.filter(ImageFilter.GaussianBlur(0.8))
        d = ImageDraw.Draw(img)
        cw = W - 2 * margin
        fh, hl = fit_lines(d, head, int(W * hs * 0.8), 40, cw - 80, 3, "Black")
        clip = Image.new("RGBA", (cw, len(hl) * int(fh.size * 1.15) + 70), (248, 246, 236, 255))
        draw_block(ImageDraw.Draw(clip), (40, 35), hl, fh, (20, 20, 20), 1.15)
        clip = clip.rotate(rng.uniform(-3, 3), expand=True, resample=Image.BICUBIC)
        fb = font(int(W * bs), "Bold")
        notes = []
        for b in bullets:
            nw = int(cw * (0.95 if vertical else 0.62))
            lines = wrap(d, b, fb, nw - 50)[:2]
            note = Image.new("RGBA", (nw, int(fb.size * (1.0 + 1.4 * len(lines)))), (255, 236, 120, 255))
            nd = ImageDraw.Draw(note)
            for k, ln in enumerate(lines):
                nd.text((25, int(fb.size * 0.5) + k * int(fb.size * 1.4)), ln, font=fb, fill=(40, 30, 10))
            notes.append(note.rotate(rng.uniform(-4, 4), expand=True, resample=Image.BICUBIC))
        gap = int(fb.size * 0.5)
        total_h = clip.height + sum(n.height + gap for n in notes) + gap
        y = top + max(0, (area_h - total_h) // 2)
        img.paste(clip, (margin, y), clip)
        y += clip.height + gap
        for i, note in enumerate(notes):
            x = margin + (i % 2) * int(W * (0.02 if vertical else 0.22))
            img.paste(note, (x, y), note)
            d.ellipse([x + note.width // 2 - 14, y + 2, x + note.width // 2 + 14, y + 30], fill=(200, 30, 40))
            y += note.height + gap

    else:  # clean
        img = Image.new("RGB", size, (246, 247, 249))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, int(H * 0.012)], fill=(37, 99, 235))
        fh, hl, fb, bl, h = _text_block(d, head, bullets, W - 2 * margin - int(W * bs * 1.6), vertical, hs * 0.9, bs, "", W)
        y = top + max(0, (area_h - h) // 2)
        for ln in hl:
            d.text((margin, y), ln, font=fh, fill=(17, 24, 39))
            y += int(fh.size * 1.18)
        y += int(fb.size * 0.9) if bl else 0
        for i, lines in enumerate(bl, 1):
            s = int(fb.size * 1.3)
            d.rounded_rectangle([margin, y + int(fb.size * 0.1), margin + s, y + int(fb.size * 0.1) + s], 12, fill=(37, 99, 235))
            d.text((margin + s // 2, y + int(fb.size * 0.1) + s // 2), str(i), font=fb, fill="white", anchor="mm")
            for ln in lines:
                d.text((margin + int(fb.size * 1.8), y), ln.strip(), font=fb, fill=(55, 65, 81))
                y += int(fb.size * 1.45)
            y += int(fb.size * 0.35)

    d = ImageDraw.Draw(img)
    if channel:
        fc = font(int(W * (0.03 if vertical else 0.018)), "Bold")
        d.text((W - margin, int(H * 0.025)), channel, font=fc, fill=(128, 128, 128), anchor="ra")
    if total:
        fc = font(int(W * (0.025 if vertical else 0.015)), "Regular")
        d.text((margin, int(H * 0.025)), f"{index + 1}/{total}", font=fc, fill=(128, 128, 128))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out


def plate(scene: dict, size: tuple[int, int], out: Path, index: int = 0) -> Path:
    """Text-free background in the same style as `slide`, for renderers that animate the text themselves."""
    W, H = size
    style = scene.get("style") or "clean"
    rng = _rng(scene.get("headline", "") + str(index))
    if style == "bigtype":
        bg, accent, _ = PALETTES[index % len(PALETTES)]
        img = Image.new("RGB", size, bg)
        ImageDraw.Draw(img).rectangle([0, 0, int(W * 0.03), H], fill=accent)
    elif style == "papercut":
        paper = [(250, 228, 196), (196, 228, 214), (214, 206, 240), (248, 206, 206)]
        img = Image.new("RGB", size, (252, 248, 238))
        d = ImageDraw.Draw(img)
        for _ in range(8):
            c = rng.choice(paper)
            x, y = rng.randint(-200, W), rng.randint(-200, H)
            r = rng.randint(int(W * 0.1), int(W * 0.28))
            d.polygon([(x + rng.randint(-r, r), y + rng.randint(-r, r)) for _ in range(6)], fill=c)
    elif style == "corkboard":
        img = Image.new("RGB", size, (176, 132, 88))
        d = ImageDraw.Draw(img)
        for _ in range(int(W * H / 900)):
            d.point((rng.randint(0, W), rng.randint(0, H)), fill=rng.choice([(150, 108, 70), (196, 152, 106), (164, 120, 80)]))
        img = img.filter(ImageFilter.GaussianBlur(0.8))
    else:  # clean
        img = Image.new("RGB", size, (246, 247, 249))
        ImageDraw.Draw(img).rectangle([0, 0, W, int(H * 0.012)], fill=(37, 99, 235))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out


def scene_with_bg(scene: dict, size: tuple[int, int], bg: Path, out: Path, channel: str = "",
                  index: int = 0, total: int = 0) -> Path:
    """Generated background + headline/bullets overlay. Text stays readable, subtitles keep their zone."""
    W, H = size
    vertical = H > W
    img = Image.open(bg).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((max(W, int(img.width * scale + 0.5)), max(H, int(img.height * scale + 0.5))), Image.LANCZOS)
    left = (img.width - W) // 2
    top_crop = int((img.height - H) * (0.45 if vertical else 0.4))
    img = img.crop((left, top_crop, left + W, top_crop + H))

    # top and bottom scrims: headline legible, subtitles always readable
    scrim = Image.new("L", (1, H), 0)
    for y in range(H):
        r = y / H
        if r < 0.55:
            v = int(200 * (1 - r / 0.55) ** 1.2)
        elif r > 0.66:
            v = int(210 * ((r - 0.66) / 0.34) ** 0.9)
        else:
            v = 0
        scrim.putpixel((0, y), v)
    dark = Image.new("RGB", size, (8, 10, 16))
    img = Image.composite(dark, img, scrim.resize(size))

    d = ImageDraw.Draw(img)
    margin = int(W * 0.07)
    accent = PALETTES[index % len(PALETTES)][1]
    d.rectangle([margin, int(H * 0.08), margin + int(W * 0.012), int(H * 0.08) + int(H * 0.16)], fill=accent)

    head = scene.get("headline") or ""
    fh, hl = fit_lines(d, head, int(W * (0.085 if vertical else 0.055)), 34,
                       W - 2 * margin - int(W * 0.03), 3, "Black")
    y = int(H * 0.08)
    for ln in hl:
        d.text((margin + int(W * 0.03), y), ln, font=fh, fill=(255, 255, 255),
               stroke_width=max(3, fh.size // 14), stroke_fill=(0, 0, 0))
        y += int(fh.size * 1.16)

    fb = font(int(W * (0.043 if vertical else 0.026)), "Bold")
    y += int(fb.size * 0.5)
    bx = margin + int(W * 0.03)
    for b in [b for b in (scene.get("bullets") or []) if b][:3]:
        lines = wrap(d, b, fb, W - bx - margin - int(fb.size * 1.6))[:2]
        d.ellipse([bx, y + int(fb.size * 0.36), bx + int(fb.size * 0.36), y + int(fb.size * 0.72)], fill=accent)
        for ln in lines:
            d.text((bx + int(fb.size * 0.9), y), ln, font=fb, fill=(245, 245, 245),
                   stroke_width=max(2, fb.size // 16), stroke_fill=(0, 0, 0))
            y += int(fb.size * 1.35)
        y += int(fb.size * 0.2)

    if channel:
        fc = font(int(W * (0.03 if vertical else 0.018)), "Bold")
        d.text((W - margin, int(H * 0.03)), channel, font=fc, fill=(230, 230, 230), anchor="ra")
    if total:
        fc = font(int(W * (0.025 if vertical else 0.015)), "Regular")
        d.text((margin, int(H * 0.03)), f"{index + 1}/{total}", font=fc, fill=(220, 220, 220))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out


def thumbnail(main: str, sub: str, theme: str, variant: int, out: Path, vertical: bool = False) -> Path:
    W, H = (1080, 1920) if vertical else (1280, 720)
    rng = _rng(main + str(variant))
    if theme == "light":
        bg, ink, accent = (250, 246, 232), (20, 20, 20), [(230, 40, 40), (20, 110, 230), (240, 160, 0)][variant % 3]
    else:
        bg, ink, accent = (14, 16, 22), (255, 255, 255), [(255, 214, 0), (80, 230, 160), (255, 90, 90)][variant % 3]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    layout = 1 if vertical else variant % 2
    if vertical and variant % 2:  # second vertical look: accent band on top
        d.rectangle([0, 0, W, int(H * 0.08)], fill=accent)
    if layout == 0:  # big type left, accent block right
        d.rectangle([int(W * 0.66), 0, W, H], fill=accent)
        for _ in range(5):
            r = rng.randint(30, 120)
            x, y = rng.randint(int(W * 0.68), W), rng.randint(0, H)
            d.ellipse([x - r, y - r, x + r, y + r], outline=bg, width=8)
        f, lines = fit_lines(d, main, int(H * 0.24), 60, int(W * 0.6), 3, balanced=True)
        fs, sl = fit_lines(d, sub, int(H * 0.07), 28, int(W * 0.6), 2, "Bold")
        lh = int(f.size * 1.2)
        block = len(lines) * lh + int(f.size * 0.25) + len(sl) * int(fs.size * 1.25)
        y = max(30, (H - block) // 2)
        for ln in lines:
            d.text((50 + 6, y + 6), ln, font=f, fill=accent if theme == "dark" else (200, 200, 200))
            d.text((50, y), ln, font=f, fill=ink)
            y += lh
        draw_block(d, (54, y + int(f.size * 0.25)), sl, fs, accent if theme == "dark" else ink, 1.25)
    else:  # centred big type with a band underneath for the sub line
        f, lines = fit_lines(d, main, int(min(H * 0.22, W * 0.28)), 56, W - 120, 3 if vertical else 2, balanced=True)
        lh = int(f.size * 1.22)
        fs, sl = fit_lines(d, sub, int(min(H * 0.075, W * 0.08)), 28, W - 100, 1, "Black")
        band_h = int(fs.size * 2.0)
        block = len(lines) * lh + int(H * 0.03) + band_h
        y = max(int(H * 0.1 if vertical and variant % 2 else 30), (H - block) // 2)
        for ln in lines:
            w = d.textlength(ln, font=f)
            d.text(((W - w) / 2, y), ln, font=f, fill=ink, stroke_width=4, stroke_fill=accent)
            y += lh
        band_top = y + int(H * 0.03)
        d.rectangle([0, band_top, W, band_top + band_h], fill=accent)
        if sl:
            d.text((W / 2, band_top + band_h / 2), sl[0], font=fs, fill=bg, anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out


def carousel_card(heading: str, body: str, idx: int, total: int, out: Path, channel: str = "") -> Path:
    W, H = 1080, 1350
    first, last = idx == 0, idx == total - 1
    bg = (17, 24, 39) if first or last else (250, 248, 243)
    ink = (255, 255, 255) if first or last else (17, 24, 39)
    accent = (255, 196, 0)
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 16], fill=accent)
    f, lines = fit_lines(d, heading, 120 if first else 88, 48, W - 160, 4)
    y = draw_block(d, (80, 200 if first else 140), lines, f, accent if first else ink, 1.2)
    fb = font(46, "Regular")
    y += 40
    for ln in wrap(d, body, fb, W - 160):
        d.text((80, y), ln, font=fb, fill=ink)
        y += 70
    fc = font(34, "Bold")
    d.text((80, H - 90), channel, font=fc, fill=(150, 150, 150))
    d.text((W - 80, H - 90), f"{idx + 1} / {total}", font=fc, fill=(150, 150, 150), anchor="ra")
    if not last:
        d.text((W - 80, H - 160), "滑 →", font=fc, fill=accent, anchor="ra")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out
