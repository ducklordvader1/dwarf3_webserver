# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for dwarf3_webserver (one-folder, cross-platform).
# ffmpeg/ffprobe binaries are supplied via the FFMPEG_DIR env var set by CI;
# if unset, the build still succeeds but ships without bundled ffmpeg.
import os, sys
from PyInstaller.utils.hooks import collect_submodules

ffmpeg_bins = []
_ff = os.environ.get("FFMPEG_DIR")
if _ff and os.path.isdir(_ff):
    ext = ".exe" if sys.platform.startswith("win") else ""
    for tool in ("ffmpeg", "ffprobe"):
        p = os.path.join(_ff, tool + ext)
        if os.path.isfile(p):
            ffmpeg_bins.append((p, "."))

hiddenimports = collect_submodules("engineio") + collect_submodules("socketio")

a = Analysis(
    ["server.py"],
    pathex=[],
    binaries=ffmpeg_bins,
    datas=[("static", "static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="dwarf3_webserver",
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="dwarf3_webserver",
)
