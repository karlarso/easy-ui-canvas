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
            '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Fixture</title><style>'
            'body{margin:24px;font:14px/1.6 system-ui;background:#eef1f4;color:#2c3a45}'
            '.entries{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0 8px}'
            '.entry{display:flex;flex-direction:column;justify-content:center;gap:6px;min-height:96px;padding:20px 22px;border-radius:14px;background:#fff;border:1px solid #c5d0da;box-shadow:0 1px 2px #0f1b2414;text-decoration:none;color:#17324a}'
            '.entry strong{font-size:20px;line-height:1.3;color:#0b6fbe}'
            '.entry span{font-size:13px;line-height:1.45;color:#5c6b76}'
            '@media(max-width:700px){.entries{grid-template-columns:1fr}}'
            'main{min-width:0}article{max-width:100%;min-width:0}'
            '</style></head><body><h1>Fixture</h1>' + export_ui.preview_entries(tr) + '<main></main>'
            '<script>(function(){var s=new URLSearchParams(location.search).get("start");if(!s)return;'
            'document.querySelectorAll("a.entry").forEach(function(a){var h=a.getAttribute("href");'
            'a.setAttribute("href",h+(h.indexOf("?")<0?"?":"&")+"start="+encodeURIComponent(s))})})();</script>'
            '</body></html>',
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
        index = (self.stage / 'index.html').read_text(encoding='utf-8')
        self.assertIn('id="entry-flow" href="m/index.html?present=flow"', index)
        self.assertIn('id="entry-phone" href="m/index.html"', index)
        self.assertIn(tr('x.flowPreview'), index)
        self.assertIn(tr('h.mobile_preview'), index)
        mobile = (self.stage / 'm' / 'index.html').read_text(encoding='utf-8')
        self.assertEqual(mobile.count('function mobileMain'), 1)
        self.assertIn('id="m-flow"', mobile)
        self.assertIn("get('present')==='flow'", mobile)

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
            entry = export_ui.preview_entries(self._tr(lang))
            self.assertIn('<html lang="%s"' % html_lang, page)
            self.assertIn('<title>%s · %s</title>' % (named['name'], label), page)
            self.assertIn('aria-label="%s"' % label, page)
            self.assertIn(demo, page)
            self.assertIn('id="entry-flow" href="m/index.html?present=flow"', entry)
            self.assertIn('id="entry-phone" href="m/index.html"', entry)
            self.assertIn('>%s</strong>' % DICT[lang]['x.flowPreview'], entry)
            self.assertIn('>%s</strong>' % label, entry)
            other = DICT['en' if lang == 'zh' else 'zh']
            self.assertNotIn(other['h.mobile_preview'], entry)
            self.assertNotIn(other['x.flowPreview'], entry)
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
                '<style>body{margin:24px;font:14px/1.6 system-ui;background:#eef1f4;color:#2c3a45}h1{font-size:22px}'
                '.entries{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0 8px}'
                '.entry{display:flex;flex-direction:column;justify-content:center;gap:6px;min-height:96px;padding:20px 22px;border-radius:14px;background:#fff;border:1px solid #c5d0da;text-decoration:none;color:#17324a}'
                '.entry strong{font-size:20px;line-height:1.3;color:#0b6fbe}.entry span{font-size:13px;line-height:1.45;color:#5c6b76}'
                'a{color:#1385d8}</style>'
                '</head><body><h1>%s</h1><p>sample / r1 · %s</p>%s</body></html>'
                % (named['name'], named['name'], self._tr('zh')('x.indexNote'), export_ui.preview_entries(self._tr('zh'))),
                encoding='utf-8')
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(executable_path=str(chrome), args=['--no-sandbox', '--disable-dev-shm-usage'])
                page = browser.new_page(viewport={'width': 1100, 'height': 420}, locale='zh-CN')
                page.goto(index.as_uri(), wait_until='domcontentloaded')
                self.assertIn(DICT['zh']['x.flowPreview'], page.locator('#entry-flow').inner_text())
                self.assertIn(DICT['zh']['h.mobile_preview'], page.locator('#entry-phone').inner_text())
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

    def test_flow_entry_differs_from_phone_and_stays_offline(self):
        """The two index entries share one runner. Flow shows the desktop panel; phone stays full screen."""
        chrome = shutil.which('google-chrome') or '/usr/local/bin/google-chrome'
        if not Path(chrome).is_file():
            self.skipTest('chrome is not installed')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('playwright is not installed')
        stage = self.stage

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, directory, **kwargs):
                super().__init__(*args, directory=directory, **kwargs)
            def log_message(self, fmt, *args):
                pass

        def serve(directory):
            server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *args, **kwargs: Handler(*args, directory=directory, **kwargs))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            return 'http://127.0.0.1:%d' % server.server_address[1]

        origin = serve(str(stage))
        sub_origin = serve(str(self.tmp))
        shots = Path('/opt/cursor/artifacts')

        def no_overflow(page):
            box = page.evaluate('() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})')
            self.assertLessEqual(box['sw'], box['cw'] + 1, box)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chrome, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = browser.new_page(viewport={'width': 1100, 'height': 800}, locale='en-US')
            page.goto(origin + '/index.html', wait_until='domcontentloaded')
            flow_box = page.locator('#entry-flow').bounding_box()
            phone_box = page.locator('#entry-phone').bounding_box()
            self.assertGreaterEqual(flow_box['height'], 88)
            self.assertGreaterEqual(phone_box['height'], 88)
            self.assertLess(abs(flow_box['y'] - phone_box['y']), 8)
            self.assertIn(tr('x.flowPreview'), page.locator('#entry-flow').inner_text())
            self.assertIn(tr('h.mobile_preview'), page.locator('#entry-phone').inner_text())
            no_overflow(page)
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-entries-en.png'))
            page.goto(origin + '/index.html?start=detail', wait_until='domcontentloaded')
            self.assertIn('start=detail', page.locator('#entry-flow').get_attribute('href'))
            self.assertIn('start=detail', page.locator('#entry-phone').get_attribute('href'))
            page.locator('#entry-flow').click()
            page.wait_for_selector('#m-frame[data-frame-id="detail"]')
            self.assertIn('m-flow', page.locator('html').get_attribute('class') or '')
            self.assertTrue(page.locator('#m-flow').is_visible())
            page.goto(origin + '/m/index.html?present=flow', wait_until='domcontentloaded')
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            self.assertTrue(page.locator('#m-flow').is_visible())
            panel = page.locator('#m-flow').bounding_box()
            frame = page.locator('#m-frame').bounding_box()
            self.assertGreater(panel['x'], frame['x'] + frame['width'] - 4)
            page.locator('#m-phone [data-ui-id="go-detail"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="detail"]')
            page.locator('#m-flow-back').click()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            page.locator('#m-phone [data-ui-id="switch"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="state-b"]')
            page.locator('#m-flow-home').click()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            self.assertTrue(page.locator('#m-flow-back').is_enabled())
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-flow-desktop.png'))
            page.goto(origin + '/m/index.html', wait_until='domcontentloaded')
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            self.assertNotIn('m-flow', page.locator('html').get_attribute('class') or '')
            self.assertFalse(page.locator('#m-flow').is_visible())
            phone_frame = page.locator('#m-frame').bounding_box()
            self.assertGreater(phone_frame['height'], frame['height'])
            page.locator('#m-phone [data-ui-id="go-detail"]').click()
            page.wait_for_selector('#m-frame[data-frame-id="detail"]')
            page.go_back()
            page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-phone-desktop.png'))
            narrow = browser.new_page(viewport={'width': 320, 'height': 700}, locale='zh-CN')
            narrow.goto(origin + '/index.html', wait_until='domcontentloaded')
            top = narrow.locator('#entry-flow').bounding_box()
            below = narrow.locator('#entry-phone').bounding_box()
            self.assertGreater(below['y'], top['y'] + top['height'] - 4)
            no_overflow(narrow)
            if shots.is_dir():
                narrow.screenshot(path=str(shots / 'export-entries-narrow.png'))
            narrow.goto(origin + '/m/index.html?present=flow', wait_until='domcontentloaded')
            narrow.wait_for_selector('#m-frame[data-frame-id="hub"]')
            flow_top = narrow.locator('#m-frame').bounding_box()
            flow_below = narrow.locator('#m-flow').bounding_box()
            self.assertGreater(flow_below['y'], flow_top['y'] + 8)
            no_overflow(narrow)
            if shots.is_dir():
                narrow.screenshot(path=str(shots / 'export-flow-narrow.png'))
            narrow.goto(origin + '/m/index.html', wait_until='domcontentloaded')
            narrow.wait_for_selector('#m-frame[data-frame-id="hub"]')
            no_overflow(narrow)
            file_page = browser.new_page(viewport={'width': 1100, 'height': 800})
            file_page.goto((stage / 'index.html').as_uri(), wait_until='domcontentloaded')
            file_page.locator('#entry-flow').click()
            file_page.wait_for_selector('html.m-flow #m-frame[data-frame-id="hub"]')
            file_page.locator('#m-phone [data-ui-id="go-home"]').click()
            file_page.wait_for_selector('#m-frame[data-frame-id="home"]')
            file_page.go_back()
            file_page.wait_for_selector('#m-frame[data-frame-id="hub"]')
            sub = browser.new_page(viewport={'width': 1100, 'height': 800})
            sub.goto(sub_origin + '/stage/index.html', wait_until='domcontentloaded')
            sub.locator('#entry-phone').click()
            sub.wait_for_selector('#m-frame[data-frame-id="hub"]')
            self.assertNotIn('m-flow', sub.locator('html').get_attribute('class') or '')
            sub.locator('#m-phone [data-ui-id="switch"]').click()
            sub.wait_for_selector('#m-frame[data-frame-id="state-b"]')
            srcs = sub.eval_on_selector_all('#m-phone img', 'els => els.map(e => e.currentSrc || e.src)')
            self.assertTrue(srcs and all(src.startswith(sub_origin + '/stage/') for src in srcs), srcs)
            self.assertTrue(all('/api/' not in src for src in srcs), srcs)
            browser.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
