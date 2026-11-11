#!/bin/bash
# Build the macOS app and DMG (Apple Silicon).
#
#   scripts/build_macos.sh                    unsigned (ad-hoc signed) app + dmg
#   SIGN_IDENTITY="Developer ID Application: ..." NOTARY_PROFILE=<keychain profile> \
#       scripts/build_macos.sh                signed, notarised, stapled
#
# Steps: download the pinned parts (runtime.lock.json, checked by SHA-256), assemble the
# runtime (standalone Python + capstone + unicorn, trimmed Arm toolchain), build the launcher
# with PyInstaller, put the runtime and licences in the app, sign, make the DMG, notarise.
# Everything goes in build/ and dist/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PLATFORM=macos-arm64
APP_NAME="Perkons Mod Matrix"
BUILD="$ROOT/build"
DL="$BUILD/downloads"
RT="$BUILD/runtime"
DIST="$ROOT/dist"
LOCK="$ROOT/runtime.lock.json"
[ "$(uname -m)" = arm64 ] || { echo "build on an Apple Silicon Mac"; exit 1; }

lock() { /usr/bin/python3 -c "import json,sys; d=json.load(open('$LOCK')); print(eval('d'+sys.argv[1]))" "$1"; }
say() { printf '\n== %s\n' "$*"; }

fetch() {   # url sha256 -> path in downloads/
  local url="$1" sha="$2" name
  name="$(basename "${url%%\?*}")"; name="${name//%2B/+}"
  mkdir -p "$DL"
  if [ ! -f "$DL/$name" ] || [ "$(shasum -a 256 "$DL/$name" | cut -d' ' -f1)" != "$sha" ]; then
    echo "downloading $name" >&2
    curl -fL --retry 3 -o "$DL/$name.part" "$url"
    mv "$DL/$name.part" "$DL/$name"
  fi
  [ "$(shasum -a 256 "$DL/$name" | cut -d' ' -f1)" = "$sha" ] || { echo "checksum mismatch: $name" >&2; exit 1; }
  echo "$DL/$name"
}

# ---------------------------------------------------------------------------------------------
say "runtime: Python $(lock "['python']['version']")"
PY_TGZ=$(fetch "$(lock "['python']['platforms']['$PLATFORM']['url']")" "$(lock "['python']['platforms']['$PLATFORM']['sha256']")")
TC_TXZ=$(fetch "$(lock "['toolchain']['platforms']['$PLATFORM']['url']")" "$(lock "['toolchain']['platforms']['$PLATFORM']['sha256']")")

rm -rf "$RT" "$BUILD/tc" && mkdir -p "$RT" "$BUILD/tc"
tar -xzf "$PY_TGZ" -C "$RT"                          # -> runtime/python
P="$RT/python"
/usr/bin/python3 -c "import json; print('\n'.join(json.load(open('$LOCK'))['python']['wheels']['$PLATFORM']))" > "$BUILD/requirements-runtime.txt"
"$P/bin/python3" -m pip install -q --disable-pip-version-check --no-compile --only-binary :all: \
  --require-hashes -r "$BUILD/requirements-runtime.txt"
"$P/bin/python3" -I -c "import capstone, unicorn, importlib.metadata as m; print('capstone', m.version('capstone'), 'unicorn', m.version('unicorn'))"

# prune what the Mod Matrix never uses (Tk, IDLE, pip, headers, tests)
"$P/bin/python3" -m pip uninstall -q -y pip
rm -rf "$P/share" "$P/include" "$P/lib/pkgconfig" "$P/lib/"{libtcl*,itcl*,tcl9*,tk9*,thread*} \
       "$P/lib/python3.12/"{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3,config-3.12-darwin} \
       "$P/lib/python3.12/lib-dynload/"_tkinter*
find "$P/bin" -mindepth 1 ! -name python3 ! -name python3.12 -delete
find "$P" -name __pycache__ -type d -prune -exec rm -rf {} +
# bytecode inside the app, so Python never needs to write there (the server runs with -B)
"$P/bin/python3" -I -m compileall -q -j0 --invalidation-mode unchecked-hash "$P/lib/python3.12" >/dev/null || true

say "runtime: Arm GNU Toolchain $(lock "['toolchain']['version']"), trimmed"
tar -xf "$TC_TXZ" -C "$BUILD/tc"
TC_SRC="$(ls -d "$BUILD"/tc/arm-gnu-toolchain-*)"
/usr/bin/python3 -c "import json; print('\n'.join(json.load(open('$LOCK'))['toolchain']['keep']))" | while read -r p; do
  mkdir -p "$RT/toolchain/$(dirname "$p")"
  cp -Rp "$TC_SRC/$p" "$RT/toolchain/$p"
done
rm -rf "$BUILD/tc"
"$RT/toolchain/bin/arm-none-eabi-gcc" --version | head -1

