"""Pērkons Mod Matrix desktop launcher.

The app holds a runtime (a standalone Python with capstone and unicorn, and a trimmed Arm
GNU toolchain) and this launcher. It holds no framework and no mods. On start it:

  1. gets the newest perkons-re (main) as a zip from GitHub into the user's data folder,
     or uses the last one when offline (no git needed);
  2. starts perkons-re's tools/modmatrix.py with the bundled Python, the bundled compiler
     first on PATH, on a free port; the Mod Matrix fetches the mods itself;
  3. shows it in a window (pywebview), or in the default browser if no window can be made.

Everything it downloads or writes goes in the data folder (data_dir()), never in the app.

    modmatrix_launcher.py [--browser] [--framework DIR] [--repos-url URL] [--runtime DIR]

--framework and --repos-url are for testing: a local perkons-re checkout instead of the
download, and a different mod repo list instead of the official one.
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
import zipfile

APP_NAME = 'Perkons Mod Matrix Desktop'
DATA_NAME = 'Perkons Mod Matrix'          # the data folder keeps its 0.1/0.2 name: downloads and offline guides stay
APP_VERSION = '0.3.0'
FRAMEWORK_REPO = 'kiteless/perkons-re'
FRAMEWORK_REF = 'main'
COMMIT_URL = f'https://api.github.com/repos/{FRAMEWORK_REPO}/commits/{FRAMEWORK_REF}'
# git's own ref list: no API rate limit (60 an hour per address, shared on some networks)
REFS_URL = f'https://github.com/{FRAMEWORK_REPO}.git/info/refs?service=git-upload-pack'
ZIP_URL = 'https://codeload.github.com/' + FRAMEWORK_REPO + '/zip/{sha}'
TIMEOUT = 20
SERVER_START_TIMEOUT = 120
KEEP_FRAMEWORKS = 2
WINDOWS = platform.system() == 'Windows'
MACOS = platform.system() == 'Darwin'
DEVELOPER = 'remixed123'
TITLE = f'{APP_NAME}, packaged by {DEVELOPER}'
CREDIT = f'The Mod Matrix and perkons-re are by kiteless. Desktop app packaged by {DEVELOPER} (github.com/{DEVELOPER}).'
DISCLAIMER = ('Unofficial. Not affiliated with or endorsed by Erica Synths. Modded firmware is '
              'flashed entirely at your own risk.')


class LaunchError(Exception):
    pass


# -- where things are -------------------------------------------------------------------------

def data_dir():
    if WINDOWS:
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~\\AppData\\Local')
        return os.path.join(base, 'PerkonsModMatrix')         # short: Windows path limits
    if MACOS:
        return os.path.expanduser(f'~/Library/Application Support/{DATA_NAME}')
    return os.path.join(os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share'),
                        'perkons-mod-matrix')


def work_dir(data):
    """The builds' temporary folder: a path without spaces. perkons-re before its fix reads
    the linker map with paths that have no spaces, so a build under "Application Support"
    recorded none of its linked RAM and failed the emulator's RAM watch."""
    if MACOS:
        d = os.path.expanduser('~/Library/Caches/PerkonsModMatrix/tmp')
    else:
        d = os.path.join(data, 'tmp')
    if WINDOWS and ' ' in d:
        os.makedirs(d, exist_ok=True)
        d = _short_path(d)
    return d


