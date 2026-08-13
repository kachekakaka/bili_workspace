# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

root = Path(os.environ["BILI_REPOSITORY_ROOT"])
resource_bundle = Path(os.environ["BILI_LAUNCHER_RESOURCE_BUNDLE"])
version = "0.7.0"
numeric_version = (0, 7, 0, 0)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=numeric_version,
        prodvers=numeric_version,
        mask=0x3F,
        flags=0,
        OS=0x40004,
        fileType=0x1,
        subtype=0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "080404B0",
                    [
                        StringStruct("CompanyName", "bili_workspace"),
                        StringStruct("FileDescription", "bili_workspace Windows 启动器"),
                        StringStruct("FileVersion", "0.7.0.0"),
                        StringStruct("InternalName", "bili-workspace-launcher"),
                        StringStruct("OriginalFilename", "bili-workspace-launcher-0.7.0.exe"),
                        StringStruct("ProductName", "bili_workspace"),
                        StringStruct("ProductVersion", version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)

datas = [
    (str(resource_bundle / "source"), "resources/source"),
    (str(resource_bundle / "manifest.json"), "resources"),
]

a = Analysis(
    [str(root / "launcher" / "bili_workspace_launcher_entry.py")],
    pathex=[str(root / "launcher"), str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="bili-workspace-launcher-0.7.0",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,
)
