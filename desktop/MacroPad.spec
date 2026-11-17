# Windows V1: one-directory GUI build; writable config stays outside the bundle.
from pathlib import Path

project = Path(SPECPATH)
analysis = Analysis(
    [str(project / "app.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / "assets" / name), "assets") for name in (
        "macropad_device.png", "easter_egg.png", "easter_egg.wav", "app_icon.png",
    )],
    hiddenimports=[
        "pynput.keyboard._win32", "pynput.mouse._win32",
        "pynput._util.win32", "serial.tools.list_ports_windows",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Macro Pad",
    icon=str(project / "assets" / "app_icon.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Macro Pad",
)
