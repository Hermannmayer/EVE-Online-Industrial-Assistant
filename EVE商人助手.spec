# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller 打包配置
#   - database/ 和 data/ 不打包进 exe，而是放在同目录下供运行时访问
#   - ui/、services/、core/ 为代码目录，打包进 exe

a = Analysis(
    ['Main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('services', 'services'),
        ('core', 'core'),
    ],
    hiddenimports=[
        'aiosqlite', 'aiohttp', 'tenacity', 'tqdm', 'pyperclip', 'PIL',
        'aiosqlite.dump',
    ],
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'pandas', 'numpy',
        'matplotlib', 'scipy', 'sklearn', 'cv2', 'tensorflow',
        'torch', 'notebook', 'jupyter', 'IPython', 'setuptools',
        'pillow.heif', 'openpyxl', 'lxml', 'rich', 'pygments',
        'chardet',
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
    name='EVE商人助手',
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
)

# 不打包 COLLECT，因为目录结构由 build_release.py 维护
