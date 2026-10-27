"""Рисует icon.ico (и icon_preview.png) для GifDisplay."""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1024  # рисуем крупно, потом уменьшаем: края получаются гладкими
BG, PURPLE, PINK, CYAN = (20, 18, 28), (168, 85, 247), (236, 72, 153), (34, 211, 238)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, c1, c2):
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = lerp(c1, c2, (x + y) / (2 * size))
    return g


def arc_mask(box, start, end, width):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).arc(box, start, end, fill=255, width=width)
    return m


def draw():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # плитка
    tile = Image.new("L", (S, S), 0)
    ImageDraw.Draw(tile).rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=255)
    base = Image.new("RGBA", (S, S), BG + (255,))
    img.paste(base, (0, 0), tile)

    # свечение за кольцом
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ring_box = (170, 170, S - 170, S - 170)
    ImageDraw.Draw(glow).ellipse(ring_box, outline=PURPLE + (255,), width=70)
    glow = glow.filter(ImageFilter.GaussianBlur(38))
    img = Image.alpha_composite(img, glow)

    # неоновое кольцо с градиентом
    ring = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ring).ellipse(ring_box, outline=255, width=46)
    grad = gradient(S, PURPLE, PINK).convert("RGBA")
    img.paste(grad, (0, 0), ring)

    # экран внутри кольца: квадрат с закруглением
    scr = Image.new("L", (S, S), 0)
    ImageDraw.Draw(scr).rounded_rectangle((300, 300, S - 300, S - 300), radius=70, fill=255)
    screen = gradient(S, (46, 20, 96), (12, 60, 92)).convert("RGBA")
    img.paste(screen, (0, 0), scr)

    # дуга температуры и точка на конце
    box = (352, 352, S - 352, S - 352)
    d = ImageDraw.Draw(img)
    d.arc(box, 0, 360, fill=(255, 255, 255, 40), width=34)
    arc = arc_mask(box, 140, 400, 34)
    img.paste(gradient(S, CYAN, PINK).convert("RGBA"), (0, 0), arc)
    cx = cy = S // 2
    r = (S - 704) // 2
    ex, ey = cx + r * math.cos(math.radians(40)), cy + r * math.sin(math.radians(40))
    d.ellipse((ex - 30, ey - 30, ex + 30, ey + 30), fill=(255, 255, 255, 255))
    return img


def main():
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon_preview.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(os.path.join(HERE, "icon.ico"), sizes=[(s, s) for s in sizes])
    print("icon.ico готов")


if __name__ == "__main__":
    main()
