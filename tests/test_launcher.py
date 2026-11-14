"""The launcher's framework handling and server environment, with a pretend GitHub.

    python -m unittest discover -s tests
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'launcher'))
import modmatrix_launcher as L  # noqa: E402

SHA1, SHA2 = 'a' * 40, 'b' * 40
RUNTIME = {'packages': {'capstone': '5.0.9', 'unicorn': '2.1.4'}}


def framework_zip(sha, files=None):
    files = {'tools/modmatrix.py': '# server', 'requirements.txt': 'capstone==5.0.9\nunicorn==2.1.4\n',
             **(files or {})}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr(f'perkons-re-{sha}/', '')
        for path, text in files.items():
            z.writestr(f'perkons-re-{sha}/{path}', text)
    return buf.getvalue()


class FakeGitHub:
    def __init__(self):
        self.sha, self.zips, self.down, self.log, self.api_limited = SHA1, {}, False, [], False

    def __call__(self, url, accept=None):
        self.log.append(url)
        if self.down:
            raise OSError('network down')
        if url == L.COMMIT_URL:
            if self.api_limited:
                raise urllib.error.HTTPError(url, 403, 'rate limit exceeded', {}, None)
            return self.sha.encode()
        if url == L.REFS_URL:
            return (f'001e# service=git-upload-pack\n0000015a{"f" * 40} HEAD\0multi_ack symref=HEAD:refs/heads/main\n'
                    f'003d{self.sha} refs/heads/main\n003d{"e" * 40} refs/heads/mainline\n0000').encode()
        for sha, data in self.zips.items():
            if url == L.ZIP_URL.format(sha=sha):
                return data
        raise OSError(f'404 {url}')


class TestFrameworks(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix='pmm-test-')
        self.gh = FakeGitHub()
        self.gh.zips = {SHA1: framework_zip(SHA1), SHA2: framework_zip(SHA2)}
        self.saved, L.FETCH = L.FETCH, self.gh
        self.logged = []
        self.fw = L.Frameworks(self.data, self.logged.append)

    def tearDown(self):
        L.FETCH = self.saved
        shutil.rmtree(self.data, ignore_errors=True)

    def test_first_start_downloads_main(self):
        path, notice = self.fw.prepare(RUNTIME)
        self.assertEqual(path, os.path.join(self.data, 'framework', SHA1))
        self.assertTrue(os.path.exists(os.path.join(path, 'tools', 'modmatrix.py')))
        self.assertIsNone(notice)
        self.assertEqual(self.fw.current()[0], SHA1)

    def test_same_commit_is_not_downloaded_again(self):
        self.fw.prepare(RUNTIME)
        n = len(self.gh.log)
        self.fw.prepare(RUNTIME)
        self.assertEqual(self.gh.log[n:], [L.COMMIT_URL])

    def test_an_update_replaces_it_and_old_ones_are_pruned(self):
        self.fw.prepare(RUNTIME)
        self.gh.sha = SHA2
        path, _ = self.fw.prepare(RUNTIME)
        self.assertEqual(self.fw.current()[0], SHA2)
        self.assertTrue(path.endswith(SHA2))
        sha3 = 'c' * 40
        self.gh.zips[sha3], self.gh.sha = framework_zip(sha3), sha3
        self.fw.prepare(RUNTIME)
        kept = sorted(d for d in os.listdir(os.path.join(self.data, 'framework')) if len(d) == 40)
        self.assertEqual(kept, [SHA2, sha3])

    def test_api_rate_limit_asks_git(self):
        self.gh.api_limited = True
        path, notice = self.fw.prepare(RUNTIME)
        self.assertTrue(path.endswith(SHA1))
        self.assertIsNone(notice)

    def test_offline_uses_the_last_one(self):
        self.fw.prepare(RUNTIME)
        self.gh.down = True
        path, notice = self.fw.prepare(RUNTIME)
        self.assertTrue(path.endswith(SHA1))
        self.assertIn('Offline', notice)

    def test_offline_on_the_first_start_says_so(self):
        self.gh.down = True
        with self.assertRaisesRegex(L.LaunchError, 'internet'):
            self.fw.prepare(RUNTIME)

    def test_an_update_needing_other_packages_is_not_used(self):
        self.fw.prepare(RUNTIME)
        self.gh.zips[SHA2] = framework_zip(SHA2, {'requirements.txt': 'capstone==6.0.0\nunicorn==2.1.4\n'})
        self.gh.sha = SHA2
        path, notice = self.fw.prepare(RUNTIME)
        self.assertTrue(path.endswith(SHA1))
        self.assertIn('newer version of this app', notice)
        self.assertEqual(self.fw.current()[0], SHA1)

    def test_a_zip_escaping_its_folder_is_refused(self):
        self.gh.zips[SHA1] = framework_zip(SHA1, {'../../escape.txt': 'x'})
        with self.assertRaisesRegex(L.LaunchError, 'bad path'):
            self.fw.prepare(RUNTIME)
        self.assertFalse(os.path.exists(os.path.join(self.data, 'escape.txt')))

    def test_a_zip_without_the_mod_matrix_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr(f'perkons-re-{SHA1}/README.md', 'x')
        self.gh.zips[SHA1] = buf.getvalue()
        with self.assertRaisesRegex(L.LaunchError, 'no tools/modmatrix.py'):
            self.fw.prepare(RUNTIME)
        self.assertIsNone(self.fw.current())

    def test_a_failed_update_keeps_the_last_one(self):
        self.fw.prepare(RUNTIME)
        self.gh.sha = 'd' * 40                       # no zip for it
        path, notice = self.fw.prepare(RUNTIME)
        self.assertTrue(path.endswith(SHA1))
        self.assertIn('could not be downloaded', notice)


class TestHelpers(unittest.TestCase):
    def test_requirements(self):
        self.assertEqual(L.parse_requirements('capstone==5.0.9\n# x\nunicorn == 2.1.4  # pinned\nother>=1\n'),
                         {'capstone': '5.0.9', 'unicorn': '2.1.4'})

    def test_server_env(self):
        class R:
            toolchain_bin = '/app/runtime/toolchain/bin'
        saved = dict(os.environ)
        try:
            os.environ.update(PERKONS_MODS='/somewhere', PERKONS_REPOS_URL='http://x', PYTHONPATH='/p',
                              ARM_GCC_PREFIX='/old/', PATH='/usr/bin')
            env = L.server_env(R, '/data')
        finally:
            os.environ.clear()
            os.environ.update(saved)
        self.assertNotIn('PERKONS_MODS', env)
        self.assertNotIn('PERKONS_REPOS_URL', env)
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['PATH'].split(os.pathsep)[0], R.toolchain_bin)
        self.assertEqual(env['ARM_GCC_PREFIX'], os.path.join(R.toolchain_bin, 'arm-none-eabi-'))
        self.assertEqual(env['PERKONS_CACHE'], os.path.join('/data', 'cache'))
        self.assertEqual(env['TMPDIR'], L.work_dir('/data'))
        self.assertEqual(L.server_env(R, '/data', 'file:///r.json')['PERKONS_REPOS_URL'], 'file:///r.json')

    @unittest.skipIf(L.WINDOWS, 'on Windows: the short path, if 8.3 names are on')
    def test_builds_run_in_a_folder_without_spaces(self):
        self.assertNotIn(' ', L.work_dir(os.path.join(tempfile.gettempdir(), 'Application Support', 'X')))

    def test_cache_link(self):
        d = tempfile.mkdtemp()
        try:
            fw = os.path.join(d, 'fw')
            os.makedirs(fw)
            L.link_cache(fw, os.path.join(d, 'cache'))
            self.assertEqual(os.path.realpath(os.path.join(fw, '.cache')), os.path.realpath(os.path.join(d, 'cache')))
            L.link_cache(fw, os.path.join(d, 'cache'))         # again: fine
        finally:
            shutil.rmtree(d)


MATRIX = 'http://127.0.0.1:5555/'
MODS = {'options': [
    {'id': 'kiteless/perkons-re-mods:fx-reverb', 'title': 'FX REVERB', 'summary': 'A reverb.', 'kind': 'mod',
     'repo': 'kiteless/perkons-re-mods', 'ref': 'main', 'dir': 'fx-reverb', 'author': 'kiteless',
     'readme': 'https://github.com/kiteless/perkons-re-mods/blob/main/fx-reverb/README.md'},
    {'id': 'remixed123/perkons-re-mods:voice-akords', 'title': 'Akords', 'summary': 'Chords.', 'kind': 'voice',
     'repo': 'remixed123/perkons-re-mods', 'ref': 'main', 'dir': 'voice-akords', 'author': 'remixed123',
     'readme': 'https://github.com/remixed123/perkons-re-mods/blob/main/voice-akords/README.md'},
    {'id': 'kiteless/perkons-re-mods:pattern-bpm', 'title': 'pattern bpm', 'summary': '', 'kind': 'mod',
     'repo': 'kiteless/perkons-re-mods', 'ref': 'main', 'dir': 'pattern-bpm', 'readme': None},
]}
README = 'https://raw.githubusercontent.com/remixed123/perkons-re-mods/main/voice-akords/README.md'


class FakeWeb:
    def __init__(self):
        self.down, self.log = False, []

    def __call__(self, url, accept=None, timeout=None):
        self.log.append(url)
        if url == MATRIX + 'api/mods':
            return json.dumps(MODS).encode()
        if self.down:
            raise OSError('network down')
        if url == README:
            return '# Akords\n'.encode()
        raise OSError(f'404 {url}')


class TestGuides(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.web, self.saved = FakeWeb(), L.FETCH
        L.FETCH = self.web
        self.guides = L.Guides(self.data, MATRIX, lambda msg: None)

    def tearDown(self):
        L.FETCH = self.saved
        shutil.rmtree(self.data)

    def test_mods_a_to_z_with_kind_and_readme_path(self):
        mods = self.guides.mods()
        self.assertEqual([m['title'] for m in mods], ['Akords', 'FX REVERB', 'pattern bpm'])
        self.assertEqual([m['kind'] for m in mods], ['engine', 'mod', 'mod'])
        self.assertEqual(mods[0]['readme'], 'voice-akords/README.md')
        self.assertIsNone(mods[2]['readme'])

    def test_refresh_reads_the_repos_again(self):
        new = {'id': 'remixed123/perkons-re-mods:voice-kick-lab', 'title': 'Kick Lab', 'summary': '', 'kind': 'voice',
               'repo': 'remixed123/perkons-re-mods', 'ref': 'main', 'dir': 'voice-kick-lab', 'author': 'remixed123',
               'readme': 'https://github.com/remixed123/perkons-re-mods/blob/main/voice-kick-lab/README.md'}
        akords = MODS['options'][1]
        # remixed123 answers (Akords + a new one); kiteless fails: its mods are kept as they were
        self.guides.fresh = lambda: {'options': [akords, new], 'failed': [['kiteless/perkons-re-mods', 'down']]}
        self.assertEqual([m['title'] for m in self.guides.mods(fresh=True)], ['Akords', 'FX REVERB', 'Kick Lab', 'pattern bpm'])
        # a repo that answers replaces what the Mod Matrix had (a mod taken out is gone)
        self.guides.fresh = lambda: {'options': [new], 'failed': []}
        self.assertEqual([m['title'] for m in self.guides.mods(fresh=True)], ['Kick Lab'])
        # not fresh: the Mod Matrix's list
        self.assertEqual(len(self.guides.mods()), 3)

    def test_refresh_failing_gives_the_mod_matrix_list(self):
        def broken():
            raise L.LaunchError('no python')
        self.guides.fresh = broken
        self.assertEqual(len(self.guides.mods(fresh=True)), 3)

    def test_readme_is_kept_for_offline(self):
        args = ('remixed123/perkons-re-mods', 'main', 'voice-akords/README.md')
        self.assertEqual(self.guides.readme(*args), ('# Akords\n', False))
        self.web.down = True
        self.assertEqual(self.guides.readme(*args), ('# Akords\n', True))

    def test_offline_without_a_copy_says_so(self):
        self.web.down = True
        with self.assertRaises(L.LaunchError):
            self.guides.readme('remixed123/perkons-re-mods', 'main', 'voice-akords/README.md')

    def test_only_readmes_in_a_repo(self):
        for repo, ref, path in [('x', 'main', 'a/README.md'), ('a/b', 'main', '../x.md'), ('a/b', '..', 'x.md'),
                                ('a/b', 'main', 'a/../../x.md'), ('a/b', 'main', 'x.py'), ('a/b', 'main', '/etc/x.md'),
                                ('a/b', 'main', '.git/x.md')]:
            with self.assertRaises(ValueError, msg=(repo, ref, path)):
                self.guides.readme(repo, ref, path)
        self.assertEqual(self.web.log, [])


class TestShell(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.web, self.saved = FakeWeb(), L.FETCH
        L.FETCH = self.web
        self.shell = L.Shell(MATRIX, self.data, lambda msg: None)
        self.url = self.shell.start()

    def tearDown(self):
        self.shell.stop()
        L.FETCH = self.saved
        shutil.rmtree(self.data)

    def get(self, path, host=None):
        import http.client
        c = http.client.HTTPConnection(self.url[len('http://'):-1], timeout=5)
        c.request('GET', path, headers={'Host': host} if host else {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body

    def test_page_holds_the_mod_matrix(self):
        status, body = self.get('/')
        self.assertEqual(status, 200)
        self.assertIn(f'src="{MATRIX}"'.encode(), body)
        self.assertIn(b'frame-src http://127.0.0.1:5555;', body)
        self.assertNotIn(b'{{', body)

    def test_guides_api(self):
        status, body = self.get('/guides/mods')
        self.assertEqual((status, len(json.loads(body)['mods'])), (200, 3))
        status, body = self.get('/guides/readme?repo=remixed123/perkons-re-mods&ref=main&path=voice-akords/README.md')
        self.assertEqual((status, json.loads(body)['text']), (200, '# Akords\n'))
        self.assertEqual(self.get('/guides/readme?repo=a/b&ref=main&path=../x.md')[0], 400)

    def test_files(self):
        self.assertEqual(self.get('/ui/guides.js')[0], 200)
        self.assertEqual(self.get('/ui/vendor/purify.min.js')[0], 200)
        for path in ['/ui/../modmatrix_launcher.py', '/ui/%2e%2e/modmatrix_launcher.py', '/ui/shell.html', '/ui/x.py']:
            self.assertEqual(self.get(path)[0], 404, path)

    def test_other_hosts_are_refused(self):
        self.assertEqual(self.get('/guides/mods', host='evil.example:80')[0], 403)

    def test_apply_needs_the_page(self):
        import http.client
        for headers in [{}, {'X-PMM': '1', 'Origin': 'http://evil.example'}, {'X-PMM': '1', 'Host': 'evil.example:80'}]:
            for path in ['/updates/apply', '/updates/clear']:
                c = http.client.HTTPConnection(self.url[len('http://'):-1], timeout=5)
                c.request('POST', path, headers=headers)
                self.assertEqual(c.getresponse().status, 403, (path, headers))
                c.close()


def option(repo, name, title, **kw):
    return {'id': f'{repo}:{name}', 'title': title, 'summary': '', 'repo': repo, 'ref': 'main', 'dir': name,
            'kind': 'mod', 'memory': {'v1.3.0': {'main': 10}}, 'requires': [], 'local': None, **kw}


K, R = 'kiteless/perkons-re-mods', 'remixed123/perkons-re-mods'
OLD = [option(K, 'fx-reverb', 'FX REVERB'), option(R, 'voice-akords', 'Akords'), option(R, 'voice-kick-lab', 'Kick Lab'),
       option(K, 'gone', 'Gone')]


class FakeServer:
    url = MATRIX

    def __init__(self, now):
        self.now, self.framework, self.restarted = now, '/fw/old', []
        self.runtime = type('R', (), {'info': RUNTIME})()

    def fresh_options(self):
        return self.now

    def restart(self, framework):
        self.restarted.append(framework)


class UpdatesWeb:
    """GitHub for the update check: branch commits, compares, the Mod Matrix's list."""
    def __init__(self):
        self.heads = {L.FRAMEWORK_REPO: SHA1, K: SHA1, R: SHA1}
        self.files = {}
        self.compare_refused = False

    def __call__(self, url, accept=None, timeout=None):
        if url == MATRIX + 'api/mods':
            return json.dumps({'options': OLD}).encode()
        for repo, sha in self.heads.items():
            if url == L.GIT_REFS_URL.format(repo=repo):
                return f'003d{sha} refs/heads/main\n0000'.encode()
            if url.startswith(f'https://api.github.com/repos/{repo}/compare/'):
                if self.compare_refused:
                    raise urllib.error.HTTPError(url, 403, 'rate limit exceeded', {}, None)
                return json.dumps({'commits': [{'commit': {'message': 'First\n\nmore'}}, {'commit': {'message': 'Second'}}],
                                   'files': [{'filename': f} for f in self.files.get(repo, [])]}).encode()
        raise OSError(f'404 {url}')


