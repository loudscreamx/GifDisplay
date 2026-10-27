"""GifDisplay: показ гифки/видео с датчиками на экране водянки (Smart Monitor, 320x320).

Протокол хост -> экран:  5A A5 <cmd> 00 <len: uint32 LE> <payload>
  0x81 приветствие, 0x90 запрос разрешения, 0x80 яркость(?), 0x85 кадр H.264.
Экран принимает Annex-B H.264 Constrained Baseline, один кадр на пакет.
"""
import argparse
import logging
import os
import queue
import re
import struct
import subprocess
import threading
import time
import winreg

from PIL import Image, ImageEnhance

from overlay import Overlay
from sensors import Sensors

log = logging.getLogger("gifdisplay")
STILL_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
VIDEO_EXTS = (".gif", ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".wmv")

W = H = 320
FRAME_BYTES = W * H * 3
FPS = 30
FFMPEG_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "ffmpeg.exe")
FFMPEG_ORIGINAL = r"C:\Program Files (x86)\Smart Screen V28\ffmpeg.exe"
NO_WINDOW = subprocess.CREATE_NO_WINDOW


HW_MIN_DEFAULT = 103  # ниже этого значения подсветка почти не светится (подобрано на экране водянки); уточняется в окне


def hw_level(percent, hw_min=HW_MIN_DEFAULT):
    """Байт яркости для экрана (0..255): 0% гасит подсветку, 1..100% растягиваются от порога hw_min до максимума."""
    p = max(0, min(100, percent))
    if p == 0:
        return 0
    lo = max(1, min(254, hw_min))
    return round(lo + (255 - lo) * p / 100)


def preview_factor(percent):
    """Во сколько затемнять превью: после порога яркость растёт линейно, а глаз видит её по гамме ~2,2."""
    return max((max(0, min(100, percent)) / 100) ** (1 / 2.2), 0.04)


def ffmpeg_path():
    for p in (FFMPEG_LOCAL, FFMPEG_ORIGINAL):
        if os.path.exists(p):
            return p
    return "ffmpeg"


def packet(cmd, payload=b""):
    return b"\x5a\xa5" + bytes([cmd, 0]) + struct.pack("<I", len(payload)) + payload


def find_port(vid="1F3A", pid="0007"):
    """COM-порт экрана по USB-идентификатору (интерфейс MI_00)."""
    base = rf"SYSTEM\CurrentControlSet\Enum\USB\VID_{vid}&PID_{pid}&MI_00"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                inst = winreg.EnumKey(k, i)
                try:
                    with winreg.OpenKey(k, inst + r"\Device Parameters") as p:
                        return winreg.QueryValueEx(p, "PortName")[0]
                except OSError:
                    continue
    except OSError:
        pass
    return None


