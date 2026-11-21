#!/bin/bash
# Build the Linux app (x86_64): dist/perkons-mod-matrix/ and dist/ModMatrixDesktop-Linux.tar.gz.
#
#   scripts/build_linux.sh
#
# Same steps as build_macos.sh: download the pinned parts (runtime.lock.json, checked by
# SHA-256), assemble the runtime (standalone Python + capstone + unicorn, trimmed Arm
# toolchain), build the launcher with PyInstaller, put the runtime and licences next to it.
# The Linux app has no window of its own: it opens in the default browser (the launcher's
# --browser mode), so it needs no GTK, WebKitGTK or Qt. Build it on the oldest Linux it
# should run on (glibc): CI uses Ubuntu 22.04.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PLATFORM=linux-x86_64
NAME=perkons-mod-matrix
LOCK="$ROOT/runtime.lock.json"
BUILD="$ROOT/build/linux"
DL="$ROOT/build/downloads"
DIST="$ROOT/dist-linux"
RT="$BUILD/runtime"
[ "$(uname -s)-$(uname -m)" = Linux-x86_64 ] || { echo "build on Linux x86_64"; exit 1; }

lock() { python3 -c "import json,sys; d=json.load(open('$LOCK')); print(eval('d'+sys.argv[1]))" "$1"; }
say() { printf '\n== %s\n' "$*"; }

fetch() {   # url sha256 -> path in downloads/
  local url="$1" sha="$2" name
  name="$(basename "${url%%\?*}")"; name="${name//%2B/+}"
  mkdir -p "$DL"
  if [ ! -f "$DL/$name" ] || [ "$(sha256sum "$DL/$name" | cut -d' ' -f1)" != "$sha" ]; then
    echo "downloading $name" >&2
    curl -fL --retry 3 -o "$DL/$name.part" "$url"
    mv "$DL/$name.part" "$DL/$name"
  fi
  [ "$(sha256sum "$DL/$name" | cut -d' ' -f1)" = "$sha" ] || { echo "checksum mismatch: $name" >&2; exit 1; }
  echo "$DL/$name"
}

# ---------------------------------------------------------------------------------------------
TC_VERSION=$(lock "['toolchain']['version']")
TC_GCC=$(lock "['toolchain']['gcc']")

say "runtime: Python $(lock "['python']['version']") for $PLATFORM"
PY_TGZ=$(fetch "$(lock "['python']['platforms']['$PLATFORM']['url']")" "$(lock "['python']['platforms']['$PLATFORM']['sha256']")")
TC_TXZ=$(fetch "$(lock "['toolchain']['platforms']['$PLATFORM']['url']")" "$(lock "['toolchain']['platforms']['$PLATFORM']['sha256']")")

rm -rf "$RT" "$BUILD/tc" && mkdir -p "$RT" "$BUILD/tc"
tar -xzf "$PY_TGZ" -C "$RT"                          # -> runtime/python
P="$RT/python"
python3 -c "import json; print('\n'.join(json.load(open('$LOCK'))['python']['wheels']['$PLATFORM']))" > "$BUILD/requirements-runtime.txt"
"$P/bin/python3" -m pip install -q --disable-pip-version-check --no-compile --only-binary :all: \
  --require-hashes -r "$BUILD/requirements-runtime.txt"
"$P/bin/python3" -I -c "import capstone, unicorn, importlib.metadata as m; print('capstone', m.version('capstone'), 'unicorn', m.version('unicorn'))"

# prune what the Mod Matrix never uses (Tk, IDLE, pip, headers, tests)
"$P/bin/python3" -m pip uninstall -q -y pip
rm -rf "$P/share" "$P/include" "$P/lib/pkgconfig" "$P/lib/"{libtcl*,itcl*,tcl9*,tk9*,thread*} \
       "$P/lib/python3.12/"{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} \
       "$P/lib/python3.12/"config-3.12-* "$P/lib/python3.12/lib-dynload/"_tkinter*
find "$P/bin" -mindepth 1 ! -name python3 ! -name python3.12 -delete
find "$P" -name __pycache__ -type d -prune -exec rm -rf {} +
# bytecode inside the app, so Python never needs to write there (the server runs with -B)
"$P/bin/python3" -I -m compileall -q -j0 --invalidation-mode unchecked-hash "$P/lib/python3.12" >/dev/null || true

