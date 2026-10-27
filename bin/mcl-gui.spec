# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['G:/vibe coding/mc-launcher/mclauncher/mcl-gui.py'],
    pathex=[],
    binaries=[],
    datas=[('G:/vibe coding/mc-launcher/mclauncher', 'mclauncher')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    name='mcl-gui',
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
    icon=['G:/vibe coding/mc-launcher/mclauncher/gui/assets/app.ico'],
)
