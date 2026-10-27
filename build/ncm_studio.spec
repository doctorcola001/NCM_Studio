# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置

    pyinstaller build/ncm_studio.spec --noconfirm

产物：dist/NCM_Studio.exe（单文件、无控制台窗口、带 GUI 与 --cli 两种模式）
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent          # noqa: F821  (SPECPATH 由 PyInstaller 注入)

HIDDEN = [
    'mutagen.mp3', 'mutagen.flac', 'mutagen.id3', 'mutagen.easyid3',
    'mutagen._util', 'mutagen._file',
    'Crypto.Cipher.AES', 'Crypto.Util.strxor', 'Crypto.Util.Padding',
]

EXCLUDE = [
    'tkinter', 'unittest', 'pydoc', 'pytest', 'numpy', 'pandas',
    'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtQml',
    'PyQt6.QtQuick', 'PyQt6.QtBluetooth', 'PyQt6.QtMultimedia',
    'PyQt6.Qt3DCore', 'PyQt6.QtSql', 'PyQt6.QtNetwork',
    'kivy',
]

a = Analysis(                                     # noqa: F821
    [str(ROOT / 'desktop' / 'app.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)                  # noqa: F821

exe = EXE(                                        # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NCM_Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                                # GUI 程序；CLI 模式自己 AttachConsole
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