say "runtime: Arm GNU Toolchain $TC_VERSION, trimmed"
tar -xf "$TC_TXZ" -C "$BUILD/tc"
TC_SRC="$(ls -d "$BUILD"/tc/arm-gnu-toolchain-*)"
python3 -c "import json; print('\n'.join(json.load(open('$LOCK'))['toolchain']['keep']))" | while read -r p; do
  mkdir -p "$RT/toolchain/$(dirname "$p")"
  cp -Rp "$TC_SRC/$p" "$RT/toolchain/$p"
done
rm -rf "$BUILD/tc"
# every program and library in the runtime must find what it links
find "$RT" -type f \( -perm -u+x -o -name '*.so' -o -name '*.so.*' \) -print0 | while IFS= read -r -d '' f; do
  file -b "$f" | grep -q ELF || continue
  ldd "$f" 2>/dev/null | { grep 'not found' || true; } | sed "s|^|missing: $f: |"
done | tee "$BUILD/missing.txt"
[ ! -s "$BUILD/missing.txt" ] || { echo "the runtime links libraries this system doesn't have"; exit 1; }
"$RT/toolchain/bin/arm-none-eabi-gcc" --version | head -1
echo 'int f(int x) { return x * 3; }' | "$RT/toolchain/bin/arm-none-eabi-gcc" -mcpu=cortex-m7 -O2 -x c -c -o /dev/null - \
  || { echo "the bundled compiler doesn't run"; exit 1; }

python3 - "$LOCK" "$RT/runtime.json" "$PLATFORM" "$TC_VERSION" <<'EOF'
import json, sys
lock = json.load(open(sys.argv[1]))
pk = {l.split('==')[0]: l.split('==')[1].split()[0] for l in lock['python']['wheels'][sys.argv[3]]}
json.dump({'platform': sys.argv[3], 'python': lock['python']['version'], 'packages': pk,
           'toolchain': sys.argv[4]}, open(sys.argv[2], 'w'), indent=1)
EOF
du -sh "$RT/python" "$RT/toolchain"

# ---------------------------------------------------------------------------------------------
say "launcher: PyInstaller $(lock "['launcher']['pyinstaller']") (no pywebview: the browser is the window)"
VENV="$BUILD/venv"
if [ ! -x "$VENV/bin/pyinstaller" ]; then
  rm -rf "$BUILD/buildpython" "$VENV"
  mkdir -p "$BUILD/buildpython" && tar -xzf "$PY_TGZ" -C "$BUILD/buildpython"
  "$BUILD/buildpython/python/bin/python3" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --disable-pip-version-check "pyinstaller==$(lock "['launcher']['pyinstaller']")"
fi
rm -rf "$DIST" "$BUILD/pyinstaller"
"$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN --distpath "$DIST" --workpath "$BUILD/pyinstaller" modmatrix.spec
APP="$DIST/$NAME"

say "app: runtime, licences and README"
cp -Rp "$RT" "$APP/runtime"
mkdir -p "$APP/licenses"
cp -p licenses/* "$APP/licenses/"
cp -p "$RT/toolchain/share/doc/arm-none-eabi/readme.txt" "$APP/licenses/arm-gnu-toolchain-readme.txt"
cp -p "$RT/python/lib/python3.12/LICENSE.txt" "$APP/licenses/python-LICENSE.txt" 2>/dev/null || true
for pkg in capstone unicorn; do
  for f in "$RT"/python/lib/python3.12/site-packages/$pkg-*.dist-info/{LICENSE*,COPYING*,licenses/*}; do
    [ -f "$f" ] && cp -p "$f" "$APP/licenses/$pkg-$(basename "$f")"
  done
done
for d in "$VENV"/lib/python3.12/site-packages/pyinstaller-*.dist-info; do
  for f in "$d"/{LICENSE*,COPYING*,licenses/*}; do
    [ -f "$f" ] && cp -p "$f" "$APP/licenses/launcher-pyinstaller-$(basename "$f")"
  done
done
cp -p scripts/README-LINUX.txt "$APP/README.txt"

say "tar.gz"
TGZ="$DIST/ModMatrixDesktop-Linux.tar.gz"   # no version: README links to releases/latest/download/
tar -czf "$TGZ" -C "$DIST" "$NAME"
du -sh "$APP" "$TGZ"
echo "-> $TGZ"
