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
import urllib.request
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


PROCESSOR_URL = L.CONTENT_URL.format(name='processor.json')


def processor(updated, fmt=1, **kw):
    return {'format': fmt, 'updated': updated, 'official': 175, 'engines': [], **kw}


class FakeContent:
    def __init__(self):
        self.file, self.log = processor('2099-01-01', note='online'), []

    def __call__(self, url, accept=None, timeout=None):
        self.log.append(url)
        if url == PROCESSOR_URL and self.file is not None:
            return json.dumps(self.file).encode()
        raise OSError('network down')


class TestProcessor(unittest.TestCase):
    """The PROCESSOR & MEMORY numbers: GitHub's, else the newer of last time's and the app's own."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.web, self.saved = FakeContent(), L.FETCH
        L.FETCH = self.web
        self.p = L.Content(self.data, lambda msg: None, 'processor.json', L.parse_processor)
        with open(os.path.join(L.content_dir(), 'processor.json'), encoding='utf-8') as f:
            self.own = json.load(f)

    def tearDown(self):
        L.FETCH = self.saved
        shutil.rmtree(self.data)

    def test_the_apps_own_copy_is_readable(self):
        self.assertTrue(L.processor_readable(self.own))
        self.assertTrue(self.own['engines'])
        for e in self.own['engines']:
            self.assertLessEqual(e['low'], e['high'], e['id'])
        ids = [e['id'] for e in self.own['engines']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(self.own['planner']['defaults']) <= set(ids))

    def test_online_is_used_and_kept_for_offline(self):
        self.assertEqual(self.p.get(), {'data': self.web.file, 'source': 'online'})
        self.web.file = None
        self.assertEqual(self.p.get(), {'data': processor('2099-01-01', note='online'), 'source': 'saved'})

    def test_offline_on_the_first_start_uses_the_apps_own(self):
        self.web.file = None
        self.assertEqual(self.p.get(), {'data': self.own, 'source': 'app'})

    def test_a_saved_copy_older_than_the_apps_own_is_not_used(self):
        self.web.file = processor('2000-01-01')
        self.p.get()
        self.web.file = None
        self.assertEqual(self.p.get()['source'], 'app')

    def test_a_newer_format_is_ignored(self):
        self.p.get()                                     # a readable one saved
        for bad in [processor('2099-02-01', fmt=L.PROCESSOR_FORMAT + 1), {'format': 1}, [1, 2], 'x']:
            self.web.file = bad
            got = self.p.get()
            self.assertEqual((got['source'], got['data']['updated']), ('saved', '2099-01-01'), bad)


class TestPage(unittest.TestCase):
    """The PROCESSOR & MEMORY text: the same fallbacks, and the app's own copy has every part."""

    PARTS = ['plan-button', 'contents', 'diagram', 'engines', 'other-mods', 'planner']

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.text, self.urls = None, []
        self.saved, L.FETCH = L.FETCH, self.fetch
        self.p = L.Content(self.data, lambda msg: None, 'processor.md', L.parse_page)
        with open(os.path.join(L.content_dir(), 'processor.md'), encoding='utf-8') as f:
            self.own = f.read()

    def fetch(self, url, accept=None, timeout=None):
        self.urls.append(url)
        if url == L.GIT_REFS_URL.format(repo=L.APP_REPO):
            return f'003d{SHA2} refs/heads/main\n0000'.encode()
        if url in (L.CONTENT_URL.format(name='processor.md'), L.CONTENT_AT_URL.format(sha=SHA2, name='processor.md')) \
                and self.text is not None:
            return self.text.encode()
        raise OSError('network down')

    def tearDown(self):
        L.FETCH = self.saved
        shutil.rmtree(self.data)

    def test_the_apps_own_copy_has_every_part(self):
        import re
        L.parse_page(self.own.encode())
        self.assertEqual(sorted(re.findall(r'^<!-- pmm:([a-z-]+) -->$', self.own, re.M)), sorted(self.PARTS))
        shell = open(os.path.join(L.ui_dir(), 'shell.html'), encoding='utf-8').read()
        for part in self.PARTS:
            self.assertIn(f'data-part="{part}"', shell)

    def test_the_troubleshooting_page_is_readable(self):
        with open(os.path.join(L.content_dir(), 'troubleshooting.md'), 'rb') as f:
            text, _ = L.parse_page(f.read())
        self.assertIn('<!-- pmm:contents -->', text)

    def test_online_saved_and_the_apps_own(self):
        self.assertEqual(self.p.get(), {'data': self.own, 'source': 'app'})
        self.text = '<!-- pmm:page format=1 updated=2099-01-01 -->\n# New\n'
        self.assertEqual(self.p.get(), {'data': self.text, 'source': 'online'})
        new, self.text = self.text, None
        self.assertEqual(self.p.get(), {'data': new, 'source': 'saved'})

    def test_refresh_asks_past_githubs_cache(self):
        self.text = '<!-- pmm:page format=1 updated=2099-01-01 -->\n# New\n'
        self.p.get()
        self.p.get(fresh=True)
        self.assertEqual(self.urls, [L.CONTENT_URL.format(name='processor.md'),
                                     L.GIT_REFS_URL.format(repo=L.APP_REPO),
                                     L.CONTENT_AT_URL.format(sha=SHA2, name='processor.md')])

    def test_unreadable_pages_are_ignored(self):
        for bad in ['# no header\n', '<!-- pmm:page format=99 updated=2099-01-01 -->\n# x\n']:
            self.text = bad
            self.assertEqual(self.p.get()['source'], 'app', bad)


