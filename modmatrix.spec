# PyInstaller spec: the launcher only. The runtime (Python + toolchain) is copied into the app
# by scripts/build_macos.sh / build_windows.ps1 after this runs.
import re
import sys

VERSION = re.search(r"APP_VERSION = '([^']+)'", open('launcher/modmatrix_launcher.py').read()).group(1)
NAME = 'Perkons Mod Matrix Desktop'
DEVELOPER = 'remixed123'
ICON = {'darwin': 'assets/icon.icns', 'win32': 'assets/icon.ico'}.get(sys.platform)
import os
ICON = ICON if ICON and os.path.exists(ICON) else None

VERSION_FILE = None
if sys.platform == 'win32':   # the exe's Properties > Details
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    nums = tuple(int(n) for n in (VERSION.split('.') + ['0'] * 4)[:4])
    VERSION_FILE = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums),
        kids=[StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', DEVELOPER), StringStruct('FileDescription', f'{NAME}, packaged by {DEVELOPER}'),
            StringStruct('ProductName', NAME), StringStruct('FileVersion', VERSION),
            StringStruct('ProductVersion', VERSION), StringStruct('OriginalFilename', f'{NAME}.exe'),
            StringStruct('LegalCopyright', f'{DEVELOPER}. Unofficial, not endorsed by Erica Synths.')])]),
              VarFileInfo([VarStruct('Translation', [0x0409, 1200])])])

a = Analysis(['launcher/modmatrix_launcher.py'], datas=[('launcher/ui', 'ui')], excludes=['tkinter', 'unittest', 'pydoc', 'test'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=ICON, version=VERSION_FILE,
          argv_emulation=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(coll, name=f'{NAME}.app', icon=ICON, bundle_identifier='io.github.remixed123.perkonsmodmatrix',
                 version=VERSION,
                 info_plist={'CFBundleShortVersionString': VERSION, 'CFBundleVersion': VERSION,
                             'LSMinimumSystemVersion': '11.0', 'NSHighResolutionCapable': True,
                             'LSApplicationCategoryType': 'public.app-category.music',
                             'NSHumanReadableCopyright': f'The Mod Matrix and perkons-re are by kiteless. Desktop app packaged by {DEVELOPER}. '
                                                           'Unofficial. Not affiliated with or endorsed by Erica Synths.'})
