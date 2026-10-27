"""Отчёт о совместимости: что видит программа (экран, COM-порты, ffmpeg, права). Его можно приложить к issue на GitHub.
В отчёте нет имён пользователя, путей и серийных номеров: только идентификаторы устройств и версии."""
import ctypes
import os
import platform
import subprocess
import winreg

import gifdisplay as gd

VERSION = "1.0.0"
USB = r"SYSTEM\CurrentControlSet\Enum\USB"


def com_ports():
    """[(VID:PID, порт, название)] для всех USB-устройств, у которых есть COM-порт (в том числе экран)."""
    out = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, USB) as usb:
            for i in range(winreg.QueryInfoKey(usb)[0]):
                dev = winreg.EnumKey(usb, i)  # VID_1F3A&PID_0007[&MI_00]
                try:
                    with winreg.OpenKey(usb, dev) as dk:
                        for j in range(winreg.QueryInfoKey(dk)[0]):
                            inst = winreg.EnumKey(dk, j)
                            with winreg.OpenKey(dk, inst) as ik:
                                try:
                                    with winreg.OpenKey(ik, "Device Parameters") as p:
                                        port = winreg.QueryValueEx(p, "PortName")[0]
                                except OSError:
                                    continue
                                try:
                                    name = str(winreg.QueryValueEx(ik, "FriendlyName")[0])
                                except OSError:
                                    name = str(winreg.QueryValueEx(ik, "DeviceDesc")[0]) if _has(ik, "DeviceDesc") else ""
                                name = name.split(";")[-1]
                            vid_pid = dev.upper().replace("VID_", "").replace("PID_", "").split("&MI")[0].replace("&", ":")
                            out.append((vid_pid, port, name))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def _has(key, name):
    try:
        winreg.QueryValueEx(key, name)
        return True
    except OSError:
        return False


def pawnio_installed():
    """Драйвер PawnIO (его использует LibreHardwareMonitor для температур CPU, вентиляторов, помпы)."""
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO",
                                           0, winreg.KEY_READ | view))
            return True
        except OSError:
            continue
    return os.path.isdir(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "PawnIO"))


def ffmpeg_line():
    path = gd.ffmpeg_path()
    try:
        out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=10,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout.splitlines()
        return out[0] if out else "no output"
    except (OSError, subprocess.SubprocessError) as e:
        return f"not available ({e.__class__.__name__})"


def build(status="", sensors_mode="", language="", media_kind=""):
    port = gd.find_port()
    ports = com_ports()
    lines = [
        f"GifDisplay {VERSION}",
        f"Windows: {platform.platform()}",
        f"Administrator: {bool(ctypes.windll.shell32.IsUserAnAdmin())}",
        f"Interface language: {language}",
        "",
        "Expected display: USB VID:PID 1F3A:0007 (320x320)",
        f"Display found: {'yes, port ' + port if port else 'NO'}",
        "USB devices with a COM port (current or previously connected):",
        *(["  " + f"{v}  {p}  {n}" for v, p, n in ports] or ["  none"]),
        "",
        f"Stream status: {status}",
        f"Sensors: {sensors_mode}",
        f"PawnIO driver (CPU temperature, fans, pump): {'installed' if pawnio_installed() else 'NOT installed'}",
        f"Media: {media_kind or 'none'}",
        f"ffmpeg: {ffmpeg_line()}",
    ]
    return "\n".join(lines)
