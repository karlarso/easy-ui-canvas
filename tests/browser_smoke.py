#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser smoke test (needs `pip install playwright` and a Chromium/Chrome; neither is shipped here).
Checks: default language follows navigator.language, the list-page switch persists server-side and reaches the canvas
page on another port, and no console/page errors. With --shots DIR it also saves screenshots.
Run: python3 tests/browser_smoke.py [--shots docs/images]   (env UIC_CHROME=/path/to/chrome to use an installed Chrome)"""
import argparse
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_server import ServerTest  # noqa: E402  (reuse the throw-away runtime helpers)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('SKIP: playwright is not installed (optional)')
    sys.exit(0)

SHOTS = None


class BrowserSmoke(ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.en_canvas = json.loads(cls.cli('new', '--name', 'Example (en)', '--from', 'example-en'))
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        launch = {'args': ['--no-sandbox']}
        if os.environ.get('UIC_CHROME'):
            launch['executable_path'] = os.environ['UIC_CHROME']
        try:
            cls.browser = cls.pw.chromium.launch(**launch)
        except Exception as error:  # no browser installed: skip (servers are cleaned up by the class cleanups)
            raise unittest.SkipTest('no usable Chromium/Chrome (set UIC_CHROME): %s' % str(error).splitlines()[0])
        cls.addClassCleanup(cls.browser.close)

    def page(self, locale, width=1280, height=800):
        context = self.browser.new_context(locale=locale, viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        return context, page

    def test_default_language_follows_browser(self):
        self.cli('lang', 'auto')
        for locale, expected in (('en-US', 'en'), ('zh-CN', 'zh'), ('fr-FR', 'en')):
            context, page = self.page(locale)
            page.goto(self.list_url + '/')
            page.wait_for_selector('#lang-select')
            self.assertEqual(page.evaluate('window.tr.lang'), expected, locale)
            self.assertEqual(page.errors, [], locale)
            context.close()

    def test_switch_on_list_page_reaches_canvas_and_mobile(self):
        self.cli('lang', 'auto')
        context, page = self.page('en-US')
        page.goto(self.list_url + '/')
        page.wait_for_selector('#lang-select')
        title_en = page.inner_text('h1')
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / 'smoke-list.png'))
        page.select_option('#lang-select', 'zh')
        page.wait_for_function('window.tr.lang === "zh" || document.querySelector("h1").innerText !== %s' % json.dumps(title_en))
        page.wait_for_timeout(500)
        title_zh = page.inner_text('h1')
        self.assertNotEqual(title_en, title_zh)
        # different port = different origin: the canvas page must still be Chinese
        page.goto(self.canvas_url + '/')
        page.wait_for_selector('#annotate')
        self.assertEqual(page.evaluate('window.tr.lang'), 'zh')
        zh_button = page.inner_text('#annotate')
        page.goto(self.canvas_url + '/m/')
        self.assertEqual(page.evaluate('window.tr.lang'), 'zh')
        # and back to English
        self.set_lang('en')
        page.goto(self.canvas_url + '/')
        page.wait_for_selector('#annotate')
        self.assertNotEqual(page.inner_text('#annotate'), zh_button)
        self.assertEqual(page.errors, [])
        context.close()

    def test_screenshots(self):
        if not SHOTS:
            self.skipTest('no --shots directory given')
        self.set_lang('en')
        context, page = self.page('en-US', 1440, 900)
        page.goto('http://127.0.0.1:%d/' % self.en_canvas['port'])
        page.wait_for_selector('#annotate')
        page.wait_for_timeout(1200)
        page.screenshot(path=str(SHOTS / 'smoke-canvas.png'))
        self.assertEqual(page.errors, [])
        context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shots', type=Path)
    args, rest = parser.parse_known_args()
    SHOTS = args.shots
    unittest.main(argv=[sys.argv[0]] + rest, verbosity=2, defaultTest='BrowserSmoke')
