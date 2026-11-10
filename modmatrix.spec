# PyInstaller spec: the launcher only. The runtime (Python + toolchain) is copied into the app
# by scripts/build_macos.sh / build_windows.ps1 after this runs.
import re
import sys

VERSION = re.search(r"APP_VERSION = '([^']+)'", open('launcher/modmatrix_launcher.py').read()).group(1)
NAME = 'Perkons Mod Matrix'
ICON = {'darwin': 'assets/icon.icns', 'win32': 'assets/icon.ico'}.get(sys.platform)
import os
ICON = ICON if ICON and os.path.exists(ICON) else None

a = Analysis(['launcher/modmatrix_launcher.py'], excludes=['tkinter', 'unittest', 'pydoc', 'test'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=ICON,
          argv_emulation=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(coll, name=f'{NAME}.app', icon=ICON, bundle_identifier='io.github.remixed123.perkonsmodmatrix',
                 version=VERSION,
                 info_plist={'CFBundleShortVersionString': VERSION, 'CFBundleVersion': VERSION,
                             'LSMinimumSystemVersion': '11.0', 'NSHighResolutionCapable': True,
                             'LSApplicationCategoryType': 'public.app-category.music',
                             'NSHumanReadableCopyright': 'Unofficial. Not affiliated with or endorsed by Erica Synths.'})