/usr/bin/python3 - "$LOCK" "$RT/runtime.json" "$PLATFORM" <<'EOF'
import json, sys
lock = json.load(open(sys.argv[1]))
pk = {l.split('==')[0]: l.split('==')[1].split()[0] for l in lock['python']['wheels'][sys.argv[3]]}
json.dump({'platform': sys.argv[3], 'python': lock['python']['version'], 'packages': pk,
           'toolchain': lock['toolchain']['version']}, open(sys.argv[2], 'w'), indent=1)
EOF
du -sh "$RT/python" "$RT/toolchain"

# ---------------------------------------------------------------------------------------------
say "launcher: PyInstaller $(lock "['launcher']['pyinstaller']"), pywebview $(lock "['launcher']['pywebview']")"
VENV="$BUILD/venv"
if [ ! -x "$VENV/bin/pyinstaller" ] || ! "$VENV/bin/python" -c "import webview" 2>/dev/null; then
  rm -rf "$BUILD/buildpython" "$VENV"
  mkdir -p "$BUILD/buildpython" && tar -xzf "$PY_TGZ" -C "$BUILD/buildpython"
  "$BUILD/buildpython/python/bin/python3" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --disable-pip-version-check \
    "pyinstaller==$(lock "['launcher']['pyinstaller']")" "pywebview==$(lock "['launcher']['pywebview']")"
fi
rm -rf "$DIST" "$BUILD/pyinstaller"
"$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN --distpath "$DIST" --workpath "$BUILD/pyinstaller" modmatrix.spec
APP="$DIST/$APP_NAME.app"

say "app: runtime and licences"
cp -Rp "$RT" "$APP/Contents/Resources/runtime"
mkdir -p "$APP/Contents/Resources/licenses"
cp -p licenses/* "$APP/Contents/Resources/licenses/"
cp -p "$RT/toolchain/share/doc/arm-none-eabi/readme.txt" "$APP/Contents/Resources/licenses/arm-gnu-toolchain-readme.txt"
cp -p "$RT/python/lib/python3.12/LICENSE.txt" "$APP/Contents/Resources/licenses/python-LICENSE.txt" 2>/dev/null || true
for pkg in capstone unicorn; do
  for f in "$RT"/python/lib/python3.12/site-packages/$pkg-*.dist-info/{LICENSE*,COPYING*,licenses/*}; do
    [ -f "$f" ] && cp -p "$f" "$APP/Contents/Resources/licenses/$pkg-$(basename "$f")"
  done
done
for d in "$VENV"/lib/python3.12/site-packages/{pywebview,pyobjc_core,pyinstaller}-*.dist-info; do
  pkg="$(basename "$d" | sed 's/-[0-9].*//')"
  for f in "$d"/{LICENSE*,COPYING*,licenses/*}; do
    [ -f "$f" ] && cp -p "$f" "$APP/Contents/Resources/licenses/launcher-$pkg-$(basename "$f")"
  done
done

# ---------------------------------------------------------------------------------------------
if [ -n "${SIGN_IDENTITY:-}" ]; then
  say "signing with $SIGN_IDENTITY"
  sign() { codesign --force --timestamp --options runtime -s "$SIGN_IDENTITY" "$@"; }
  # inside out: every Mach-O in the runtime and PyInstaller's files, then the app; only the
  # bundled Python gets an entitlement (allow-jit, for unicorn)
  PYBIN="$APP/Contents/Resources/runtime/python/bin/python3.12"
  find "$APP/Contents" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.so' \) -print0 |
    while IFS= read -r -d '' f; do
      if [ "$f" != "$PYBIN" ] && [ "$f" != "$APP/Contents/MacOS/$APP_NAME" ] && file -b "$f" | grep -q Mach-O; then
        sign "$f"
      fi
    done
  sign --entitlements "$ROOT/entitlements.plist" "$PYBIN"
  sign "$APP"
  codesign --verify --deep --strict "$APP"
else
  say "ad-hoc signing (unsigned build)"
  codesign --force --deep -s - "$APP"
fi

say "dmg"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -Rp "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
VERSION=$(/usr/bin/python3 -c "import re;print(re.search(r\"APP_VERSION = '([^']+)'\", open('launcher/modmatrix_launcher.py').read()).group(1))")
DMG="$DIST/ModMatrixDesktop-macOS.dmg"   # no version: README links to releases/latest/download/
hdiutil create -quiet -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format ULMO "$DMG"   # LZMA: ~40% smaller than UDZO
if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp -s "$SIGN_IDENTITY" "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    say "notarising"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    spctl -a -t open --context context:primary-signature -vv "$DMG" || true
  fi
fi
du -sh "$APP" "$DMG"
echo "-> $DMG"
