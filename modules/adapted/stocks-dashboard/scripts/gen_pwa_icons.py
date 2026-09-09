import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


# -*- coding: utf-8 -*-
"""Generate PWA / Android app icons from the STOCKSWORLD 'SW' brand badge.
Outputs to docs/: icon-192.png, icon-512.png, icon-512-maskable.png, apple-touch-icon.png.
  python scripts/gen_pwa_icons.py
Needs Pillow (pip install pillow). Uses the blue->indigo->violet brand gradient.
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs")

# brand gradient stops (blue-600 -> indigo-600 -> violet-600)
C0 = (37, 99, 235)
C1 = (79, 70, 229)
C2 = (124, 58, 237)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def grad_color(t):
    # t in [0,1] along the diagonal; two-segment interpolation through C1 at t=0.5
    if t < 0.5:
        return lerp(C0, C1, t / 0.5)
    return lerp(C1, C2, (t - 0.5) / 0.5)


def base_square(size):
    """Full-bleed diagonal-gradient square with a centered bold 'SW'."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    m = 2 * (size - 1)
    for y in range(size):
        for x in range(size):
            px[x, y] = grad_color((x + y) / m)
    d = ImageDraw.Draw(img)
    # bold font; fall back through a few common bold faces
    font = None
    for fp in (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, int(size * 0.40))
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    txt = "SW"
    box = d.textbbox((0, 0), txt, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    pos = ((size - tw) / 2 - box[0], (size - th) / 2 - box[1])
    # soft shadow then white text
    d.text((pos[0] + size * 0.012, pos[1] + size * 0.012), txt, font=font, fill=(15, 23, 42, 90))
    d.text(pos, txt, font=font, fill=(255, 255, 255))
    return img


def rounded(img, radius_frac=0.22):
    size = img.size[0]
    r = int(size * radius_frac)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def maskable(size=512):
    """Full-bleed gradient (no rounding) with SW kept inside the ~80% safe zone."""
    bg = base_square(size)  # full bleed; SW already centered at 40% — well within safe zone
    return bg.convert("RGBA")


def main():
    sq512 = base_square(512)
    rounded(sq512, 0.22).save(os.path.join(OUT, "icon-512.png"))
    rounded(sq512.resize((192, 192), Image.LANCZOS), 0.22).save(os.path.join(OUT, "icon-192.png"))
    maskable(512).save(os.path.join(OUT, "icon-512-maskable.png"))
    # apple touch icon: full-bleed (iOS applies its own rounding), 180px
    base_square(180).convert("RGB").save(os.path.join(OUT, "apple-touch-icon.png"))
    for f in ("icon-192.png", "icon-512.png", "icon-512-maskable.png", "apple-touch-icon.png"):
        p = os.path.join(OUT, f)
        print("wrote %s (%d bytes)" % (f, os.path.getsize(p)))


if __name__ == "__main__":
    main()
