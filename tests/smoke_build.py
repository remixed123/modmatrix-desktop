"""End-to-end check of a built runtime, without the window: the launcher fetches perkons-re
and starts the Mod Matrix with the bundled Python and toolchain; then, through the Mod
Matrix's own API, an official image is loaded and built with mods from two repos, with the
emulator check on, and the image downloaded.

    python tests/smoke_build.py <official .img> [--runtime DIR] [--framework DIR] [--keep]

Uses a temporary data folder, its path with a space (--keep: print it and leave it). The repo
list is the official one (--repos-url: another). Voice-map is the platform, in every build.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
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
    args = argparse.Namespace(framework=a.framework, repos_url=a.repos_url)
    t0 = time.time()
    server, url, notice = L.prepare_and_start(args, runtime, data, log, log)
    try:
        print(f'server at {url} after {time.time() - t0:.1f}s; notice: {notice}')
        st = api(url, '/api/status')
        assert st['gcc'], st
        repos = api(url, '/api/repos')
        print('repos:', [(r['repo'], r['mods'], r['error']) for r in repos['repos']])
        assert all(not r['error'] for r in repos['repos']), repos
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
