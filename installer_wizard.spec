import os

block_cipher = None

payload_zip = os.path.join('installer', 'build', 'app_payload.zip')
release_manifest = os.path.join('installer', 'build', 'release_manifest.json')

datas = [
    ('app/icon.ico', 'app'),
    ('app/icon.png', 'app'),
    ('LICENSE.md', 'legal_docs'),
    ('EULA.md', 'legal_docs'),
    ('NOTICE.md', 'legal_docs'),
    ('THIRD_PARTY_NOTICES.md', 'legal_docs'),
    ('SECURITY.md', 'legal_docs'),
]

if os.path.exists(payload_zip):
    datas.append((payload_zip, 'installer_payload'))
if os.path.exists(release_manifest):
    datas.append((release_manifest, 'installer_payload'))

a = Analysis(
    ['installer/installer_wizard.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'playwright',
        'playwright.__main__',
        'playwright.sync_api',
        'playwright._impl._driver',
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BrowerAI Studio Labs Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='app/icon.ico' if os.path.exists('app/icon.ico') else None,
)
