#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for "Design notes": the toolbar button opens a read-only dialog that renders the canvas's DESIGN.md (headings, lists,
table, code, link; HTML escaped, images are not requested), the button is hidden when there is no DESIGN.md, history versions show the DESIGN.md kept
in their snapshot (hidden when the snapshot has none), both languages, narrow screens, and /m/ is unchanged. Throw-away canvases in a temporary
runtime. Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself otherwise.
Run: python3 tests/browser_design_notes.py"""
import json
import os
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('SKIP: playwright is not installed (optional)')
    sys.exit(0)

OLD = '# Old notes\n\nOnly in r1.\n'
NEW = '''# Checkout redesign · r2

First paragraph with **bold**, `inline code` and a [docs link](https://example.com/docs?a=1&b=2).
Second line of the same paragraph.

## Options

- Option A
  - nested detail
- Option B

1. Step one
2. Step two

| Name | Score |
|:-----|------:|
| A | 3 |
| B | 5 |

```
const x = "<b>not bold</b>";
```

![tracker](https://tracker.invalid/pixel.png) [relative](./other.md) [js](javascript:window.__xss=1)

<script>window.__xss=1</script>
<img src="https://tracker.invalid/img.png" onerror="window.__xss=1">
'''
FRAME = '<div style="padding:16px"><button data-ui-id="go" data-ui-label="Go">Go</button></div>'


class DesignNotes(test_server.ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        created = json.loads(cls.cli('new', '--name', 'Design notes'))
        cls.url = 'http://127.0.0.1:%d' % created['port']
        cls.cdir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % created['port']))
        cls.cid = created['id']
        project = json.loads((cls.cdir / 'project.json').read_text())
        project['frames'] = [{'id': 'f01', 'title': 'Screen 1', 'width': 390, 'height': 700, 'path': 'frames/f01.html'}]
        project.pop('groupColumns', None)
        project.pop('notes', None)
        project['revision'] = 'r1'
        shutil.rmtree(cls.cdir / 'frames', ignore_errors=True)
        (cls.cdir / 'frames').mkdir()
        (cls.cdir / 'frames' / 'f01.html').write_text(FRAME)
        (cls.cdir / 'project.json').write_text(json.dumps(project, indent=2))
        (cls.cdir / 'DESIGN.md').write_text(OLD, encoding='utf-8')
        cls.cli('snapshot', '--canvas', cls.cid)  # snapshots/r1 keeps DESIGN.md
        snaps = cls.cdir / 'snapshots'
        shutil.copytree(snaps / 'r1', snaps / 'r0')  # an older snapshot made before DESIGN.md was kept
        (snaps / 'r0' / 'DESIGN.md').unlink()
        zero = json.loads((snaps / 'r0' / 'project.json').read_text())
        zero['revision'] = 'r0'
        (snaps / 'r0' / 'project.json').write_text(json.dumps(zero))
        project['revision'] = 'r2'
        (cls.cdir / 'project.json').write_text(json.dumps(project, indent=2))
        (cls.cdir / 'DESIGN.md').write_text(NEW, encoding='utf-8')
        other = json.loads(cls.cli('new', '--name', 'No notes'))  # a canvas without DESIGN.md
        cls.other_url = 'http://127.0.0.1:%d' % other['port']
        cls.other_dir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % other['port']))
        (cls.other_dir / 'DESIGN.md').unlink(missing_ok=True)
        cls.pw = sync_playwright().start()
        cls.addClassCleanup(cls.pw.stop)
        launch = {'args': ['--no-sandbox']}
        if os.environ.get('UIC_CHROME'):
            launch['executable_path'] = os.environ['UIC_CHROME']
        try:
            cls.browser = cls.pw.chromium.launch(**launch)
        except Exception as error:
            raise unittest.SkipTest('no usable Chromium/Chrome (set UIC_CHROME): %s' % str(error).splitlines()[0])
        cls.addClassCleanup(cls.browser.close)

    def open(self, url=None, width=1440, height=900, locale='en-US'):
        context = self.browser.new_context(locale=locale, viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors, page.requests = [], []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' and 'tracker.invalid' not in msg.text else None)
        page.on('request', lambda request: page.requests.append(request.url))
        self.addCleanup(context.close)
        page.goto(url or self.url)
        page.wait_for_selector('#board>.frame .phone', state='attached')
        page.wait_for_timeout(300)
        return page

    def button_visible(self, page):
        return page.locator('#design-notes').is_visible()

    def open_dialog(self, page):
        page.wait_for_selector('#design-notes', state='visible')
        page.click('#design-notes')
        page.wait_for_selector('#design-dialog[open]')

    def open_history(self, page, rev):
        page.click('#history')
        page.locator('#history-menu .hm-item', has_text=rev).first.click()
        page.wait_for_function("document.body.classList.contains('history-mode')")

    # --- button and dialog ---------------------------------------------------------------------------------------------
    def test_button_opens_dialog_with_rendered_design_md(self):
        page = self.open()
        self.assertTrue(self.button_visible(page))
        self.assertEqual(page.inner_text('#design-notes'), 'Design notes')
        self.open_dialog(page)
        self.assertEqual(page.inner_text('#dn-title'), 'Design notes')
        self.assertIn('read-only', page.inner_text('#dn-sub'))
        body = page.locator('#dn-body')
        self.assertEqual(body.locator('h3').inner_text(), 'Checkout redesign · r2')
        self.assertEqual(body.locator('h4').inner_text(), 'Options')
        self.assertEqual(body.locator('strong').inner_text(), 'bold')
        self.assertEqual(body.locator('p code').first.inner_text(), 'inline code')
        self.assertEqual(body.locator('ul > li').count(), 3)  # Option A, nested detail, Option B
        self.assertEqual(body.locator('ul ul > li').inner_text(), 'nested detail')
        self.assertEqual(body.locator('ol > li').count(), 2)
        self.assertEqual(body.locator('table th').all_inner_texts(), ['Name', 'Score'])
        self.assertEqual(body.locator('table tbody tr').count(), 2)
        self.assertEqual(body.locator('table tbody tr:nth-child(2) td.al-r').inner_text(), '5')
        self.assertEqual(body.locator('pre code').inner_text(), 'const x = "<b>not bold</b>";')
        link = body.locator('a')
        self.assertEqual(link.count(), 1)
        self.assertEqual(link.get_attribute('href'), 'https://example.com/docs?a=1&b=2')
        self.assertEqual(link.get_attribute('target'), '_blank')
        self.assertIn('noopener', link.get_attribute('rel'))
        self.assertEqual(page.errors, [])

    def test_html_is_text_and_nothing_executes_or_loads(self):
        page = self.open()
        self.open_dialog(page)
        text = page.inner_text('#dn-body')
        self.assertIn('<script>window.__xss=1</script>', text)
        self.assertIn('<img src="https://tracker.invalid/img.png" onerror="window.__xss=1">', text)
        self.assertIn('![tracker](https://tracker.invalid/pixel.png)', text)
        self.assertIn('relative', text)
        self.assertEqual(page.locator('#dn-body img, #dn-body script, #dn-body iframe, #dn-body svg').count(), 0)
        self.assertEqual(page.locator('#dn-body a[href^="javascript"], #dn-body a[href^="."]').count(), 0)
        self.assertIsNone(page.evaluate('window.__xss'))
        page.wait_for_timeout(300)
        self.assertEqual([u for u in page.requests if 'tracker.invalid' in u], [])
        self.assertEqual([u for u in page.requests if u.endswith('DESIGN.md')], [])  # only the dedicated API is used
        self.assertTrue(any(u.endswith('/api/design') for u in page.requests))

    def test_dialog_is_read_only_and_closes_three_ways(self):
        page = self.open()
        self.open_dialog(page)
        self.assertEqual(page.locator('#design-dialog input, #design-dialog textarea, #design-dialog [contenteditable]').count(), 0)
        page.keyboard.press('c')  # comment shortcut is ignored while a dialog is open
        self.assertFalse(page.evaluate("document.body.classList.contains('comment-mode')"))
        page.keyboard.press('Escape')
        self.assertFalse(page.evaluate("document.getElementById('design-dialog').open"))
        self.open_dialog(page)
        page.click('#dn-close')
        self.assertFalse(page.evaluate("document.getElementById('design-dialog').open"))
        self.open_dialog(page)
        page.mouse.click(5, 5)  # backdrop
        self.assertFalse(page.evaluate("document.getElementById('design-dialog').open"))
        page.wait_for_function("document.getElementById('dn-body').innerHTML===''")  # content is dropped on close
        self.assertEqual(page.errors, [])

    def test_long_content_scrolls_inside_the_dialog_and_fits_a_narrow_screen(self):
        original = (self.cdir / 'DESIGN.md').read_text(encoding='utf-8')
        try:
            (self.cdir / 'DESIGN.md').write_text(''.join('## Section %d\n\nParagraph %d. %s\n\n' % (i, i, 'word ' * 40) for i in range(120)), encoding='utf-8')
            page = self.open(width=390, height=700)
            self.open_dialog(page)
            box = page.evaluate("(()=>{const r=document.getElementById('design-dialog').getBoundingClientRect();return [r.left,r.right,r.top,r.bottom,innerWidth,innerHeight]})()")
            self.assertGreaterEqual(box[0], 0)
            self.assertLessEqual(box[1], box[4])
            self.assertGreaterEqual(box[2], 0)
            self.assertLessEqual(box[3], box[5])
            self.assertTrue(page.evaluate("(()=>{const b=document.getElementById('dn-body');return b.scrollHeight>b.clientHeight+100&&getComputedStyle(b).overflowY==='auto'})()"))
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth>innerWidth"))
        finally:
            (self.cdir / 'DESIGN.md').write_text(original, encoding='utf-8')

    # --- no DESIGN.md --------------------------------------------------------------------------------------------------
    def test_button_is_hidden_without_design_md(self):
        page = self.open(self.other_url)
        page.wait_for_timeout(300)
        self.assertFalse(self.button_visible(page))
        self.assertTrue(page.evaluate("document.getElementById('design-notes').hidden"))
        self.assertEqual(page.errors, [])  # no failed request is logged for a canvas without DESIGN.md

    def test_removed_design_md_hides_the_button_on_click(self):
        saved = (self.cdir / 'DESIGN.md').read_text(encoding='utf-8')
        try:
            page = self.open()
            self.assertTrue(self.button_visible(page))
            (self.cdir / 'DESIGN.md').unlink()
            page.click('#design-notes')
            page.wait_for_function("document.getElementById('design-notes').hidden")
            self.assertFalse(page.evaluate("document.getElementById('design-dialog').open"))
        finally:
            (self.cdir / 'DESIGN.md').write_text(saved, encoding='utf-8')

    # --- history -------------------------------------------------------------------------------------------------------
    def test_history_shows_the_snapshot_design_md_read_only(self):
        page = self.open()
        self.open_dialog(page)
        self.assertEqual(page.locator('#dn-body h3').inner_text(), 'Checkout redesign · r2')
        page.keyboard.press('Escape')
        self.open_history(page, 'r1')
        page.wait_for_selector('#design-notes', state='visible')
        self.open_dialog(page)
        self.assertEqual(page.locator('#dn-body h3').inner_text(), 'Old notes')
        self.assertIn('r1', page.inner_text('#dn-sub'))
        self.assertTrue(any('/api/snapshots/r1/design' in u for u in page.requests))
        page.keyboard.press('Escape')
        page.click('#history-back')
        page.wait_for_function("!document.body.classList.contains('history-mode')")
        self.open_dialog(page)
        self.assertEqual(page.locator('#dn-body h3').inner_text(), 'Checkout redesign · r2')
        self.assertEqual(page.errors, [])

    def test_history_without_design_md_hides_the_button(self):
        page = self.open()
        self.assertTrue(self.button_visible(page))
        self.open_history(page, 'r0')
        page.wait_for_function("document.getElementById('design-notes').hidden")
        self.assertFalse(self.button_visible(page))
        page.click('#history-back')
        page.wait_for_function("!document.getElementById('design-notes').hidden")
        self.assertTrue(self.button_visible(page))

    def test_history_deep_link_loads_the_snapshot_design_md(self):
        page = self.open(self.url + '/#view=flow&frame=f01&rev=r1')
        page.wait_for_function("document.body.classList.contains('history-mode')")
        self.open_dialog(page)
        self.assertEqual(page.locator('#dn-body h3').inner_text(), 'Old notes')

    # --- language and the phone page -----------------------------------------------------------------------------------
    def test_chinese_labels(self):
        self.cli('lang', 'auto')
        page = self.open(locale='zh-CN')
        self.assertEqual(page.inner_text('#design-notes'), '\u8bbe\u8ba1\u8bf4\u660e')
        self.open_dialog(page)
        self.assertEqual(page.inner_text('#dn-title'), '\u8bbe\u8ba1\u8bf4\u660e')
        self.assertIn('\u53ea\u8bfb', page.inner_text('#dn-sub'))

    def test_phone_page_is_unchanged(self):
        context = self.browser.new_context(locale='en-US', viewport={'width': 390, 'height': 800})
        self.addCleanup(context.close)
        m = context.new_page()
        m.goto(self.url + '/m/')
        m.wait_for_selector('#m-phone')
        self.assertEqual(m.locator('#design-notes, #design-dialog').count(), 0)

    def test_design_md_is_not_served_as_a_static_file(self):
        for path in ('/project/DESIGN.md', '/DESIGN.md', '/tool/DESIGN.md', '/project/../DESIGN.md'):
            status, body = test_server.http(self.url + path)
            self.assertNotEqual(status, 200, path)
            self.assertNotIn('Checkout redesign', body, path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
