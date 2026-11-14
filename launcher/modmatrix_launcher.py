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
APP_VERSION = '0.5.1'
FRAMEWORK_REPO = 'kiteless/perkons-re'
FRAMEWORK_REF = 'main'
COMMIT_URL = f'https://api.github.com/repos/{FRAMEWORK_REPO}/commits/{FRAMEWORK_REF}'
# git's own ref list: no API rate limit (60 an hour per address, shared on some networks)
REFS_URL = f'https://github.com/{FRAMEWORK_REPO}.git/info/refs?service=git-upload-pack'   # = GIT_REFS_URL for it
ZIP_URL = 'https://codeload.github.com/' + FRAMEWORK_REPO + '/zip/{sha}'
GIT_REFS_URL = 'https://github.com/{repo}.git/info/refs?service=git-upload-pack'
COMPARE_URL = 'https://api.github.com/repos/{repo}/compare/{old}...{new}'
APP_REPO = 'remixed123/modmatrix-desktop'
APP_LATEST_URL = f'https://github.com/{APP_REPO}/releases/latest'      # redirects to the newest release
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def redirect_target(url, timeout=TIMEOUT):
    """Where `url` redirects to (its Location), without following it; None if it doesn't."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={'User-Agent': f'perkons-mod-matrix-desktop/{APP_VERSION}'}, method='HEAD')
    try:
        with opener.open(req, timeout=timeout):
            return None
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.headers.get('Location')
        raise


REDIRECT = redirect_target   # tests replace it


def ref_commit(repo, ref='main'):
    """The commit a branch is at, from git's own ref list (no GitHub API rate limit)."""
    refs = FETCH(GIT_REFS_URL.format(repo=repo)).decode('ascii', 'replace')
    m = re.search(r'([0-9a-f]{40}) refs/heads/' + re.escape(ref) + r'(?=[\s\x00]|$)', refs)
    if not m:
        raise LaunchError(f'no branch {ref} in {repo}')
    return m.group(1)


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
            sha = ref_commit(FRAMEWORK_REPO, FRAMEWORK_REF)
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

# The repo list and every repo's manifest, read again now with the framework's own code (the
# Mod Matrix reads them once, at start): {options: [as the Mod Matrix's], failed: [[repo, why]]}.
REFRESH = '''
import json, sys
sys.path.insert(0, "tools")
from perkons import repos
out, failed = [], []
for r in repos.config():
    try:
        out += repos.options(repos.manifest(r["repo"], r["ref"]), r["ref"])
    except Exception as e:
        failed.append([r["repo"], str(e)])
sys.stdout.write(json.dumps({"options": out, "failed": failed}))
'''
REFRESH_TIMEOUT = 60