def _short_path(path):
    """The 8.3 form of an existing Windows path (no spaces), or the path itself."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)):
            return buf.value
    except Exception:
        pass
    return path


def runtime_dir(override=None):
    """The bundled runtime: Contents/Resources/runtime in the macOS app, runtime\\ next to
    the .exe on Windows; when run from source, build/runtime (or --runtime)."""
    if override:
        return os.path.abspath(override)
    if getattr(sys, 'frozen', False):
        exe = os.path.dirname(os.path.abspath(sys.executable))
        if MACOS:
            return os.path.join(os.path.dirname(exe), 'Resources', 'runtime')
        return os.path.join(exe, 'runtime')
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, 'build', 'runtime')


class Runtime:
    def __init__(self, root):
        self.root = root = os.path.abspath(root)
        info = os.path.join(root, 'runtime.json')
        if not os.path.exists(info):
            raise LaunchError(f'the app is incomplete: no runtime at {root}')
        with open(info) as f:
            self.info = json.load(f)
        self.python = os.path.join(root, 'python', 'python.exe' if WINDOWS else 'bin/python3')
        self.toolchain_bin = os.path.join(root, 'toolchain', 'bin')
        for path in (self.python, os.path.join(self.toolchain_bin, 'arm-none-eabi-gcc' + ('.exe' if WINDOWS else ''))):
            if not os.path.exists(path):
                raise LaunchError(f'the app is incomplete: {path} is missing')


# -- logging -----------------------------------------------------------------------------------

class Log:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + '.1')
        self.f = open(path, 'a', encoding='utf-8')
        self.lock = threading.Lock()

    def __call__(self, msg):
        line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}'
        with self.lock:
            self.f.write(line + '\n')
            self.f.flush()
        if sys.stderr:
            try:
                print(line, file=sys.stderr, flush=True)
            except (OSError, ValueError):
                pass


# -- the framework (perkons-re) ---------------------------------------------------------------

def fetch(url, accept=None, timeout=TIMEOUT):
    headers = {'User-Agent': f'perkons-mod-matrix-desktop/{APP_VERSION}'}
    if accept:
        headers['Accept'] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


FETCH = fetch          # tests replace it


def parse_requirements(text):
    """{name: version} for the 'name==version' lines of a requirements.txt."""
    out = {}
    for line in text.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_.-]+)\s*==\s*([^\s;#]+)', line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def compatible(framework, runtime_info):
    """Whether the bundled Python packages are the versions the framework pins. Returns
    a list of differences (empty: compatible)."""
    path = os.path.join(framework, 'requirements.txt')
    if not os.path.exists(path):
        return []
    with open(path) as f:
        want = parse_requirements(f.read())
    have = {k.lower(): v for k, v in runtime_info.get('packages', {}).items()}
    return [f'{k} {v} (this app has {have.get(k, "none")})' for k, v in sorted(want.items()) if have.get(k) != v]


class Frameworks:
    """framework/<sha>/ folders in the data folder; current.json names the one in use."""

    def __init__(self, data, log):
        self.dir = os.path.join(data, 'framework')
        self.current_file = os.path.join(self.dir, 'current.json')
        self.log = log
        os.makedirs(self.dir, exist_ok=True)

    def current(self):
        try:
            with open(self.current_file) as f:
                sha = json.load(f)['sha']
        except (OSError, ValueError, KeyError):
            return None
        path = os.path.join(self.dir, sha)
        return (sha, path) if os.path.exists(os.path.join(path, 'tools', 'modmatrix.py')) else None

    def latest_sha(self):
        """The commit main is at: from the API, or (refused, e.g. its rate limit) git's ref list."""
        try:
            sha = FETCH(COMMIT_URL, accept='application/vnd.github.sha').decode().strip()
        except urllib.error.HTTPError as e:
            self.log(f'GitHub API: {e}; asking git instead')
            refs = FETCH(REFS_URL).decode('ascii', 'replace')
            m = re.search(r'([0-9a-f]{40}) refs/heads/' + re.escape(FRAMEWORK_REF) + r'\b', refs)
            sha = m.group(1) if m else refs[:80]
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise LaunchError(f'unexpected answer from GitHub for {FRAMEWORK_REPO}: {sha[:80]!r}')
        return sha

    def install(self, sha):
        dest = os.path.join(self.dir, sha)
        if os.path.exists(os.path.join(dest, 'tools', 'modmatrix.py')):
            return dest
        tmp = dest + '.part'
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        zpath = tmp + '.zip'
        with open(zpath, 'wb') as f:
            f.write(FETCH(ZIP_URL.format(sha=sha)))
        try:
            with zipfile.ZipFile(zpath) as z:
                for info in z.infolist():
                    rel = info.filename.partition('/')[2]       # drop the "perkons-re-<sha>/" top
                    if not rel.strip('/'):
                        continue
                    rel = os.path.normpath(rel)
                    if rel.startswith('..') or os.path.isabs(rel) or ':' in rel:
                        raise LaunchError(f'bad path in the perkons-re zip: {info.filename!r}')
                    target = os.path.join(tmp, rel)
                    if info.is_dir():
                        os.makedirs(target, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with z.open(info) as src, open(target, 'wb') as out:
                        shutil.copyfileobj(src, out)
        finally:
            os.remove(zpath)
        if not os.path.exists(os.path.join(tmp, 'tools', 'modmatrix.py')):
            shutil.rmtree(tmp, ignore_errors=True)
            raise LaunchError('the perkons-re download has no tools/modmatrix.py')
        os.replace(tmp, dest)
        return dest

    def set_current(self, sha):
        with open(self.current_file + '.tmp', 'w') as f:
            json.dump({'sha': sha, 'installed': time.strftime('%Y-%m-%dT%H:%M:%S')}, f)
        os.replace(self.current_file + '.tmp', self.current_file)
        self.prune(sha)

    def prune(self, keep_sha):
        """Remove all but the newest KEEP_FRAMEWORKS versions (always keeping keep_sha)."""
        dirs = [d for d in os.listdir(self.dir) if re.fullmatch(r'[0-9a-f]{40}(\.part)?', d)]
        full = sorted((d for d in dirs if not d.endswith('.part') and d != keep_sha),
                      key=lambda d: os.path.getmtime(os.path.join(self.dir, d)), reverse=True)
        for d in [d for d in dirs if d.endswith('.part')] + full[KEEP_FRAMEWORKS - 1:]:
            shutil.rmtree(os.path.join(self.dir, d), ignore_errors=True)

    def prepare(self, runtime_info, status=lambda msg: None):
        """The framework folder to run: the newest perkons-re if it can be fetched and this
        app's packages suit it, else the last one used. Returns (path, notice or None)."""
        cur = self.current()
        try:
            status('Checking for Mod Matrix updates...')
            sha = self.latest_sha()
        except Exception as e:
            if cur:
                self.log(f'offline or GitHub unreachable ({e}); using perkons-re {cur[0][:10]}')
                return cur[1], 'Offline: using the Mod Matrix downloaded before.'
            raise LaunchError('The first start needs an internet connection, to download the Mod Matrix '
                              f'from GitHub ({e}).') from None
        if cur and cur[0] == sha:
            return cur[1], None
        try:
            status('Downloading the Mod Matrix...')
            path = self.install(sha)
        except Exception as e:
            if cur:
                self.log(f'download of perkons-re {sha[:10]} failed ({e}); using {cur[0][:10]}')
                return cur[1], 'The Mod Matrix update could not be downloaded: using the one downloaded before.'
            raise
        diffs = compatible(path, runtime_info)
        if diffs and cur:
            self.log(f'perkons-re {sha[:10]} needs {", ".join(diffs)}; staying on {cur[0][:10]}')
            return cur[1], 'A newer Mod Matrix needs a newer version of this app; using the one downloaded before.'
        if diffs:
            self.log(f'perkons-re {sha[:10]} needs {", ".join(diffs)}; trying it anyway')
        self.set_current(sha)
        self.log(f'perkons-re {sha[:10]} installed')
        return path, None


def link_cache(framework, cache):
    """Point <framework>/.cache at the shared cache folder, so downloaded mods and memory
    measurements survive framework updates (for perkons-re without PERKONS_CACHE)."""
    link = os.path.join(framework, '.cache')
    if os.path.islink(link) or (WINDOWS and os.path.isdir(link) and _is_junction(link)):
        return
    if os.path.exists(link):
        return                       # a real folder (a developer's checkout): leave it
    os.makedirs(cache, exist_ok=True)
    try:
        if WINDOWS:
            subprocess.run(['cmd', '/c', 'mklink', '/J', link, cache], check=True, capture_output=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            os.symlink(cache, link)
    except (OSError, subprocess.CalledProcessError):
        pass                         # PERKONS_CACHE still does it on a framework that reads it


def _is_junction(path):
    try:
        return bool(os.lstat(path).st_file_attributes & 0x400)     # FILE_ATTRIBUTE_REPARSE_POINT
    except (OSError, AttributeError):
        return False


# -- the Mod Matrix server ----------------------------------------------------------------------

def server_env(runtime, data, repos_url=None):
    """The server's environment: the bundled compiler first, only the official mod repo
    list (unless testing), caches and temporary files in the data folder."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('PERKONS_', 'PYTHON', 'ARM_GCC')) and k not in ('VIRTUAL_ENV', '__PYVENV_LAUNCHER__')}
    env['PATH'] = runtime.toolchain_bin + os.pathsep + env.get('PATH', '')
    env['ARM_GCC_PREFIX'] = os.path.join(runtime.toolchain_bin, 'arm-none-eabi-')
    env['PERKONS_CACHE'] = os.path.join(data, 'cache')
    env['TMPDIR'] = env['TEMP'] = env['TMP'] = work_dir(data)
    env['PYTHONUTF8'] = '1'
    if repos_url:
        env['PERKONS_REPOS_URL'] = repos_url
    return env


# Runs tools/modmatrix.py, and ends it when the launcher is gone (its stdin pipe closes), so
# a crashed or force-quit app leaves no server behind.
BOOTSTRAP = '''
import os, runpy, sys, threading
def watch():
    sys.stdin.buffer.read()
    os._exit(0)
threading.Thread(target=watch, daemon=True).start()
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


class Server:
    def __init__(self, runtime, framework, data, log, repos_url=None):
        self.runtime, self.framework, self.data, self.log = runtime, framework, data, log
        self.repos_url = repos_url
        self.proc, self.url, self.shell = None, None, None

    def start(self):
        tmp = work_dir(self.data)
        shutil.rmtree(tmp, ignore_errors=True)            # what a previous run left behind
        os.makedirs(tmp, exist_ok=True)
        link_cache(self.framework, os.path.join(self.data, 'cache'))
        script = os.path.join(self.framework, 'tools', 'modmatrix.py')
        cmd = [self.runtime.python, '-I', '-B', '-u', '-c', BOOTSTRAP, script, '--port', '0', '--no-browser']
        self.log(f'starting: {script}')
        kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if WINDOWS else {'start_new_session': True}
        self.proc = subprocess.Popen(cmd, cwd=self.framework, env=server_env(self.runtime, self.data, self.repos_url),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding='utf-8', errors='replace', bufsize=1, **kw)
        found = threading.Event()

        def read():
            for line in self.proc.stdout:
                line = line.rstrip()
                self.log(f'[server] {line}')
                m = re.search(r'PERKONS MOD MATRIX at (http://127\.0\.0\.1:\d+/)', line)
                if m and not found.is_set():
                    self.url = m.group(1)
                    found.set()
            found.set()
        threading.Thread(target=read, daemon=True).start()
        found.wait(SERVER_START_TIMEOUT)
        if not self.url:
            code = self.proc.poll()
            self.stop()
            raise LaunchError('The Mod Matrix did not start' + (f' (exit code {code})' if code is not None else '') +
                              '. Details are in the log file.')
        self.log(f'Mod Matrix at {self.url}')
        return self.url

    def stop(self):
        if self.shell:
            self.shell.stop()
            self.shell = None
        p = self.proc
        if not p or p.poll() is not None:
            return
        self.log('stopping the Mod Matrix')
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(5)
        shutil.rmtree(work_dir(self.data), ignore_errors=True)


# -- the app's own page: MOD MATRIX and USER GUIDES tabs ----------------------------------------
#
# The window shows a small page served from here: the Mod Matrix in an iframe (tab 1, untouched)
# and the mods' READMEs (tab 2). The guides need no firmware: the mod list comes from the Mod
# Matrix's /api/mods (all repos), each README from GitHub, kept in the data folder for offline use.

RAW_URL = 'https://raw.githubusercontent.com/{repo}/{ref}/{path}'
REPO_RE = re.compile(r'^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$')
REF_RE = re.compile(r'^[A-Za-z0-9._/-]+$')
DOC_PATH_RE = re.compile(r'^[A-Za-z0-9._/ -]+\.md$', re.IGNORECASE)
README_TIMEOUT = 8
UI_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
            '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png'}


def ui_dir():
    """The page's files: ui/ in the frozen app, launcher/ui when run from source."""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'ui')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui')


def _safe_rel(path):
    """A relative path with no '..', no empty or hidden parts (a file name inside a folder)."""
    parts = path.split('/')
    return bool(path) and all(p and p not in ('.', '..') and not p.startswith('.') for p in parts)


class Guides:
    def __init__(self, data, matrix_url, log):
        self.root = os.path.join(data, 'guides')
        self.matrix_url, self.log = matrix_url, log

    def mods(self):
        """Every offered mod (all repos), A-Z by title, with its README's path in its repo."""
        opts = json.loads(FETCH(self.matrix_url + 'api/mods', timeout=SERVER_START_TIMEOUT))['options']
        out = []
        for o in opts:
            repo, ref, readme = o.get('repo'), o.get('ref') or 'main', o.get('readme')
            path = None
            prefix = f'https://github.com/{repo}/blob/{ref}/'
            if repo and readme and readme.startswith(prefix):
                path = readme[len(prefix):]
            out.append({'id': o['id'], 'title': o.get('title') or o['id'], 'summary': o.get('summary', ''),
                        'kind': 'engine' if o.get('kind') == 'voice' else 'mod',
                        'repo': repo, 'ref': ref, 'dir': o.get('dir'), 'author': o.get('author'),
                        'readme': path})
        out.sort(key=lambda m: (m['title'].casefold(), m['id']))
        return out

    def cache_path(self, repo, ref, path):
        owner, name = repo.split('/')
        return os.path.join(self.root, owner, name, *ref.split('/'), *path.split('/'))

    def readme(self, repo, ref, path):
        """(text, from_cache). Fresh from GitHub when it answers, else the copy from last
        time; LaunchError if neither."""
        if not (REPO_RE.match(repo or '') and REF_RE.match(ref or '') and _safe_rel(ref)
                and DOC_PATH_RE.match(path or '') and _safe_rel(path)):
            raise ValueError('not a README in a mod repo')
        cached = self.cache_path(repo, ref, path)
        try:
            raw = FETCH(RAW_URL.format(repo=repo, ref=ref, path=urllib.request.quote(path)), timeout=README_TIMEOUT)
            text = raw.decode('utf-8', errors='replace')
        except Exception as e:
            if os.path.exists(cached):
                with open(cached, encoding='utf-8') as f:
                    return f.read(), True
            self.log(f'guide {repo}/{path}: {e}')
            raise LaunchError('This guide could not be downloaded, and there is no copy from an earlier visit. '
                              'Check the internet connection.') from None
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        tmp = cached + '.part'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, cached)
        return text, False


