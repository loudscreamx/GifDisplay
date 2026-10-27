"""Рисует анимацию с котом (тот же спрайт, что в иконке) для экрана 320x320: media/cat_idle.gif.

Кот моргает, шевелит ухом и чуть «дышит», на фоне мерцают звёздочки. Внизу оставлено свободное место
под надписи датчиков. Запуск: python make_cat_gif.py
"""
import os

from PIL import Image

import make_cat_icon as cat

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "media", "cat_idle.gif")
GRID = 40            # сетка кадра 40x40, каждая клетка 8x8 px = 320x320
SCALE = 8
STEP = 100           # мс на кадр
TOTAL = 8000         # мс на весь цикл
OFFSET = (4, 1)      # левый верхний угол кота в сетке: по центру и выше, снизу остаётся место под цифры

BG = cat.PALETTE["B"]
STAR = (150, 140, 200)
STARS = [(2, 4, 0), (36, 6, 5), (1, 17, 9), (38, 20, 3), (3, 31, 7), (37, 33, 12), (19, 1, 8)]  # x, y, фаза

BLINKS = (2200, 6300, 6800)      # начало моргания, мс
EAR_TWITCH = (4000, 7300)        # начало движения ухом, мс


def sprite(eyes="open", ear=False):
    """32x32 клетки спрайта кота: левая половина из make_cat_icon, правая зеркалится."""
    rows = [list(r + r[::-1]) for r in cat.LEFT]
    if eyes != "open":
        for y in range(11, 17):  # стираем глаза: вместо них шерсть
            for x in list(range(5, 12)) + list(range(20, 27)):
                if rows[y][x] == "K" or rows[y][x] == "W":
                    rows[y][x] = "O"
        if eyes == "half":       # прищур: нижняя часть глаза без блика
            for y in (14, 15):
                for x in list(range(6, 11)) + list(range(21, 26)):
                    rows[y][x] = "K"
        else:                    # закрыты: тонкая линия
            for x in list(range(6, 11)) + list(range(21, 26)):
                rows[15][x] = "K"
    if ear:  # левое ухо чуть откидывается влево: сдвигаем его пиксели на клетку
        for y in range(2, 6):
            seg = rows[y][2:9]
            rows[y][2:9] = ["B"] * 7
            rows[y][1:8] = [c if c != "B" else rows[y][1 + i] for i, c in enumerate(seg)]
    return rows


def state(t):
    """Состояние кота и смещение «дыхания» в момент t (мс)."""
    eyes = "open"
    for b in BLINKS:
        if b <= t < b + 100 or b + 200 <= t < b + 300:
            eyes = "half"
        elif b + 100 <= t < b + 200:
            eyes = "closed"
    ear = any(e <= t < e + 100 or e + 200 <= t < e + 300 for e in EAR_TWITCH)
    bob = 1 if (t // 700) % 2 else 0
    return eyes, ear, bob


def frame(t):
    img = Image.new("RGB", (GRID, GRID), BG)
    px = img.load()
    for x, y, phase in STARS:  # звёздочки мерцают с разными фазами
        if ((t // STEP) + phase) % 12 < 4:
            px[x, y] = STAR
    eyes, ear, bob = state(t)
    for y, row in enumerate(sprite(eyes, ear)):
        for x, ch in enumerate(row):
            if ch != "B":    # фон плитки пропускаем: у кадра свой фон со звёздами
                px[OFFSET[0] + x, OFFSET[1] + y + bob] = cat.PALETTE[ch]
    return img.resize((GRID * SCALE, GRID * SCALE), Image.NEAREST)


def main():
    frames = [frame(t) for t in range(0, TOTAL, STEP)]
    pal = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=16, dither=Image.Dither.NONE) for f in frames]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pal[0].save(OUT, save_all=True, append_images=pal[1:], duration=STEP, loop=0, optimize=False, disposal=1)
    print(f"{len(frames)} кадров, {os.path.getsize(OUT) / 1024:.0f} КБ -> {OUT}")


if __name__ == "__main__":
    main()
