"""Окно управления GifDisplay."""
import copy
import ctypes
import json
import logging
import logging.handlers
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
import winreg
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

import gifdisplay as gd
import i18n
import clockfmt
import diagnostics
import theme
from i18n import tr, up
from overlay import default_widgets, hidden_widgets, label_for, normalize
from presets import PresetStore
from scrollframe import ScrollFrame
from sensors import CATALOG, SENSOR_ORDER, Sensors
from tray import Tray

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", "."), "GifDisplay")
CONFIG = os.path.join(CONFIG_DIR, "config.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GifDisplay"

os.makedirs(CONFIG_DIR, exist_ok=True)
logging.basicConfig(
    handlers=[logging.handlers.RotatingFileHandler(os.path.join(CONFIG_DIR, "log.txt"), maxBytes=200_000,
                                                   backupCount=1, encoding="utf-8")],
    level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("app")



def _initial_language():
    """Язык из настроек; пока не выбран: язык Windows, иначе английский."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            code = json.load(f).get("language")
    except (OSError, ValueError):
        code = None
    return code if code in i18n.LANGS else i18n.detect()


FROZEN = getattr(sys, "frozen", False)  # собранная программа (PyInstaller) или запуск из исходников
APP_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))  # ресурсы: ffmpeg, шрифты, переводы
i18n.set_language(_initial_language(), os.path.join(APP_DIR, "locales"))

PANEL_W = 440
# длинные подписи (немецкий, французский…) в форме датчика ужимают колонки, чтобы ничего не уходило под полосу прокрутки
TIGHT = i18n.language() in ("de", "fr", "es", "pt", "tr", "ja", "pl")
FORM_LABEL_W = 98 if TIGHT else 125
FORM_COLS = (46, 48, 48, 26) if TIGHT else (54, 58, 54, 36)
SCROLL_W = 0  # прибавка к ширине области вкладок: полоса прокрутки «Датчиков» входит в PANEL_W, окно остаётся прежним  # ширина правой панели: вкладки, поля и кнопки подгоняются под неё
SENSOR_NAMES = {k: tr(v[0]) for k, v in CATALOG.items()}


TASK_NAME = "GifDisplay"
IPC_PORT = int(os.environ.get("GIFDISPLAY_PORT", 47653))  # локальный порт для «покажи окно» от повторного запуска
ICON_FILE = "cat_gray.ico"
# что копирует «применить стиль ко всем»: оформление, но не подпись, положение, порог и видимость
STYLE_KEYS = ("font", "size", "label_size", "color", "label_color", "label_on", "warn_color", "shadow",
              "label_shadow", "label_gap")
SHADE_DIRS = {tr("Выкл"): "off", tr("Снизу"): "bottom", tr("Сверху"): "top", tr("Слева"): "left", tr("Справа"): "right"}


def widgets_from(raw, legacy_shadow=True):
    """Виджеты из настроек. Раньше тень была одной общей настройкой: выключенную переносим на виджеты без своей."""
    ws = normalize(raw)
    if legacy_shadow is False:
        for w, r in zip(ws, raw):
            if "shadow" not in r:
                w["shadow"] = w["label_shadow"] = False
    return ws


def shade_from(data):
    """Сторона затемнения из настроек или пресета; старые настройки хранили только флаг shade (вкл = снизу)."""
    d = data.get("shade_dir")
    if d in SHADE_DIRS.values():
        return d
    return "bottom" if data.get("shade", True) else "off"


DRAG_MODES = {tr("Свободно"): "free", tr("По сетке"): "grid"}
SCALE_MODES = {tr("Заполнить"): "fill", tr("Вписать"): "fit", tr("Растянуть"): "stretch", tr("По центру"): "center"}
PLAY_MODES = {tr("Зациклить"): "loop", tr("Туда-обратно"): "pingpong"}
EXE = sys.executable if FROZEN else os.path.join(os.path.dirname(sys.executable), "pythonw.exe")  # чем запускать себя
SCRIPT_ARGS = [] if FROZEN else [os.path.abspath(__file__)]
WORK_DIR = os.path.dirname(sys.executable) if FROZEN else APP_DIR
NO_WINDOW = subprocess.CREATE_NO_WINDOW


def btn_w(text, base):
    """Ширина маленькой кнопки в знаках: по подписи; иероглифы шире латиницы примерно вдвое."""
    return max(base, int(len(text) * (1.9 if i18n.language() in ("zh", "ja", "ko") else 1)) + 2)


def is_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def relaunch_as_admin():
    """Перезапуск себя с правами администратора. True, если новый процесс стартовал."""
    args = " ".join(f'"{a}"' for a in [*SCRIPT_ARGS, *sys.argv[1:]])
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", EXE, args, WORK_DIR, 1) > 32


def autostart_enabled():
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def _remove_run_entry():
    """Старый автозапуск через реестр заменён задачей планировщика."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, RUN_NAME)
    except OSError:
        pass


def set_autostart(on):
    """Задача при входе в систему с наивысшими правами: стартует без запроса UAC."""
    if on:
        script = f"""
$u = "$env:USERDOMAIN\\$env:USERNAME"
$a = New-ScheduledTaskAction -Execute '{EXE}' -Argument '{" ".join(f'"{a}"' for a in SCRIPT_ARGS)} --minimized' -WorkingDirectory '{WORK_DIR}'
$t = New-ScheduledTaskTrigger -AtLogOn -User $u
$p = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Highest
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
"""
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
        if r.returncode != 0:
            raise OSError(r.stderr.strip() or tr("не удалось создать задачу"))
        _remove_run_entry()
    else:
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, creationflags=NO_WINDOW)
        _remove_run_entry()


DEFAULT_PROFILE = os.path.join(APP_DIR, "default_profile.json")  # стандартный профиль: новые пользователи получают его сразу


def load_default_profile():
    """Настройки для первого запуска (когда своих ещё нет): стандартный профиль из default_profile.json, если он есть."""
    try:
        with open(DEFAULT_PROFILE, encoding="utf-8") as f:
            prof = json.load(f)
    except (OSError, ValueError):
        return {}
    media = prof.get("media")
    if media and not os.path.isabs(media):
        media = os.path.join(APP_DIR, media)  # путь в профиле относительно папки программы
    prof["media"] = media if media and os.path.exists(media) else None
    name = prof.pop("name", tr("Стандартный"))
    return dict(prof, presets={name: dict(prof)}, preset=name)  # профиль доступен и в списке пресетов


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GifDisplay")
        try:
            self.iconbitmap(os.path.join(APP_DIR, ICON_FILE))
        except tk.TclError:
            pass
        self.resizable(False, False)
        self.cfg = load_config() or load_default_profile()
        choice = self.cfg.get("theme_choice")
        self.theme_choice = choice if choice in theme.CHOICES else theme.DEFAULT_CHOICE
        self.theme_active = theme.resolve(self.theme_choice)
        self.t = dict(theme.THEMES[self.theme_active])
        self.drag_mode = self.cfg.get("drag_mode", "free") if self.cfg.get("drag_mode") in ("free", "grid") else "free"
        self.grid_step = self.cfg.get("grid_step", 10)
        self.pixel = None  # раньше переключал шрифт; сейчас шрифт один, параметр остаётся только в сигнатурах theme
        self.style = ttk.Style(self)
        # пресеты лежат файлами в папке presets рядом с программой; у установленной (в Program Files) они в настройках пользователя
        self.store = PresetStore(APP_DIR, CONFIG_DIR, user_first=FROZEN)
        self.presets = self.store.load_all()
        failed = {}
        for name, data in (self.cfg.pop("presets", None) or {}).items():  # пресеты прежних версий жили в настройках: переносим
            if name not in self.presets:
                try:
                    self.store.save(name, data)
                except OSError:
                    failed[name] = data
                self.presets[name] = data
        if failed:  # не удалось записать файл: оставляем в настройках, чтобы пресеты не потерялись
            log.warning("не удалось записать пресеты в папку %s", self.store.dir)
            self.cfg["presets"] = failed
        log.info("запуск: админ=%s, файл=%r (есть: %s), аргументы=%s", is_admin(), self.cfg.get("media"),
                 os.path.exists(self.cfg.get("media") or ""), sys.argv[1:])
        self.sensors = Sensors()
        self.streamer = gd.Streamer(self.sensors)
        s, ov = self.streamer, self.streamer.overlay
        s.brightness = self.cfg.get("brightness", 100)
        s.hw_min = self.cfg.get("hw_min", gd.HW_MIN_DEFAULT)
        s.speed = self.cfg.get("speed", 1.0)
        s.play_mode = self.cfg.get("play_mode") if self.cfg.get("play_mode") in PLAY_MODES.values() else "loop"
        s.scale_mode = self.cfg.get("scale_mode") if self.cfg.get("scale_mode") in SCALE_MODES.values() else "fill"
        s.show_sensors = self.cfg.get("show_sensors", True)
        ov.shade_dir = shade_from(self.cfg)
        ov.safe = self.cfg.get("safe", 0)
        for font_path in self.cfg.get("fonts", []):  # свои шрифты из файлов, добавленные раньше
            if os.path.exists(font_path):
                ov.add_font(font_path)
        if self.cfg.get("widgets"):
            ov.widgets = widgets_from(self.cfg["widgets"], self.cfg.get("shadow", True))
            # у каждого датчика всегда есть строка в списке: удалённые когда-то или новые возвращаются выключенными
            have = {w["sensor"] for w in ov.widgets}
            missing = [k for k in CATALOG if k not in have]
            if missing:
                ov.widgets += hidden_widgets(missing, start=len(ov.widgets))
        if self.cfg.get("media") and os.path.exists(self.cfg["media"]):
            s.set_media(self.cfg["media"])
        self.sel = None  # выбранный виджет (dict)
        self._loading = False
        self._drag = None
        self._last_frame = None
        self._img_item = None

        theme.apply(self.style, self, self.t, self.pixel)

        header = ttk.Frame(self, padding=(12, 12, 16, 0))  # правый край = край правой панели
        header.grid(row=0, column=0, columnspan=2, sticky="we")
        self.logo = ImageTk.PhotoImage(Image.open(os.path.join(APP_DIR, ICON_FILE)).resize((40, 40), Image.NEAREST))
        ttk.Label(header, image=self.logo).grid(row=0, column=0, padx=(0, 10))
        self.title_label = ttk.Label(header, text="GifDisplay", font=theme.fonts(self.pixel)[3])
        self.title_label.grid(row=0, column=1)
        header.columnconfigure(2, weight=1)
        pick = ttk.Frame(header)
        pick.grid(row=0, column=2, sticky="e")
        self.theme_names = {tr(c): c for c in theme.CHOICES}  # в списке названия на языке интерфейса, в настройках русские ключи
        ttk.Label(pick, text=up(tr("Тема")), style="Caption.TLabel").grid(row=0, column=0, padx=(0, 12))
        self.theme_var = tk.StringVar(value=tr(self.theme_choice))
        tc = ttk.Combobox(pick, textvariable=self.theme_var, values=list(self.theme_names), state="readonly", width=max(12, max(map(len, self.theme_names)) + 2))
        tc.grid(row=0, column=1)
        tc.bind("<<ComboboxSelected>>", lambda _: self.on_theme_choice())
        ttk.Label(pick, text=up(tr("Язык")), style="Caption.TLabel").grid(row=0, column=2, padx=(16, 12))
        self.lang_var = tk.StringVar(value=i18n.LANGS[i18n.language()])
        lc = ttk.Combobox(pick, textvariable=self.lang_var, values=list(i18n.LANGS.values()), state="readonly", width=11)
        lc.grid(row=0, column=3)
        lc.bind("<<ComboboxSelected>>", lambda _: self.on_language())

        left = self.left = ttk.Frame(self, padding=12)
        # рамка = отдельный фрейм: у самого холста рамки нет, иначе картинка смещается и справа/снизу видна чёрная полоса
        self.canvas_border = tk.Frame(left, bg=self.t["accent"], padx=3, pady=3)
        self.canvas_border.grid(row=0, column=0)
        self.canvas = tk.Canvas(self.canvas_border, width=gd.W, height=gd.H, bg="black", highlightthickness=0, bd=0)
        self.canvas.grid(row=0, column=0)
        self.draw_safe_frame()
        ttk.Label(left, text=tr("Виджеты можно перетаскивать мышкой"), style="Muted.TLabel").grid(row=1, column=0, pady=(6, 0))
        drag = ttk.Frame(left)
        drag.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(drag, text=up(tr("Выравнивание")), style="Caption.TLabel").grid(row=0, column=0, padx=(0, 12))
        self.drag_var = tk.StringVar(value=next((k for k, v in DRAG_MODES.items() if v == self.drag_mode), tr("Свободно")))
        cb = ttk.Combobox(drag, textvariable=self.drag_var, values=list(DRAG_MODES), state="readonly", width=10)
        cb.grid(row=0, column=1)
        cb.bind("<<ComboboxSelected>>", lambda _: self.on_drag_mode())
        self.step_box = ttk.Frame(drag)  # шаг нужен только для сетки: в режиме «Свободно» поле скрыто
        self.step_box.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(self.step_box, text=tr("шаг")).grid(row=0, column=0, padx=(0, 4))
        self.step_var = tk.IntVar(value=self.grid_step)
        sb = ttk.Spinbox(self.step_box, from_=2, to=50, textvariable=self.step_var, width=3, command=self.on_drag_mode)
        sb.grid(row=0, column=1)
        sb.bind("<KeyRelease>", lambda _: self.on_drag_mode())
        self.update_step_visibility()
        self.btn = ttk.Button(left, text=tr("Старт"), command=self.toggle, style="Start.TButton")
        self.btn.grid(row=3, column=0, sticky="we", pady=(12, 0))
        self.status = tk.StringVar()
        ttk.Label(left, textvariable=self.status, wraplength=gd.W).grid(row=4, column=0, sticky="w", pady=(10, 0))
        left.rowconfigure(5, weight=1)
        author = ttk.Frame(left)  # подпись автора внизу левой колонки
        author.grid(row=5, column=0, sticky="sw")
        ttk.Label(author, text=tr("Автор: loudscreamx ·"), style="Muted.TLabel").grid(row=0, column=0)
        link = ttk.Label(author, text="github.com/loudscreamx", style="Muted.TLabel", cursor="hand2")
        link.grid(row=0, column=1, padx=(4, 0))
        link.configure(font=(theme.fonts()[2][0], 8, "underline"))
        link.bind("<Button-1>", lambda _: webbrowser.open("https://github.com/loudscreamx"))
        diag = ttk.Label(author, text=tr("Диагностика"), style="Muted.TLabel", cursor="hand2")
        diag.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        diag.configure(font=(theme.fonts()[2][0], 8, "underline"))
        diag.bind("<Button-1>", lambda _: self.show_diagnostics())
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        right = self.right = ttk.Frame(self, padding=(0, 12, 16, 16))
        right.columnconfigure(0, minsize=PANEL_W)
        self.build_presets(right)
        bar = ttk.Frame(right)
        bar.grid(row=1, column=0, sticky="w", pady=(10, 0))
        host = ttk.Frame(right)
        host.grid(row=2, column=0, sticky="nwe", pady=(10, 0))
        host.columnconfigure(0, weight=1)
        self.pages, self.tab_buttons = {}, {}
        host.rowconfigure(0, weight=1)
        self.build_main(host)
        self.build_sensors(host)
        self.update_idletasks()  # размер окна задаёт «Основное»; «Датчики» в этой же области, лишнее прокручивается
        host.configure(width=PANEL_W + SCROLL_W, height=self.pages["Основное"].winfo_reqheight())
        host.grid_propagate(False)
        for i, name in enumerate(self.pages):  # свои вкладки: стандартные ttk-вкладки в этой теме капризничали
            b = tk.Button(bar, text=tr(name), relief="flat", bd=0, padx=14, pady=7, cursor="hand2",
                          command=lambda n=name: self.show_page(n))
            b.grid(row=0, column=i, padx=(0, 4))
            self.tab_buttons[name] = b
        self.current_page = "Основное"
        self.left.grid(row=1, column=0, sticky="n")
        self.right.grid(row=1, column=1, sticky="n")
        self.show_page(self.current_page)

        self.tray = Tray(os.path.join(APP_DIR, ICON_FILE), "GifDisplay", self.tray_menu)
        self.start_ipc()
        # крестик прячет окно в трей (если значок не создался, крестик закрывает программу)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray if self.tray.ok else self.close)
        if self.cfg.get("autostart_stream", True) and s.media:
            s.start()
        self.tick()
        self.draw_preview()

    # ---------- вкладка «Основное» ----------
    def show_page(self, name):
        self.current_page = name
        for n, page in self.pages.items():  # окно подстраивается под высоту вкладки, без пустого места
            if n == name:
                page.grid()
            else:
                page.grid_remove()
        t, fb = self.t, theme.fonts(self.pixel)[1]
        for n, b in self.tab_buttons.items():
            active = n == name
            b.configure(bg=t["accent"] if active else t["field"], fg=t["on_accent"] if active else t["text"],
                        activebackground=t["accent2"], activeforeground=t["on_accent"], font=fb)

    def draw_safe_frame(self):
        """Пунктир безопасной зоны в превью; на сам экран он не попадает. Совпадает с краем кадра пиксель в пиксель."""
        m = self.streamer.overlay.safe
        self.canvas.delete("frame")
        self.canvas.create_rectangle(m, m, gd.W - 1 - m, gd.H - 1 - m, outline="#8a86a0", dash=(4, 4), tags="frame")

    def on_scale(self):
        self.streamer.set_scale(SCALE_MODES[self.scale_var.get()])
        self.save()

    def on_play(self):
        self.streamer.set_play(PLAY_MODES[self.play_var.get()])
        self.save()

    def on_safe(self):
        try:
            v = max(0, min(30, int(self.safe_var.get())))
        except (ValueError, tk.TclError):
            return
        self.streamer.overlay.safe = v
        self.draw_safe_frame()
        self.save()

    def restyle(self):
        """Применяет self.t / self.pixel ко всему окну (после смены темы)."""
        theme.apply(self.style, self, self.t, self.pixel)
        self.title_label.configure(font=theme.fonts(self.pixel)[3])
        self.canvas_border.configure(bg=self.t["accent"])
        self.sens_scroll.set_bg(self.t["bg"])
        for b in self.swatches.values():  # цветные квадраты: рамка в цвет темы, пустые заполняются фоном полей
            b.configure(highlightbackground=self.t["muted"])
            if not self.sel:
                b.configure(bg=self.t["field"], activebackground=self.t["field"])
        self.show_page(self.current_page)

    def show_diagnostics(self):
        """Окно с отчётом о совместимости (найден ли экран, COM-порты, ffmpeg, права): его копируют в issue на GitHub."""
        text = diagnostics.build(status=status_text(self.streamer.status), sensors_mode=self.sensors.mode,
                                 language=i18n.language(), media_kind=os.path.splitext(self.streamer.media or "")[1].lower())
        win = tk.Toplevel(self)
        win.title(tr("Диагностика"))
        win.configure(bg=self.t["bg"])
        win.transient(self)
        box = tk.Text(win, width=78, height=19, wrap="word", bg=self.t["field"], fg=self.t["text"], relief="flat",
                      insertbackground=self.t["text"], font=("Consolas", 10), padx=10, pady=8)
        box.insert("1.0", text)
        box.configure(state="disabled")
        box.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 8))
        copy_btn = ttk.Button(win, text=tr("Копировать"), style="Small.TButton", width=btn_w(tr("Копировать"), 14))

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)
            copy_btn.configure(text=tr("Готово!"))
            win.after(1500, lambda: copy_btn.winfo_exists() and copy_btn.configure(text=tr("Копировать")))

        copy_btn.configure(command=copy)
        copy_btn.grid(row=1, column=0, sticky="e", padx=(12, 4), pady=(0, 12))
        ttk.Button(win, text=tr("Закрыть"), style="Small.TButton", width=btn_w(tr("Закрыть"), 10), command=win.destroy).grid(
            row=1, column=1, sticky="w", padx=(4, 12), pady=(0, 12))
        win.columnconfigure(0, weight=1)
        win.columnconfigure(1, weight=1)
        win.resizable(False, False)
        win.grab_set()

    def report_callback_exception(self, exc, val, tb):
        """Ошибки в обработчиках окна попадают в log.txt, а не пропадают вместе с консолью."""
        log.error("ошибка в обработчике", exc_info=(exc, val, tb))

    def on_language(self):
        """Язык применяется при перезапуске: окно строится один раз. Программа сама закрывается и запускается заново."""
        code = next((c for c, n in i18n.LANGS.items() if n == self.lang_var.get()), None)
        if not code or code == i18n.language():
            return
        self.cfg["language"] = code
        self.save()
        self.restart()

    def restart(self):
        """Запускает вторую копию, которая дожидается выхода этой, и закрывает эту."""
        args = [EXE, *SCRIPT_ARGS, "--wait-prev", *[x for x in sys.argv[1:] if x not in ("--minimized", "--wait-prev")]]
        self.close()
        subprocess.Popen(args, cwd=WORK_DIR, creationflags=NO_WINDOW)

    def on_theme_choice(self):
        self.theme_choice = self.theme_names.get(self.theme_var.get(), theme.DEFAULT_CHOICE)
        self.apply_theme_choice()
        self.save()

    def apply_theme_choice(self):
        active = theme.resolve(self.theme_choice)
        self.theme_active = active
        self.t = dict(theme.THEMES[active])
        self.restyle()

    def watch_system_theme(self):
        """При выборе «Как в системе» окно следом за Windows переключается между тёмной и светлой темой."""
        if self.theme_choice == theme.DEFAULT_CHOICE and theme.resolve(self.theme_choice) != self.theme_active:
            self.apply_theme_choice()

    # ---------- пресеты ----------
    def build_presets(self, parent):
        outer = ttk.Frame(parent)
        outer.grid(row=0, column=0, sticky="we")
        f = ttk.Frame(outer)
        f.grid(row=0, column=0, sticky="we")
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text=up(tr("Пресет")), style="Caption.TLabel").grid(row=0, column=0, padx=(0, 12))
        self.preset_var = tk.StringVar(value=self.cfg.get("preset", ""))
        self.preset_box = ttk.Combobox(f, textvariable=self.preset_var, values=sorted(self.presets), state="readonly", width=8)
        self.preset_box.grid(row=0, column=1, sticky="we")
        self.preset_box.bind("<<ComboboxSelected>>", lambda _: self.load_preset())
        ttk.Button(f, text=tr("Создать"), command=self.create_preset, style="Small.TButton").grid(row=0, column=2, padx=(8, 0))
        self.save_btn = ttk.Button(f, text=tr("Сохранить"), command=self.save_preset, style="Small.TButton")
        self.save_btn.grid(row=0, column=3, padx=(4, 0))
        ttk.Button(f, text=tr("Удалить"), command=self.delete_preset, style="Small.TButton").grid(row=0, column=4, padx=(4, 0))
        f.update_idletasks()  # ширина строки не зависит от длины подписей на разных языках: список пресетов сжимается
        f.configure(width=PANEL_W, height=f.winfo_reqheight())
        f.grid_propagate(False)
        where = ttk.Label(outer, text=tr("Пресеты хранятся в папке (нажми, чтобы открыть):\n{path}", path=self.store.dir), style="Muted.TLabel",
                          wraplength=PANEL_W, justify="left", cursor="hand2")
        where.grid(row=1, column=0, sticky="w", pady=(6, 0))
        where.bind("<Button-1>", lambda _: self.open_presets_folder())

    def snapshot(self):
        s, ov = self.streamer, self.streamer.overlay
        return copy.deepcopy(dict(media=s.media, brightness=s.brightness, speed=s.speed, play_mode=s.play_mode,
                                  scale_mode=s.scale_mode, show_sensors=s.show_sensors,
                                  shade_dir=ov.shade_dir, widgets=ov.widgets))

    def open_presets_folder(self):
        """Открывает папку с пресетами в проводнике."""
        try:
            os.startfile(self.store.dir)
        except OSError as e:
            messagebox.showerror("GifDisplay", tr("Не удалось открыть папку\n{path}\n{err}", path=self.store.dir, err=e), parent=self)

    def store_preset(self, name):
        """Записывает пресет файлом в папку presets; при ошибке сообщает, а пресет остаётся в памяти до закрытия."""
        try:
            self.store.save(name, self.presets[name])
        except OSError as e:
            messagebox.showerror("GifDisplay", tr("Не удалось записать пресет в папку\n{path}\n{err}", path=self.store.dir, err=e), parent=self)

    def create_preset(self):
        """Новый пресет из текущих настроек под новым именем."""
        name = simpledialog.askstring(tr("Новый пресет"), tr("Название пресета:"), parent=self)
        name = (name or "").strip()
        if not name:
            return
        if name in self.presets and not messagebox.askyesno("GifDisplay", tr("Пресет «{name}» уже есть. Заменить?", name=name), parent=self):
            return
        self.presets[name] = self.snapshot()
        self.store_preset(name)
        self.preset_var.set(name)
        self.preset_box.configure(values=sorted(self.presets))
        self.cfg["preset"] = name
        self.save()

    def save_preset(self):
        """Обновляет выбранный пресет текущими настройками; если пресет не выбран, создаёт новый."""
        name = self.preset_var.get()
        if name not in self.presets:
            return self.create_preset()
        self.presets[name] = self.snapshot()
        self.store_preset(name)
        self.save()
        self.save_btn.configure(text=tr("Готово!"))  # короткое подтверждение на самой кнопке
        self.after(1200, lambda: self.save_btn.configure(text=tr("Сохранить")))

    def load_preset(self):
        data = self.presets.get(self.preset_var.get())
        if not data:
            return
        s, ov = self.streamer, self.streamer.overlay
        data = copy.deepcopy(data)
        media = data.get("media")
        if media and os.path.exists(media):
            s.set_media(media)
            self.path_var.set(media)
        elif media:
            messagebox.showwarning("GifDisplay", tr("Файл из пресета не найден:\n{path}", path=media), parent=self)
        s.brightness = data.get("brightness", 100)
        self.bright.set(s.brightness)
        self.bright_text.set(f"{up(tr('Яркость экрана'))}  {s.brightness}%")
        speed = data.get("speed", 1.0)
        s.set_speed(speed)
        self.speed_var.set(speed)
        self.speed_text.set(f"{up(tr('Скорость'))}  {speed:.1f}×")
        mode = data.get("play_mode")  # старые пресеты могли хранить удалённые режимы «один раз» / «N раз»
        s.set_play(mode if mode in PLAY_MODES.values() else "loop")
        self.play_var.set(next((k for k, v in PLAY_MODES.items() if v == s.play_mode), tr("Зациклить")))
        scale = data.get("scale_mode")  # у пресетов старых версий этого поля нет: тогда «Заполнить»
        s.set_scale(scale if scale in SCALE_MODES.values() else "fill")
        self.scale_var.set(next((k for k, v in SCALE_MODES.items() if v == s.scale_mode), tr("Заполнить")))
        s.show_sensors = data.get("show_sensors", True)
        ov.shade_dir = shade_from(data)
        self.sens.set(s.show_sensors)
        self.shade_var.set(next((k for k, v in SHADE_DIRS.items() if v == ov.shade_dir), tr("Снизу")))
        if data.get("widgets"):
            ov.widgets = widgets_from(data["widgets"], data.get("shadow", True))
        self.select(None)
        self.refresh_tree()
        self.cfg["preset"] = self.preset_var.get()
        self.save()

    def delete_preset(self):
        name = self.preset_var.get()
        if name in self.presets and messagebox.askyesno("GifDisplay", tr("Удалить пресет «{name}»?", name=name), parent=self):
            del self.presets[name]
            self.store.delete(name)
            self.preset_var.set("")
            self.preset_box.configure(values=sorted(self.presets))
            self.cfg["preset"] = ""
            self.save()

    def caption(self, parent, row, text=None, var=None, pady=(12, 6), columnspan=2):
        """Подпись блока: пиксельный шрифт, заглавные. Все блоки отделяются одинаково (12 сверху, 6 до контрола)."""
        kw = {"textvariable": var} if var is not None else {"text": up(tr(text))}
        ttk.Label(parent, style="Caption.TLabel", **kw).grid(row=row, column=0, columnspan=columnspan, sticky="w", pady=pady)

    def build_main(self, parent):
        s, ov = self.streamer, self.streamer.overlay
        f = ttk.Frame(parent)
        f.grid(row=0, column=0, sticky="nsew")
        f.columnconfigure(1, weight=1)
        self.pages["Основное"] = f

        self.caption(f, 0, "Файл (гифка, видео, картинка)", pady=(0, 8))
        self.path_var = tk.StringVar(value=s.media or tr("не выбран"))
        ttk.Label(f, textvariable=self.path_var, wraplength=PANEL_W).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Button(f, text=tr("Выбрать файл…"), command=self.pick).grid(row=2, column=0, columnspan=2, sticky="we")
        video = ", ".join(e[1:].upper() for e in gd.VIDEO_EXTS)
        still = ", ".join(e[1:].upper() for e in gd.STILL_EXTS)
        ttk.Label(f, text=tr("Гифки и видео: {video}.\nКартинки (неподвижно): {still}.\nЗвук не играет.", video=video, still=still),
                  style="Muted.TLabel", wraplength=PANEL_W, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.bright_text = tk.StringVar(value=f"{up(tr('Яркость экрана'))}  {s.brightness}%")
        self.caption(f, 4, var=self.bright_text)
        self.bright = tk.IntVar(value=s.brightness)
        ttk.Scale(f, from_=0, to=100, variable=self.bright, command=self.on_bright).grid(
            row=5, column=0, columnspan=2, sticky="we")

        self.speed_var = tk.DoubleVar(value=s.speed)
        self.speed_text = tk.StringVar(value=f"{up(tr('Скорость'))}  {s.speed:.1f}\u00d7")
        self.caption(f, 6, var=self.speed_text)
        sp = ttk.Scale(f, from_=0.5, to=3.0, variable=self.speed_var, command=self.on_speed_move)
        sp.grid(row=7, column=0, columnspan=2, sticky="we")
        sp.bind("<ButtonRelease-1>", self.on_speed_set)

        pair = ttk.Frame(f)  # «Воспроизведение» и «Подгонка кадра» в одной строке
        pair.grid(row=8, column=0, columnspan=2, sticky="we")
        pair.columnconfigure(0, weight=1, uniform="pair")
        pair.columnconfigure(1, weight=1, uniform="pair")
        ttk.Label(pair, text=up(tr("Воспроизведение")), style="Caption.TLabel").grid(row=0, column=0, sticky="w", pady=(12, 6))
        ttk.Label(pair, text=up(tr("Подгонка кадра")), style="Caption.TLabel").grid(row=0, column=1, sticky="w", pady=(12, 6), padx=(6, 0))
        self.play_var = tk.StringVar(value=next((k for k, v in PLAY_MODES.items() if v == s.play_mode), tr("Зациклить")))
        cb = ttk.Combobox(pair, textvariable=self.play_var, values=list(PLAY_MODES), state="readonly", width=12)
        cb.grid(row=1, column=0, sticky="we", padx=(0, 6))
        cb.bind("<<ComboboxSelected>>", lambda _: self.on_play())
        self.scale_var = tk.StringVar(value=next((k for k, v in SCALE_MODES.items() if v == s.scale_mode), tr("Заполнить")))
        sm = ttk.Combobox(pair, textvariable=self.scale_var, values=list(SCALE_MODES), state="readonly", width=12)
        sm.grid(row=1, column=1, sticky="we", padx=(6, 0))
        sm.bind("<<ComboboxSelected>>", lambda _: self.on_scale())

        # настройки показа: подпись слева, контрол справа; левые края и интервалы везде одинаковые
        self.caption(f, 10, "Показ на экране")
        self.sens = tk.BooleanVar(value=s.show_sensors)
        self.auto = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(f, text=tr("Показывать датчики"), variable=self.sens, command=self.on_flags).grid(
            row=11, column=0, columnspan=2, sticky="w")

        self.caption(f, 12, "Система")
        ttk.Checkbutton(f, text=tr("Запускать с Windows"), variable=self.auto, command=self.on_auto).grid(
            row=13, column=0, columnspan=2, sticky="w")

    # ---------- вкладка «Датчики» ----------
    def build_sensors(self, parent):
        ov = self.streamer.overlay
        scroll = self.sens_scroll = ScrollFrame(parent, self.t["bg"])  # окно одного размера: лишнее прокручивается
        scroll.grid(row=0, column=0, sticky="nsew")
        f = scroll.inner
        f.configure(padding=(0, 0, 8 if not TIGHT else 4, 0))  # зазор справа до полосы прокрутки: кнопки не упираются в неё
        f.columnconfigure(1, weight=1)
        self.pages["Датчики"] = scroll

        self.caption(f, 0, "Датчики на экране", columnspan=1, pady=(0, 6))
        ttk.Button(f, text=tr("Сбросить"), style="Small.TButton", width=btn_w(tr("Сбросить"), 9), command=self.reset_widgets).grid(
            row=0, column=1, sticky="e")
        ttk.Label(f, text=tr("Галочка включает датчик на экране. Выбери строку, чтобы настроить его ниже."),
                  style="Muted.TLabel", wraplength=PANEL_W - 40).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))
        tree_box = ttk.Frame(f)
        tree_box.grid(row=2, column=0, columnspan=2, sticky="we")
        tree_box.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_box, show="tree", height=5, selectmode="browse")
        self.tree.column("#0", width=PANEL_W - 60, stretch=True)  # список + его полоса + полоса области помещаются в панель
        self.tree.grid(row=0, column=0, sticky="we")
        scroll = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-1>", self.on_tree_click, add="+")

        self.v = {
            "label": tk.StringVar(), "label_on": tk.BooleanVar(), "label_size": tk.IntVar(),
            "label_shadow": tk.BooleanVar(), "label_gap": tk.IntVar(), "size": tk.IntVar(),
            "shadow": tk.BooleanVar(), "font": tk.StringVar(), "x": tk.IntVar(), "y": tk.IntVar(),
            "warn_at": tk.IntVar(), "clock_12h": tk.BooleanVar(), "clock_sec": tk.BooleanVar(),
            "date_fmt": tk.StringVar(),
        }
        changed = lambda _=None: self.apply_form()

        def row_label(r, text):
            ttk.Label(f, text=text, wraplength=FORM_LABEL_W, justify="left").grid(row=r, column=0, sticky="w", pady=(6, 0), padx=(0, 8))

        def spin(parent, key, lo, hi, width=4):
            sb = ttk.Spinbox(parent, from_=lo, to=hi, textvariable=self.v[key], width=width, command=self.apply_form)
            sb.bind("<KeyRelease>", changed)
            return sb

        def swatch(parent, key):
            b = tk.Button(parent, width=5, relief="flat", highlightthickness=2, bg=self.t["field"],
                          highlightbackground=self.t["muted"], command=lambda: self.pick_color(key))
            self.swatches[key] = b
            return b

        def hint(parent, col, text, pad=(4, 0)):
            ttk.Label(parent, text=text, style="Muted.TLabel").grid(row=0, column=col, padx=pad, sticky="w")

        def grid_cols(cell):
            """Одинаковые колонки у строк «число / подпись / цвет / подпись»: цветные квадраты и поля встают друг под другом."""
            for i, m in enumerate(FORM_COLS):
                cell.columnconfigure(i, minsize=m)

        def look_cell(r, size_key, color_key, shadow_key):
            """Строка «размер, цвет, тень» для названия или значения: одинаковая раскладка у обоих."""
            cell = ttk.Frame(f)
            cell.grid(row=r, column=1, sticky="w", pady=(6, 0))
            grid_cols(cell)
            spin(cell, size_key, 8, 120).grid(row=0, column=0, sticky="w")
            hint(cell, 1, tr("размер"))
            swatch(cell, color_key).grid(row=0, column=2, sticky="w")
            hint(cell, 3, tr("цвет"))
            ttk.Checkbutton(cell, text=tr("тень"), variable=self.v[shadow_key], command=self.apply_form).grid(row=0, column=4)

        self.swatches = {}
        self.sel_caption = tk.StringVar(value=up(tr("Настройки")))
        self.caption(f, 3, var=self.sel_caption)

        # название (подпись над значением)
        row_label(4, tr("Название"))
        f.grid_slaves(row=4, column=0)[0].grid_configure(sticky="nw", pady=(12, 0))  # строка двухэтажная: подпись у поля
        cell = ttk.Frame(f)
        cell.grid(row=4, column=1, sticky="we", pady=(6, 0))
        cell.columnconfigure(0, weight=1)
        e = ttk.Entry(cell, textvariable=self.v["label"], width=5)
        e.grid(row=0, column=0, sticky="we")
        e.bind("<KeyRelease>", changed)
        ttk.Button(cell, text=tr("Сброс"), style="Small.TButton", width=btn_w(tr("Сброс"), 6), command=self.reset_label).grid(
            row=0, column=1, padx=(6, 0))
        ttk.Checkbutton(cell, text=tr("показывать название"), variable=self.v["label_on"], command=self.apply_form).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row_label(5, tr("Вид названия"))
        look_cell(5, "label_size", "label_color", "label_shadow")
        row_label(6, tr("Отступ от значения"))
        cell = ttk.Frame(f)
        cell.grid(row=6, column=1, sticky="w", pady=(6, 0))
        grid_cols(cell)
        spin(cell, "label_gap", 0, 40).grid(row=0, column=0, sticky="w")
        hint(cell, 1, "px")

        # значение (число)
        row_label(7, tr("Вид значения"))
        look_cell(7, "size", "color", "shadow")
        row_label(8, tr("Предупреждение"))
        cell = ttk.Frame(f)
        cell.grid(row=8, column=1, sticky="w", pady=(6, 0))
        grid_cols(cell)
        spin(cell, "warn_at", 0, 9999).grid(row=0, column=0, sticky="w")
        hint(cell, 1, tr("порог"))
        swatch(cell, "warn_color").grid(row=0, column=2, sticky="w")
        hint(cell, 3, tr("цвет"))
        ttk.Label(f, text=tr("Порог 0 выключает предупреждение"), style="Muted.TLabel").grid(
            row=9, column=1, sticky="w", pady=(2, 0))

        # общее для всего датчика
        row_label(10, tr("Шрифт"))
        cell = ttk.Frame(f)
        cell.grid(row=10, column=1, sticky="we", pady=(6, 0))
        cell.columnconfigure(0, weight=1)
        self.font_box = ttk.Combobox(cell, textvariable=self.v["font"], values=sorted(ov.fonts), state="readonly")
        self.font_box.grid(row=0, column=0, sticky="we")
        self.font_box.bind("<<ComboboxSelected>>", changed)
        ttk.Button(cell, text=tr("Файл…"), style="Small.TButton", width=btn_w(tr("Файл…"), 7), command=self.add_font_file).grid(row=0, column=1, padx=(6, 0))
        row_label(11, tr("Положение"))
        cell = ttk.Frame(f)
        cell.grid(row=11, column=1, sticky="w", pady=(6, 0))
        grid_cols(cell)
        spin(cell, "x", 0, 320).grid(row=0, column=0, sticky="w")
        hint(cell, 1, "X")
        spin(cell, "y", 0, 320).grid(row=0, column=2, sticky="w")
        hint(cell, 3, "Y")

        # то, что относится ко всему экрану, а не к одному датчику
        self.caption(f, 12, "Весь экран")
        row_label(13, tr("Затемнение"))
        cell = ttk.Frame(f)
        cell.grid(row=13, column=1, sticky="w", pady=(6, 0))
        self.shade_var = tk.StringVar(value=next((k for k, v in SHADE_DIRS.items() if v == ov.shade_dir), tr("Снизу")))
        sc = ttk.Combobox(cell, textvariable=self.shade_var, values=list(SHADE_DIRS), state="readonly", width=8)
        sc.grid(row=0, column=0, columnspan=2, sticky="w")
        sc.bind("<<ComboboxSelected>>", lambda _: self.on_shade())
        row_label(14, tr("Отступ от края"))
        cell2 = ttk.Frame(f)
        cell2.grid(row=14, column=1, sticky="w", pady=(6, 0))
        grid_cols(cell2)
        self.safe_var = tk.IntVar(value=ov.safe)
        sb = ttk.Spinbox(cell2, from_=0, to=30, textvariable=self.safe_var, width=4, command=self.on_safe)
        sb.grid(row=0, column=0, sticky="w")
        sb.bind("<KeyRelease>", lambda _: self.on_safe())
        hint(cell2, 1, "px")

        self.style_btn = ttk.Button(f, text=tr("Применить стиль ко всем датчикам"), command=self.style_to_all)
        self.style_btn.grid(row=15, column=0, columnspan=2, sticky="we", pady=(12, 0))
        ttk.Label(f, text=tr("Стиль копирует шрифт, размеры, цвета и тени. Названия, положение и пороги остаются свои."),
                  style="Muted.TLabel", wraplength=PANEL_W - 40).grid(row=16, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.build_clock_rows(f, row_label)
        self.refresh_tree()

    def build_clock_rows(self, f, row_label):
        """Строки для часов (12 ч, секунды) и даты (формат). Вставляются на место строки «Название» (ниже всё сдвигается).
        Часам и дате не нужны «Название», его вид и «Предупреждение»: update_kind прячет их, у обычных датчиков наоборот."""
        self.rows_hidden = (f.grid_slaves(row=4) + f.grid_slaves(row=5) + f.grid_slaves(row=6)
                            + f.grid_slaves(row=8) + f.grid_slaves(row=9))
        for w_ in f.grid_slaves():
            if int(w_.grid_info()["row"]) >= 4:
                w_.grid_configure(row=int(w_.grid_info()["row"]) + 2)
        row_label(4, tr("Время"))
        cell = ttk.Frame(f)
        cell.grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(cell, text=tr("12-часовой формат"), variable=self.v["clock_12h"], command=self.apply_form).grid(row=0, column=0)
        ttk.Checkbutton(cell, text=tr("секунды"), variable=self.v["clock_sec"], command=self.apply_form).grid(row=0, column=1, padx=(14, 0))
        self.rows_time = f.grid_slaves(row=4)
        row_label(5, tr("Формат даты"))
        cell2 = ttk.Frame(f)
        cell2.grid(row=5, column=1, sticky="we", pady=(6, 0))
        self.date_disp = tk.StringVar()
        self.date_box = ttk.Combobox(cell2, textvariable=self.date_disp, state="readonly", width=20)
        self.date_box.grid(row=0, column=0, sticky="w")
        self.date_box.bind("<<ComboboxSelected>>", self.on_date_fmt)
        self.date_keys = {}
        self.rows_datefmt = f.grid_slaves(row=5)
        self.update_kind()

    def refresh_date_box(self, w):
        """Список форматов с примером на сегодняшней дате."""
        self.date_keys = {clockfmt.date_text(k): k for k in clockfmt.DATE_FORMATS}
        self.date_box.configure(values=list(self.date_keys))
        self.date_disp.set(clockfmt.date_text(w["date_fmt"]))

    def on_date_fmt(self, _=None):
        key = self.date_keys.get(self.date_disp.get())
        if key:
            self.v["date_fmt"].set(key)
            self.apply_form()

    def update_kind(self):
        """Форма под вид виджета: у часов время, у даты формат, у обоих нет названия и предупреждения."""
        kind = self.sel["sensor"] if self.sel else ""
        own = kind in ("clock", "date")
        show = lambda ws, on: [x.grid() if on else x.grid_remove() for x in ws]
        show(self.rows_hidden, not own)
        show(self.rows_time, kind == "clock")
        show(self.rows_datefmt, kind == "date")

    def reset_label(self):
        """Возвращает названию стандартное имя датчика (то, что было до переименования)."""
        w = self.sel
        if w:
            self.v["label"].set(label_for(w["sensor"]))
            self.apply_form()

    def row_text(self, w):
        if w["sensor"] in ("clock", "date"):
            return SENSOR_NAMES[w["sensor"]]
        return f"{w['label'] or '—'}  ·  {SENSOR_NAMES.get(w['sensor'], '?')}"

    def update_row(self, w):
        """Обновляет одну строку списка (галочка и название), не сбрасывая прокрутку."""
        if self.tree.exists(w["uid"]):
            self.tree.item(w["uid"], text=self.row_text(w), image=theme.tree_flag(w["show"]))

    def ordered_widgets(self):
        """Порядок строк: включённые сверху, внутри групп по важности датчика (сортировка устойчивая)."""
        rank = {k: i for i, k in enumerate(SENSOR_ORDER)}
        return sorted(self.streamer.overlay.widgets, key=lambda w: (not w["show"], rank.get(w["sensor"], len(rank))))

    def reorder_tree(self, keep=None):
        """Переставляет строки на месте (после включения/выключения), не пересоздавая список и выбор."""
        for i, w in enumerate(self.ordered_widgets()):
            self.tree.move(w["uid"], "", i)
        if keep and self.tree.exists(keep):
            self.tree.see(keep)

    def refresh_tree(self, keep=None):
        """Заново наполняет список; выбирает keep или, если не указано, первый датчик, чтобы настройки не пустовали."""
        ov = self.streamer.overlay
        self.tree.delete(*self.tree.get_children())
        ordered = self.ordered_widgets()
        for w in ordered:
            self.tree.insert("", "end", iid=w["uid"], text=self.row_text(w), image=theme.tree_flag(w["show"]))
        target = keep if keep and self.tree.exists(keep) else (ordered[0]["uid"] if ordered else None)
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)

    def select(self, w):
        self.sel = w
        self._loading = True
        try:
            if w:
                for k, var in self.v.items():
                    var.set(w[k])
                for k, b in self.swatches.items():
                    b.configure(bg=w[k], activebackground=w[k])
                name = (w["label"] if w["sensor"] not in ("clock", "date") else "") or SENSOR_NAMES.get(w["sensor"], "")
                self.sel_caption.set(up(f"{tr('Настройки')}  ·  {name}"))
                self.refresh_date_box(w)
        finally:
            self._loading = False
        self.update_kind()

    def widget_by_uid(self, uid):
        return next((w for w in self.streamer.overlay.widgets if w["uid"] == uid), None)

    def on_tree_select(self, _):
        sel = self.tree.selection()
        self.select(self.widget_by_uid(sel[0]) if sel else None)

    def on_tree_click(self, event):
        """Клик по флажку в строке включает или выключает датчик на экране."""
        if self.tree.identify_element(event.x, event.y) != "image":
            return
        w = self.widget_by_uid(self.tree.identify_row(event.y))
        if w:
            w["show"] = not w["show"]
            self.update_row(w)
            self.reorder_tree(w["uid"])
            self.save()

    def apply_form(self):
        w = self.sel
        if self._loading or not w:
            return
        try:
            for k, var in self.v.items():
                w[k] = var.get()
        except tk.TclError:
            return  # поле пустое/недописанное
        self.update_row(w)
        self.sel_caption.set(up(f"{tr('Настройки')}  ·  {(w['label'] if w['sensor'] not in ('clock', 'date') else '') or SENSOR_NAMES.get(w['sensor'], '')}"))
        self.update_kind()
        self.save()

    def pick_color(self, key):
        w = self.sel
        if not w:
            return
        _, hexcol = colorchooser.askcolor(color=w[key], parent=self)
        if hexcol:
            w[key] = hexcol
            self.swatches[key].configure(bg=hexcol, activebackground=hexcol)
            self.save()

    def style_to_all(self):
        """Оформление выбранного датчика (шрифт, размеры, цвета) копируется на все остальные."""
        src = self.sel
        if not src:
            return
        for w in self.streamer.overlay.widgets:
            if w is not src:
                for k in STYLE_KEYS:
                    w[k] = src[k]
        self.save()
        self.style_btn.configure(text=tr("Готово!"))  # короткое подтверждение на самой кнопке
        self.after(1200, lambda: self.style_btn.configure(text=tr("Применить стиль ко всем датчикам")))

    def add_font_file(self):
        """Добавляет в список свой шрифт из файла и выбирает его для текущего виджета; путь запоминается."""
        path = filedialog.askopenfilename(title=tr("Выбери файл шрифта"), filetypes=[(tr("Шрифты"), "*.ttf *.otf"), (tr("Все файлы"), "*.*")])
        if not path:
            return
        name = self.streamer.overlay.add_font(path)
        if not name:
            messagebox.showwarning("GifDisplay", tr("Не удалось открыть этот шрифт. Нужен файл .ttf или .otf."), parent=self)
            return
        fonts = self.cfg.setdefault("fonts", [])
        if path not in fonts:
            fonts.append(path)
        self.font_box.configure(values=sorted(self.streamer.overlay.fonts))
        if self.sel:
            self.v["font"].set(name)
            self.apply_form()
        else:
            self.save()

    def reset_widgets(self):
        self.streamer.overlay.widgets = default_widgets()
        self.select(None)
        self.refresh_tree()
        self.save()

    # ---------- перетаскивание в превью ----------
    def hit(self, x, y):
        boxes = self.streamer.overlay.boxes
        for w in reversed(self.streamer.overlay.widgets):
            b = boxes.get(w["uid"])
            if b and b[0] - 4 <= x <= b[2] + 4 and b[1] - 4 <= y <= b[3] + 4:
                return w
        return None

    def on_press(self, e):
        w = self.hit(e.x, e.y)
        if w:
            # хватаем виджет там, где он нарисован (с учётом сдвига от отступа), чтобы он не прыгал. Сохранённое положение
            # здесь НЕ меняем: просто клик по виджету не должен «запоминать» сдвиг, меняется оно только при перетаскивании
            dx, dy = self.streamer.overlay.shifts.get(w["uid"], (0, 0))
            self._drag = (w, e.x - (w["x"] + dx), e.y - (w["y"] + dy))
            if self.drag_mode == "grid":
                self.draw_grid()
            self.tree.selection_set(w["uid"])
            self.select(w)

    def on_drag(self, e):
        if self._drag:
            w, dx, dy = self._drag
            w["x"], w["y"] = int(e.x - dx), int(e.y - dy)  # за край не вылезет: рамки держит отрисовка
            self.snap_move(w)
            self.sync_xy(w)

    def on_release(self, _):
        if self._drag:
            self._drag = None
            self.canvas.delete("grid")
            self.save()

    def sync_xy(self, w):
        self._loading = True
        self.v["x"].set(w["x"])
        self.v["y"].set(w["y"])
        self._loading = False

    def snap_move(self, w):
        """В режиме «по сетке» левый верхний угол рамки виджета цепляется к узлам сетки."""
        if self.drag_mode == "grid":
            step = max(2, int(self.grid_step))
            b = self.streamer.overlay.measure(w)
            w["x"] += round(b[0] / step) * step - b[0]
            w["y"] += round(b[1] / step) * step - b[1]

    def draw_grid(self):
        """Сетка точками в узлах, а не сплошными линиями: ненавязчиво и видно на любой картинке."""
        self.canvas.delete("grid")
        step = max(2, int(self.grid_step))
        show = step * -(-6 // step)  # частую сетку (шаг 2–5) рисуем реже, чтобы точки не слипались
        for gx in range(0, gd.W, show):
            for gy in range(0, gd.H, show):
                self.canvas.create_rectangle(gx, gy, gx + 1, gy + 1, outline="", fill="#c8c4dc", tags="grid")
        self.canvas.tag_raise("frame")

    def update_step_visibility(self):
        if self.drag_mode == "grid":
            self.step_box.grid()
        else:
            self.step_box.grid_remove()

    def on_drag_mode(self):
        self.drag_mode = DRAG_MODES[self.drag_var.get()]
        self.update_step_visibility()
        try:
            self.grid_step = max(2, min(50, int(self.step_var.get())))
        except (ValueError, tk.TclError):
            pass
        self.save()

    # ---------- общие настройки ----------
    def pick(self):
        path = filedialog.askopenfilename(
            title=tr("Выбери гифку, видео или картинку"),
            filetypes=[(tr("Гифки, видео и картинки"), " ".join("*" + e for e in gd.VIDEO_EXTS + gd.STILL_EXTS)),
                       (tr("Все файлы"), "*.*")])
        if path:
            self.streamer.set_media(path)
            self.path_var.set(path)
            self.save()

    def on_bright(self, _):
        self.streamer.brightness = int(float(self.bright.get()))
        self.bright_text.set(f"{up(tr('Яркость экрана'))}  {self.streamer.brightness}%")
        self.save()

    def on_speed_move(self, _):
        self.speed_text.set(f"{up(tr('Скорость'))}  {round(self.speed_var.get() * 10) / 10:.1f}×")

    def on_speed_set(self, _):
        self.streamer.set_speed(round(self.speed_var.get() * 10) / 10)
        self.save()

    def on_auto(self):
        if not is_admin():
            messagebox.showwarning("GifDisplay", tr("Для автозапуска нужны права администратора: запусти программу от администратора."))
            self.auto.set(autostart_enabled())
            return
        try:
            set_autostart(self.auto.get())
        except (OSError, subprocess.SubprocessError) as e:
            messagebox.showerror("GifDisplay", tr("Не удалось изменить автозапуск:\n{err}", err=e))
            self.auto.set(autostart_enabled())

    def on_flags(self):
        self.streamer.show_sensors = self.sens.get()
        self.save()

    def on_shade(self):
        self.streamer.overlay.shade_dir = SHADE_DIRS[self.shade_var.get()]
        self.save()

    def toggle(self):
        if self.streamer.running:
            self.streamer.stop()
        else:
            self.streamer.start()

    def save(self):
        s, ov = self.streamer, self.streamer.overlay
        self.cfg.update(media=s.media, brightness=s.brightness, hw_min=s.hw_min, speed=s.speed, play_mode=s.play_mode,
                        scale_mode=s.scale_mode, show_sensors=s.show_sensors,
                        shade_dir=ov.shade_dir, widgets=ov.widgets,
                        theme_choice=self.theme_choice, safe=ov.safe,
                        drag_mode=self.drag_mode, grid_step=self.grid_step)
        save_config(self.cfg)

    def start_ipc(self):
        """Второй запуск (ярлык) стучится сюда и просит показать окно, вместо второй копии программы."""
        try:
            srv = socket.socket()
            srv.bind(("127.0.0.1", IPC_PORT))
            srv.listen(4)
        except OSError:
            return

        def loop():
            while True:
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(1)
                    try:
                        if conn.recv(8) == b"show":
                            self.tray.commands.put("show")
                    except OSError:
                        pass

        threading.Thread(target=loop, daemon=True).start()

    def tray_menu(self):
        return [(1, tr("Открыть окно")), (2, tr("Остановить показ") if self.streamer.running else tr("Запустить показ")),
                (0, None), (3, tr("Выход"))]

    def hide_to_tray(self):
        self.save()
        self.withdraw()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def tick(self):
        self._tick_n = getattr(self, "_tick_n", 0) + 1
        if self._tick_n % 10 == 0:
            self.watch_system_theme()
        self.btn.configure(text=tr("Стоп") if self.streamer.running else tr("Старт"))
        self.status.set(f"{status_text(self.streamer.status)}\n{self.sensors.mode}")
        while True:  # команды из меню трея
            try:
                cmd = self.tray.commands.get_nowait()
            except queue.Empty:
                break
            if cmd == "show":
                self.show_window()
            elif cmd == "toggle":
                self.toggle()
            elif cmd == "quit":
                self.close()
                return
        self.after(200, self.tick)

    def draw_preview(self):
        frame = self.streamer.preview
        hidden = self.state() == "withdrawn"
        if frame is not None and frame is not self._last_frame and self.streamer.running and not hidden:
            self._last_frame = frame
            self._img = ImageTk.PhotoImage(Image.frombytes("RGB", (gd.W, gd.H), frame))
            if self._img_item is None:
                self._img_item = self.canvas.create_image(0, 0, anchor="nw", image=self._img)
                self.canvas.tag_raise("frame")
            else:
                self.canvas.itemconfigure(self._img_item, image=self._img)
            self.canvas.delete("sel")
            self.canvas.tag_raise("frame")
            b = self.streamer.overlay.boxes.get(self.sel["uid"]) if self.sel else None
            if b and self.sens.get():  # рамка выделения ровно по границе текста, без запаса: у края совпадает с безопасной зоной
                self.canvas.create_rectangle(max(b[0], 0), max(b[1], 0), min(b[2] - 1, gd.W - 1), min(b[3] - 1, gd.H - 1),
                                             outline=self.t["accent"], tags="sel")
        self.after(33, self.draw_preview)

    def close(self):
        self.save()
        self.tray.stop()
        self.streamer.stop()
        self.destroy()


_STATUS = (  # статус показа приходит из потока по-русски; здесь он переводится, подстановки (порт) сохраняются
    (re.compile(r"Идёт показ \((.+)\)$"), "Идёт показ ({port})"),
    (re.compile(r"(.+) занят \(закрой Smart Screen V28\), жду…$"), "{port} занят (закрой Smart Screen V28), жду…"),
)


def status_text(text):
    for rx, key in _STATUS:
        m = rx.match(text)
        if m:
            return tr(key, port=m.group(1))
    return tr(text)


def signal_running(cmd=b"show"):
    """Если программа уже запущена, просит её открыть окно. True, если она ответила."""
    try:
        with socket.create_connection(("127.0.0.1", IPC_PORT), timeout=0.5) as c:
            c.sendall(cmd)
        return True
    except OSError:
        return False


def run_task():
    """Запуск через задачу планировщика: права есть, окна UAC нет."""
    r = subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def selftest():
    """Проверка собранной программы без окна: файлы на месте, переводы читаются, .NET-библиотека датчиков загружается.
    Результат пишется в selftest.json в папке настроек (приложение без консоли ничего не печатает)."""
    out = {"frozen": FROZEN, "ffmpeg": os.path.exists(gd.FFMPEG_LOCAL), "language": i18n.language(),
           "translated_strings": len(i18n._catalog), "icon": os.path.exists(os.path.join(APP_DIR, ICON_FILE)),
           "default_profile": os.path.exists(DEFAULT_PROFILE)}
    try:
        import sensors
        os.environ["PATH"] = sensors.LIB_DIR + os.pathsep + os.environ["PATH"]
        if FROZEN:
            os.environ.setdefault("PYTHONNET_PYDLL", os.path.join(sys._MEIPASS, f"python{sys.version_info[0]}{sys.version_info[1]}.dll"))
        import clr
        clr.AddReference(os.path.join(sensors.LIB_DIR, "LibreHardwareMonitorLib.dll"))
        from LibreHardwareMonitor.Hardware import Computer
        out["sensor_library"] = type(Computer()).__name__
    except Exception as e:
        out["sensor_library"] = f"error: {e!r}"
    with open(os.path.join(CONFIG_DIR, "selftest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if "--wait-prev" in sys.argv:  # перезапуск после смены языка: ждём выхода прежней копии
        for _w in range(40):
            if not signal_running(b"ping"):
                break
            time.sleep(0.25)
    elif signal_running(b"ping" if "--minimized" in sys.argv else b"show"):
        sys.exit(0)  # уже запущена: просто показали окно
    if not is_admin() and "--no-elevate" not in sys.argv:
        if run_task():  # запускаем с правами через задачу и открываем окно, когда программа поднимется
            for _ in range(40):
                time.sleep(0.5)
                if signal_running(b"show"):
                    break
            sys.exit(0)
        if relaunch_as_admin():  # задачи нет (автозапуск выключен): обычный запрос UAC
            sys.exit(0)
    try:
        app = App()
        if "--minimized" in sys.argv and app.tray.ok:
            app.withdraw()  # при автозапуске окно сразу уходит в трей
        elif "--minimized" in sys.argv:
            app.iconify()
        app.mainloop()
    except Exception:  # у программы без консоли ошибка иначе пропадает: пишем её в log.txt
        log.exception("аварийный выход")
        raise
