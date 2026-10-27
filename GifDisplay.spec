# Сборка программы: python -m PyInstaller GifDisplay.spec --noconfirm   (результат: dist/GifDisplay/GifDisplay.exe)
from PyInstaller.utils.hooks import collect_all

datas = [
    ("cat_gray.ico", "."),
    ("default_profile.json", "."),
    ("fonts", "fonts"),
    ("locales", "locales"),
    ("lib", "lib"),
    ("media/cat_idle.gif", "media"),
    ("ffmpeg", "ffmpeg"),
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
]
binaries = []
hiddenimports = ["clr", "clr_loader", "pythonnet"]
for pkg in ("pythonnet", "clr_loader"):  # датчики читаются через .NET: нужны их библиотеки
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(["app.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter.test", "unittest", "pydoc", "test", "numpy"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GifDisplay", console=False, icon="cat_gray.ico",
          version="version_info.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="GifDisplay")
