"""Оформление окна: наборы цветов и их применение к стилям ttk. Меняется на лету, без перезапуска."""
import winreg

from PIL import Image, ImageDraw, ImageTk

# Цвета взяты из иконки с котом: фон плитки, серая шерсть, светлая мордочка, тёмный контур, розовый нос.
THEMES = {
    "Тёмная": dict(bg="#1b1626", panel="#241e33", field="#322a45", text="#e2e4ec", muted="#9296a2",
                   border="#4a4562", accent="#ee809c", accent2="#de788a", on_accent="#1b1626"),
    "Светлая": dict(bg="#eef0f6", panel="#ffffff", field="#dfe2ec", text="#2a2a36", muted="#626674",
                    border="#b4b8c8", accent="#d65d7e", accent2="#c24f6f", on_accent="#ffffff"),
}
CHOICES = ["Как в системе", "Тёмная", "Светлая"]
DEFAULT_CHOICE = "Как в системе"
FAMILY = "Segoe UI"  # один шрифт на всё окно

# галочка 8x8 пикселей; в флажке каждая клетка рисуется блоком 2x2
TICK = ("........",
        "......##",
        ".....##.",
        "##..##..",
        ".####...",
        "..##....",
        "........",
        "........")
CHECK = 20  # сторона флажка, px