class Shell:
    """The local web server for the app's page (127.0.0.1, a free port)."""

    def __init__(self, matrix_url, data, log):
        self.matrix_url = matrix_url
        self.guides = Guides(data, matrix_url, log)
        self.log = log
        self.httpd, self.url = None, None

    def start(self):
        from http.server import ThreadingHTTPServer
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.httpd.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}/'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.log(f'app page at {self.url}')
        return self.url

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    def index(self):
        import html
        with open(os.path.join(ui_dir(), 'shell.html'), encoding='utf-8') as f:
            text = f.read()
        origin = self.matrix_url.rstrip('/')
        return (text.replace('{{MATRIX_URL}}', html.escape(self.matrix_url))
                    .replace('{{MATRIX_ORIGIN}}', html.escape(origin))
                    .replace('{{TITLE}}', html.escape(TITLE))
                    .replace('{{CREDIT}}', html.escape(CREDIT)))

    def handler(self):
        from http import HTTPStatus
        from http.server import BaseHTTPRequestHandler
        import urllib.parse
        shell = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def send(self, status, body, ctype):
                if isinstance(body, str):
                    body = body.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)

            def send_json(self, obj, status=HTTPStatus.OK):
                self.send(status, json.dumps(obj), 'application/json')

            def do_GET(self):
                # only this machine's page: a web site can't reach us through a DNS name
                if self.headers.get('Host') != shell.url[len('http://'):-1]:
                    return self.send(HTTPStatus.FORBIDDEN, 'forbidden', 'text/plain')
                url = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(url.query)
                try:
                    if url.path == '/':
                        return self.send(HTTPStatus.OK, shell.index(), UI_TYPES['.html'])
                    if url.path == '/guides/mods':
                        return self.send_json({'mods': shell.guides.mods()})
                    if url.path == '/guides/readme':
                        arg = lambda k: q.get(k, [''])[0]
                        text, cached = shell.guides.readme(arg('repo'), arg('ref'), arg('path'))
                        return self.send_json({'text': text, 'cached': cached})
                    if url.path.startswith('/ui/'):
                        rel = urllib.parse.unquote(url.path[len('/ui/'):])
                        ext = os.path.splitext(rel)[1].lower()
                        full = os.path.join(ui_dir(), *rel.split('/'))
                        if _safe_rel(rel) and ext in UI_TYPES and rel != 'shell.html' and os.path.isfile(full):
                            with open(full, 'rb') as f:
                                return self.send(HTTPStatus.OK, f.read(), UI_TYPES[ext])
                    return self.send(HTTPStatus.NOT_FOUND, 'not found', 'text/plain')
                except ValueError as e:
                    return self.send_json({'error': str(e)}, HTTPStatus.BAD_REQUEST)
                except LaunchError as e:
                    return self.send_json({'error': str(e)}, HTTPStatus.BAD_GATEWAY)
                except Exception as e:
                    shell.log(f'app page {url.path}: {traceback.format_exc()}')
                    return self.send_json({'error': f'{type(e).__name__}: {e}'}, HTTPStatus.INTERNAL_SERVER_ERROR)

        return Handler


