"""Датчики для виджетов на экране.

Встроенные источники: psutil (CPU, память, сеть) и nvidia-smi (видеокарта NVIDIA).
Всё остальное (температура CPU, обороты кулеров и помпы, iGPU) может положить во внешний файл
sensors.json любой помощник с нужными правами: {"cpu_temp": 52.0, "pump_rpm": 2400, ...}.
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

import psutil

from i18n import screen_tr, tr

NO_WINDOW = subprocess.CREATE_NO_WINDOW
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SENSORS_FILE = os.path.join(BASE_DIR, "sensors.json")
LIB_DIR = os.path.join(BASE_DIR, "lib")

# id: (название, единица, знаков после запятой)
CATALOG = {
    "cpu_load": ("Загрузка CPU", "%", 0),
    "cpu_temp": ("Температура CPU", "°", 0),
    "cpu_fan": ("Кулер CPU", " об/м", 0),
    "ram_load": ("Память (ОЗУ)", "%", 0),
    "gpu_temp": ("Видеокарта: температура", "°", 0),
    "gpu_load": ("Видеокарта: загрузка", "%", 0),
    "gpu_mem": ("Видеокарта: память", "%", 0),
    "gpu_power": ("Видеокарта: мощность", " Вт", 0),
    "gpu_fan": ("Видеокарта: кулер", "%", 0),
    "gpu_clock": ("Видеокарта: частота", " МГц", 0),
    "igpu_temp": ("Встроенная графика: температура", "°", 0),
    "liquid_temp": ("Температура жидкости", "°", 0),
    "pump_rpm": ("Помпа", " об/м", 0),
    "case_fan": ("Корпусной кулер", " об/м", 0),
    "net_down": ("Сеть: загрузка", " МБ/с", 1),
    "net_up": ("Сеть: отдача", " МБ/с", 1),
    "clock": ("Часы", "", 0),  # не датчики: текст берётся из системных часов при рисовании (см. clockfmt.py)
    "date": ("Дата", "", 0),
}


# порядок датчиков в списке окна, от самых важных: температуры, загрузка, охлаждение, память, остальное
SENSOR_ORDER = ["gpu_temp", "cpu_temp", "gpu_load", "cpu_load", "liquid_temp", "pump_rpm", "cpu_fan", "gpu_fan",
                "case_fan", "ram_load", "gpu_power", "gpu_mem", "gpu_clock", "igpu_temp", "net_down", "net_up", "clock", "date"]

LHM_URL ="http://localhost:8085/data.json"

# id: регулярка по пути датчика в дереве LibreHardwareMonitor; из нескольких совпадений берётся максимум
LHM_RULES = {
    "cpu_temp": r"/ AMD Ryzen[^/]* / Temperatures / (Core \(Tctl/Tdie\)|CPU Package)$",
    "cpu_fan": r"/ Fans / CPU Fan$",
    "pump_rpm": r"/ Fans / System Fan #\d+ / Pump$",
    "case_fan": r"/ Fans / System Fan #(1|3)$",
    "igpu_temp": r"/ AMD Radeon\(TM\) Graphics / Temperatures / GPU VR SoC$",
}


# виртуальные и служебные адаптеры: VPN-туннель дублирует трафик физической сети, и он считался бы дважды
SKIP_NICS = re.compile(r"loopback|bluetooth|hamachi|happ|xray|\btun\b|\btap\b|vpn|virtual|vmware|vethernet|"
                       r"wireguard|zerotier|npcap|teredo|isatap", re.I)


def real_net_totals():
    """Суммарно принято/отправлено байт по работающим физическим адаптерам."""
    up = psutil.net_if_stats()
    rx = tx = 0
    for name, c in psutil.net_io_counters(pernic=True).items():
        if name in up and up[name].isup and not SKIP_NICS.search(name):
            rx += c.bytes_recv
            tx += c.bytes_sent
    return rx, tx


def format_value(sensor_id, v):
    """Текст значения для виджета. Скорость сети переключается между КБ/с и МБ/с, чтобы на простое не было «0.0»."""
    if sensor_id == "clock":
        return time.strftime("%H:%M")
    if v is None:
        return "--"
    if sensor_id in ("net_down", "net_up"):
        kb = v * 1024
        return f"{v:.1f} {screen_tr('МБ/с')}" if kb >= 1000 else f"{kb:.0f} {screen_tr('КБ/с')}"  # «1023 КБ/с» странно рядом с МБ/с
    _, unit, dec = CATALOG.get(sensor_id, ("?", "", 0))
    return f"{v:.{dec}f}{screen_tr(unit)}"


def _num(s):
    try:
        return float(s)
    except ValueError:
        return None  # "[N/A]" и подобное


def _lhm_value(text):
    m = re.search(r"-?\d+(?:[.,]\d+)?", text or "")
    return float(m.group().replace(",", ".")) if m else None


def _lhm_walk(node, path, out):
    path = f"{path} / {node.get('Text', '')}" if path else node.get("Text", "")
    if node.get("Value"):
        v = _lhm_value(node["Value"])
        if v is not None:
            out.append((path, v))
    for c in node.get("Children", []):
        _lhm_walk(c, path, out)


class Sensors:
    def __init__(self):
        self.data = {k: None for k in CATALOG}
        self.mode = tr("датчики: ограниченный доступ (нет прав администратора)")
        self._computer = None
        psutil.cpu_percent(None)
        self._net = (time.time(), *real_net_totals())
        threading.Thread(target=self._loop, daemon=True).start()

    def _nvidia(self, d):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed,clocks.gr",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, creationflags=NO_WINDOW).stdout
            t, u, mu, mt, p, fan, clk = [_num(x.strip()) for x in out.strip().splitlines()[0].split(",")]
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return
        d["gpu_temp"], d["gpu_load"], d["gpu_power"], d["gpu_fan"], d["gpu_clock"] = t, u, p, fan, clk
        d["gpu_mem"] = mu / mt * 100 if mu is not None and mt else None

    def _network(self, d):
        now, (rx, tx) = time.time(), real_net_totals()
        t0, rx0, tx0 = self._net
        dt = max(now - t0, 1e-3)
        d["net_down"] = max(rx - rx0, 0) / dt / 1e6  # МБ/с; max(…, 0): счётчики адаптера могут сброситься
        d["net_up"] = max(tx - tx0, 0) / dt / 1e6
        self._net = (now, rx, tx)

    def _lhm(self, d):
        try:
            with urllib.request.urlopen(LHM_URL, timeout=2) as r:
                tree = json.load(r)
        except (OSError, ValueError):
            return  # LibreHardwareMonitor не запущен: значения остаются прежними/«--»
        flat = []
        _lhm_walk(tree, "", flat)
        self._apply_rules(d, flat)

    @staticmethod
    def _apply_rules(d, flat):
        for sid, rule in LHM_RULES.items():
            vals = [v for p, v in flat if re.search(rule, p)]
            d[sid] = max(vals) if vals else None

    def _open_native(self):
        """Читаем датчики сами через LibreHardwareMonitorLib: нужны права администратора."""
        try:
            if not ctypes.windll.shell32.IsUserAnAdmin():
                return
            os.environ["PATH"] = LIB_DIR + os.pathsep + os.environ["PATH"]
            sys.path.append(LIB_DIR)
            if getattr(sys, "frozen", False):  # в собранной программе python3xx.dll лежит рядом: pythonnet сам её не находит
                os.environ.setdefault("PYTHONNET_PYDLL", os.path.join(sys._MEIPASS, f"python{sys.version_info[0]}{sys.version_info[1]}.dll"))
            import clr
            clr.AddReference(os.path.join(LIB_DIR, "LibreHardwareMonitorLib.dll"))
            from LibreHardwareMonitor.Hardware import Computer
            c = Computer()
            c.IsCpuEnabled = c.IsMotherboardEnabled = c.IsGpuEnabled = True
            c.Open()
            self._computer = c
            self.mode = tr("датчики: полный доступ")
        except Exception:  # нет pythonnet/библиотеки/драйвера: останется чтение через веб-сервер
            self._computer = None

    def _native(self, d):
        flat = []

        def walk(hw):
            hw.Update()
            for s in hw.Sensors:
                group = {"Temperature": "Temperatures", "Fan": "Fans"}.get(str(s.SensorType))
                if group and s.Value is not None:
                    flat.append((f"/ {hw.Name} / {group} / {s.Name}", float(s.Value)))
            for sub in hw.SubHardware:
                walk(sub)

        try:
            for hw in self._computer.Hardware:
                walk(hw)
        except Exception:
            return
        self._apply_rules(d, flat)

    def _external(self, d):
        try:
            with open(SENSORS_FILE, encoding="utf-8") as f:
                extra = json.load(f)
        except (OSError, ValueError):
            return
        for k, v in extra.items():
            if k in CATALOG and (v is None or isinstance(v, (int, float))):
                d[k] = v

    def _loop(self):
        self._open_native()
        while True:
            d = self.data
            d["cpu_load"] = psutil.cpu_percent(None)
            d["ram_load"] = psutil.virtual_memory().percent
            self._nvidia(d)
            self._network(d)
            if self._computer is not None:
                self._native(d)
            else:
                self._lhm(d)
            self._external(d)
            time.sleep(1)
