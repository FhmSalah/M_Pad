# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project = Path(SPECPATH)

assets = [
    "macropad_device.png",
    "easter_egg.png",
    "easter_egg.wav",
    "app_icon.png",
]

a = Analysis(
    [str(project / "app.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "config.json"), "."),
        *[(str(project / "assets" / name), "assets") for name in assets],
    ],
    hiddenimports=[
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "pynput._util.darwin",
        "serial.tools.list_ports_osx",
        "AppKit",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Macro Pad",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Macro Pad",
)

app = BUNDLE(
    coll,
    name="Macro Pad.app",
    icon=str(project / "assets" / "app_icon.icns"),
    bundle_identifier="com.macropad.desktop",
)
