#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-to-end checks against real processes: loopback-only default bind, Host header guard, server-side language
setting shared across ports, localized API errors, localized pages and CLI output.
Uses a throw-away runtime directory and free ports (never touches ~/ui-canvas-runtime). Run: python3 tests/test_server.py"""
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANVAS = str(ROOT / 'scripts' / 'canvas.py')


def free_block(size=10):
    """Find `size` consecutive free loopback ports."""
    import random
    for _ in range(200):
        base = random.randint(20000, 40000)
        socks = []
        try:
            for port in range(base, base + size):
                sock = socket.socket()
                sock.bind(('127.0.0.1', port))
                socks.append(sock)
            return base
        except OSError:
            continue
        finally:
            for sock in socks:
                sock.close()
    raise RuntimeError('no free port block')


def lan_ip():
    """A non-loopback address of this machine, or None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('192.0.2.1', 9))  # TEST-NET-1; no packet is sent for UDP connect
        ip = sock.getsockname()[0]
        sock.close()
        return None if ip.startswith('127.') else ip
    except OSError:
        return None


def http(url, method='GET', body=None, headers=None):
    request = urllib.request.Request(url, method=method, headers=headers or {},
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace')


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='uic-test-')
        cls.addClassCleanup(cls._shutdown)  # runs even when setUpClass fails half way
        base = free_block()
        cls.list_port = base
        cls.env = dict(os.environ, UI_CANVAS_RUNTIME=cls.tmp, UI_CANVAS_LIST_PORT=str(base),
                       UI_CANVAS_PORT_RANGE='%d-%d' % (base + 1, base + 9))
        for key in ('UI_CANVAS_BIND', 'UI_CANVAS_LANG'):
            cls.env.pop(key, None)
        cls.env['LC_ALL'] = cls.env['LANG'] = 'C'
        cls.cli('ensure-list')
        created = json.loads(cls.cli('new', '--name', 'Smoke'))
        cls.canvas_id, cls.canvas_port = created['id'], created['port']
        cls.created = created
        cls.list_url = 'http://127.0.0.1:%d' % cls.list_port
        cls.canvas_url = 'http://127.0.0.1:%d' % cls.canvas_port

    @classmethod
    def _shutdown(cls):
        try:
            for item in json.loads(cls.cli('list'))['canvases']:
                cls.cli('stop', '--canvas', item['id'], check=False)
        except Exception:
            pass
        try:
            health = json.loads(http('http://127.0.0.1:%d/healthz' % cls.list_port)[1])
            os.kill(health['pid'], 15)
        except Exception:
            pass
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def cli(cls, *args, env_extra=None, check=True):
        env = dict(cls.env, **(env_extra or {}))
        result = subprocess.run([sys.executable, CANVAS] + list(args), env=env, capture_output=True, text=True, timeout=60)
        if check and result.returncode != 0:
            raise RuntimeError('canvas.py %s failed: %s %s' % (' '.join(args), result.stdout, result.stderr))
        return result.stdout

    def set_lang(self, value, port=None):
        port = port or self.list_port
        status, text = http('http://127.0.0.1:%d/api/lang' % port, 'POST', {'lang': value},
                            {'Origin': 'http://127.0.0.1:%d' % port})
        self.assertEqual(status, 200, text)
        return json.loads(text)

    # --- security defaults -------------------------------------------------------------------------------------
    def test_default_bind_is_loopback_only(self):
        self.assertEqual([item['bind'] for item in self.created['urls']], ['127.0.0.1'])
        ip = lan_ip()
        if not ip:
            self.skipTest('no non-loopback address on this machine')
        for port in (self.list_port, self.canvas_port):
            sock = socket.socket()
            sock.settimeout(2)
            try:
                self.assertNotEqual(sock.connect_ex((ip, port)), 0, 'port %d must not accept connections on %s' % (port, ip))
            finally:
                sock.close()

    def test_host_header_guard(self):
        for url in (self.list_url, self.canvas_url):
            self.assertEqual(http(url + '/healthz', headers={'Host': 'evil.example'})[0], 403)
            self.assertEqual(http(url + '/healthz', headers={'Host': 'localhost:%s' % url.rsplit(':', 1)[1]})[0], 200)
            self.assertEqual(http(url + '/healthz')[0], 200)

    def test_cross_origin_write_rejected(self):
        status, _ = http(self.list_url + '/api/lang', 'POST', {'lang': 'en'}, {'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)

    # --- language ----------------------------------------------------------------------------------------------
    def test_language_switch_applies_everywhere(self):
        self.assertEqual(self.set_lang('zh')['effective'], 'zh')
        # the other port (a different origin, so localStorage would not be shared) sees the same stored language
        status, text = http(self.canvas_url + '/api/lang')
        self.assertEqual((status, json.loads(text)['effective']), (200, 'zh'))
        for url in (self.list_url + '/', self.canvas_url + '/', self.canvas_url + '/m/'):
            status, page = http(url)
            self.assertEqual(status, 200, url)
            self.assertIn('window.UIC_LANG="zh"', page.replace(' ', ''), url)
        self.assertEqual(self.set_lang('en')['effective'], 'en')
        status, text = http(self.canvas_url + '/api/lang')
        self.assertEqual(json.loads(text)['effective'], 'en')
        for url in (self.list_url + '/', self.canvas_url + '/', self.canvas_url + '/m/'):
            self.assertIn('window.UIC_LANG="en"', http(url)[1].replace(' ', ''), url)

    def test_api_errors_follow_language(self):
        dictionary = json.loads((ROOT / 'assets' / 'i18n.json').read_text(encoding='utf-8'))
        errors = {}
        for lang in ('zh', 'en'):
            self.set_lang(lang)
            status, text = http(self.list_url + '/api/lang', 'POST', {'lang': 'bogus'}, {'Origin': self.list_url})
            self.assertEqual(status, 400)
            errors[lang] = json.loads(text)['error']
        self.assertNotEqual(errors['zh'], errors['en'])
        self.assertIn(errors['zh'], dictionary['zh'].values())
        self.assertIn(errors['en'], dictionary['en'].values())
        self.set_lang('en')

    def test_header_overrides_stored_language(self):
        self.set_lang('en')
        status, text = http(self.list_url + '/api/lang', 'POST', {'lang': 'bogus'},
                            {'Origin': self.list_url, 'X-UIC-Lang': 'zh'})
        self.assertIn(json.loads(text)['error'], json.loads((ROOT / 'assets' / 'i18n.json').read_text('utf-8'))['zh'].values())

    def test_cli_output_follows_language(self):
        self.cli('lang', 'zh')
        self.assertEqual(json.loads(self.cli('lang'))['effective'], 'zh')
        zh_help = self.cli('--help')
        self.cli('lang', 'en')
        self.assertEqual(json.loads(self.cli('lang'))['effective'], 'en')
        en_help = self.cli('--help')
        self.assertTrue(re.search('[\u4e00-\u9fff]', zh_help))
        self.assertFalse(re.search('[\u4e00-\u9fff]', en_help))
        # an explicit environment variable wins over the stored value
        self.assertEqual(json.loads(self.cli('lang', env_extra={'UI_CANVAS_LANG': 'zh'}))['effective'], 'zh')

    # --- basic behaviour -----------------------------------------------------------------------------------------
    def test_project_and_list(self):
        status, text = http(self.canvas_url + '/api/project')
        self.assertEqual(status, 200)
        project = json.loads(text)
        self.assertTrue(project['frames'])
        self.assertRegex(self.canvas_id, r'^[1-9]\d*$')
        self.assertEqual(self.created['display_id'], '#' + self.canvas_id)
        self.assertNotIn('#', self.created['dir'])
        self.assertTrue(self.created['dir'].endswith('-' + self.canvas_id))
        status, text = http(self.canvas_url + '/healthz')
        self.assertEqual(status, 200)
        health = json.loads(text)
        self.assertEqual(health['id'], self.canvas_id)
        self.assertEqual(health['display_id'], '#' + self.canvas_id)
        status, text = http(self.list_url + '/api/canvases')
        self.assertEqual(status, 200)
        self.assertIn(self.canvas_id, text)
        self.assertIn('#' + self.canvas_id, text)
        listed = json.loads(self.cli('comments', '--canvas', '#' + self.canvas_id))
        self.assertEqual(listed['project_id'], project['id'])

    def test_rename_display_name(self):
        created = json.loads(self.cli('new', '--name', 'Before'))
        cid, port = created['id'], created['port']
        cdir = Path(created['dir'])
        url = 'http://127.0.0.1:%d' % port
        try:
            status, text = http(url + '/api/project')
            self.assertEqual(status, 200)
            project = json.loads(text)
            self.cli('snapshot', '--canvas', cid)
            snap_path = cdir / 'snapshots' / project['revision'] / 'project.json'
            snap_bytes = snap_path.read_bytes()
            self.assertEqual(json.loads(snap_bytes)['name'], 'Before')
            page_list = http(self.list_url + '/')[1]
            self.assertIn("'/rename'", page_list)
            self.assertIn('l.rename', page_list)
            page = http(url + '/')[1]
            self.assertIn('id="brand-rename"', page)
            self.assertIn('id="brand-title"', page)
            status, text = http(self.list_url + '/api/canvases/%s/rename' % cid, 'POST', {'name': '  Alpha  '},
                                {'Origin': self.list_url, 'Content-Type': 'application/json'})
            self.assertEqual(status, 200, text)
            body = json.loads(text)
            self.assertEqual(body['name'], 'Alpha')
            self.assertEqual(body['id'], cid)
            self.assertEqual(body['display_id'], '#' + cid)
            self.assertEqual(body['port'], port)
            self.assertEqual(body['dir'], cdir.name)
            self.assertEqual(body['project_id'], project['id'])
            self.assertEqual(body['revision'], project['revision'])
            canvas = json.loads((cdir / 'canvas.json').read_text(encoding='utf-8'))
            live = json.loads((cdir / 'project.json').read_text(encoding='utf-8'))
            self.assertEqual(canvas['name'], 'Alpha')
            self.assertEqual(live['name'], 'Alpha')
            self.assertEqual(canvas['id'], cid)
            self.assertEqual(live['id'], project['id'])
            self.assertEqual(live['revision'], project['revision'])
            self.assertEqual(cdir.name, created['dir'].rstrip('/').split('/')[-1])
            self.assertEqual(snap_path.read_bytes(), snap_bytes)
            self.assertEqual(hashlib.sha256(snap_bytes).hexdigest(), hashlib.sha256(snap_path.read_bytes()).hexdigest())
            status, text = http(url + '/api/project')
            self.assertEqual(json.loads(text)['name'], 'Alpha')
            self.assertEqual(json.loads(text)['revision'], project['revision'])
            status, text = http(url + '/healthz')
            health = json.loads(text)
            self.assertEqual(health['name'], 'Alpha')
            self.assertEqual(health['id'], cid)
            self.assertEqual(health['port'], port)
            status, text = http(self.list_url + '/api/canvases')
            listed = {item['id']: item for item in json.loads(text)['canvases']}
            self.assertEqual(listed[cid]['name'], 'Alpha')
            self.assertEqual(listed[cid]['port'], port)
            self.assertEqual(listed[cid]['dir'], cdir.name)
            for bad in ('   ', 'x' * 101):
                status, text = http(self.list_url + '/api/canvases/%s/rename' % cid, 'POST', {'name': bad},
                                    {'Origin': self.list_url})
                self.assertEqual(status, 400, text)
                self.assertEqual(json.loads((cdir / 'canvas.json').read_text(encoding='utf-8'))['name'], 'Alpha')
                self.assertEqual(json.loads((cdir / 'project.json').read_text(encoding='utf-8'))['name'], 'Alpha')
            status, text = http(url + '/api/rename', 'POST', {'name': '  Beta  '}, {'Origin': url})
            self.assertEqual(status, 200, text)
            self.assertEqual(json.loads(text)['name'], 'Beta')
            self.assertEqual(json.loads(text)['port'], port)
            self.assertEqual(json.loads(text)['dir'], cdir.name)
            self.assertEqual(json.loads(text)['revision'], project['revision'])
            self.assertEqual(json.loads((cdir / 'canvas.json').read_text(encoding='utf-8'))['name'], 'Beta')
            self.assertEqual(json.loads((cdir / 'project.json').read_text(encoding='utf-8'))['name'], 'Beta')
            self.assertEqual(json.loads((cdir / 'project.json').read_text(encoding='utf-8'))['id'], project['id'])
            status, _ = http(url + '/api/rename', 'POST', {'name': 'Evil'}, {'Origin': 'http://evil.example'})
            self.assertEqual(status, 403)
            status, _ = http(self.list_url + '/api/canvases/%s/rename' % cid, 'POST', {'name': 'Evil'},
                             {'Origin': 'http://evil.example'})
            self.assertEqual(status, 403)
            self.assertEqual(json.loads((cdir / 'canvas.json').read_text(encoding='utf-8'))['name'], 'Beta')
            status, text = http(url + '/api/snapshots/%s/project' % project['revision'])
            self.assertEqual(status, 200, text)
            self.assertEqual(json.loads(text)['name'], 'Before')
            self.assertEqual(cdir.name, '%d-%s' % (port, cid))
        finally:
            self.cli('stop', '--canvas', cid, check=False)
            self.cli('remove', '--canvas', cid, '--yes', check=False)



if __name__ == '__main__':
    unittest.main(verbosity=2)
