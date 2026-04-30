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
        # yfinance / pandas / requests pull these dynamically; listing them
        # explicitly keeps PyInstaller from missing them in the frozen build.
        'lxml.etree',
        'lxml._elementpath',
        'pkg_resources.py2_warn',
        # yfinance dependencies that aren't auto-detected
        'multitasking',
        'frozendict',
        'platformdirs',
        'appdirs',
        'peewee',
        'beautifulsoup4',
        'bs4',
        'html5lib',
        'soupsieve',
        # urllib3 / requests
        'certifi',
        'charset_normalizer',
        'idna',
        # pandas occasionally needs these explicitly
        'pandas._libs.tslibs.base',
        'pandas._libs.tslibs.nattype',
        'pandas._libs.tslibs.np_datetime',
        # Windows toast notifications (optional at runtime)
        'win10toast',
        'pythoncom',
        'pywintypes',
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
