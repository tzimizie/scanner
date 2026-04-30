# PyInstaller spec — produces a single self-contained stockscanner.exe.
# Build with: pyinstaller stockscanner.spec
# (or via build_windows.bat / GitHub Actions)

block_cipher = None


a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # yfinance / pandas occasionally pull these dynamically; listing them
        # explicitly keeps PyInstaller from missing them in the frozen build.
        'lxml.etree',
        'lxml._elementpath',
        'pkg_resources.py2_warn',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim a few hundred MB of stuff yfinance/pandas don't need at runtime.
        'matplotlib',
        'tkinter',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='stockscanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
