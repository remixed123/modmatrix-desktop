#!/bin/bash
# Build the macOS app and DMG: Apple Silicon, or Intel with "intel".
#
#   scripts/build_macos.sh                    unsigned (ad-hoc signed) app + dmg
#   scripts/build_macos.sh intel              the Intel (x86_64) app, in build/intel and dist-intel/:
#                                             on an Intel Mac, or under Rosetta on Apple Silicon
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
APP_NAME="Perkons Mod Matrix Desktop"
LOCK="$ROOT/runtime.lock.json"
DL="$ROOT/build/downloads"
if [ "${1:-}" = intel ]; then
  PLATFORM=macos-x86_64
  BUILD="$ROOT/build/intel"
  DIST="$ROOT/dist-intel"
  DMG_NAME=ModMatrixDesktop-macOS-Intel.dmg
  ENTITLEMENTS="$ROOT/entitlements-intel.plist"
  APP_ENTITLEMENTS=(--entitlements "$ROOT/entitlements-intel-launcher.plist")
  arch -x86_64 /usr/bin/true 2>/dev/null || { echo "needs an Intel Mac or Rosetta (softwareupdate --install-rosetta)"; exit 1; }
else
  PLATFORM=macos-arm64
  BUILD="$ROOT/build"
  DIST="$ROOT/dist"
  DMG_NAME=ModMatrixDesktop-macOS.dmg
  ENTITLEMENTS="$ROOT/entitlements.plist"
  APP_ENTITLEMENTS=()
  [ "$(uname -m)" = arm64 ] || { echo "build on an Apple Silicon Mac (or: $0 intel)"; exit 1; }
fi
RT="$BUILD/runtime"

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
# the toolchain's version for this platform (Arm's Intel Mac builds stopped at 14.2.rel1)
TC_VERSION=$(lock "['toolchain']['platforms']['$PLATFORM'].get('version', d['toolchain']['version'])")
TC_GCC=$(lock "['toolchain']['platforms']['$PLATFORM'].get('gcc', d['toolchain']['gcc'])")
GCC_LOCK=$(lock "['toolchain']['gcc']")

say "runtime: Python $(lock "['python']['version']") for $PLATFORM"
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

say "runtime: Arm GNU Toolchain $TC_VERSION, trimmed"
tar -xf "$TC_TXZ" -C "$BUILD/tc"
TC_SRC="$(ls -d "$BUILD"/tc/arm-gnu-toolchain-*)"
/usr/bin/python3 -c "import json; print('\n'.join(json.load(open('$LOCK'))['toolchain']['keep']))" | sed "s/$GCC_LOCK/$TC_GCC/" | while read -r p; do
  mkdir -p "$RT/toolchain/$(dirname "$p")"
  cp -Rp "$TC_SRC/$p" "$RT/toolchain/$p"
done
rm -rf "$BUILD/tc"
# a toolchain build that links a library from outside macOS (Arm's Intel 14.2 cc1: Homebrew's
# zstd) gets that library built from its pinned source and put next to the binary
ZSTD_URL=$(lock "['toolchain']['platforms']['$PLATFORM'].get('zstd', {}).get('url', '')")
if [ -n "$ZSTD_URL" ]; then
  ZSTD_VERSION=$(lock "['toolchain']['platforms']['$PLATFORM']['zstd']['version']")
  say "runtime: zstd $ZSTD_VERSION for the toolchain"
  ZSTD_TGZ=$(fetch "$ZSTD_URL" "$(lock "['toolchain']['platforms']['$PLATFORM']['zstd']['sha256']")")
  rm -rf "$BUILD/zstd" && mkdir -p "$BUILD/zstd" && tar -xzf "$ZSTD_TGZ" -C "$BUILD/zstd"
  ZS="$BUILD/zstd/zstd-$ZSTD_VERSION"
  ZARCH=$([ "$PLATFORM" = macos-x86_64 ] && echo x86_64 || echo arm64)
  (cd "$ZS/lib" && clang -dynamiclib -arch "$ZARCH" -mmacosx-version-min=11.0 -O3 -DXXH_NAMESPACE=ZSTD_ \
     -install_name @loader_path/libzstd.1.dylib -compatibility_version 1 -current_version "$ZSTD_VERSION" \
     common/*.c compress/*.c decompress/*.c decompress/*.S -o "$BUILD/zstd/libzstd.1.dylib")
  find "$RT/toolchain" -type f -perm -u+x -print0 | while IFS= read -r -d '' f; do
    old=$(otool -L "$f" 2>/dev/null | awk '/libzstd/ && !/@loader_path/ {print $1}')
    [ -n "$old" ] || continue
    cp "$BUILD/zstd/libzstd.1.dylib" "$(dirname "$f")/libzstd.1.dylib"
    install_name_tool -change "$old" @loader_path/libzstd.1.dylib "$f" 2>/dev/null
    codesign --force -s - "$(dirname "$f")/libzstd.1.dylib" "$f"     # signed properly later
    echo "  $(basename "$f"): $old -> @loader_path/libzstd.1.dylib"
  done
  cp "$ZS/LICENSE" "$BUILD/zstd-LICENSE.txt"
  rm -rf "$ZS"
fi
# nothing in the runtime may need a library from outside macOS
find "$RT" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.so' \) -print0 | while IFS= read -r -d '' f; do
  otool -L "$f" 2>/dev/null | tail -n +2 | awk '{print $1}' | { grep -v -E '^(/usr/lib/|/System/|@)' || true; } | sed "s|^|outside macOS: $f: |"
done | tee "$BUILD/outside.txt"
[ ! -s "$BUILD/outside.txt" ] || { echo "the runtime links libraries that a clean Mac doesn't have"; exit 1; }
"$RT/toolchain/bin/arm-none-eabi-gcc" --version | head -1
echo 'int f(int x) { return x * 3; }' | "$RT/toolchain/bin/arm-none-eabi-gcc" -mcpu=cortex-m7 -O2 -x c -c -o /dev/null - \
  || { echo "the bundled compiler doesn't run"; exit 1; }

/usr/bin/python3 - "$LOCK" "$RT/runtime.json" "$PLATFORM" "$TC_VERSION" <<'EOF'
import json, sys
lock = json.load(open(sys.argv[1]))
pk = {l.split('==')[0]: l.split('==')[1].split()[0] for l in lock['python']['wheels'][sys.argv[3]]}
json.dump({'platform': sys.argv[3], 'python': lock['python']['version'], 'packages': pk,
           'toolchain': sys.argv[4]}, open(sys.argv[2], 'w'), indent=1)
EOF
file -b "$P/bin/python3.12" "$RT/toolchain/libexec/gcc/arm-none-eabi/$TC_GCC/cc1" | sed 's/^/  /' 
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
[ -z "$ZSTD_URL" ] || cp -p "$BUILD/zstd-LICENSE.txt" "$APP/Contents/Resources/licenses/zstd-LICENSE.txt"
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
  sign --entitlements "$ENTITLEMENTS" "$PYBIN"
  sign ${APP_ENTITLEMENTS[@]+"${APP_ENTITLEMENTS[@]}"} "$APP"
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
DMG="$DIST/$DMG_NAME"   # no version: README links to releases/latest/download/
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
file -b "$APP/Contents/MacOS/$APP_NAME" | sed 's/^/  launcher: /'
du -sh "$APP" "$DMG"
echo "-> $DMG"
