"""Draw the app icon: a firmware chip marked PMM over a dotted drum waveform, on the Mod Matrix's purple.

Writes assets/icon.png (1024 px), assets/icon.icns (macOS) and assets/icon.ico (Windows).
The outputs are committed, so builds (and CI) don't need this script. Needs Pillow and the
macOS DIN Alternate Bold font: run it on a Mac with  python3 scripts/make_icon.py
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'assets')
FONT = '/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf'

# the Mod Matrix's palette (launcher/ui/shell.css)
PURPLE, BLUE, LIGHTBLUE, TEXT = '#40318d', '#352879', '#6c5eb5', '#a59ffd'
YELLOW, WHITE, CYAN = '#b8c76f', '#ffffff', '#70a4b2'

S = 4                # supersampling
N = 1024 * S


def px(v):
    return int(v * S)


def rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def draw():
    img = Image.new('RGBA', (N, N), (0, 0, 0, 0))

    # tile: Apple's grid, 824 px rounded square centred on 1024, with a soft shadow
    x0, x1, r = px(100), px(924), px(185)
    shadow = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0, x0 + px(12), x1, x1 + px(12)), r, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(px(12))))

    # vertical gradient from the light purple to the dark blue-purple
    top, bot = rgb(LIGHTBLUE), rgb(BLUE)
    grad = Image.new('RGBA', (1, N))
    for y in range(N):
        t = min(max((y - x0) / (x1 - x0), 0), 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
    grad = grad.resize((N, N))
    mask = Image.new('L', (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0, x0, x1, x1), r, fill=255)
    img.paste(grad, (0, 0), mask)

    # sound: a recorded drum track, drawn in dots (dense noise, sharp hits that decay), behind
    # the chip; seeded, so every run draws the same icon
    waves = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    w = ImageDraw.Draw(waves)
    rnd = random.Random(1983)
    mid_y, amp = N / 2, px(360)
    hits, x = [], 70
    while x < 960:                                   # a hit every ~48 px, varied loudness
        hits.append((x, rnd.uniform(0.3, 1.0), rnd.uniform(11, 26)))
        x += rnd.choice((32, 48, 48, 64))

    def env(xp):
        e = 0.09
        for hx, level, tau in hits:
            if xp >= hx - 4:
                rise = min((xp - hx + 4) / 4, 1)
                e = max(e, level * rise * math.exp(-max(xp - hx, 0) / tau))
        return e

    dot = px(2.1)
    colour = rgb(TEXT)
    for col in range(100, 925, 2):
        e = env(col)
        for _ in range(int(12 + 85 * e)):
            y = e * amp * rnd.random() ** 1.7 * rnd.choice((-1, 1))
            cx, cy = px(col) + rnd.uniform(-S, S), mid_y + y
            w.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=colour + (255,))
        if rnd.random() < 0.05:                      # stray dots above and below
            cy = mid_y + rnd.uniform(-1.25, 1.25) * amp
            w.ellipse((px(col) - dot, cy - dot, px(col) + dot, cy + dot), fill=colour + (200,))
    wmask = Image.new('L', (N, N), 0)
    ImageDraw.Draw(wmask).rounded_rectangle((x0, x0, x1, x1), r, fill=255)
    clipped = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    clipped.paste(waves, (0, 0), Image.composite(waves.getchannel('A'), Image.new('L', (N, N), 0), wmask))
    img.alpha_composite(clipped)

    d = ImageDraw.Draw(img)

    # chip: square body with 6 pins a side, on a soft shadow so it sits above the waves
    c0, c1 = px(322), px(702)              # body
    pin_len, pin_w, pins = px(54), px(26), 6
    sh = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((c0 - pin_len, c0 - pin_len + px(10), c1 + pin_len, c1 + pin_len + px(10)), px(50), fill=(20, 10, 60, 90))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(px(18))))
    span = c1 - c0
    for i in range(pins):
        mid = c0 + span * (i + 0.5) / pins
        a, b = mid - pin_w / 2, mid + pin_w / 2
        rr = px(7)
        d.rounded_rectangle((a, c0 - pin_len, b, c0 + px(10)), rr, fill=TEXT)   # top
        d.rounded_rectangle((a, c1 - px(10), b, c1 + pin_len), rr, fill=TEXT)   # bottom
        d.rounded_rectangle((c0 - pin_len, a, c0 + px(10), b), rr, fill=TEXT)   # left
        d.rounded_rectangle((c1 - px(10), a, c1 + pin_len, b), rr, fill=TEXT)   # right

    d.rounded_rectangle((c0, c0, c1, c1), px(40), fill=PURPLE, outline=TEXT, width=px(12))
    # inner die line and the pin-1 dot
    inset = px(40)
    d.rounded_rectangle((c0 + inset, c0 + inset, c1 - inset, c1 - inset), px(18), outline=LIGHTBLUE, width=px(5))
    dot = px(18)
    cx, cy = c0 + px(74), c0 + px(74)
    d.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=YELLOW)

    # PMM
    font = ImageFont.truetype(FONT, px(132))
    text = 'PMM'
    l, t, rgt, btm = d.textbbox((0, 0), text, font=font)
    mid = (c0 + c1) / 2
    d.text((mid - (l + rgt) / 2, mid - (t + btm) / 2 + px(12)), text, font=font, fill=WHITE)

    return img.resize((1024, 1024), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    img = draw()
    img.save(os.path.join(OUT, 'icon.png'))
    img.save(os.path.join(OUT, 'icon.icns'),
             append_images=[img.resize((s, s), Image.LANCZOS) for s in (16, 32, 64, 128, 256, 512)])
    img.save(os.path.join(OUT, 'icon.ico'), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print('wrote assets/icon.png, icon.icns, icon.ico')


if __name__ == '__main__':
    main()
