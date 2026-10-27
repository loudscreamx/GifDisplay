"""Виджеты с датчиками поверх картинки: шрифт, цвет, положение и показ настраиваются для каждого."""
import copy
import glob
import os
import uuid
import winreg

from PIL import Image, ImageDraw, ImageFont

import clockfmt
from i18n import screen_tr
from sensors import format_value

W = H = 320
SAFE = 10  # отступ от края экрана: надписи не заходят ближе
FONT_DIR = r"C:\Windows\Fonts"
BUNDLED_FONTS =os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FALLBACK_FONT = "Segoe UI"

WIDGET_DEFAULTS = {
    "sensor": "cpu_load", "label": "CPU", "show": True, "label_on": True,
    "x": 18, "y": 228, "font": "Segoe UI Bold", "size": 40, "label_size": 15,
    "color": "#ffffff", "label_color": "#d2d2dc", "warn_at": 0, "warn_color": "#ff5a5a", "shadow": True,
    "label_shadow": True, "label_gap": 3,
    "clock_12h": False, "clock_sec": False, "date_fmt": "dmy",  # только для виджетов «Часы» и «Дата»
}


def installed_fonts():
    """{имя шрифта: файл} из реестра шрифтов Windows (только .ttf/.otf)."""
    fonts = {}
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[1]):
                name, path, _ = winreg.EnumValue(key, i)
                if "&" in name or not str(path).lower().endswith((".ttf", ".otf")):
                    continue
                for suffix in (" (TrueType)", " (OpenType)"):
                    name = name.replace(suffix, "")
                fonts[name] = path if os.path.isabs(path) else os.path.join(FONT_DIR, path)
    return fonts


def new_widget(**kw):
    w = copy.deepcopy(WIDGET_DEFAULTS)
    w.update(kw)
    w["uid"] = uuid.uuid4().hex[:6]
    return w


# подписи готовых виджетов, которые лежат в списке выключенными, пока их не включат
EXTRA_LABELS = {"cpu_temp": "CPU t", "gpu_load": "GPU", "ram_load": "RAM", "gpu_power": "GPU Вт",
                "gpu_fan": "Кулер GPU", "liquid_temp": "Жидкость", "pump_rpm": "Помпа", "cpu_fan": "Кулер CPU",
                "net_down": "Сеть ↓", "net_up": "Сеть ↑", "case_fan": "Корпус", "igpu_temp": "iGPU",
                "gpu_mem": "VRAM", "gpu_clock": "GPU МГц", "clock": "", "date": ""}

LABELS = {"cpu_load": "CPU", "gpu_temp": "GPU", **EXTRA_LABELS}  # подписи по умолчанию для всех датчиков (по-русски: это ключи перевода)


def label_for(sensor):
    """Подпись по умолчанию на языке интерфейса (на экране: латиница или кириллица, иначе английская)."""
    return screen_tr(LABELS.get(sensor, sensor))


