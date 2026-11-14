#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The UI export's phone preview is a static copy of /m/: same start rule, relative assets, data-goto only.
Run: python3 tests/test_export_mobile.py
"""
import importlib.util
import json
import re
import shutil
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ui_export', ROOT / 'scripts' / 'export_ui.py')
export_ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_ui)

DICT = json.loads((ROOT / 'assets' / 'i18n.json').read_text(encoding='utf-8'))
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082')


def tr(key, **params):
    text = DICT['en'].get(key, key)
    for name, value in params.items():
        text = text.replace('{' + name + '}', str(value))
    return text


def boot_from(page):
    match = re.search(r'<script type="application/json" id="m-boot">(.*?)</script>', page)
    return json.loads(match.group(1))


class ExportMobileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='uic-export-m-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / 'project'
        frames = self.root / 'frames'
        media = self.root / 'media'
        frames.mkdir(parents=True)
        media.mkdir()
        (media / 'dot.png').write_bytes(PNG)
        (frames / 'home.html').write_text(
            '<div class="screen"><h1>Home</h1><a data-goto="hub" data-ui-id="to-hub">To hub</a></div>', encoding='utf-8')
        (frames / 'hub.html').write_text(
            '<div class="screen" data-keep-scroll="main"><h1>Hub</h1>'
            '<a data-goto="detail" data-ui-id="go-detail">Open detail</a>'
            '<a data-goto="home" data-ui-id="go-home">Home</a>'
            '<a data-goto="state-b" data-ui-id="switch">Switch</a>'
            '<button type="button" data-ui-id="save">Save</button>'
            '<img src="/project/media/dot.png" alt=""></div>', encoding='utf-8')
        (frames / 'detail.html').write_text(
            '<div class="screen"><a data-goto="hub" data-ui-id="back">Back</a><p>Detail</p></div>', encoding='utf-8')
        (frames / 'state-b.html').write_text(
            '<div class="screen"><h1>State B</h1><a data-goto="hub" data-ui-id="switch-back">Back to hub</a>'
            '<img src="/project/media/dot.png" alt=""></div>', encoding='utf-8')
        self.config = {
            'id': 'fixture', 'name': 'Fixture', 'revision': 'v1', 'columns': 2,
            'flow_start': 'hub',
            'frames': [
                {'id': 'home', 'title': 'Home', 'width': 390, 'height': 800, 'path': 'frames/home.html'},
                {'id': 'hub', 'title': 'Hub', 'width': 390, 'height': 800, 'path': 'frames/hub.html'},
                {'id': 'detail', 'title': 'Detail', 'width': 390, 'height': 800, 'path': 'frames/detail.html'},
                {'id': 'state-b', 'title': 'State B', 'width': 390, 'height': 800, 'path': 'frames/state-b.html'},
            ],
        }
        (self.root / 'project.json').write_text(json.dumps(self.config), encoding='utf-8')
        self.stage = self.tmp / 'stage'
        (self.stage / 'assets').mkdir(parents=True)
        shutil.copy(ROOT / 'assets' / 'canvas.css', self.stage / 'assets' / 'canvas.css')
        (self.stage / 'media').mkdir()
        shutil.copy(self.root / 'media' / 'dot.png', self.stage / 'media' / 'dot.png')
        pages = {frame['id']: export_ui.offline_fragment((self.root / frame['path']).read_text(encoding='utf-8'))
                 for frame in self.config['frames']}
        export_ui.write_mobile_preview(self.stage, self.config, pages, ROOT, tr, 'en')
        (self.stage / 'index.html').write_text(
            '<!doctype html><title>Fixture</title><p><a href="m/index.html">%s</a></p>' % tr('h.mobile_preview'),
            encoding='utf-8')

    def test_start_rule_and_relative_assets(self):
        page = (self.stage / 'm' / 'index.html').read_text(encoding='utf-8')
        boot = boot_from(page)
        self.assertEqual(boot['flow_start'], 'hub')
        self.assertIsNone(boot['start'])
        self.assertEqual([frame['id'] for frame in boot['frames']], ['home', 'hub', 'detail', 'state-b'])
        self.assertEqual(set(boot['pages']), {'home', 'hub', 'detail', 'state-b'})
        self.assertIn('media/dot.png', boot['pages']['hub'])
        self.assertNotIn('/project/media/', boot['pages']['hub'])
        self.assertNotIn('localhost', page)
        self.assertNotIn('tailscale', page.lower())
        self.assertNotRegex(page, r'https?://')
        self.assertIn('<base href="../">', page)
        self.assertIn('href="assets/canvas.css"', page)
        self.assertIn('function mobileLoadFrame', page)
        self.assertIn('function flowClickAction', page)
        self.assertIn('function keepScrollCapture', page)
        self.assertNotIn('/api/comments', page)
        self.assertNotIn('canvas.json', page)
        self.assertIn('m/index.html', (self.stage / 'index.html').read_text(encoding='utf-8'))

    def _tr(self, lang):
        def inner(key, **params):
            text = DICT[lang].get(key) or DICT['en'].get(key, key)
            for name, value in params.items():
                text = text.replace('{' + name + '}', str(value))
            return text
        return inner

    def test_entry_label_follows_the_export_language_not_the_canvas_name(self):
        """A Chinese canvas name does not choose the language. The export lang does."""
        named = dict(self.config, name='PauseLab \u00b7 \u6539\u7248')
        pages = {frame['id']: export_ui.offline_fragment((self.root / frame['path']).read_text(encoding='utf-8'))
                 for frame in self.config['frames']}
        expect = {
            'zh': ('zh-CN', DICT['zh']['h.mobile_preview'], DICT['zh']['flow.demoEnd']),
            'en': ('en', DICT['en']['h.mobile_preview'], DICT['en']['flow.demoEnd']),
        }
        for lang, (html_lang, label, demo) in expect.items():
            stage = self.tmp / ('lang-' + lang)
            export_ui.write_mobile_preview(stage, named, pages, ROOT, self._tr(lang), lang)
            page = (stage / 'm' / 'index.html').read_text(encoding='utf-8')
            entry = export_ui.mobile_preview_entry(self._tr(lang))
            self.assertIn('<html lang="%s"' % html_lang, page)
            self.assertIn('<title>%s · %s</title>' % (named['name'], label), page)
            self.assertIn('aria-label="%s"' % label, page)
            self.assertIn(demo, page)
            self.assertIn('aria-label="%s"' % label, entry)
            self.assertIn('>%s</a>' % label, entry)
            other = DICT['en' if lang == 'zh' else 'zh']['h.mobile_preview']
            self.assertNotIn(other, entry)
        # The English export of a Chinese-named canvas still says Mobile preview.
        en_page = (self.tmp / 'lang-en' / 'm' / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn(DICT['zh']['h.mobile_preview'], en_page.split('id="m-boot"', 1)[0])
        shots = Path('/opt/cursor/artifacts')
        chrome = Path('/usr/local/bin/google-chrome')
        if shots.is_dir() and chrome.is_file():
            index = self.tmp / 'zh-index.html'
            index.write_text(
                '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<title>%s</title>'
                '<style>body{margin:24px;font:14px/1.6 system-ui;background:#eef1f4;color:#2c3a45}h1{font-size:22px}a{color:#1385d8}</style>'
                '</head><body><h1>%s</h1><p>sample / r1 · %s</p>%s</body></html>'
                % (named['name'], named['name'], self._tr('zh')('x.indexNote'), export_ui.mobile_preview_entry(self._tr('zh'))),
                encoding='utf-8')
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=str(chrome), args=['--no-sandbox', '--disable-dev-shm-usage'])
                page = browser.new_page(viewport={'width': 1100, 'height': 420}, locale='zh-CN')
                page.goto(index.as_uri(), wait_until='domcontentloaded')
                self.assertEqual(page.locator('a[href="m/index.html"]').inner_text(), DICT['zh']['h.mobile_preview'])
                page.screenshot(path=str(shots / 'export-index-zh.png'))
                browser.close()

    def test_browser_follows_links_back_and_state(self):
        chrome = shutil.which('google-chrome') or '/usr/local/bin/google-chrome'
        if not Path(chrome).is_file():
            self.skipTest('chrome is not installed')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('playwright is not installed')
        stage = self.stage

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(stage), **kwargs)
            def log_message(self, fmt, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        origin = 'http://127.0.0.1:%d' % port
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chrome, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = browser.new_page(viewport={'width': 1100, 'height': 800})
            foreign = []
            page.on('request', lambda req: foreign.append(req.url) if not req.url.startswith(origin) and not req.url.startswith('data:') else None)
            page.goto(origin + '/index.html', wait_until='domcontentloaded')
            page.locator('a[href="m/index.html"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            self.assertNotEqual(page.locator('#m-frame').get_attribute('data-frame-id'), 'home')
            page.locator('#m-phone [data-ui-id="go-detail"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="detail"]')
            page.go_back()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            page.locator('#m-phone [data-ui-id="go-home"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="home"]')
            page.go_back()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            page.locator('#m-phone [data-ui-id="save"]').click()
            page.wait_for_timeout(150)
            self.assertEqual(page.locator('#m-frame').get_attribute('data-frame-id'), 'hub')
            self.assertIn('End of demo', page.locator('#m-toast').inner_text())
            page.locator('#m-phone [data-ui-id="switch"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="state-b"]')
            self.assertIn('media/dot.png', page.locator('#m-phone').inner_html())
            page.locator('#m-phone [data-ui-id="switch-back"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            narrow = browser.new_page(viewport={'width': 390, 'height': 780})
            narrow.goto(origin + '/m/?start=detail', wait_until='domcontentloaded')
            narrow.wait_for_selector('#m-frame[data-frame-id="detail"]')
            narrow.locator('#m-phone [data-ui-id="back"]').click()
            narrow.wait_for_selector('#m-frame[data-frame-id="hub"]')
            box = narrow.locator('#m-frame').bounding_box()
            self.assertLessEqual(box['x'] + box['width'], 391)
            shots = Path('/opt/cursor/artifacts')
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-fixture-desktop.png'))
                narrow.screenshot(path=str(shots / 'export-fixture-narrow.png'))
            file_page = browser.new_page(viewport={'width': 390, 'height': 780})
            file_page.goto((stage / 'm' / 'index.html').as_uri(), wait_until='domcontentloaded')
            file_page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            file_page.locator('#m-phone [data-goto="state-b"]').click()
            file_page.wait_for_selector('#m-frame[data-frame-id="state-b"]')
            srcs = file_page.eval_on_selector_all('#m-phone img', 'els => els.map(e => e.currentSrc || e.src)')
            self.assertTrue(any(src.startswith('file:') and src.endswith('dot.png') for src in srcs), srcs)
            browser.close()
        self.assertEqual(foreign, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
