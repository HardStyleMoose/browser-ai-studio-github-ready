import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis([
    'app/main.py',
],
    pathex=[],
    binaries=[],
    datas=[
        ('app/icon.ico', 'app'),
        ('app/icon.png', 'app'),
        ('LICENSE.md', 'legal_docs'),
        ('EULA.md', 'legal_docs'),
        ('NOTICE.md', 'legal_docs'),
        ('THIRD_PARTY_NOTICES.md', 'legal_docs'),
        ('SECURITY.md', 'legal_docs'),
        ('ui/', 'ui'),
        ('automation/', 'automation'),
        ('vision/', 'vision'),
        ('ai/', 'ai'),
        ('plugins/', 'plugins'),
        ('themes/', 'themes'),
        ('models/', 'models'),
        ('config/', 'config'),
    ],
    hiddenimports=[
        'playwright',
        'playwright.__main__',
        'playwright.sync_api',
        'playwright._impl._driver',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel',
    ] + collect_submodules('sb3_contrib'),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BrowserAI_Lab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='app/icon.ico' if os.path.exists('app/icon.ico') else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BrowserAI_Lab')