def atom(*commits):
    """A GitHub commits feed: (sha, date, message), newest first."""
    import html
    entries = ''.join(
        f'<entry><id>x</id><link type="text/html" rel="alternate" href="https://github.com/a/b/commit/{sha}"/>'
        f'<title>{html.escape(msg.splitlines()[0])}</title><updated>{date}</updated>'
        f'<content type="html">&lt;pre&gt;{html.escape(html.escape(msg))}&lt;/pre&gt;</content></entry>'
        for sha, date, msg in commits)
    return f'<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode()


class FakeGuides:
    def __init__(self):
        self.list = [{'id': 'r/m:voice-a', 'title': 'Akords', 'kind': 'engine', 'repo': 'r/m', 'ref': 'main',
                      'dir': 'voice-a', 'author': 'r'}]

    def mods(self):
        return self.list


class TestNews(unittest.TestCase):
    """WHAT'S NEW: each mod's changes; NEW = not marked as seen (by commit, not date)."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.feeds, self.down = {}, False
        self.saved, L.FETCH = L.FETCH, self.fetch
        self.guides = FakeGuides()
        self.news = L.News(self.data, self.guides, lambda msg: None)
        self.set('voice-a', ('a100000', '2026-11-10T00:00:00Z', 'Akords: first\n\nThe details.'))
        self.set(None, ('f100000', '2026-11-09T00:00:00Z', 'framework change'))

    def tearDown(self):
        L.FETCH = self.saved
        shutil.rmtree(self.data)

    def set(self, folder, *commits):
        url = L.FRAMEWORK_FEED if folder is None else L.FEED_URL.format(repo='r/m', ref='main', path=folder)
        self.feeds[url] = atom(*commits)

    def fetch(self, url, accept=None, timeout=None):
        if self.down or url not in self.feeds:
            raise OSError('down')
        if isinstance(self.feeds[url], Exception):
            raise self.feeds[url]
        return self.feeds[url]

    def new(self, fresh=True):
        r = self.news.get(fresh=fresh)
        return {i['title']: [c['sha'] for c in i['changes'] if c['new']] for i in r['items']}, r

    def test_parse(self):
        got = L.parse_feed(atom(('abc1234', '2026-11-17T08:00:00Z', 'Title line <b>\n\nBody & more')))
        self.assertEqual(got, [{'sha': 'abc1234', 'date': '2026-11-17T08:00:00Z', 'title': 'Title line <b>',
                                'body': 'Body & more', 'url': 'https://github.com/a/b/commit/abc1234'}])

    def test_first_run_nothing_is_new_then_new_changes_are(self):
        self.assertEqual(self.new()[0], {'Mod Matrix (perkons-re)': [], 'Akords': []})
        # a new change, and an older-dated one merged in later: both new
        self.set('voice-a', ('a300000', '2026-11-12T00:00:00Z', 'newer'), ('a100000', '2026-11-10T00:00:00Z', 'first'),
                 ('a200000', '2026-11-01T00:00:00Z', 'merged later, older date'))
        self.assertEqual(self.new()[0]['Akords'], ['a300000', 'a200000'])
        # marked as seen: nothing new, and it stays so
        self.news.mark_seen()
        self.assertEqual(self.new()[0]['Akords'], [])

    def test_a_new_mod_and_a_removed_one(self):
        self.new()
        self.guides.list = [{'id': 'r/m:voice-b', 'title': 'Kick Lab', 'kind': 'engine', 'repo': 'r/m',
                             'ref': 'main', 'dir': 'voice-b', 'author': 'r'}]
        self.set('voice-b', ('b100000', '2026-11-11T00:00:00Z', 'kick'))
        _, r = self.new()
        self.assertEqual([i['title'] for i in r['items'] if i['added']], ['Kick Lab'])
        self.assertEqual(r['removed'], ['Akords'])
        self.news.mark_seen()
        _, r = self.new()
        self.assertEqual(([i['title'] for i in r['items'] if i['added']], r['removed']), ([], []))

    def test_offline_uses_the_saved_changes(self):
        self.new()
        self.down = True
        _, r = self.new()
        akords = next(i for i in r['items'] if i['title'] == 'Akords')
        self.assertEqual(([c['sha'] for c in akords['changes']], akords.get('offline'), r['offline']), (['a100000'], True, []))

    def test_a_feed_first_read_later_starts_as_seen(self):
        del self.feeds[L.FEED_URL.format(repo='r/m', ref='main', path='voice-a')]
        _, r = self.new()
        self.assertEqual(r['offline'], ['Akords'])
        self.set('voice-a', ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.assertEqual(self.new()[0]['Akords'], [])

    def test_kept_for_a_while(self):
        self.new()
        self.set('voice-a', ('a900000', '2026-11-12T00:00:00Z', 'newer'), ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.assertEqual(self.new(fresh=False)[0]['Akords'], [])     # the last read, for NEWS_TTL
        self.assertEqual(self.new(fresh=True)[0]['Akords'], ['a900000'])

    def test_unsafe_folders_are_skipped(self):
        self.guides.list = [dict(self.guides.list[0], dir='../x'), dict(self.guides.list[0], repo='bad repo')]
        self.assertEqual([f['key'] for f in self.news.feeds()], [L.FRAMEWORK_REPO])


class FakeFrameworks:
    repo = L.FRAMEWORK_REPO

    def __init__(self, sha):
        self.sha = sha

    def current(self):
        return (self.sha, '/x')


class TestNewsSinceTheBuild(unittest.TestCase):
    """Once a firmware is built (the Mod Matrix's /api/builds), NEW = what changed in the build's
    mods and perkons-re since it, by the feeds at the commits it was made from."""
    BUILT, FW1, FW2 = 'b' * 40, 'c' * 40, 'd' * 40

    set, fetch, new, tearDown = TestNews.set, TestNews.fetch, TestNews.new, TestNews.tearDown

    def setUp(self):
        TestNews.setUp(self)
        self.guides.matrix_url = 'http://127.0.0.1:1/'
        self.guides.list.append({'id': 'r/m:voice-k', 'title': 'Kick Lab', 'kind': 'engine', 'repo': 'r/m',
                                 'ref': 'main', 'dir': 'voice-k', 'author': 'r'})
        self.set('voice-k', ('k100000', '2026-11-10T00:00:00Z', 'kick'))
        self.news.frameworks = FakeFrameworks(self.FW1)
        self.news.note_framework()

    def build(self, when=None):
        import datetime
        when = when or datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.feeds['http://127.0.0.1:1/api/builds'] = json.dumps({'builds': [{
            'when': when, 'version': '1.3.0', 'tag': 'mm-ak',
            'mods': [{'id': 'r/m:voice-a', 'title': 'AKORDS', 'repo': 'r/m', 'ref': 'main', 'commit': self.BUILT}]}]}).encode()

    def at(self, folder, sha, *commits):
        url = (L.REF_FEED_URL.format(repo=L.FRAMEWORK_REPO, ref=sha) if folder is None
               else L.FEED_URL.format(repo='r/m', ref=sha, path=folder))
        self.feeds[url] = atom(*commits)

    def test_changes_since_the_build(self):
        self.new()                                                    # first run: all seen
        self.build()                                                  # built after (with FW1)
        self.at('voice-a', self.BUILT, ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.at(None, self.FW1, ('f100000', '2026-11-09T00:00:00Z', 'framework change'))
        self.set('voice-a', ('a200000', '2026-11-12T00:00:00Z', 'since'), ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.set('voice-k', ('k200000', '2026-11-12T00:00:00Z', 'kick again'), ('k100000', '2026-11-10T00:00:00Z', 'kick'))
        self.set(None, ('f200000', '2026-11-12T00:00:00Z', 'fw since'), ('f100000', '2026-11-09T00:00:00Z', 'framework change'))
        new, r = self.new()
        self.assertEqual(new, {'Mod Matrix (perkons-re)': ['f200000'], 'Akords': ['a200000'], 'Kick Lab': []},
                         'Kick Lab is not in the build')
        self.assertEqual(r['build']['mods'], ['AKORDS'])
        with open(os.path.join(self.data, 'news', 'at.json')) as f:
            self.assertEqual(len(json.load(f)), 2, 'both built feeds kept (read in parallel)')
        self.news.mark_seen()
        self.assertEqual(self.new()[0]['Akords'], [], 'marked as seen after the build')

    def test_seen_before_the_build_doesnt_hide_its_changes(self):
        self.set('voice-a', ('a200000', '2026-11-12T00:00:00Z', 'since'), ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.new()                                                    # first run: a200000 counts as seen
        self.at('voice-a', self.BUILT, ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.build()
        self.assertEqual(self.new()[0]['Akords'], ['a200000'])

    def test_the_build_is_kept_when_the_mod_matrix_cant_say(self):
        self.new()
        self.build('2099-01-01T00:00:00+00:00')
        self.at('voice-a', self.BUILT, ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.new()
        del self.feeds['http://127.0.0.1:1/api/builds']               # stopped, or not answering
        self.assertEqual(self.new()[1]['build']['mods'], ['AKORDS'])

    def test_a_perkons_re_without_build_records_drops_the_kept_build(self):
        self.new()
        self.build()
        self.at('voice-a', self.BUILT, ('a100000', '2026-11-10T00:00:00Z', 'first'))
        self.assertEqual(self.new()[1]['build']['mods'], ['AKORDS'])
        self.feeds['http://127.0.0.1:1/api/builds'] = urllib.error.HTTPError(
            'http://127.0.0.1:1/api/builds', 404, 'Not Found', {}, None)  # back to an older perkons-re
        self.assertIsNone(self.new()[1]['build'], 'since you last looked again')
        del self.feeds['http://127.0.0.1:1/api/builds']               # and then not answering: still none
        self.assertIsNone(self.new()[1]['build'])

    def test_a_build_is_matched_with_the_perkons_re_it_was_made_with(self):
        self.build('2001-01-01T00:00:00+00:00')
        self.assertIsNone(self.news.build()['framework'])
        self.build()
        self.news.frameworks = FakeFrameworks(self.FW2)               # UPDATE NOW: after the build
        self.news.note_framework()
        self.assertEqual(self.news.build()['framework'], {'repo': L.FRAMEWORK_REPO, 'commit': self.FW1})


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
        for view in [b'matrix', b'guides', b'limits']:
            self.assertIn(b'data-view="' + view + b'"', body)
        self.assertIn(b'<script src="/ui/limits.js">', body)

    def test_about(self):
        import html
        body = self.get('/')[1].decode('utf-8')
        self.assertIn(f'Version {L.APP_VERSION} &middot; {L.build_name()}', body)
        self.assertIn(html.escape(L.DISCLAIMER), body)
        self.assertIn('https://github.com/kiteless/perkons-re"', body)
        self.assertIn(f'https://github.com/{L.APP_REPO}/releases"', body)
        self.assertEqual(self.get('/ui/icon-128.png')[0], 200)
        self.assertEqual(self.get('/ui/about.js')[0], 200)

    def test_mac_and_windows_about_say_the_same(self):
        import re
        spec = open(os.path.join(os.path.dirname(L.ui_dir()), '..', 'modmatrix.spec'), encoding='utf-8').read()
        ns = {'DEVELOPER': L.DEVELOPER}
        for name in ('CREDIT', 'DISCLAIMER'):
            src = re.search(rf'^{name} = (.*?)\n(?=\S)', spec, re.M | re.S).group(1)
            ns[name] = eval(src, ns)
        self.assertEqual(ns['DISCLAIMER'], L.DISCLAIMER)
        self.assertTrue(L.CREDIT.startswith(ns['CREDIT'][:-1]), (ns['CREDIT'], L.CREDIT))

    def test_guides_api(self):
        status, body = self.get('/guides/mods')
        mods = json.loads(body)['mods']
        self.assertEqual((status, len(mods)), (200, 5))
        self.assertEqual([(m['kind'], m['repo'], m['readme']) for m in mods[:2]],
                         [('matrix', L.FRAMEWORK_REPO, 'README.md'), ('matrix', L.FRAMEWORK_REPO, 'docs/voice-map.md')])
        self.assertTrue(all(m['kind'] != 'matrix' for m in mods[2:]))
        status, body = self.get('/guides/readme?repo=remixed123/perkons-re-mods&ref=main&path=voice-akords/README.md')
        self.assertEqual((status, json.loads(body)['text']), (200, '# Akords\n'))
        self.assertEqual(self.get('/guides/readme?repo=a/b&ref=main&path=../x.md')[0], 400)

    def test_limits_data(self):
        status, body = self.get('/limits/data')            # FakeWeb has no processor.json: the app's own
        self.assertEqual((status, json.loads(body)['source']), (200, 'app'))
        status, body = self.get('/limits/page')
        self.assertEqual((status, json.loads(body)['source']), (200, 'app'))
        status, body = self.get('/content/troubleshooting')
        self.assertEqual((status, json.loads(body)['source']), (200, 'app'))
        self.assertEqual(self.get('/content/../x')[0], 404)
        self.assertEqual(self.get('/content/processor')[0], 404)

    def test_news(self):
        status, body = self.get('/news')                   # FakeWeb has no feeds: offline, nothing saved
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['offline'][:2], ['Mod Matrix (perkons-re)', 'Akords'])

    def test_files(self):
        self.assertEqual(self.get('/ui/guides.js')[0], 200)
        self.assertEqual(self.get('/ui/limits.js')[0], 200)
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
                return json.dumps({'commits': [{'commit': {'message': 'First\n\nmore'}}, {'commit': {'message': 'Second'}}]}).encode()
        raise OSError(f'404 {url}')


class TestUpdates(unittest.TestCase):
    def setUp(self):
        self.web, self.saved = UpdatesWeb(), (L.FETCH, L.REDIRECT)
        L.FETCH = self.web
        L.REDIRECT = lambda url: f'https://github.com/{L.APP_REPO}/releases/tag/v{L.APP_VERSION}'
        self.server = FakeServer({'options': [dict(o) for o in OLD], 'failed': []})
        fw = type('F', (), {'repo': L.FRAMEWORK_REPO, 'ref': L.FRAMEWORK_REF,
                            'current': lambda self: (SHA1, '/fw/old'),
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

    def test_code_changes_are_not_updates(self):
        self.web.heads[R] = SHA2                                 # WHAT'S NEW lists them instead
        r = self.up.check()
        self.assertEqual((r['restart'], self.up.found_anything(r)), (False, False))
        self.assertEqual(self.up.state(), {})

    def test_the_mod_matrix_compare_is_asked_once(self):
        self.web.heads[L.FRAMEWORK_REPO] = SHA2
        self.up.check()
        self.web.compare_refused = True
        self.assertEqual(self.up.check()['framework']['commits'], ['Second', 'First'])   # kept
        self.up.compares.clear()
        r = self.up.check()
        self.assertEqual((r['framework']['commits'], r['restart']), ([], True))

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
        self.up.check(quiet=True)
        self.assertEqual(len(calls), 3)

    def test_the_button_stays_until_cleared(self):
        newer = lambda url: f'https://github.com/{L.APP_REPO}/releases/tag/v99.0.0'
        same = L.REDIRECT
        self.assertEqual(self.up.state(), {})
        L.REDIRECT = newer
        self.up.check(quiet=True)
        at = self.up.state()['at']
        self.assertEqual(self.up.state()['result']['app']['version'], '99.0.0')
        del self.web.heads[R]                                    # GitHub unreachable: kept
        self.assertTrue(self.up.check(quiet=True)['failed'])
        self.assertTrue(self.up.check()['failed'])
        self.assertEqual(self.up.state()['result']['app']['version'], '99.0.0')
        self.web.heads[R] = SHA1
        self.up.check(quiet=True)
        at = self.up.state()['at']
        L.REDIRECT = same                                        # nothing new any more: kept, unless the
        self.assertFalse(self.up.found_anything(self.up.check(quiet=True)))     # person looks (full check)
        self.assertEqual(self.up.state()['at'], at)
        L.REDIRECT = newer
        self.up.check(quiet=True)
        self.up.clear('99')
        self.assertEqual(self.up.state()['cleared'], '99')       # the page compares it with what it shows
        self.up.check(quiet=True)
        self.assertEqual(self.up.state()['cleared'], '99')
        L.REDIRECT = same
        self.up.check()
        self.assertEqual(self.up.state(), {})
        L.REDIRECT = newer
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



SHA3 = 'c' * 40


class DevWeb:
    """GitHub for the developer settings: branches of a few repos, codeload zips, the official repo list."""
    def __init__(self):
        self.branches = {L.FRAMEWORK_REPO: {'main': SHA1, 'voice-akords-fw': SHA3}, R: {'main': SHA1, 'feature/x': SHA2},
                         K: {'main': SHA1}, 'remixed123/perkons-re': {'main': SHA1, 'voice-x': SHA3}}
        self.official = {'repos': [{'repo': K, 'default': True}, {'repo': R, 'ref': 'main', 'note': 'Glenn'}]}
        self.down, self.log = False, []

    def __call__(self, url, accept=None, timeout=None):
        self.log.append(url)
        if self.down:
            raise OSError('network down')
        if url == L.OFFICIAL_REPOS_URL:
            return json.dumps(self.official).encode()
        if url == L.COMMIT_URL:
            return self.branches[L.FRAMEWORK_REPO]['main'].encode()
        for repo, refs in self.branches.items():
            if url == L.GIT_REFS_URL.format(repo=repo):
                return ''.join(f'{len(sha) + len(ref) + 17:04x}{sha} refs/heads/{ref}\n' for ref, sha in refs.items()).encode() + b'0000'
            for sha in refs.values():
                if url == L.REPO_ZIP_URL.format(repo=repo, sha=sha):
                    return framework_zip(sha)
        raise OSError(f'404 {url}')


class TestDeveloper(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp(prefix='pmm-dev-')
        self.web, self.saved = DevWeb(), L.FETCH
        L.FETCH = self.web
        self.args = type('A', (), {'framework': None, 'repos_url': None})()
        self.dev = L.Developer(self.data, lambda msg: None, self.args)
        self.runtime = type('R', (), {'info': RUNTIME})()

    def tearDown(self):
        L.FETCH = self.saved
        shutil.rmtree(self.data, ignore_errors=True)

    def test_the_panels_choices(self):
        s = self.dev.validate({'framework': 'voice-akords-fw', 'repos': {R: 'feature/x', K: '', 'x/y': '-'}})
        self.assertEqual(s, {'framework': {'repo': L.FRAMEWORK_REPO, 'ref': 'voice-akords-fw'},
                             'repos': [{'repo': R, 'ref': 'feature/x'}], 'off': ['x/y']})
        self.assertEqual(self.dev.validate({'framework': 'main', 'repos': {K: '', R: ''}}), L.Developer.empty())
        for bad in ({'framework': '../x'}, {'repos': {'not a repo': 'main'}}, {'repos': {R: 'a b'}}):
            with self.assertRaises(ValueError, msg=bad):
                self.dev.validate(bad)

    def test_saved_until_back_to_official(self):
        self.assertEqual((self.dev.load(), self.dev.label()), (L.Developer.empty(), ''))
        s = self.dev.validate({'framework': 'voice-akords-fw', 'repos': {R: 'feature/x', K: '-'}})
        self.dev.save(s)
        self.assertEqual(L.Developer(self.data, lambda msg: None, self.args).load(), s)
        self.assertEqual(self.dev.label(), f'perkons-re: voice-akords-fw; mod repos: {R} feature/x, {K} left out')
        self.dev.save(L.Developer.empty())
        self.assertFalse(os.path.exists(self.dev.path))
        self.assertEqual(self.dev.label(), '')

    def test_the_choices_list_every_branch_of_registered_repos(self):
        self.dev.save(self.dev.validate({'framework': 'voice-akords-fw', 'repos': {R: 'feature/x'}}))
        c = self.dev.choices()
        # kiteless's perkons-re, then R's owner's (registered); K's owner is kiteless: no second one
        self.assertEqual([(r['repo'], r['branches']) for r in c['framework']['repos']],
                         [(L.FRAMEWORK_REPO, ['main', 'voice-akords-fw']), ('remixed123/perkons-re', ['main', 'voice-x'])])
        self.assertEqual(c['framework']['chosen'], {'repo': L.FRAMEWORK_REPO, 'ref': 'voice-akords-fw'})
        self.assertEqual([(r['repo'], r['official'], r['branches'], r['chosen']) for r in c['repos']],
                         [(K, 'main', ['main'], ''), (R, 'main', ['feature/x', 'main'], 'feature/x')])
        self.assertEqual(c['repos'][1]['note'], 'Glenn')
        self.web.official['repos'].append({'repo': 'someone/their-mods'})    # no perkons-re of theirs: not offered
        self.assertEqual(len(self.dev.choices()['framework']['repos']), 2)
        self.web.down = True                               # offline, the list from last time: no branches
        c = self.dev.choices()
        self.assertEqual((c['repos'][1]['branches'], bool(c['repos'][1]['failed'])), ([], True))
        os.remove(self.dev.official_copy)
        with self.assertRaises(L.LaunchError):
            self.dev.choices()

    def test_the_flags_take_precedence(self):
        self.dev.save(self.dev.validate({'repos': {R: 'feature/x'}}))
        self.args.repos_url = 'https://example.com/repos.json'
        self.assertEqual(self.dev.repos_url(), self.args.repos_url)
        self.assertIn('(--repos-url)', self.dev.label())

    def test_kiteless_list_with_the_chosen_branches(self):
        self.dev.save(self.dev.validate({'repos': {R: 'feature/x', 'someone/their-mods': 'dev'}}))
        url = self.dev.repos_url()
        self.assertTrue(url.startswith('file:'))
        with urllib.request.urlopen(url) as f:          # what the framework's repos.config() does with it
            got = json.load(f)['repos']
        self.assertEqual(got, [{'repo': K, 'default': True},
                               {'repo': R, 'ref': 'feature/x', 'note': 'Glenn', 'default': True}])   # someone's: not listed
        self.web.down = True                            # offline: the official list from last time
        with open(self.dev.list_path, 'w') as f:
            f.write('{}')
        self.dev.repos_url()
        with open(self.dev.list_path) as f:
            self.assertEqual(len(json.load(f)['repos']), 2)

    def test_a_repo_left_out(self):
        self.dev.save(self.dev.validate({'repos': {K: '-'}}))
        with urllib.request.urlopen(self.dev.repos_url()) as f:
            self.assertEqual(json.load(f), {'repos': [{'repo': R, 'ref': 'main', 'note': 'Glenn'}]})
        with self.assertRaises(ValueError):                # not all of them
            self.dev.check(self.dev.validate({'repos': {K: '-', R: '-'}}))
        self.assertIsNone(L.Developer(tempfile.mkdtemp(), print, self.args).repos_url())   # nothing set: official

    def test_only_what_kiteless_has_registered(self):
        with self.assertRaises(ValueError) as e:
            self.dev.check(self.dev.validate({'repos': {'someone/their-mods': 'dev'}}))
        self.assertIn("not in kiteless's mod repo list", str(e.exception))
        with self.assertRaises(ValueError):
            self.dev.check(self.dev.validate({'repos': {'someone/their-mods': '-'}}))
        # saved before (or edited by hand): left out, the official list used
        self.dev.save({'framework': None, 'repos': [{'repo': 'someone/their-mods', 'ref': 'dev'}], 'off': []})
        self.assertIsNone(self.dev.repos_url())
        # another perkons-re in the saved file: ignored
        self.web.down = True                               # the list can't be read: nothing is taken as listed
        os.remove(self.dev.official_copy)
        with self.assertRaises(L.LaunchError):
            self.dev.check(self.dev.validate({'repos': {R: 'feature/x'}}))

    def test_a_registered_owners_perkons_re(self):
        fork = {'repo': 'remixed123/perkons-re', 'ref': 'voice-x'}
        s = self.dev.validate({'framework': fork})
        self.assertEqual(s['framework'], fork)
        self.assertEqual(self.dev.validate({'framework': {**fork, 'ref': 'main'}})['framework']['ref'], 'main')  # its main: not official
        self.dev.check(s)
        self.dev.save(s)
        self.assertEqual(self.dev.label(), 'perkons-re: remixed123/perkons-re voice-x')
        path, fws, _ = self.dev.framework(self.runtime)
        self.assertEqual((path, fws.repo), (os.path.join(self.data, 'framework-dev', SHA3), 'remixed123/perkons-re'))
        # someone kiteless doesn't list
        other = self.dev.validate({'framework': {'repo': 'someone/perkons-re', 'ref': 'main'}})
        with self.assertRaises(ValueError):
            self.dev.check(other)
        self.dev.save(other)
        self.assertEqual(self.dev.framework(self.runtime)[1].repo, L.FRAMEWORK_REPO)    # saved: ignored, official
        with self.assertRaises(ValueError):
            self.dev.validate({'framework': {'repo': 'remixed123/perkons-re-mods', 'ref': 'main'}})   # not a perkons-re

    def test_a_framework_branch_goes_in_its_own_folder(self):
        self.dev.save(self.dev.validate({'framework': 'voice-akords-fw'}))
        path, fws, notice = self.dev.framework(self.runtime)
        self.assertEqual(path, os.path.join(self.data, 'framework-dev', SHA3))
        self.assertEqual((fws.repo, fws.ref, notice), (L.FRAMEWORK_REPO, 'voice-akords-fw', None))
        self.assertNotIn(L.COMMIT_URL, self.web.log)
        # another branch: not the one downloaded before, even offline
        other = L.Frameworks(self.data, lambda msg: None, L.FRAMEWORK_REPO, 'feature/y')
        self.assertIsNone(other.current())
        self.web.down = True
        with self.assertRaises(L.LaunchError):
            other.prepare(RUNTIME)
        # the official one is untouched by it
        self.assertFalse(os.path.exists(os.path.join(self.data, 'framework', 'current.json')))

    def test_a_framework_branch_asking_for_other_packages_is_still_used(self):
        fws = L.Frameworks(self.data, lambda msg: None, L.FRAMEWORK_REPO, 'voice-akords-fw')
        fws.prepare(RUNTIME)
        self.web.branches[L.FRAMEWORK_REPO]['voice-akords-fw'] = SHA2
        _, notice = fws.prepare({'packages': {'capstone': '9', 'unicorn': '2.1.4'}})
        self.assertEqual(fws.current()[0], SHA2)
        self.assertIn('capstone', notice)

    def test_a_deleted_branch_is_refused_before_anything_restarts(self):
        with self.assertRaises(ValueError) as e:
            self.dev.check(self.dev.validate({'repos': {R: 'nope'}}))
        self.assertIn('no branch nope', str(e.exception))
        self.dev.check(self.dev.validate({'framework': 'voice-akords-fw', 'repos': {R: 'feature/x'}}))

    def test_apply_restarts_and_goes_back_if_it_fails(self):
        class Server:
            framework, repos_url, fail = '/fw/official', None, False

            def __init__(self):
                self.started = []

            def restart(self, framework):
                self.started.append((framework, self.repos_url))
                if self.fail and framework != '/fw/official':
                    raise L.LaunchError('did not start')
                self.framework = framework
        server = Server()
        up = type('U', (), {'lock': __import__('threading').Lock(), 'snapshot': lambda self: None,
                            'frameworks': None, 'last': 1, 'flag': 1})()
        self.dev.server, self.dev.updates = server, up
        self.dev.apply({'framework': 'voice-akords-fw', 'repos': {R: 'feature/x'}}, self.runtime)
        self.assertEqual(server.framework, os.path.join(self.data, 'framework-dev', SHA3))
        self.assertTrue(server.repos_url.startswith('file:'))
        self.assertEqual((up.frameworks.ref, up.last, up.flag), ('voice-akords-fw', None, None))
        self.assertTrue(self.dev.label())
        # that perkons-re won't start: the settings before stay
        server.framework, server.repos_url, server.fail = '/fw/official', None, True
        self.dev.save(L.Developer.empty())
        with self.assertRaises(L.LaunchError):
            self.dev.apply({'framework': 'voice-akords-fw'}, self.runtime)
        self.assertEqual(self.dev.load(), L.Developer.empty())
        self.assertEqual(server.started[-1], ('/fw/official', None))


class TestDeveloperFollowers(unittest.TestCase):
    def test_guides_and_news_follow_the_framework(self):
        d = tempfile.mkdtemp()
        try:
            shell = L.Shell(MATRIX, d, lambda msg: None)
            fws = type('F', (), {'repo': L.FRAMEWORK_REPO, 'ref': 'voice-akords-fw', 'current': lambda self: None})()
            shell.set_framework(fws)
            saved, L.FETCH = L.FETCH, FakeWeb()
            try:
                g = shell.guides.listing()
                feed = shell.news.feeds()[0]
            finally:
                L.FETCH = saved
            self.assertEqual((g[0]['repo'], g[0]['ref']), (L.FRAMEWORK_REPO, 'voice-akords-fw'))
            self.assertEqual(feed['url'], f'https://github.com/{L.FRAMEWORK_REPO}/commits/voice-akords-fw.atom')
            shell.set_framework(None)
            self.assertEqual(shell.guides.framework, (L.FRAMEWORK_REPO, L.FRAMEWORK_REF))
        finally:
            shutil.rmtree(d)

    def test_the_panel_is_on_the_page(self):
        d = tempfile.mkdtemp()
        try:
            shell = L.Shell(MATRIX, d, lambda msg: None, developer=L.Developer(d, lambda msg: None))
            page = shell.index()
            self.assertIn('src="/ui/dev.js"', page)
            self.assertIn('id="about-version"', page)
            self.assertNotIn('{{', page)
        finally:
            shutil.rmtree(d)


if __name__ == '__main__':
    unittest.main()