def system_is_dark():
    """Тёмная ли тема приложений в Windows (параметр AppsUseLightTheme: 0 = тёмная)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


def resolve(choice):
    """Имя набора цветов по выбору в списке: «Как в системе» смотрит на настройку Windows."""
    if choice == "Светлая":
        return "Светлая"
    if choice == "Тёмная":
        return "Тёмная"
    return "Тёмная" if system_is_dark() else "Светлая"


def fonts(pixel=None):
    """(основной, кнопки и вкладки, мелкий, заголовок). Параметр оставлен для совместимости: шрифт один."""
    return (FAMILY, 10), (FAMILY, 9, "bold"), (FAMILY, 8), (FAMILY, 16, "bold")


def _flag(bg, fill, border, tick=None, gap=8):
    """Картинка флажка: квадрат с рамкой и отступ справа до подписи; с галочкой, если задан её цвет.
    bg=None даёт прозрачный фон: под картинкой видна подсветка выбранной строки списка."""
    im = Image.new("RGB", (CHECK + gap, CHECK), bg) if bg else Image.new("RGBA", (CHECK + gap, CHECK), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, CHECK - 1, CHECK - 1), fill=border)
    d.rectangle((2, 2, CHECK - 3, CHECK - 3), fill=fill)
    if tick:
        for y, row in enumerate(TICK):
            for x, ch in enumerate(row):
                if ch == "#":
                    d.rectangle((2 + x * 2, 2 + y * 2, 3 + x * 2, 3 + y * 2), fill=tick)
    return im


_flags = {}  # ключ -> ImageTk.PhotoImage; создаются один раз, при смене темы только перерисовываются


def _flag_images(root, t):
    bg = t["bg"]
    pics = {"off": _flag(bg, t["field"], t["border"]), "hover": _flag(bg, t["field"], t["accent"]),
            "on": _flag(bg, t["accent"], t["accent"], t["on_accent"])}
    created = bool(_flags)
    for key, im in pics.items():
        if key in _flags:
            _flags[key].paste(im)
        else:
            _flags[key] = ImageTk.PhotoImage(im, master=root)
    return created


_tree_flags = {}  # флажки для строк списка датчиков: фон панели вместо фона окна


def _tree_images(root, t):
    # фон прозрачный; у включённого рамка цвета «текст на акценте», чтобы квадрат был виден и на розовой выбранной строке
    pics = {False: _flag(None, t["field"], t["border"], gap=6),
            True: _flag(None, t["accent"], t["on_accent"], t["on_accent"], gap=6)}
    for key, im in pics.items():
        if key in _tree_flags:
            _tree_flags[key].paste(im)
        else:
            _tree_flags[key] = ImageTk.PhotoImage(im, master=root)


def tree_flag(on):
    """Картинка флажка для строки списка: включён / выключен."""
    return _tree_flags[bool(on)]


def apply(style, root, t, pixel=None):
    """Раскладывает цвета темы t по виджетам. Возвращает шрифты для обычных tk-виджетов."""
    f, fb, fs, fh = fonts()
    style.theme_use("clam")
    root.configure(bg=t["bg"])
    _tree_images(root, t)
    if not _flag_images(root, t):  # элемент и раскладку флажка создаём один раз
        style.element_create("flag.indicator", "image", _flags["off"], ("selected", _flags["on"]),
                             ("active", _flags["hover"]), sticky="")
        style.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("flag.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])
    style.configure(".", background=t["bg"], foreground=t["text"], bordercolor=t["border"], lightcolor=t["border"],
                    darkcolor=t["border"], troughcolor=t["field"], focuscolor=t["bg"], font=f)
    style.configure("TFrame", background=t["bg"])
    style.configure("TLabel", background=t["bg"], foreground=t["text"])
    style.configure("Muted.TLabel", background=t["bg"], foreground=t["muted"], font=fs)
    style.configure("Caption.TLabel", background=t["bg"], foreground=t["muted"], font=(FAMILY, 8, "bold"))
    style.configure("TCheckbutton", background=t["bg"], foreground=t["text"], padding=(0, 2))
    style.map("TCheckbutton", background=[("active", t["bg"])], foreground=[("active", t["accent"])])
    style.configure("TButton", background=t["field"], foreground=t["text"], borderwidth=2, relief="flat",
                    padding=(10, 6), font=fb, anchor="center")
    style.map("TButton", background=[("pressed", t["accent2"]), ("active", t["accent"])],
              foreground=[("pressed", t["on_accent"]), ("active", t["on_accent"])])
    style.configure("Small.TButton", background=t["field"], foreground=t["text"], borderwidth=2, relief="flat",
                    padding=(6, 6), font=fb, anchor="center")
    style.map("Small.TButton", background=[("pressed", t["accent2"]), ("active", t["accent"])],
              foreground=[("pressed", t["on_accent"]), ("active", t["on_accent"])])
    style.configure("Start.TButton", background=t["accent2"], foreground=t["on_accent"], borderwidth=2,
                    padding=(10, 9), font=fb)
    style.map("Start.TButton", background=[("pressed", t["accent"]), ("active", t["accent"])])
    for w in ("TCombobox", "TSpinbox", "TEntry"):
        style.configure(w, fieldbackground=t["field"], background=t["field"], foreground=t["text"],
                        insertcolor=t["text"], arrowcolor=t["text"], bordercolor=t["border"],
                        selectbackground=t["accent"], selectforeground=t["on_accent"], padding=4, font=f)
    style.map("TCombobox", fieldbackground=[("readonly", t["field"])], foreground=[("readonly", t["text"])],
              selectbackground=[("readonly", t["field"])], selectforeground=[("readonly", t["text"])],
              background=[("active", t["accent"])])
    style.map("TSpinbox", background=[("active", t["accent"])])
    style.configure("Horizontal.TScale", background=t["accent"], troughcolor=t["field"], bordercolor=t["border"],
                    lightcolor=t["accent"], darkcolor=t["accent"])
    style.layout("Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [  # без стрелки раскрытия
        ("Treeitem.image", {"side": "left", "sticky": ""}),
        ("Treeitem.focus", {"side": "left", "sticky": "", "children": [("Treeitem.text", {"side": "left", "sticky": ""})]})]})])
    style.configure("Vertical.TScrollbar", background=t["field"], troughcolor=t["panel"], bordercolor=t["border"],
                    arrowcolor=t["text"], lightcolor=t["field"], darkcolor=t["field"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", t["accent"])])
    style.configure("Treeview", background=t["panel"], fieldbackground=t["panel"], foreground=t["text"],
                    rowheight=24, bordercolor=t["border"], font=f)
    style.map("Treeview", background=[("selected", t["accent"])], foreground=[("selected", t["on_accent"])])
    for w in ("TCombobox", "TSpinbox", "TEntry"):  # размер шрифта внутри полей задаётся опцией виджета, не стилем
        root.option_add(f"*{w}.font", f)
    for opt, val in (("background", t["field"]), ("foreground", t["text"]), ("selectBackground", t["accent"]),
                     ("selectForeground", t["on_accent"]), ("font", f)):
        root.option_add(f"*TCombobox*Listbox.{opt}", val)
    return f, fb, fs, fh
