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
        self.sha, self.zips, self.down, self.log = SHA1, {}, False, []

    def __call__(self, url, accept=None):
        self.log.append(url)
        if self.down:
            raise OSError('network down')
        if url == L.COMMIT_URL:
            return self.sha.encode()
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


if __name__ == '__main__':
    unittest.main()
