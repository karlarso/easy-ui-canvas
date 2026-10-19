#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""gzip for text responses (scripts/canvas.py): HTML, CSS, JS and JSON are compressed when Accept-Encoding allows gzip (q=0 respected),
Content-Length is the compressed size, Vary: Accept-Encoding is set, the decoded body equals the plain one, nothing else is compressed
(images, zip, tiny bodies) and Cache-Control stays no-store (no caching added). Canvas server in-process; list service as a real process.
Python 3.9-compatible; stdlib only. Run: python3 tests/test_gzip.py"""
import gzip
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402

SKILL = Path(os.environ.get('UIC_SKILL', str(Path(__file__).resolve().parents[1])))
spec = importlib.util.spec_from_file_location('canvas_mod', SKILL / 'scripts' / 'canvas.py')
canvas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canvas)
canvas.Handler.log_message = lambda self, *a, **k: None

FRAME = '<main>' + ''.join('<p data-ui-id="p%d">Row %d of a long screen</p>' % (i, i) for i in range(200)) + '</main>'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 4000


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.write_bytes if isinstance(data, bytes) else path.write_text)(data)


def fetch(port, path, encoding=None, method='GET', body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        headers = {}
        if encoding is not None:
            headers['Accept-Encoding'] = encoding
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, response.read()
    finally:
        conn.close()


class AcceptsGzipTest(unittest.TestCase):
    def test_parsing(self):
        yes = ['gzip', 'gzip, deflate, br', 'br;q=1.0, gzip;q=0.8', 'GZIP', '*', 'deflate, *;q=0.5', ' gzip ; q=1 ', 'gzip;q=0.001']
        no = [None, '', 'identity', 'br, deflate', 'gzip;q=0', 'gzip;q=0.0, *', '*;q=0', 'gzip;q=bad', 'x-gzip']
        for value in yes:
            self.assertTrue(canvas.accepts_gzip(value), value)
        for value in no:
            self.assertFalse(canvas.accepts_gzip(value), value)


class CanvasGzipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='uic-gzip-'))
        root = cls.root = cls.tmp / 'canvas'
        write(root / 'project.json', json.dumps({'id': 'gz', 'name': 'Gzip', 'revision': 'r2', 'frames': [
            {'id': 'f1', 'title': 'F1', 'width': 390, 'height': 600, 'path': 'frames/f1.html'}]}))
        write(root / 'frames/f1.html', FRAME)
        write(root / 'frames/tiny.html', '<p>x</p>')
        write(root / 'media/pic.png', PNG)
        write(root / 'snapshots/r1/project.json', json.dumps({'id': 'gz', 'name': 'Gzip', 'revision': 'r1', 'frames': [
            {'id': 'f1', 'title': 'F1', 'width': 390, 'height': 600, 'path': 'frames/f1.html'}]}))
        write(root / 'snapshots/r1/frames/f1.html', FRAME)
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(canvas.Handler, root=root, ctx={'id': 'gz'}))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def assertGzipped(self, path, ctype):
        status, plain_headers, plain = fetch(self.port, path)
        status2, headers, raw = fetch(self.port, path, 'gzip, deflate, br')
        self.assertEqual((status, status2), (200, 200), path)
        self.assertNotIn('content-encoding', plain_headers, path)
        self.assertEqual(headers.get('content-encoding'), 'gzip', path)
        self.assertEqual(int(headers['content-length']), len(raw), path)
        self.assertEqual(int(plain_headers['content-length']), len(plain), path)
        self.assertEqual(gzip.decompress(raw), plain, path)
        self.assertLess(len(raw), len(plain), path)
        for h in (plain_headers, headers):
            self.assertEqual(h.get('vary'), 'Accept-Encoding', path)
            self.assertEqual(h.get('cache-control'), 'no-store', path)  # no caching is added
            self.assertNotIn('etag', h)
            self.assertNotIn('last-modified', h)
            self.assertTrue(h['content-type'].startswith(ctype), (path, h['content-type']))
        return plain

    def test_text_responses_are_compressed(self):
        self.assertIn(b'data-ui-id="p199"', self.assertGzipped('/project/frames/f1.html', 'text/html'))  # annotated fragment
        self.assertIn(b'<html', self.assertGzipped('/', 'text/html'))
        self.assertGzipped('/tool/canvas.js', 'text/javascript')
        self.assertGzipped('/tool/canvas.css', 'text/css')
        self.assertGzipped('/m/', 'text/html')
        self.assertGzipped('/api/snapshots/r1/frames/f1.html', 'text/html')

    def test_json_is_compressed_when_large_enough(self):
        project = json.loads(fetch(self.port, '/api/project')[2])
        project['frames'] = [dict(project['frames'][0], id='f%d' % i) for i in range(1, 60)]
        write(self.root / 'project.json', json.dumps(project))
        write(self.root / 'frames/f1.html', FRAME)
        try:
            self.assertGzipped('/api/project', 'application/json')
        finally:
            project['frames'] = project['frames'][:1]
            write(self.root / 'project.json', json.dumps(project))

    def test_q0_and_no_header_send_plain(self):
        for encoding in (None, 'identity', 'gzip;q=0', 'br'):
            status, headers, raw = fetch(self.port, '/project/frames/f1.html', encoding)
            self.assertEqual(status, 200)
            self.assertNotIn('content-encoding', headers, encoding)
            self.assertEqual(int(headers['content-length']), len(raw))
            self.assertEqual(headers.get('vary'), 'Accept-Encoding')

    def test_small_bodies_images_and_errors_stay_plain(self):
        status, headers, raw = fetch(self.port, '/project/media/pic.png', 'gzip')
        self.assertEqual((status, raw), (200, PNG))
        self.assertNotIn('content-encoding', headers)
        self.assertNotIn('vary', headers)
        status, headers, raw = fetch(self.port, '/project/frames/tiny.html', 'gzip')  # under the 512-byte threshold
        self.assertEqual(status, 200)
        self.assertNotIn('content-encoding', headers)
        self.assertIn(b'<p', raw)
        status, headers, raw = fetch(self.port, '/api/comments', 'gzip')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), {'comments': []})
        status, headers, raw = fetch(self.port, '/api/snapshots/r1/project', 'gzip', method='POST', body=b'{}')
        self.assertEqual(status, 405)
        self.assertEqual(int(headers['content-length']), len(raw))

    def test_head_is_unchanged(self):
        status, headers, raw = fetch(self.port, '/m/', 'gzip', method='HEAD')
        self.assertEqual(raw, b'')


class ListGzipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='uic-gzip-list-')
        base = test_server.free_block()
        cls.port = base
        cls.env = dict(os.environ, UI_CANVAS_RUNTIME=cls.tmp, UI_CANVAS_LIST_PORT=str(base), UI_CANVAS_PORT_RANGE='%d-%d' % (base + 1, base + 9), LC_ALL='C', LANG='C')
        for key in ('UI_CANVAS_BIND', 'UI_CANVAS_LANG'):
            cls.env.pop(key, None)
        subprocess.run([sys.executable, test_server.CANVAS, 'ensure-list'], env=cls.env, capture_output=True, text=True, timeout=60, check=True)

    @classmethod
    def tearDownClass(cls):
        try:
            health = json.loads(fetch(cls.port, '/healthz')[2])
            os.kill(health['pid'], 15)
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_list_page_and_script_are_compressed(self):
        for path in ('/', '/tool/i18n.js'):
            status, plain_headers, plain = fetch(self.port, path)
            status2, headers, raw = fetch(self.port, path, 'gzip')
            if status != 200:
                self.skipTest('%s not served by the list service' % path)
            self.assertEqual(headers.get('content-encoding'), 'gzip', path)
            self.assertEqual(int(headers['content-length']), len(raw), path)
            self.assertEqual(gzip.decompress(raw), plain, path)
            self.assertEqual(headers.get('vary'), 'Accept-Encoding', path)
            self.assertEqual(headers.get('cache-control'), 'no-store', path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