class TestUpdates(unittest.TestCase):
    def setUp(self):
        self.web, self.saved = UpdatesWeb(), (L.FETCH, L.REDIRECT)
        L.FETCH = self.web
        L.REDIRECT = lambda url: f'https://github.com/{L.APP_REPO}/releases/tag/v{L.APP_VERSION}'
        self.server = FakeServer({'options': [dict(o) for o in OLD], 'failed': []})
        fw = type('F', (), {'current': lambda self: (SHA1, '/fw/old'),
                            'prepare': lambda self, info: ('/fw/new', None)})()
        self.up = L.Updates(self.server, fw, lambda msg: None)
        self.up.snapshot()

    def tearDown(self):
        L.FETCH, L.REDIRECT = self.saved

    def test_nothing_changed(self):
        r = self.up.check()
        self.assertEqual(r.pop('this_app'), {'version': L.APP_VERSION, 'latest': L.APP_VERSION})
        self.assertFalse(any(r.values()), r)

    def test_mods_added_removed_and_changed_need_a_restart(self):
        now = [o for o in self.server.now['options'] if o['title'] != 'Gone']
        now[1]['memory'] = {'v1.3.0': {'main': 12}}
        now[1]['summary'] = 'new words'
        now.append(option(R, 'voice-synth-lab', 'Synth Lab'))
        self.server.now = {'options': now, 'failed': []}
        r = self.up.check()
        self.assertEqual([m['title'] for m in r['added']], ['Synth Lab'])
        self.assertEqual([m['title'] for m in r['removed']], ['Gone'])
        self.assertEqual([(m['title'], m['what']) for m in r['changed']], [('Akords', ['RAM figures', 'description'])])
        self.assertTrue(r['restart'])

    def test_a_repo_that_fails_removes_nothing(self):
        self.server.now = {'options': [o for o in OLD if o['repo'] == R], 'failed': [[K, 'down']]}
        r = self.up.check()
        self.assertEqual((r['removed'], r['restart'], r['failed']), ([], False, [[K, 'down']]))

    def test_code_changes_need_nothing(self):
        self.web.heads[R] = SHA2
        self.web.files[R] = ['voice-kick-lab/src/m7/kick_lab.c', 'README.md']
        r = self.up.check()
        self.assertEqual(([m['title'] for m in r['code']], r['restart']), (['Kick Lab'], False))
        self.web.compare_refused = True
        self.assertEqual([m['title'] for m in self.up.check()['code']], ['Kick Lab'])    # asked once, kept
        self.up.compares.clear()
        r = self.up.check()
        self.assertEqual((r['code'], r['unknown']), ([], [R]))

    def test_quiet_check_reuses_the_last_result_while_github_has_nothing_new(self):
        calls = []
        fresh = self.server.fresh_options
        self.server.fresh_options = lambda: calls.append(1) or fresh()
        self.up.check(quiet=True)
        self.up.check(quiet=True)
        self.assertEqual(len(calls), 1)                          # the repos read once
        self.up.check()                                          # the button: always read again
        self.assertEqual(len(calls), 2)
        self.web.heads[R] = SHA2                                 # something new: read again
        self.web.files[R] = ['voice-akords/x.c']
        self.assertEqual([m['title'] for m in self.up.check(quiet=True)['code']], ['Akords'])
        self.assertEqual(len(calls), 3)

    def test_the_button_stays_until_cleared(self):
        self.assertEqual(self.up.state(), {})
        self.web.heads[R] = SHA2
        self.web.files[R] = ['voice-akords/x.c']
        self.up.check(quiet=True)
        at = self.up.state()['at']
        self.assertEqual([m['title'] for m in self.up.state()['result']['code']], ['Akords'])
        del self.web.heads[R]                                    # GitHub unreachable: kept
        self.assertTrue(self.up.check(quiet=True)['failed'])
        self.assertEqual(self.up.check()['code'], [])
        self.assertEqual(self.up.state()['at'], at)
        self.web.heads[R] = SHA1                                 # nothing new any more: kept, unless the
        self.assertFalse(self.up.found_anything(self.up.check(quiet=True)))     # person looks (full check)
        self.assertEqual(self.up.state()['at'], at)
        self.web.heads[R] = SHA2
        self.up.check(quiet=True)
        self.up.clear('Akords')
        self.assertEqual(self.up.state()['cleared'], 'Akords')   # the page compares it with what it shows
        self.up.check(quiet=True)
        self.assertEqual(self.up.state()['cleared'], 'Akords')
        self.web.heads[R] = SHA1
        self.up.check()
        self.assertEqual(self.up.state(), {})
        self.web.heads[R] = SHA2
        self.up.check()
        self.up.apply()                                          # UPDATE NOW: a new start, nothing found yet
        self.assertEqual(self.up.state(), {})

    def test_a_new_mod_matrix_needs_a_restart(self):
        self.web.heads[L.FRAMEWORK_REPO] = SHA2
        r = self.up.check()
        self.assertEqual((r['framework']['commits'], r['restart']), (['Second', 'First'], True))
        self.up.apply()
        self.assertEqual(self.server.restarted, ['/fw/new'])

    def test_a_newer_app(self):
        L.REDIRECT = lambda url: f'https://github.com/{L.APP_REPO}/releases/tag/v99.0.0'
        r = self.up.check()
        self.assertEqual((r['app']['version'], r['restart']), ('99.0.0', False))
        self.assertTrue(r['app']['download'].endswith('/releases/download/v99.0.0/' + L.APP_FILE))
        self.assertEqual(r['this_app'], {'version': L.APP_VERSION, 'latest': '99.0.0'})
        self.assertTrue(self.up.found_anything(r))
        L.REDIRECT = lambda url: f'https://github.com/{L.APP_REPO}/releases/tag/v0.0.9'
        r = self.up.check()
        self.assertIsNone(r['app'])
        self.assertEqual(r['this_app']['latest'], '0.0.9')
        L.REDIRECT = lambda url: (_ for _ in ()).throw(OSError('offline'))
        r = self.up.check()
        self.assertEqual((r['this_app']['latest'], r['failed'][0][0]), (None, 'this app'))


if __name__ == '__main__':
    unittest.main()
