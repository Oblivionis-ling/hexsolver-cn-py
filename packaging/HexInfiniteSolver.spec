# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata


project_root = Path.cwd().resolve()
version = (project_root / "VERSION").read_text(encoding="utf-8").strip()
artifact_name = f"HexInfiniteSolver-{version}-windows-x64"
asset_root = project_root / "build" / "package_assets"
managed_bin = project_root / "managed_core" / "bin"

datas = [
    (str(managed_bin / "HexcellsHeadless.exe"), "managed_core/bin"),
    (str(managed_bin / "UnityEngine.dll"), "managed_core/bin"),
    (str(managed_bin / "TextMeshPro-5.6-Runtime.dll"), "managed_core/bin"),
    (str(project_root / "src" / "hexsolver_cn" / "assets"), "src/hexsolver_cn/assets"),
]
datas += collect_data_files("qtawesome")
datas += copy_metadata("qtawesome")
datas += copy_metadata("ortools")

binaries = collect_dynamic_libs("ortools")
conda_library_bin = Path(sys.prefix) / "Library" / "bin"
conda_runtime_names = (
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "liblzma.dll",
    "libbz2.dll",
    "libexpat.dll",
    "ffi.dll",
    "sqlite3.dll",
)
binaries += [
    (str(conda_library_bin / name), ".")
    for name in conda_runtime_names
    if (conda_library_bin / name).is_file()
]

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "ortools.sat.python.cp_model_helper",
        "ortools.util.python.sorted_interval_list",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cv2",
        "onnxruntime",
        "rapidocr",
        "src.hexsolver_cn.detector",
        "src.hexsolver_cn.ocr",
        "matplotlib",
        "scipy",
        "IPython",
        "pytest",
        "tkinter",
    ],
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
    name=artifact_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(asset_root / "HexInfiniteSolver.ico"),
    version=str(asset_root / "version_info.txt"),
)