class Server:
    def __init__(self, runtime, framework, data, log, repos_url=None):
        self.runtime, self.framework, self.data, self.log = runtime, framework, data, log
        self.repos_url = repos_url
        self.proc, self.url, self.shell = None, None, None

    def fresh_options(self):
        """The repos' mods as they are on GitHub now (Guides' fresh)."""
        kw = {'creationflags': subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
        r = subprocess.run([self.runtime.python, '-I', '-B', '-c', REFRESH], cwd=self.framework,
                           env=server_env(self.runtime, self.data, self.repos_url), capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=REFRESH_TIMEOUT, **kw)
        if r.returncode:
            raise LaunchError((r.stderr.strip().splitlines() or ['no output'])[-1])
        return json.loads(r.stdout)

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
        self.stop_matrix()

    def restart(self, framework):
        """The Mod Matrix again (the app's page keeps running), on `framework`; back on the
        one before if it won't start. Returns its url."""
        old = self.framework
        self.stop_matrix()
        self.framework, self.url = framework, None
        try:
            self.start()
        except LaunchError:
            if framework == old:
                raise
            self.log(f'the new Mod Matrix did not start; back to {old}')
            self.stop_matrix()
            self.framework, self.url = old, None
            self.start()
            raise LaunchError('The updated Mod Matrix did not start, so the app went back to the one it had. '
                              'Details are in the log file.') from None
        if self.shell:
            self.shell.set_matrix(self.url)
        return self.url

    def stop_matrix(self):
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


# -- CHECK FOR UPDATES ---------------------------------------------------------------------------
#
# What changed since the Mod Matrix started: the app itself (a newer release), perkons-re (only
# used after a restart), the mods offered (the Mod Matrix reads the list, RAM figures and
# requirements once, at start: a restart needed) and mods whose code changed (a build fetches a
# mod's code as it is then: nothing to do). UPDATE NOW restarts the Mod Matrix inside the app.

# a mod's fields that matter for building, and what to call a change of them
CHANGE_NAMES = (('memory', 'RAM figures'), ('requires', 'requirements'), ('conflicts', 'conflicts'),
                ('target', 'firmware version'), ('patches', 'build settings'), ('code', 'build settings'),
                ('kind', 'type'), ('dir', 'folder'),
                ('title', 'description'), ('summary', 'description'), ('description', 'description'))
MAX_COMMITS = 6
AUTO_CHECK_MINUTES = 60      # the page's quiet check: after this long running, at most this often


def auto_check_minutes():
    """MODMATRIX_AUTO_CHECK_MINUTES: a shorter time, to try the quiet check (development)."""
    try:
        return max(1, int(os.environ.get('MODMATRIX_AUTO_CHECK_MINUTES', AUTO_CHECK_MINUTES)))
    except ValueError:
        return AUTO_CHECK_MINUTES


def version_tuple(text):
    return tuple(int(n) for n in re.findall(r'\d+', text or '')[:3])


def first_line(msg, width=140):
    line = (msg or '').strip().splitlines()[0] if (msg or '').strip() else ''
    return line if len(line) <= width else line[:width - 1].rstrip() + '\u2026'


class Updates:
    def __init__(self, server, frameworks, log):
        self.server, self.frameworks, self.log = server, frameworks, log
        self.lock = threading.Lock()
        self.base = {'framework': None, 'repos': {}}
        self.compares = {}          # (repo, old, new) -> compare(): commits don't change
        self.last = None            # (what GitHub had, the result): a quiet check with nothing new reuses it
        # what the button shows, kept here so it survives the page reloading (the Mac's web view
        # can reload a page left in the background): {result, at, cleared}. A check that finds
        # nothing doesn't clear it (GitHub unreachable, a check while waking up); only the
        # person's CLEAR (cleared = what they cleared), UPDATE NOW, or a full check that
        # reached everything and found nothing
        self.flag = None

    def snapshot(self):
        """Note what the Mod Matrix starts with: perkons-re's commit and each mod repo's
        (in the background: the repos take the Mod Matrix a moment to read)."""
        base = {'framework': self.frameworks.current()[0] if self.frameworks and self.frameworks.current() else None,
                'repos': {}}
        try:
            for repo, ref in sorted(self.repos(self.matrix_options())):
                try:
                    base['repos'][(repo, ref)] = ref_commit(repo, ref)
                except Exception as e:
                    self.log(f'updates: {repo} {ref}: {e}')
        except Exception as e:
            self.log(f'updates: the mod list: {e}')
        self.base = base

    def matrix_options(self):
        return json.loads(FETCH(self.server.url + 'api/mods', timeout=SERVER_START_TIMEOUT))['options']

    @staticmethod
    def repos(options):
        return {(o['repo'], o.get('ref') or 'main') for o in options if o.get('repo') and not o.get('local')}

    def compare(self, repo, old, new):
        """(first lines of the commit messages, newest first; files changed), or None (the API refused)."""
        key = (repo, old, new)
        if key not in self.compares:
            self.compares[key] = self._compare(repo, old, new)
            if self.compares[key] is None:
                del self.compares[key]      # refused (its rate limit): ask again next time
                return None
        return self.compares[key]

    def _compare(self, repo, old, new):
        try:
            c = json.loads(FETCH(COMPARE_URL.format(repo=repo, old=old, new=new), accept='application/vnd.github+json'))
        except Exception as e:
            self.log(f'updates: compare {repo}: {e}')
            return None
        msgs = [first_line(x.get('commit', {}).get('message')) for x in reversed(c.get('commits', []))]
        return {'commits': [m for m in msgs if m][:MAX_COMMITS], 'more': max(0, len(msgs) - MAX_COMMITS),
                'files': [f['filename'] for f in c.get('files', [])]}

    def probe(self):
        """What GitHub has now, cheaply (no API calls): the newest app release, and the
        commit perkons-re and each mod repo are at. {app, framework, repos, failed}."""
        got = {'app': None, 'framework': None, 'repos': {}, 'failed': []}
        try:
            where = REDIRECT(APP_LATEST_URL) or ''
            if '/releases/tag/' in where:
                got['app'] = where.rstrip('/').rsplit('/', 1)[-1]
        except Exception as e:
            got['failed'].append(['this app', str(e)])
        if self.base['framework']:
            try:
                got['framework'] = ref_commit(FRAMEWORK_REPO, FRAMEWORK_REF)
            except Exception as e:
                got['failed'].append([FRAMEWORK_REPO, str(e)])
        for (repo, ref) in sorted(self.base['repos']):
            try:
                got['repos'][(repo, ref)] = ref_commit(repo, ref)
            except Exception as e:
                got['failed'].append([repo, str(e)])
        return got

    def check(self, quiet=False):
        """What changed since the Mod Matrix started. quiet (the automatic check): when
        GitHub has nothing new since the last check, that check's result, without reading
        the repos again."""
        with self.lock:
            got = self.probe()
            seen = json.dumps([got['app'], got['framework'], sorted(got['repos'].items()), bool(got['failed'])])
            if quiet and self.last and self.last[0] == seen:
                return self.last[1]
            out = self._check(got)
            self.last = (seen, out)
            self._remember(out, quiet)
            return out

    @staticmethod
    def found_anything(r):
        return bool(r['app'] or r['restart'] or r['code'] or r['unknown'])

    def _remember(self, out, quiet):
        if self.found_anything(out):
            if not self.flag or self.flag['result'] != out:
                self.flag = {'result': out, 'at': time.time(), 'cleared': self.flag and self.flag['cleared']}
        elif not quiet and not out['failed']:
            self.flag = None

    def state(self):
        """The button's state, no GitHub: {result, at, cleared} or {}."""
        with self.lock:
            return dict(self.flag or {})

    def clear(self, key):
        """CLEAR in the panel: the finding the person has seen (the page's summary of it)."""
        with self.lock:
            if self.flag:
                self.flag['cleared'] = str(key)[:4000]

    def _check(self, got):
        out = {'app': None, 'framework': None, 'added': [], 'removed': [], 'changed': [], 'code': [],
               'unknown': [], 'failed': list(got['failed']), 'restart': False}
        # the app
        tag = got['app']
        if tag and version_tuple(tag) > version_tuple(APP_VERSION):
            out['app'] = {'version': tag.lstrip('v'), 'url': f'https://github.com/{APP_REPO}/releases/tag/{tag}'}
        # perkons-re
        old = self.base['framework']
        new = got['framework']
        if old and new and new != old:
            diff = self.compare(FRAMEWORK_REPO, old, new) or {}
            out['framework'] = {'repo': FRAMEWORK_REPO, 'commits': diff.get('commits', []), 'more': diff.get('more', 0)}
        # the mods offered: the Mod Matrix's list against the repos now
        then = {o['id']: o for o in self.matrix_options() if o.get('repo') and not o.get('local')}
        try:
            now_all = self.server.fresh_options()
        except Exception as e:
            now_all = {'options': [], 'failed': [['the mod repos', str(e)]]}
            self.log(f'updates: reading the repos: {e}')
        failed = {r.lower() for r, _ in now_all.get('failed', [])}
        out['failed'] += now_all.get('failed', [])
        now = {o['id']: o for o in now_all['options'] if o.get('repo')}
        title = lambda o: o.get('title') or o['id']
        info = lambda o: {'id': o['id'], 'title': title(o), 'repo': o['repo']}
        for i in sorted(set(now) - set(then)):
            out['added'].append(info(now[i]))
        for i in sorted(set(then) - set(now)):
            if then[i]['repo'].lower() not in failed:
                out['removed'].append(info(then[i]))
        for i in sorted(set(then) & set(now)):
            what = []
            for key, name in CHANGE_NAMES:
                if then[i].get(key) != now[i].get(key) and name not in what:
                    what.append(name)
            if what:
                out['changed'].append({**info(now[i]), 'what': what})
        # mods whose code changed (their folders), repo by repo
        listed = {m['id'] for m in out['added'] + out['changed']}
        for (repo, ref), old in sorted(self.base['repos'].items()):
            new = got['repos'].get((repo, ref))
            if repo.lower() in failed or not new or new == old:
                continue
            diff = self.compare(repo, old, new)
            if diff is None:
                out['unknown'].append(repo)
                continue
            for o in sorted((o for o in now.values() if o['repo'] == repo and o['id'] not in listed), key=title):
                if any(f.startswith(o['dir'].rstrip('/') + '/') for f in diff['files']):
                    out['code'].append(info(o))
        out['restart'] = bool(out['framework'] or out['added'] or out['removed'] or out['changed'])
        self.log('updates: ' + json.dumps({k: v for k, v in out.items() if v}))
        return out

    def apply(self):
        """UPDATE NOW: the newest perkons-re (if there is one), and the Mod Matrix started
        again, so it reads the repos again. Returns a notice or None."""
        with self.lock:
            notice = None
            framework = self.server.framework
            if self.frameworks:
                framework, notice = self.frameworks.prepare(self.server.runtime.info)
            self.server.restart(framework)
            self.last = None
            self.flag = None
        threading.Thread(target=self.snapshot, daemon=True).start()
        return notice


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
    def __init__(self, data, matrix_url, log, fresh=None):
        self.root = os.path.join(data, 'guides')
        self.matrix_url, self.log = matrix_url, log
        self.fresh = fresh          # () -> {options, failed}: the repos read again now (Server.fresh_options)

    def mods(self, fresh=False):
        """Every offered mod (all repos), A-Z by title, with its README's path in its repo.
        The Mod Matrix reads the repos once, when it starts; fresh: read them again now (for
        mods released since), each repo that answers replacing what the Mod Matrix has."""
        opts = json.loads(FETCH(self.matrix_url + 'api/mods', timeout=SERVER_START_TIMEOUT))['options']
        if fresh and self.fresh:
            try:
                now = self.fresh()
            except Exception as e:
                self.log(f'guides: reading the repos again failed: {e}')
            else:
                failed = {r.lower() for r, _ in now.get('failed', [])}
                on_disk = {o['repo'].lower() for o in opts if o.get('repo') and o.get('local')}   # a developer's clone
                opts = ([o for o in opts if not o.get('repo') or o['repo'].lower() in failed | on_disk] +
                        [o for o in now['options'] if o['repo'].lower() not in on_disk])
                for repo, err in now.get('failed', []):
                    self.log(f'guides: {repo}: {err}')
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

    def __init__(self, matrix_url, data, log, fresh=None, updates=None):
        self.matrix_url = matrix_url
        self.guides = Guides(data, matrix_url, log, fresh)
        self.updates = updates
        self.log = log
        self.httpd, self.url = None, None

    def set_matrix(self, url):
        """The Mod Matrix restarted (UPDATE NOW): on a new port."""
        self.matrix_url = self.guides.matrix_url = url

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
                    .replace('{{AUTO_CHECK}}', str(auto_check_minutes()))
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
                        return self.send_json({'mods': shell.guides.mods(fresh=q.get('fresh') == ['1'])})
                    if url.path == '/updates/check' and shell.updates:
                        return self.send_json(shell.updates.check(quiet=q.get('quiet') == ['1']))
                    if url.path == '/updates/state' and shell.updates:
                        return self.send_json(shell.updates.state())
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

            def do_POST(self):
                # only the app's own page: the custom header can't be sent by another site's page
                # without a CORS preflight, which this server never answers
                if (self.headers.get('Host') != shell.url[len('http://'):-1] or self.headers.get('X-PMM') != '1'
                        or self.headers.get('Origin', shell.url.rstrip('/')) != shell.url.rstrip('/')):
                    return self.send(HTTPStatus.FORBIDDEN, 'forbidden', 'text/plain')
                try:
                    if self.path == '/updates/apply' and shell.updates:
                        return self.send_json({'notice': shell.updates.apply()})
                    if self.path == '/updates/clear' and shell.updates:
                        n = int(self.headers.get('Content-Length') or 0)
                        body = json.loads(self.rfile.read(min(n, 8192)) or b'{}')
                        shell.updates.clear(body.get('key', ''))
                        return self.send_json({})
                    return self.send(HTTPStatus.NOT_FOUND, 'not found', 'text/plain')
                except LaunchError as e:
                    return self.send_json({'error': str(e)}, HTTPStatus.BAD_GATEWAY)
                except Exception as e:
                    shell.log(f'app page {self.path}: {traceback.format_exc()}')
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
    frameworks = None
    if args.framework:
        framework, notice = os.path.abspath(args.framework), None
    else:
        frameworks = Frameworks(data, log)
        framework, notice = frameworks.prepare(runtime.info, status)
    status('Starting the Mod Matrix...')
    server = Server(runtime, framework, data, log, args.repos_url)
    matrix_url = server.start()
    updates = Updates(server, frameworks, log)
    threading.Thread(target=updates.snapshot, daemon=True).start()
    server.shell = Shell(matrix_url, data, log, server.fresh_options, updates)
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
                                   min_size=(800, 600), background_color='#40318d',
                                   text_select=True)     # pywebview blocks selecting (so copying) text otherwise
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