class Encoder:
    """ffmpeg: сырые RGB-кадры на входе, H.264 baseline на выходе, по кадру на пакет."""

    def __init__(self, on_unit, use_nvenc=True):
        if use_nvenc:
            codec = ["-c:v", "h264_nvenc", "-profile:v", "baseline", "-bf", "0", "-g", str(FPS),
                     "-rc", "cbr", "-b:v", "3M", "-zerolatency", "1", "-delay", "0"]
        else:
            codec = ["-c:v", "libx264", "-profile:v", "baseline", "-preset", "veryfast", "-crf", "20",
                     "-x264-params", f"keyint={FPS}:repeat-headers=1:bframes=0:slices=1:threads=1:sliced-threads=0:rc-lookahead=0:vbv-maxrate=4000:vbv-bufsize=1000"]
        cmd = [ffmpeg_path(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-vf", "format=yuv420p", *codec, "-flush_packets", "1", "-f", "h264", "-"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, creationflags=NO_WINDOW)
        self.on_unit = on_unit
        threading.Thread(target=self._read, daemon=True).start()

    def write(self, rgb_bytes):
        self.proc.stdin.write(rgb_bytes)

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.terminate()

    def _read(self):
        buf = b""
        cur = b""
        while True:
            chunk = self.proc.stdout.read1(65536)
            if not chunk:
                return
            buf += chunk
            starts = [m.start() for m in re.finditer(rb"\x00\x00\x01", buf)]
            if len(starts) < 2:
                continue
            bounds = [s - 1 if s > 0 and buf[s - 1] == 0 else s for s in starts]
            for a, b in zip(bounds, bounds[1:]):
                nal = buf[a:b]
                off = 4 if nal[2] == 0 else 3
                cur += nal
                if (nal[off] & 0x1F) in (1, 5):
                    self.on_unit(cur)
                    cur = b""
            buf = buf[bounds[-1]:]


SCALE_FILTERS = {
    "fill": f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",                      # заполнить, лишнее обрезать
    "fit": f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",  # целиком, с полями
    "stretch": f"scale={W}:{H}",                                                                    # на весь экран с искажением
    "center": f"crop='min(iw,{W})':'min(ih,{H})',pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black",       # без масштабирования
}


def _filter(speed, fit="fill"):
    return f"setpts=PTS/{speed:.3f},fps={FPS}," + SCALE_FILTERS.get(fit, SCALE_FILTERS["fill"])


class Source:
    """Гифка, видео или картинка в бесконечный поток сырых кадров 320x320 (подгонка кадра по режиму fit)."""

    def __init__(self, path, speed=1.0, fit="fill"):
        # картинки зацикливаются через -loop (на jpg -stream_loop виснет), видео и гифки через -stream_loop
        still = os.path.splitext(path)[1].lower() in STILL_EXTS
        loop = ["-loop", "1", "-framerate", str(FPS)] if still else ["-stream_loop", "-1"]
        cmd = [ffmpeg_path(), "-v", "error", *loop, "-i", path, "-an", "-vf", _filter(speed, fit),
               "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)

    def read(self):
        data = self.proc.stdout.read(FRAME_BYTES)
        return data if len(data) == FRAME_BYTES else None

    def close(self):
        """Останавливает ffmpeg; возвращает его сообщение об ошибке (если было)."""
        self.proc.terminate()
        try:
            return self.proc.communicate(timeout=2)[1].decode("utf-8", "replace").strip()[:300]
        except (subprocess.SubprocessError, OSError):
            return ""


class PingPongSource:
    """Туда-обратно: один проход (до MAX_SECONDS) целиком в памяти, затем вперёд и назад по кругу."""

    MAX_SECONDS = 15  # ограничение по памяти: кадр 320x320 весит 300 КБ

    def __init__(self, path, speed=1.0, fit="fill"):
        still = os.path.splitext(path)[1].lower() in STILL_EXTS
        pre = ["-loop", "1", "-framerate", str(FPS)] if still else []
        limit = ["-frames:v", "1"] if still else ["-t", str(self.MAX_SECONDS)]
        cmd = [ffmpeg_path(), "-v", "error", *pre, "-i", path, "-an", "-vf", _filter(speed, fit), *limit,
               "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
        r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, timeout=120)
        self.error = r.stderr.decode("utf-8", "replace").strip()[:300]
        n = len(r.stdout) // FRAME_BYTES
        self._frames = [r.stdout[i * FRAME_BYTES:(i + 1) * FRAME_BYTES] for i in range(n)]
        # вперёд и назад без дублирования крайних кадров
        self._order = list(range(n)) + (list(range(n - 2, 0, -1)) if n > 2 else [])
        self._i = 0

    def read(self):
        if not self._order:
            return None
        frame = self._frames[self._order[self._i % len(self._order)]]
        self._i += 1
        return frame

    def close(self):
        return self.error


class Streamer:
    """Фоновый поток: читает источник, рисует датчики, кодирует и отправляет на экран."""

    def __init__(self, sensors):
        self.overlay = Overlay(sensors)
        self.media = None
        self.brightness = 100
        self.hw_min = HW_MIN_DEFAULT  # порог, с которого экран начинает светиться
        self.speed = 1.0
        self.play_mode = "loop"   # loop (по кругу) / pingpong (туда-обратно)
        self.scale_mode = "fill"  # fill / fit / stretch / center: как кадр ложится на экран
        self.show_sensors = True
        self.use_nvenc = False  # NVENC отдаёт кадры пачками (интервалы 33/66 мс): на экране рывки
        self._status = "Остановлено"
        self._retry_at = 0.0
        self._sent_brightness = None
        self.preview = None
        self._media_changed = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, text):
        if text != self._status:
            log.info("состояние: %s", text)
        self._status = text

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def set_media(self, path):
        self.media = path
        self._media_changed.set()

    def set_play(self, mode):
        if mode != self.play_mode:
            self.play_mode = mode
            self._media_changed.set()  # источник перезапускается с новым режимом

    def set_scale(self, mode):
        if mode in SCALE_FILTERS and mode != self.scale_mode:
            self.scale_mode = mode
            self._media_changed.set()  # источник перезапускается с новой подгонкой

    def set_speed(self, speed):
        if abs(speed - self.speed) > 0.01:
            self.speed = speed
            self._media_changed.set()  # источник перезапускается с новым множителем

    def start(self):
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        """Показ с переподключением: экран выдернули, ПК ушёл в сон, USB переткнули: ждём экран и продолжаем сами."""
        while not self._stop.is_set():
            if not self._session():
                break
            self._stop.wait(2)

    def _session(self):
        """Одно подключение к экрану. True, если связь потеряна (нужно переподключиться), False, если остановили."""
        port = None
        while port is None:  # при входе в Windows экран может появиться позже программы
            port_name = find_port()
            if not port_name:
                self.status = "Экран не найден (USB 1F3A:0007), жду…"
            else:
                try:
                    port = os.open(r"\\.\%s" % port_name, os.O_RDWR | os.O_BINARY)
                except OSError:
                    self.status = f"{port_name} занят (закрой Smart Screen V28), жду…"
            if port is None and self._stop.wait(2):
                return False
        units = queue.Queue(maxsize=8)
        lost = threading.Event()  # писать в порт перестало получаться: экран отключён

        st = self.stats = {"dropped": 0, "sent": 0, "bytes": 0, "wmax": 0.0, "wsum": 0.0, "gaps": []}

        def on_unit(au):
            try:
                units.put_nowait(au)
            except queue.Full:
                st["dropped"] += 1  # экран не успевает: пропускаем кадр, не копим задержку

        def sender():
            last = None
            while True:
                au = units.get()
                if au is None:
                    return
                t = time.perf_counter()
                try:
                    os.write(port, packet(0x85, au))
                except OSError:
                    lost.set()
                    return
                w = time.perf_counter() - t
                st["sent"] += 1
                st["bytes"] += len(au)
                st["wsum"] += w
                st["wmax"] = max(st["wmax"], w)
                if last is not None:
                    st["gaps"].append(t - last)
                last = t

        enc = Encoder(on_unit, self.use_nvenc)
        sender_thread = threading.Thread(target=sender, daemon=True)
        sender_thread.start()
        src = None
        try:
            os.write(port, packet(0x81, b"\x01"))
            time.sleep(0.05)
            os.write(port, packet(0x90, b"\x01"))
            time.sleep(0.05)
            self._sent_brightness = None  # яркость уйдёт в экран перед первым кадром
            self.status = f"Идёт показ ({port_name})"
            t0 = time.perf_counter()
            n = 0
            while not self._stop.is_set() and not lost.is_set():
                if self._media_changed.is_set() or (src is None and self.media and time.time() >= self._retry_at):
                    self._media_changed.clear()
                    if src:
                        src.close()
                        src = None
                    if self.media:
                        log.info("открываю источник: %s (скорость %.1f, режим %s)", self.media, self.speed, self.play_mode)
                        src = PingPongSource(self.media, self.speed, self.scale_mode) if self.play_mode == "pingpong" \
                            else Source(self.media, self.speed, self.scale_mode)
                        self.status = f"Идёт показ ({port_name})"
                raw = src.read() if src else None
                if raw is None:
                    if src:  # не открылся: файл остаётся выбранным, пробуем позже
                        log.warning("источник не читается: %s", src.close() or "без сообщения ffmpeg")
                        src = None
                        self._retry_at = time.time() + 3
                        self.status = "Не удалось прочитать файл, пробую снова…"
                    raw = bytes(FRAME_BYTES)
                img = Image.frombytes("RGB", (W, H), raw)
                img = self.overlay.apply(img, self.show_sensors)
                want = hw_level(self.brightness, self.hw_min)
                if self._sent_brightness != want:  # яркость подсветки самого экрана, 0 = не горит
                    os.write(port, packet(0x80, bytes([want])))
                    self._sent_brightness = want
                out = img.tobytes()
                # в экран уходит полная яркость (её регулирует подсветка), а превью затемняем, чтобы было видно эффект
                self.preview = out if self.brightness >= 100 else \
                    ImageEnhance.Brightness(img).enhance(preview_factor(self.brightness)).tobytes()
                enc.write(out)
                n += 1
                delay = t0 + n / FPS - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
        except (OSError, BrokenPipeError):
            lost.set()
        finally:
            if src:
                src.close()
            enc.close()
            units.put(None)
            time.sleep(0.2)
            try:
                os.close(port)
            except OSError:
                pass
        if lost.is_set() and not self._stop.is_set():
            self.status = "Связь с экраном потеряна"
            return True
        if self.status.startswith("Идёт"):
            self.status = "Остановлено"
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--seconds", type=float, default=0, help="0 = бесконечно")
    ap.add_argument("--nvenc", action="store_true", help="NVENC вместо libx264 (рывки)")
    args = ap.parse_args()
    s = Streamer(Sensors())
    s.use_nvenc = args.nvenc
    s.set_media(args.media)
    s.start()
    try:
        t0 = time.time()
        while s.running and (not args.seconds or time.time() - t0 < args.seconds):
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    s.stop()
    st = getattr(s, "stats", None)
    if st and st["sent"]:
        g = sorted(st["gaps"])
        print(f"кадров {st['sent']}, пропущено {st['dropped']}, {st['bytes'] * 8 / (st['sent'] / FPS) / 1e6:.1f} Мбит/с, "
              f"запись avg {st['wsum'] / st['sent'] * 1000:.1f} мс, max {st['wmax'] * 1000:.0f} мс, "
              f"интервал p50 {g[len(g) // 2] * 1000:.0f} p95 {g[int(len(g) * .95)] * 1000:.0f} max {g[-1] * 1000:.0f} мс", flush=True)
    print(s.status, flush=True)


if __name__ == "__main__":
    main()
