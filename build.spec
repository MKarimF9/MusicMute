# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'),('torch_cache', 'torch_cache')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# onedir, not onefile: PyInstaller's onefile mode unpacks itself via an extra
# wrapper process at launch, which combined with a macOS .app bundle can spawn
# a second GUI shell (duplicate menu-bar icon, or Finder launching it via
# Terminal instead of as a normal app). onedir avoids that — see
# build_server.spec, which hit this exact bug first.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MusicMute',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MusicMute',
)

app = BUNDLE(
    coll,
    name='MusicMute.app',
    icon=None,
    bundle_identifier='com.musicmute.app',
    info_plist={
        'NSHighResolutionCapable': True,
    },
)
