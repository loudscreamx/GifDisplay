"""Пиксель-арт иконка: кот «Хорошо, я понял». Рисуем левую половину морды 16x32 и зеркалим. -> icon.ico"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

PALETTE = {
    "B": (27, 22, 38),      # фон плитки
    "N": (42, 42, 54),      # контур
    "O": (146, 150, 162),   # серый
    "D": (98, 102, 116),    # полоски
    "L": (226, 228, 236),   # светлая мордочка
    "E": (222, 120, 138),   # внутри уха
    "K": (18, 12, 22),      # глаза
    "W": (255, 255, 255),   # блик
    "P": (238, 128, 156),   # нос
}

LEFT = [  # 32 строки по 16 символов: левая половина, центр справа
    "BBBBBBBBBBBBBBBB",
    "BBBBBBBBBBBBBBBB",
    "BBBBNNBBBBBBBBBB",
    "BBBNOONBBBBBBBBB",
    "BBNOEEONBBBBBBBB",
    "BBNOEEOONBBBBBBB",
    "BNOOEEOOONNNNNNN",
    "BNOOOOOOOOOODOOD",
    "BNOOOOOOOOOODOOD",
    "BNOOOOOOOOOOOOOD",
    "BNOOOOOOOOOOOOOO",
    "BNOOOOOKKKOOOOOO",
    "BNOOOOKKKKKOOOOO",
    "BNOOOOKWWKKOOOOO",
    "BNOOOOKWKKKOOOOO",
    "BNOOOOKKKKKOOOOO",
    "BNOOOOOKKKOOOOOO",
    "BNOOOOOOOOOLLLLL",
    "BNOOOOOOOOLLLPPP",
    "BNOOOOOOOOLLLLPP",
    "BNOOOOOOOLLLLLLN",
    "BNOOOOOOOLLLNNNL",
    "BNOOOOOOLLLLLLLL",
    "BNOOOOOOOLLLLLLL",
    "BBNOOOOOOOLLLLLL",
    "BBNOOOOOOOOLLLLL",
    "BBBNOOOOOOOOOLLL",
    "BBBBNNOOOOOOOOOO",
    "BBBBBBNNNNNNNNNN",
    "BBBBBBBBBBBBBBBB",
    "BBBBBBBBBBBBBBBB",
    "BBBBBBBBBBBBBBBB",
]


def build():
    img = Image.new("RGBA", (32, 32))
    px = img.load()
    for y, row in enumerate(LEFT):
        assert len(row) == 16, (y, len(row))
        full = row + row[::-1]
        for x, ch in enumerate(full):
            px[x, y] = PALETTE[ch] + (255,)
    return img


def tile(small, size=1024):
    cat = small.resize((size, size), Image.NEAREST)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 5, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(cat, (0, 0), mask)
    return out


def main():
    big = tile(build())
    big.resize((256, 256), Image.NEAREST).save(os.path.join(HERE, "icon_preview.png"))
    # маленькие размеры тоже масштабируем без сглаживания, чтобы пиксели оставались чёткими
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [big.resize((s, s), Image.NEAREST) for s in sizes]
    # имя файла меняем при каждой смене рисунка: Windows кэширует значки по пути
    frames[-1].save(os.path.join(HERE, "cat_gray.ico"), sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print("готово")


if __name__ == "__main__":
    main()