# -- the window ---------------------------------------------------------------------------------

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
:root {{ color-scheme: dark; }}
body {{ margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
  background: #40318d; color: #a59ffd; font: 15px/1.5 Menlo, Consolas, monospace; text-align: center; }}
main {{ max-width: 560px; padding: 24px; }}
h1 {{ font-size: 18px; letter-spacing: .1em; margin: 0 0 16px; }}
.msg {{ color: #fff; white-space: pre-wrap; }}
.small {{ font-size: 12px; margin-top: 28px; opacity: .8; }}
</style></head><body><main><h1>PERKONS MOD MATRIX</h1><div class="msg">{msg}</div>
<div class="small">{small}</div><div class="small">{credit}</div></main></body></html>"""


def page(msg, small=DISCLAIMER):
    import html
    return PAGE.format(msg=html.escape(msg), small=html.escape(small), credit=html.escape(CREDIT))


def prepare_and_start(args, runtime, data, log, status):
    """Framework, then server, then the app's page. Returns (server, the page's url, notice)."""
    if args.framework:
        framework, notice = os.path.abspath(args.framework), None
    else:
        framework, notice = Frameworks(data, log).prepare(runtime.info, status)
    status('Starting the Mod Matrix...')
    server = Server(runtime, framework, data, log, args.repos_url)
    matrix_url = server.start()
    server.shell = Shell(matrix_url, data, log)
    return server, server.shell.start(), notice


def unblock_bundle(log):
    """Windows: take the "downloaded from the internet" mark (the Zone.Identifier stream) off
    the app's own DLLs. Explorer's Extract All copies it from the zip onto every file, and
    .NET won't load a marked DLL: pythonnet's, which the window needs."""
    if not (WINDOWS and getattr(sys, 'frozen', False)) or os.environ.get('MODMATRIX_NO_UNBLOCK'):
        return
    n = 0
    for folder, _, files in os.walk(getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))):
        for name in files:
            if name.lower().endswith('.dll'):
                try:
                    os.remove(os.path.join(folder, name) + ':Zone.Identifier')
                    n += 1
                except OSError:
                    pass                     # not marked
    if n:
        log(f'removed the downloaded-from-the-internet mark from {n} DLLs')


def window_backend():
    """pywebview with what its window needs loaded (on Windows: .NET via pythonnet), so a
    failure shows here, before anything starts, and the browser can be used instead."""
    import webview
    if WINDOWS:
        import clr  # noqa: F401
    return webview


def run_window(args, runtime, data, log):
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    try:
        webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
    except Exception:
        pass
    window = webview.create_window(TITLE, html=page('Starting...'), width=1180, height=860,
                                   min_size=(800, 600), background_color='#40318d')
    state = {'server': None}

    def work():
        try:
            server, url, notice = prepare_and_start(args, runtime, data, log,
                                                    lambda msg: window.load_html(page(msg)))
            state['server'] = server
            if notice:
                log(notice)
            window.load_url(url)
        except Exception as e:
            log(traceback.format_exc())
            window.load_html(page(f'{e}', f'Log file: {os.path.join(data, "launcher.log")}\n\n{DISCLAIMER}'))

    window.events.closed += lambda: state['server'] and state['server'].stop()
    try:
        webview.start(work, debug=bool(os.environ.get('MODMATRIX_DEBUG')))
    finally:
        if state['server']:
            state['server'].stop()


def run_browser(args, runtime, data, log):
    server, url, notice = prepare_and_start(args, runtime, data, log, log)
    if notice:
        log(notice)
    webbrowser.open(url)
    print(f'{APP_NAME} is at {url} (close this window or press Ctrl-C to quit)', flush=True)
    try:
        server.proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument('--browser', action='store_true', help='use the default browser, not a window')
    ap.add_argument('--framework', help='a local perkons-re folder instead of the download (testing)')
    ap.add_argument('--repos-url', help='a mod repo list instead of the official one (testing)')
    ap.add_argument('--runtime', help='the runtime folder (when run from source)')
    ap.add_argument('--selftest', action='store_true', help='check the window can load, then exit (CI)')
    # macOS may pass -psn_... to an app started from Finder on old systems
    args, _ = ap.parse_known_args(argv)
    data = data_dir()
    os.makedirs(data, exist_ok=True)
    log = Log(os.path.join(data, 'launcher.log'))
    log(f'{TITLE} {APP_VERSION} on {platform.platform()}; data: {data}')
    try:
        runtime = Runtime(runtime_dir(args.runtime))
    except LaunchError as e:
        log(str(e))
        raise SystemExit(str(e))
    unblock_bundle(log)
    if not args.browser or args.selftest:
        try:
            window_backend()
        except Exception as e:
            log(f'no window ({type(e).__name__}: {e}); using the browser')
            if args.selftest:
                return 1
            args.browser = True
    if args.selftest:
        log('selftest: the window can load')
        return 0
    try:
        (run_browser if args.browser else run_window)(args, runtime, data, log)
    except LaunchError as e:
        log(str(e))
        raise SystemExit(str(e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
