"""End-to-end check of a built runtime, without the window: the launcher fetches perkons-re
and starts the Mod Matrix with the bundled Python and toolchain; then, through the Mod
Matrix's own API, an official image is loaded and built with mods from two repos, with the
emulator check on, and the image downloaded. Before that, the bundled toolchain compiles
and links Cortex-M7 code with LTO in a folder with a space, and the bundled Python runs
capstone and unicorn.

    python tests/smoke_build.py [<official .img>] [--runtime DIR] [--framework DIR] [--keep]

Without an image (CI: the official firmware is never put there) it stops before the build.

Uses a temporary data folder, its path with a space (--keep: print it and leave it). The repo
list is the official one (--repos-url: another). Voice-map is the platform, in every build.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'launcher'))
import modmatrix_launcher as L  # noqa: E402

OPTIONS = ['kiteless/perkons-re-mods:fx-reverb']
VOICES = ['remixed123/perkons-re-mods:voice-akords', 'kiteless/perkons-re-mods:voice-zibens',
          'kiteless/perkons-re-mods:voice-step-sampler']


def api(url, path, body=None):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(url.rstrip('/') + path, data=data, method='POST' if data is not None else 'GET')
    with urllib.request.urlopen(req, timeout=600) as r:
        raw = r.read()
    return raw if path.startswith('/api/download') else json.loads(raw)


C_SOURCE = """#include <stdint.h>
volatile uint32_t out;
static uint32_t mix(uint32_t a, uint32_t b) { return (a * 2654435761u) ^ (b >> 3); }
void entry(void) { out = mix(out, 7u); }
"""

EMULATE = """import capstone, unicorn
from unicorn.arm_const import UC_ARM_REG_R0
code = bytes.fromhex('4ff02a00')       # mov.w r0, #42 (Thumb-2)
mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
mu.mem_map(0x8000000, 0x1000)
mu.mem_write(0x8000000, code)
mu.emu_start(0x8000001, 0x8000000 + len(code))
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
print(mu.reg_read(UC_ARM_REG_R0), next(md.disasm(code, 0x8000000)).mnemonic)
"""


def check_runtime(runtime, data):
    """The bundled toolchain and Python, with the server's environment."""
    env = L.server_env(runtime, data)
    os.makedirs(env['TMPDIR'], exist_ok=True)
    work = os.path.join(data, 'tool check')
    os.makedirs(work)
    src, elf = os.path.join(work, 'my src.c'), os.path.join(work, 'out file.elf')
    with open(src, 'w') as f:
        f.write(C_SOURCE)
    pre = env['ARM_GCC_PREFIX']
    def run(*cmd):
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f'failed: {os.path.basename(cmd[0])}\n{r.stdout}{r.stderr}')
        return r.stdout
    run(pre + 'gcc', '-mcpu=cortex-m7', '-mthumb', '-mfloat-abi=hard', '-mfpu=fpv5-d16', '-Os', '-std=c11',
        '-ffreestanding', '-fno-builtin', '-nostdlib', '-Wl,-e,entry', '-o', elf, src)
    run(pre + 'objcopy', '-O', 'binary', elf, os.path.join(work, 'out.bin'))
    assert ' entry' in run(pre + 'nm', elf), 'nm: no entry symbol'
    assert 'entry' in run(pre + 'objdump', '-d', elf), 'objdump: no entry'
    out = run(runtime.python, '-I', '-c', EMULATE).split()
    assert out == ['42', 'mov.w'], out
    print('runtime: toolchain compiles and links, capstone and unicorn run')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image', nargs='?', help='an official firmware image (none: stop before the build)')
    ap.add_argument('--runtime')
    ap.add_argument('--framework')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--repos-url', help='a mod repo list instead of the official one')
    ap.add_argument('--options', nargs='*', default=OPTIONS, help='mod ids (besides the voices)')
    ap.add_argument('--voices', nargs='*', default=VOICES, help='voice ids, in slot order')
    a = ap.parse_args()
    data = tempfile.mkdtemp(prefix='pmm smoke ')   # a space, as in Application Support
    log = L.Log(os.path.join(data, 'launcher.log'))
    runtime = L.Runtime(L.runtime_dir(a.runtime))
    check_runtime(runtime, data)
    args = argparse.Namespace(framework=a.framework, repos_url=a.repos_url)
    t0 = time.time()
    server, page, notice = L.prepare_and_start(args, runtime, data, log, log)
    url = server.url                               # the Mod Matrix itself; `page` is the app's page
    try:
        print(f'server at {url}, app page at {page} after {time.time() - t0:.1f}s; notice: {notice}')
        st = api(url, '/api/status')
        assert st['gcc'], st
        repos = api(url, '/api/repos')
        print('repos:', [(r['repo'], r['mods'], r['error']) for r in repos['repos']])
        assert all(not r['error'] for r in repos['repos']), repos
        mods = api(url, '/api/mods?repos=' + ','.join(r['repo'] for r in repos['repos']))
        offered = {o['id'] for o in mods['options']}
        assert set(a.options + a.voices) <= offered, sorted(set(a.options + a.voices) - offered)
        guides = api(page, '/guides/mods')['mods']
        print('guides:', len(guides), 'mods,', sum(1 for g in guides if g['readme']), 'with a README')
        assert len(guides) == len(mods['options']) and all(g['readme'] for g in guides), guides
        first = guides[0]
        q = urllib.parse.urlencode({'repo': first['repo'], 'ref': first['ref'], 'path': first['readme']})
        assert api(page, f'/guides/readme?{q}')['text'].strip(), first
        if not a.image:
            print('no image: stopping before the build')
            return
        with open(a.image, 'rb') as f:
            info = api(url, '/api/inspect', f.read())
        print('image:', info['version'], 'official' if info['official'] else 'NOT OFFICIAL')
        assert info['official'] and info['supported'], info
        for _ in range(600):
            mem = api(url, f'/api/memory/{info["image"]}')
            if mem.get('state') == 'done':
                break
            time.sleep(0.5)
        job = api(url, '/api/build', {'image': info['image'], 'options': a.options + a.voices, 'voices': a.voices,
                                      'checks': True})['job']
        since = 0
        while True:
            snap = api(url, f'/api/job/{job}?since={since}')
            for line in snap['log']:
                print('  |', line)
            since = snap['next']
            if snap['state'] != 'running':
                break
            time.sleep(1)
        assert snap['state'] == 'done', snap['state']
        img = api(url, snap['download'])
        print(f'built {snap["name"]}: {len(img)} bytes, sha256 {hashlib.sha256(img).hexdigest()[:16]}')
        print(f'total {time.time() - t0:.1f}s')
    finally:
        server.stop()
        if a.keep:
            print('data folder:', data)
        else:
            shutil.rmtree(data, ignore_errors=True)


if __name__ == '__main__':
    main()
