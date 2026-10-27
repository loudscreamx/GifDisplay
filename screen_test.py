"""Первый тест: отправить H.264-видео на экран по протоколу Smart Monitor.

Формат пакета хост -> экран:  5A A5 <cmd> 00 <len: uint32 LE> <payload>
  0x81  приветствие (payload 01)       -> экран отвечает "Smart Monitor v0.0.2"
  0x90  запрос разрешения (payload 01) -> экран отвечает 320x320
  0x80  вероятно яркость (payload ff)
  0x85  кадр: Annex-B H.264 (Constrained Baseline, без B-кадров)
"""
import os
import struct
import subprocess
import sys
import time

PORT = r"\\.\COM4"
FFMPEG = r"C:\Program Files (x86)\Smart Screen V28\ffmpeg.exe"
W = H = 320
FPS = 30


def packet(cmd, payload=b""):
    return b"\x5a\xa5" + bytes([cmd, 0]) + struct.pack("<I", len(payload)) + payload


def split_access_units(stream):
    """Режет Annex-B поток на кадры; SPS/PPS прикрепляются к следующему слайсу."""
    starts = []
    i = 0
    n = len(stream)
    while i < n - 3:
        if stream[i] == 0 and stream[i + 1] == 0 and (stream[i + 2] == 1 or (stream[i + 2] == 0 and stream[i + 3] == 1)):
            starts.append(i)
            i += 3
        else:
            i += 1
    starts.append(n)
    units, cur = [], b""
    for a, b in zip(starts, starts[1:]):
        nal = stream[a:b]
        off = 4 if nal[2] == 0 else 3
        ntype = nal[off] & 0x1F
        cur += nal
        if ntype in (1, 5):
            units.append(cur)
            cur = b""
    return units


def make_clip(src_args, seconds):
    cmd = [FFMPEG, "-v", "error", *src_args, "-t", str(seconds),
           "-vf", f"scale={W}:{H},format=yuv420p", "-r", str(FPS),
           "-c:v", "libx264", "-profile:v", "baseline", "-level", "2.1",
           "-x264-params", "keyint=30:repeat-headers=1:bframes=0:slices=1:threads=1:sliced-threads=0:rc-lookahead=0",
           "-f", "h264", "-"]
    return subprocess.run(cmd, capture_output=True, check=True).stdout


def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    clip = make_clip(["-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}"], seconds)
    units = split_access_units(clip)
    print(f"{len(units)} кадров, {len(clip)} байт")

    port = os.open(PORT, os.O_RDWR | os.O_BINARY)
    try:
        os.write(port, packet(0x81, b"\x01"))
        time.sleep(0.05)
        os.write(port, packet(0x90, b"\x01"))
        time.sleep(0.05)
        os.write(port, packet(0x80, b"\xff"))
        t0 = time.perf_counter()
        for k, au in enumerate(units):
            os.write(port, packet(0x85, au))
            delay = t0 + (k + 1) / FPS - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        print("готово")
    finally:
        os.close(port)


if __name__ == "__main__":
    sys.exit(main())
