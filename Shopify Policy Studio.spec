# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
runtime = Path(sys.base_prefix)
tk_binaries = [(str(runtime / 'DLLs' / name), '.') for name in ('tcl86t.dll', 'tk86t.dll', '_tkinter.pyd')]
tk_data = [(str(runtime / 'tcl'), 'tcl'), (str(runtime / 'Lib' / 'tkinter'), 'tkinter')]


a = Analysis(
    ['policy_entry.py'],
    pathex=[],
    binaries=tk_binaries,
    datas=tk_data + [('ui_background.jpg', '.'), ('app_icon.png', '.'), ('app_icon.ico', '.'), ('taskbar_icon.ico', '.'), ('legal_rulepack.json', '.'), ('update_channel.json', '.'), ('app_version.json', '.'), ('apply_app_update.ps1', '.'), ('register_update_tasks.ps1', '.')],
    hiddenimports=['tkinter', 'tkinter.ttk', '_tkinter', 'pypdf', 'deep_translator', 'translatepy', 'charset_normalizer'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['tk_runtime_hook.py'],
    excludes=[],
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
    name='Policy Amadeus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
