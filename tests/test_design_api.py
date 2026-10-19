#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Design notes API (scripts/canvas.py): GET /api/design and GET /api/snapshots/<rev>/design read DESIGN.md by its fixed name only
(missing or symlink -> {markdown: null}, over 1 MB -> 413, bad bytes replaced), write methods are refused, DESIGN.md is still not a static file,
and `snapshot` keeps DESIGN.md. Python 3.9-compatible; stdlib only. Run: python3 tests/test_design_api.py
Uses a temp project dir and an ephemeral 127.0.0.1 port only."""
import http.client
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

SKILL = Path(os.environ.get('UIC_SKILL', str(Path(__file__).resolve().parents[1])))
spec = importlib.util.spec_from_file_location('canvas_mod', SKILL / 'scripts' / 'canvas.py')
canvas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canvas)
canvas.Handler.log_message = lambda self, *a, **k: None
DICT = json.loads((SKILL / 'assets' / 'i18n.json').read_text(encoding='utf-8'))

NOTES = '# Design notes\n\nFirst **line**.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n\u4e2d\u6587\u8bf4\u660e <script>alert(1)</script>\n'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def project_json(revision):
    return json.dumps({'id': 'design-test', 'name': 'Design', 'revision': revision,
                       'frames': [{'id': 'f1', 'title': 'F1', 'width': 390, 'height': 600, 'path': 'frames/f1.html'}]})


def make_canvas(root, revision='r3'):
    write(root / 'project.json', project_json(revision))
    write(root / 'frames/f1.html', '<main>hi</main>')


class Served(unittest.TestCase):
    @classmethod
    def serve(cls, root):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(canvas.Handler, root=root, ctx={'id': 'design-test'}))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def req(self, method, path, lang='en', body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            headers = {'X-UIC-Lang': lang}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            conn.close()

    def get_json(self, path, lang='en'):
        status, raw, headers = self.req('GET', path, lang)
        return status, json.loads(raw.decode('utf-8')), headers


class DesignApiTest(Served):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='uic-design-'))
        cls.root = cls.tmp / 'canvas'
        make_canvas(cls.root)
        write(cls.root / 'DESIGN.md', NOTES)
        write(cls.root / 'runtime/secret.txt', 'SECRET-RUNTIME')
        snaps = cls.root / 'snapshots'
        make_canvas(snaps / 'r1', 'r1')
        write(snaps / 'r1/DESIGN.md', '# Old notes\n')
        make_canvas(snaps / 'r2', 'r2')                       # snapshot without DESIGN.md
        make_canvas(snaps / 'r4', 'r4')
        write(snaps / 'r4/DESIGN.md', '')                     # empty file: exists, empty text
        make_canvas(snaps / 'r5', 'r5')
        write(snaps / 'r5/DESIGN.md', 'x' * (canvas.DESIGN_LIMIT + 1))
        outside = cls.tmp / 'outside'
        write(outside / 'secret.md', 'LEAKED-OUTSIDE')
        make_canvas(snaps / 'r6', 'r6')
        (snaps / 'r6/DESIGN.md').symlink_to(outside / 'secret.md')   # symlinked DESIGN.md
        make_canvas(snaps / 'r7', 'r7')
        (snaps / 'r7/DESIGN.md').mkdir()                      # a directory is not a file
        make_canvas(snaps / 'r8', 'r8')
        (snaps / 'r8/DESIGN.md').write_bytes(b'ok \xff\xfe bytes')    # not valid UTF-8
        make_canvas(snaps / 'r9', 'r9')
        write(snaps / 'r9/design.md', 'lower case name')      # only the exact name counts
        (snaps / 'linkrev').symlink_to(outside, target_is_directory=True)
        write(outside / 'DESIGN.md', 'LEAKED-VIA-LINKREV')
        cls.serve(cls.root)
        cls.before = {p: p.read_bytes() for p in cls.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_live_design(self):
        status, data, headers = self.get_json('/api/design')
        self.assertEqual(status, 200)
        self.assertEqual(data, {'markdown': NOTES})
        self.assertIn('application/json', headers['Content-Type'])
        self.assertEqual(headers.get('Cache-Control'), 'no-store')

    def test_live_design_follows_the_file_and_is_null_when_removed(self):
        saved = (self.root / 'DESIGN.md').read_bytes()
        try:
            write(self.root / 'DESIGN.md', 'changed')
            self.assertEqual(self.get_json('/api/design')[1], {'markdown': 'changed'})
            (self.root / 'DESIGN.md').unlink()
            self.assertEqual(self.get_json('/api/design')[:2], (200, {'markdown': None}))
        finally:
            (self.root / 'DESIGN.md').write_bytes(saved)

    def test_snapshot_design(self):
        self.assertEqual(self.get_json('/api/snapshots/r1/design')[:2], (200, {'markdown': '# Old notes\n'}))
        self.assertEqual(self.get_json('/api/snapshots/r4/design')[:2], (200, {'markdown': ''}))
        self.assertEqual(self.get_json('/api/snapshots/r8/design')[1]['markdown'], 'ok \ufffd\ufffd bytes')

    def test_snapshot_without_design_is_null(self):
        for rev in ('r2', 'r9'):
            self.assertEqual(self.get_json('/api/snapshots/%s/design' % rev)[:2], (200, {'markdown': None}), rev)

    def test_hostile_snapshot_entries_never_leak(self):
        for rev in ('r6', 'r7'):  # a symlinked or non-regular DESIGN.md counts as missing
            status, data, _ = self.get_json('/api/snapshots/%s/design' % rev)
            self.assertEqual((status, data), (200, {'markdown': None}), rev)
        for rev in ('linkrev', 'nope', '..', '.hidden', 'R1', 'r1%2f..', '%2e%2e'):  # not a snapshot at all
            status, raw, _ = self.req('GET', '/api/snapshots/%s/design' % rev)
            self.assertEqual(status, 404, rev)
            self.assertNotIn(b'LEAKED', raw, rev)

    def test_oversize_is_413(self):
        status, data, _ = self.get_json('/api/snapshots/r5/design')
        self.assertEqual((status, data), (413, {'error': DICT['en']['s.designTooBig']}))
        self.assertEqual(self.get_json('/api/snapshots/r5/design', 'zh')[1], {'error': DICT['zh']['s.designTooBig']})

    def test_only_the_fixed_name_is_served(self):
        for path in ('/api/design/../project', '/api/design/extra', '/api/design?file=../project.json', '/api/snapshots/r1/design/../project'):
            status, raw, _ = self.req('GET', path)
            if path == '/api/design?file=../project.json':
                self.assertEqual(json.loads(raw.decode('utf-8')), {'markdown': NOTES})   # query is ignored
            else:
                self.assertEqual(status, 404, path)
                self.assertNotIn(b'"frames"', raw, path)

    def test_design_is_not_a_static_file(self):
        for path in ('/project/DESIGN.md', '/project/../DESIGN.md', '/project/%2e%2e/DESIGN.md', '/project/snapshots/r1/DESIGN.md', '/DESIGN.md', '/tool/DESIGN.md'):
            status, raw, _ = self.req('GET', path)
            self.assertIn(status, (400, 403, 404), path)
            self.assertNotIn(b'Design notes', raw, path)
            self.assertNotIn(b'Old notes', raw, path)

    def test_writes_are_refused_and_nothing_changes(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            for path in ('/api/design', '/api/snapshots/r1/design'):
                status, _, _ = self.req(method, path, body=json.dumps({'markdown': 'pwn'}))
                self.assertIn(status, (404, 405, 501), method + ' ' + path)
        after = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}
        self.assertEqual(after, self.before)

    def test_project_api_is_unchanged(self):
        status, data, _ = self.get_json('/api/project')
        self.assertEqual(status, 200)
        self.assertEqual(sorted(data), ['frames', 'id', 'name', 'revision'])   # no DESIGN.md content or flag added

    def test_page_has_button_and_dialog(self):
        status, raw, _ = self.req('GET', '/')
        html = raw.decode('utf-8')
        self.assertEqual(status, 200)
        self.assertIn('id="design-notes"', html)
        self.assertIn('id="design-dialog"', html)
        self.assertIn('id="design-notes" type="button"', html)
        mobile = self.req('GET', '/m/')[1].decode('utf-8')
        self.assertNotIn('design-notes', mobile)             # the phone preview is unchanged


class SnapshotCliTest(unittest.TestCase):
    def snapshot(self, with_design):
        tmp = Path(tempfile.mkdtemp(prefix='uic-design-cli-'))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        cdir = tmp / 'canvases' / '4000-abc123'
        make_canvas(cdir, 'r7')
        write(cdir / 'canvas.json', json.dumps({'schema': 1, 'id': 'abc123', 'name': 'T'}))
        if with_design:
            write(cdir / 'DESIGN.md', NOTES)
        env = dict(os.environ, UI_CANVAS_RUNTIME=str(tmp), LC_ALL='C', LANG='C')
        env.pop('UI_CANVAS_LANG', None)
        result = subprocess.run([sys.executable, str(SKILL / 'scripts/canvas.py'), 'snapshot', '--canvas', 'abc123'], env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return cdir / 'snapshots' / 'r7'

    def test_snapshot_keeps_design_md(self):
        snap = self.snapshot(True)
        self.assertEqual((snap / 'DESIGN.md').read_text(encoding='utf-8'), NOTES)
        self.assertTrue((snap / 'project.json').is_file())

    def test_snapshot_without_design_md(self):
        snap = self.snapshot(False)
        self.assertFalse((snap / 'DESIGN.md').exists())
        self.assertTrue((snap / 'comments.json').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
