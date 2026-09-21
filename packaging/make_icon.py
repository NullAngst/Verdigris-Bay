#!/usr/bin/env python3
"""Regenerate the game icon (assets/icon.png, .ico, .icns).

Build-time only: needs Pillow (pip install pillow). The game itself never
imports this and stays pure standard library.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageChops

S = 2048                       # supersampled canvas, downscaled at the end
OUT = Path(__file__).resolve().parent.parent / "assets"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def vgradient(size, top, bottom):
    w, h = size
    img = Image.new("RGBA", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=lerp(top, bottom, y / max(1, h - 1)))
    return img


def glow(layer, radius, strength=2):
    g = layer.filter(ImageFilter.GaussianBlur(radius))
    out = g
    for _ in range(strength - 1):
        out = ImageChops.add(out, g)
    return out


def build():
    corner = int(S * 0.22)
    horizon = int(S * 0.64)

    # Rounded-square mask
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], corner, fill=255)

    # Sky
    img = vgradient((S, S), (18, 8, 42, 255), (6, 10, 22, 255))

    # Synthwave sun, sliced in its lower half
    sun_r = int(S * 0.30)
    cx, cy = S // 2, int(horizon - S * 0.02)
    sun = vgradient((S, S), (255, 196, 70, 255), (255, 40, 150, 255))
    sm = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(sm)
    sd.ellipse([cx - sun_r, cy - sun_r, cx + sun_r, cy + sun_r], fill=255)
    gap, band, y = 10, 70, cy - int(sun_r * 0.15)
    while y < cy + sun_r:
        sd.rectangle([0, y, S, y + gap], fill=0)
        y += band
        gap += 9
    sd.rectangle([0, horizon, S, S], fill=0)
    sun_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sun_layer.paste(sun, (0, 0), sm)
    img = ImageChops.add(img, glow(sun_layer, 60, 1))
    img.alpha_composite(sun_layer)

    # Water: dark verdigris with reflection streaks
    water = vgradient((S, S - horizon), (8, 40, 44, 255), (3, 12, 16, 255))
    img.paste(water, (0, horizon))
    d = ImageDraw.Draw(img)
    streak_y = horizon + 30
    step = 34
    i = 0
    while streak_y < S:
        half = int(sun_r * (0.95 - i * 0.07))
        if half > 20:
            col = lerp((255, 70, 160), (60, 200, 170), min(1, i / 7))
            d.line([(cx - half, streak_y), (cx + half, streak_y)],
                   fill=col + (255,), width=max(4, 14 - i))
        streak_y += step
        step += 10
        i += 1
    d.line([(0, horizon), (S, horizon)], fill=(90, 255, 220, 255), width=10)

    # The V: thick chevron with a cyan-verdigris glow
    v = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    vd = ImageDraw.Draw(v)
    top_y, bot_y = int(S * 0.20), int(S * 0.80)
    arm = int(S * 0.27)
    thick = int(S * 0.085)
    vd.line([(cx - arm, top_y), (cx, bot_y)], fill=(70, 235, 200, 255), width=thick)
    vd.line([(cx + arm, top_y), (cx, bot_y)], fill=(70, 235, 200, 255), width=thick)
    # square off the tips
    vd.rectangle([cx - arm - thick, top_y - thick, cx + arm + thick, top_y - thick // 2 + 4],
                 fill=(0, 0, 0, 0))
    # inner highlight
    inner = int(thick * 0.28)
    vd.line([(cx - arm, top_y), (cx, bot_y)], fill=(200, 255, 245, 255), width=inner)
    vd.line([(cx + arm, top_y), (cx, bot_y)], fill=(200, 255, 245, 255), width=inner)
    img = ImageChops.add(img, glow(v, 45, 2))
    img.alpha_composite(v)

    # Neon border
    b = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(b).rounded_rectangle([28, 28, S - 29, S - 29], corner - 24,
                                         outline=(0, 224, 255, 255), width=18)
    img = ImageChops.add(img, glow(b, 22, 1))
    img.alpha_composite(b)

    img.putalpha(mask)
    return img.resize((1024, 1024), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    master = build()
    master.save(OUT / "icon.png")
    master.resize((256, 256), Image.LANCZOS).save(OUT / "icon-256.png")
    master.save(OUT / "icon.ico",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                       (128, 128), (256, 256)])
    master.save(OUT / "icon.icns")
    for p in sorted(OUT.iterdir()):
        print(p.name, p.stat().st_size)


if __name__ == "__main__":
    main()