def hidden_widgets(sensors, start=0):
    """Выключенные готовые виджеты для датчиков sensors; start сдвигает стартовые положения, чтобы не слипались."""
    return [new_widget(sensor=s, label=label_for(s), show=False, size=26, label_size=13,
                       x=18 + ((start + i) % 2) * 150, y=16 + (((start + i) // 2) % 5) * 52)
            for i, s in enumerate(sensors)]


def default_widgets():
    ws = [
        new_widget(sensor="cpu_load", label=label_for("cpu_load"), x=18, y=228),
        new_widget(sensor="gpu_temp", label=label_for("gpu_temp"), x=170, y=228),
    ]
    ws += hidden_widgets(EXTRA_LABELS)
    return ws


# прежние подписи по умолчанию, которые заменены новыми: переименовываем только если пользователь их не менял
RENAMED_LABELS = {("gpu_load", "GPU %"): "GPU"}


def normalize(widgets):
    """Добивает недостающие поля из шаблона (настройки от старых версий программы)."""
    out = []
    for w in widgets:
        n = new_widget()
        n.update({k: v for k, v in w.items() if k in n or k == "uid"})
        n["label"] = RENAMED_LABELS.get((n["sensor"], n["label"]), n["label"])
        out.append(n)
    return out


class Overlay:
    def __init__(self, sensors):
        self.sensors = sensors
        self.widgets = default_widgets()
        self.shade_dir = "bottom"  # off / bottom / top / left / right: с какой стороны затемнять
        self.safe = 0  # вплотную к краю
        self.fonts = installed_fonts()
        self._cache = {}
        for font_path in sorted(glob.glob(os.path.join(BUNDLED_FONTS, "*.[to]tf"))):  # шрифты, поставляемые с программой
            self.add_font(font_path)
        self.boxes = {}  # uid -> (x0, y0, x1, y1): по ним превью находит виджет под курсором
        self.shifts = {}  # uid -> (dx, dy): сдвиг внутрь безопасной зоны, применённый при рисовании
        self._cache = {}
        self._shades = {}

    def add_font(self, path):
        """Подключает шрифт из файла .ttf/.otf; возвращает его имя в списке или None, если файл не открылся."""
        try:
            family, style = ImageFont.truetype(path, 12).getname()
        except (OSError, ValueError):
            return None
        name = family if style in ("Regular", "Normal", "") else f"{family} {style}"
        self.fonts[name] = path
        self._cache = {k: v for k, v in self._cache.items() if k[0] != name}  # старые размеры этого имени устарели
        return name

    def _shade(self, direction):
        """Полупрозрачный чёрный градиент у выбранного края: прозрачный до 110 px от противоположного края."""
        sh = self._shades.get(direction)
        if sh is None:
            sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(sh)
            for i in range(H):  # i = расстояние от противоположного края
                line = {"bottom": [(0, i), (W, i)], "top": [(0, H - 1 - i), (W, H - 1 - i)],
                        "right": [(i, 0), (i, H)], "left": [(W - 1 - i, 0), (W - 1 - i, H)]}[direction]
                d.line(line, fill=(0, 0, 0, int(max(0, (i - 110) / (H - 110)) * 190)))
            self._shades[direction] = sh
        return sh

    def font(self, name, size):
        key = (name, int(size))
        f = self._cache.get(key)
        if f is None:
            path = self.fonts.get(name) or self.fonts.get(FALLBACK_FONT)
            try:
                f = ImageFont.truetype(path, int(size))
            except (OSError, TypeError):
                f = ImageFont.load_default()
            self._cache[key] = f
        return f

    def _text(self, d, xy, text, font, fill, shadow=True):
        if shadow:
            d.text((xy[0] + 1, xy[1] + 1), text, font=font, fill=(0, 0, 0, 255))
        d.text(xy, text, font=font, fill=fill)
        return d.textbbox(xy, text, font=font)

    def _measure(self, d, w):
        """Текст, цвет и рамка виджета относительно его (x, y); рамка включает тень (она выступает на 1 px)."""
        v = self.sensors.data.get(w["sensor"])
        own = w["sensor"] in ("clock", "date")  # время и дата: без подписи, текст из системных часов
        if w["sensor"] == "clock":
            text = clockfmt.time_text(w)
        elif w["sensor"] == "date":
            text = clockfmt.date_text(w["date_fmt"])
        else:
            text = format_value(w["sensor"], v)
        label = "" if own else w["label"]
        color = w["warn_color"] if v is not None and w["warn_at"] and v >= w["warn_at"] else w["color"]
        fl, fv = self.font(w["font"], w["label_size"]), self.font(w["font"], w["size"])
        has_label = bool(w["label_on"] and w["label"]) and not own
        # значение ставим под подписью так, чтобы между буквами было label_gap px (по границам букв, не по размеру шрифта)
        lb = d.textbbox((0, 0), label, font=fl) if has_label else None
        vy = lb[3] + w["label_gap"] - d.textbbox((0, 0), text, font=fv)[1] if has_label else 0
        parts = [(d.textbbox((0, vy), text, font=fv), 1 if w["shadow"] else 0)]  # (рамка, выступ тени)
        if has_label:
            parts.append((lb, 1 if w["label_shadow"] else 0))
        box = (min(b[0] for b, _ in parts), min(b[1] for b, _ in parts),
               max(b[2] + e for b, e in parts), max(b[3] + e for b, e in parts))
        return text, color, fl, fv, has_label, vy, box, label

    def measure(self, w):
        """Рамка виджета на экране (x0, y0, x1, y1) по текущим данным, без рисования: для привязки и выравнивания."""
        d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        x0, y0, x1, y1 = self._measure(d, w)[6]  # шестой элемент результата — рамка
        return w["x"] + x0, w["y"] + y0, w["x"] + x1, w["y"] + y1

    def apply(self, img, draw_widgets=True):
        """Затемнение и (если draw_widgets) виджеты датчиков. Затемнение не зависит от показа датчиков."""
        if not draw_widgets:
            self.boxes = {}
            if self.shade_dir == "off":
                return img
        SAFE = self.safe  # отступ надписей от края экрана, настраивается в окне
        img = img.convert("RGBA")
        if self.shade_dir != "off":
            img = Image.alpha_composite(img, self._shade(self.shade_dir))
        if not draw_widgets:
            return img.convert("RGB")
        d = ImageDraw.Draw(img)
        boxes, shifts = {}, {}
        for w in list(self.widgets):
            if not w["show"]:
                continue
            text, color, fl, fv, has_label, vy, (x0, y0, x1, y1), label = self._measure(d, w)
            x, y = w["x"], w["y"]
            dx = dy = 0  # держим надпись целиком внутри безопасной зоны (слева/сверху важнее)
            if x + x1 > W - SAFE:
                dx = W - SAFE - (x + x1)
            if x + x0 + dx < SAFE:
                dx = SAFE - (x + x0)
            if y + y1 > H - SAFE:
                dy = H - SAFE - (y + y1)
            if y + y0 + dy < SAFE:
                dy = SAFE - (y + y0)
            if dx or dy:  # сдвиг только на время рисования: сохранённое положение не трогаем, чтобы оно вернулось
                x, y = x + dx, y + dy  # при уменьшении отступа
            shifts[w["uid"]] = (dx, dy)
            if has_label:
                self._text(d, (x, y), label, fl, w["label_color"], w["label_shadow"])
            self._text(d, (x, y + vy), text, fv, color, w["shadow"])
            boxes[w["uid"]] = (x + x0, y + y0, x + x1, y + y1)
        self.boxes = boxes
        self.shifts = shifts  # на сколько отрисовка сдвинула виджет относительно сохранённого положения
        return img.convert("RGB")
