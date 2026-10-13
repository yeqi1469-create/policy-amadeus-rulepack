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
    datas=tk_data + [('ui_background.jpg', '.'), ('app_icon.png', '.'), ('app_icon.ico', '.'), ('taskbar_icon.ico', '.'), ('legal_rulepack.json', '.'), ('app_version.json', '.')],
    hiddenimports=['tkinter', 'tkinter.ttk', '_tkinter', 'pypdf', 'deep_translator', 'translatepy', 'charset_normalizer'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['tk_runtime_hook.py'],
    excludes=['app_updater','codex_review_worker','codex_handoff','current_law_review','startup_update','session_checkpoint','signed_channel_transport','update_progress'],
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
