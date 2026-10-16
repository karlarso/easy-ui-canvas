#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the read-only snapshot API (scripts/canvas.py). Python 3.9-compatible syntax.
Run: python3 tests/test_snapshots_api.py   (UIC_SKILL=<skill dir> to override)
Uses a temp project dir and an ephemeral 127.0.0.1 port only."""
import hashlib
import http.client
import importlib.util
import json
import os
import shutil
import sqlite3
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
canvas.Handler.log_message = lambda self, *a, **k: None  # quiet test output

FRAME_HTML = '<main><h1>Old title</h1><button class="primary">Buy</button></main>'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def project_json(revision, frames=1, columns=None):
    data = {'id': 'hist-test', 'name': 'Hist', 'revision': revision,
            'frames': [{'id': 'f%d' % i, 'title': 'Frame %d' % i, 'width': 390, 'height': 600, 'path': 'frames/f%d.html' % i} for i in range(1, frames + 1)]}
    if columns is not None:
        data['columns'] = columns
    return json.dumps(data)


def tree_hash(root):
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(str(root), followlinks=False):
        dirs.sort()
        for name in sorted(files + [d for d in dirs if os.path.islink(os.path.join(base, d))]):
            full = os.path.join(base, name)
            digest.update(os.path.relpath(full, str(root)).encode())
            if os.path.islink(full):
                digest.update(os.readlink(full).encode())
            elif os.path.isfile(full):
                digest.update(Path(full).read_bytes())
    return digest.hexdigest()


class SnapshotApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='uic-snaptest-'))
        cls.root = cls.tmp / 'canvas'
        root = cls.root
        write(root / 'project.json', project_json('r11', 2, columns=4))
        write(root / 'frames/f1.html', '<main><h1>Current</h1></main>')
        write(root / 'frames/f2.html', '<main><h1>Current 2</h1></main>')
        write(root / 'runtime/secret.txt', 'SECRET-RUNTIME')
        write(root / 'logs/serve.log', 'SECRET-LOG')
        for rev, frames in (('r2', 1), ('r9', 2), ('r10', 3)):
            snap = root / 'snapshots' / rev
            write(snap / 'project.json', project_json(rev, frames))
            for i in range(1, frames + 1):
                write(snap / ('frames/f%d.html' % i), FRAME_HTML.replace('Old title', 'Old %s f%d' % (rev, i)))
            write(snap / 'media/pic.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>')
            write(snap / 'comments.json', json.dumps([{'id': 'c-' + rev, 'text': 'comment in ' + rev, 'frame': 'Frame 1', 'element': 'x', 'target': 'f1--screen', 'status': 'pending', 'created_at': '2026-01-01T00:00:00+00:00'}] if rev == 'r9' else []))
        write(root / 'snapshots/r2/frames/sub/deep.html', '<p>deep</p>')
        # hostile entries
        outside = cls.tmp / 'outside'
        write(outside / 'leak.html', 'LEAKED-OUTSIDE')
        write(outside / 'project.json', project_json('evil', 1))
        (root / 'snapshots/linkrev').symlink_to(outside, target_is_directory=True)           # symlinked snapshot dir
        (root / 'snapshots/r2/frames/escape.html').symlink_to(outside / 'leak.html')         # symlink file inside frames
        (root / 'snapshots/r9/media/link-dir').symlink_to(outside, target_is_directory=True)  # symlink dir inside media
        (root / 'snapshots/r10/comments.json.bak').write_text('x')
        write(root / 'snapshots/stray.txt', 'not a dir')
        write(root / 'snapshots/bad rev/project.json', project_json('bad', 1))               # space in name -> not listed
        write(root / 'snapshots/.hidden/project.json', project_json('hid', 1))                # leading dot -> not listed
        write(root / 'snapshots/broken/project.json', '{not json')                             # listed but valid=false
        # symlinked project.json / frames dir in snapshot
        write(root / 'snapshots/sl/frames/a.html', 'a')
        (root / 'snapshots/sl/project.json').symlink_to(outside / 'project.json')
        write(root / 'snapshots/fl/project.json', project_json('fl', 1))
        (root / 'snapshots/fl/frames').symlink_to(outside, target_is_directory=True)
        # a comment DB so we can prove it is untouched
        con = canvas.database(root)
        con.execute('INSERT INTO comments VALUES (?,?,?,?,?)', ('live1', 'hist-test', 'r11', 'cl1', json.dumps({'id': 'live1', 'text': 'live', 'revision': 'r11'})))
        con.commit()
        con.close()
        handler = partial(canvas.Handler, root=root, ctx={'id': 'hist-test'})
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.before_snap = tree_hash(root / 'snapshots')
        cls.before_db = tree_hash(root / 'runtime')
        cls.before_project = hashlib.sha256((root / 'project.json').read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            hdr = dict(headers or {})
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                hdr.setdefault('Content-Type', 'application/json')
            conn.request(method, path, body=data, headers=hdr)
            resp = conn.getresponse()
            return resp.status, resp.read(), dict(resp.getheaders())
        finally:
            conn.close()

    def get_json(self, path):
        status, body, _ = self.req('GET', path)
        return status, (json.loads(body) if body[:1] in (b'{', b'[') else None)

    # ---- list ----
    def test_list_sorted_desc_and_filtered(self):
        status, data = self.get_json('/api/snapshots')
        self.assertEqual(status, 200)
        revs = [s['rev'] for s in data['snapshots']]
        numeric = [r for r in revs if r in ('r10', 'r9', 'r2')]
        self.assertEqual(numeric, ['r10', 'r9', 'r2'])  # natural order: r10 before r9
        for hidden in ('linkrev', 'stray.txt', 'bad rev', '.hidden'):
            self.assertNotIn(hidden, revs)
        by = {s['rev']: s for s in data['snapshots']}
        self.assertEqual(by['r10']['frames'], 3)
        self.assertEqual(by['r9']['frames'], 2)
        self.assertEqual(by['r9']['comments'], 1)
        self.assertEqual(by['r2']['comments'], 0)
        self.assertTrue(by['r9']['created_at'])
        self.assertFalse(by['broken']['valid'])
        self.assertEqual(data['current_revision'], 'r11')
        self.assertFalse(any(s['current'] for s in data['snapshots']))

    def test_list_without_snapshots_dir(self):
        tmp = Path(tempfile.mkdtemp(prefix='uic-nosnap-'))
        try:
            self.assertEqual(canvas.list_snapshots(tmp), [])
            (tmp / 'snapshots').symlink_to(self.tmp / 'outside', target_is_directory=True)
            self.assertEqual(canvas.list_snapshots(tmp), [])
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

    # ---- reads ----
    def test_project_and_comments(self):
        status, data = self.get_json('/api/snapshots/r9/project')
        self.assertEqual(status, 200)
        self.assertEqual(data['revision'], 'r9')
        self.assertEqual(len(data['frames']), 2)
        status, data = self.get_json('/api/snapshots/r9/comments')
        self.assertEqual(status, 200)
        self.assertEqual(data['comments'][0]['text'], 'comment in r9')
        status, data = self.get_json('/api/snapshots/r2/comments')
        self.assertEqual(data, {'comments': []})

    def test_frames_and_media(self):
        status, body, headers = self.req('GET', '/api/snapshots/r9/frames/f1.html')
        self.assertEqual(status, 200)
        self.assertIn(b'Old r9 f1', body)
        self.assertIn(b'data-ui-id', body)  # annotated like /project/
        self.assertIn('text/html', headers['Content-Type'])
        status, body, headers = self.req('GET', '/api/snapshots/r9/media/pic.svg')
        self.assertEqual(status, 200)
        self.assertIn('svg', headers['Content-Type'])
        status, body, _ = self.req('GET', '/api/snapshots/r2/frames/sub/deep.html')
        self.assertEqual((status, body), (200, b'<p>deep</p>'))
        self.assertEqual(self.req('GET', '/api/snapshots/r9/frames/nope.html')[0], 404)
        # the old snapshot content differs from the current frame
        self.assertNotIn(b'Current', self.req('GET', '/api/snapshots/r9/frames/f1.html')[1])

    # ---- rev validation ----
    def test_bad_revs(self):
        paths = [
            '/api/snapshots/nope/project',
            '/api/snapshots/R9/project',
            '/api/snapshots/../project',
            '/api/snapshots/%2e%2e/project',
            '/api/snapshots/..%2fsnapshots%2fr9/project',
            '/api/snapshots/r9%2f..%2fr2/project',
            '/api/snapshots/.hidden/project',
            '/api/snapshots/bad%20rev/project',
            '/api/snapshots/linkrev/project',
            '/api/snapshots/linkrev/frames/leak.html',
            '/api/snapshots/stray.txt/project',
            '/api/snapshots/r9%00/project',
            '/api/snapshots/%2e/project',
            '/api/snapshots//project',
        ]
        for path in paths:
            status, body, _ = self.req('GET', path)
            self.assertIn(status, (400, 404), path)
            self.assertNotIn(b'LEAKED', body, path)
            self.assertNotIn(b'evil', body, path)

    # ---- path confinement ----
    def test_outside_frames_media(self):
        paths = [
            '/api/snapshots/r9/project.json',
            '/api/snapshots/r9/comments.json',
            '/api/snapshots/r9/runtime/secret.txt',
            '/api/snapshots/r9/frames/../project.json',
            '/api/snapshots/r9/frames/%2e%2e/project.json',
            '/api/snapshots/r9/frames/..%2fproject.json',
            '/api/snapshots/r9/frames/%2e%2e%2f%2e%2e%2fproject.json',
            '/api/snapshots/r9/frames/../../r2/frames/f1.html',
            '/api/snapshots/r9/frames/..%5cproject.json',
            '/api/snapshots/r9/media/../frames/f1.html',
            '/api/snapshots/r9/frames/',
            '/api/snapshots/r9/frames',
            '/api/snapshots/r9/media',
            '/api/snapshots/r9/',
            '/api/snapshots/r9/%2e%2e/%2e%2e/runtime/secret.txt',
            '/api/snapshots/r9/frames/f1.html%00.png',
            '/api/snapshots/r9/etc/passwd',
        ]
        for path in paths:
            status, body, _ = self.req('GET', path)
            self.assertIn(status, (400, 404), path)
            self.assertNotIn(b'SECRET', body, path)
            self.assertNotIn(b'Old r', body, path)

    def test_symlinks_rejected(self):
        for path in ('/api/snapshots/r2/frames/escape.html',
                     '/api/snapshots/r9/media/link-dir/leak.html',
                     '/api/snapshots/fl/frames/leak.html',
                     '/api/snapshots/sl/project',
                     ):
            status, body, _ = self.req('GET', path)
            self.assertIn(status, (400, 404), path)
            self.assertNotIn(b'LEAKED', body, path)
            self.assertNotIn(b'evil', body, path)
        self.assertIsNone(canvas.snapshot_file(self.root / 'snapshots/r2', 'frames/escape.html'))
        self.assertIsNone(canvas.snapshot_dir(self.root, 'linkrev'))
        self.assertIsNotNone(canvas.snapshot_dir(self.root, 'r9'))

    def test_live_project_route_still_hides_snapshots(self):
        self.assertEqual(self.req('GET', '/project/snapshots/r9/project.json')[0], 403)
        self.assertEqual(self.req('GET', '/project/runtime/secret.txt')[0], 403)
        self.assertEqual(self.req('GET', '/project/frames/f1.html')[0], 200)

    # ---- write requests ----
    def test_writes_rejected(self):
        for method in ('POST', 'PATCH', 'DELETE', 'PUT'):
            for path in ('/api/snapshots', '/api/snapshots/r9', '/api/snapshots/r9/comments', '/api/snapshots/r9/project',
                         '/api/snapshots/r9/frames/f1.html', '/api/snapshots/r9/comments/c-r9', '/api/snapshots/nope/comments'):
                status, body, headers = self.req(method, path, body={'text': 'x', 'status': 'changed'})
                self.assertIn(status, (405, 501), method + ' ' + path)
                if status == 405:
                    self.assertEqual(headers.get('Allow'), 'GET')
        # existing comment write routes must not be able to touch snapshot comments either
        status, _, _ = self.req('PATCH', '/api/comments/c-r9', body={'project_id': 'hist-test', 'revision': 'r9', 'status': 'changed'})
        self.assertIn(status, (400, 404))

    def test_zz_nothing_modified(self):
        # run last (alphabetical): all earlier requests together must leave every snapshot and the comment DB untouched
        self.assertEqual(tree_hash(self.root / 'snapshots'), self.before_snap)
        self.assertEqual(hashlib.sha256((self.root / 'project.json').read_bytes()).hexdigest(), self.before_project)
        con = sqlite3.connect(str(self.root / 'runtime/feedback.sqlite3'))
        try:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM comments').fetchone()[0], 1)
            self.assertEqual(json.loads(con.execute("SELECT payload FROM comments WHERE id='live1'").fetchone()[0]).get('text'), 'live')
        finally:
            con.close()

    # ---- columns kept for compatibility ----
    def test_columns_still_validated_and_loaded(self):
        status, data = self.get_json('/api/project')
        self.assertEqual(status, 200)
        self.assertEqual(data['columns'], 4)
        cfg, _ = canvas.manifest(self.root)
        self.assertEqual(cfg['columns'], 4)


class StaticAssetTest(unittest.TestCase):
    def test_layout_toggle_removed(self):
        for name in ('canvas.html', 'canvas.js', 'canvas.css'):
            text = (SKILL / 'assets' / name).read_text(encoding='utf-8')
            for needle in ('id="layout"', "$('layout')", 'single-row'):
                self.assertNotIn(needle, text, name + ': ' + needle)
        self.assertIn('columns', (SKILL / 'assets/canvas.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
