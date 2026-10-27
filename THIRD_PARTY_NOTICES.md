# Third-party components

GifDisplay itself is MIT-licensed (see `LICENSE`). The installer also ships these separate programs and libraries,
each under its own license:

| Component | Used for | License | Source |
|---|---|---|---|
| FFmpeg (BtbN GPL build, with libx264) | decoding GIF/video and encoding H.264 for the display; run as a separate process (`ffmpeg\ffmpeg.exe`) | GPL v3 | https://ffmpeg.org · build scripts: https://github.com/BtbN/FFmpeg-Builds |
| LibreHardwareMonitorLib and its dependency DLLs in `lib\` (HidSharp, DiskInfoToolkit, RAMSPDToolkit, BlackSharp.Core, System.*) | reading CPU / board / GPU sensors | MPL 2.0 (LibreHardwareMonitorLib); the dependencies carry their own licenses, see the project page | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor |
| PawnIO driver (installer, optional) | kernel driver used by LibreHardwareMonitor for CPU temperature, fans, pump; installed only if the user ticks the box | GPL-2.0 (driver) | https://pawnio.eu · https://github.com/namazso/PawnIO · installer: https://github.com/namazso/PawnIO.Setup |
| pythonnet | calling the .NET sensor library from Python | MIT | https://github.com/pythonnet/pythonnet |
| Python, Tcl/Tk | runtime | PSF / Tcl license | https://www.python.org |
| Pillow | image handling | HPND | https://python-pillow.org |
| psutil | CPU / memory / network counters | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Press Start 2P (font) | pixel font for on-screen text | SIL OFL 1.1 | `fonts\OFL-PressStart2P.txt` |

FFmpeg is not linked into GifDisplay: it is started as an independent program, so the GPL applies to FFmpeg only.
The corresponding source code of the bundled FFmpeg build is available from the project pages above.
