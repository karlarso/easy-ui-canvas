#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Headless-browser test: a load or refresh of the phone preview (/m/) opens the browse entry
(project.flow_start, unless ?start= names a frame), not the screen that was open before the refresh
and not a frame hash. The canvas Flow view still reloads on its hash; the tile view is left alone.
Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself otherwise.
Run: python3 tests/browser_mobile_entry.py"""
import json
import os
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

# Fired once the phone page registers its popstate listener: a browser that replays history.state
# on load does this, and it used to reopen the screen from before the refresh.
REPLAY = """
const orig = EventTarget.prototype.addEventListener;
EventTarget.prototype.addEventListener = function(type, fn, opts) {
  orig.call(this, type, fn, opts);
  if (type === 'popstate' && !window.__mobileReplay) {
    window.__mobileReplay = true;
    setTimeout(() => dispatchEvent(new PopStateEvent('popstate', {state: {f: 'detail'}})), 30);
  }
};
"""


class MobileEntry(test_server.ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cdir = next((Path(cls.tmp) / 'canvases').iterdir())
        project = json.loads((cdir / 'project.json').read_text())
        by_id = {frame['id']: frame for frame in project['frames']}
        # First frame is settings; the browse entry is home. A bug that shows "the first frame"
        # or "the last screen" cannot pass as the entry.
        project['frames'] = [by_id['settings'], by_id['detail'], by_id['home']]
        project['flow_start'] = 'home'
        (cdir / 'project.json').write_text(json.dumps(project))
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

    def open(self, url, width=390, height=844):
        context = self.browser.new_context(locale='en-US', viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        self.addCleanup(context.close)
        page.goto(self.canvas_url + url, wait_until='networkidle')
        return page

    def frame(self, page):
        return page.evaluate("document.getElementById('m-frame').dataset.frameId")

    def wait_frame(self, page, fid):
        page.wait_for_function("document.getElementById('m-frame').dataset.frameId===%s" % json.dumps(fid))

    def test_refresh_returns_to_the_browse_entry_not_the_last_frame(self):
        page = self.open('/m/')
        self.wait_frame(page, 'home')
        page.click('#m-phone [data-goto="detail"]')
        self.wait_frame(page, 'detail')
        page.reload(wait_until='networkidle')
        self.wait_frame(page, 'home')
        self.assertEqual(page.evaluate('location.hash'), '')
        self.assertEqual(page.errors, [])

    def test_reload_ignores_a_popstate_that_replays_the_previous_frame(self):
        page = self.open('/m/')
        self.wait_frame(page, 'home')
        page.click('#m-phone [data-goto="detail"]')
        self.wait_frame(page, 'detail')
        page.context.add_init_script(REPLAY)
        page.reload(wait_until='networkidle')
        page.wait_for_function('window.__mobileReplay===true')
        page.wait_for_timeout(200)
        self.assertEqual(self.frame(page), 'home')
        # Back still works after a real navigation on this load (the replay is not a permanent lock).
        page.click('#m-phone [data-goto="settings"]')
        self.wait_frame(page, 'settings')
        page.click('#m-phone [data-goto="detail"]')
        self.wait_frame(page, 'detail')
        page.go_back()
        self.wait_frame(page, 'settings')
        self.assertEqual(page.errors, [])

    def test_frame_hash_is_not_the_entry_and_is_removed(self):
        page = self.open('/m/#view=flow&frame=detail')
        self.wait_frame(page, 'home')
        self.assertEqual(page.evaluate('location.hash'), '')
        self.assertNotIn('frame=', page.evaluate('location.href'))
        self.assertEqual(page.errors, [])

    def test_query_start_is_the_entry_and_survives_refresh(self):
        page = self.open('/m/?start=detail')
        self.wait_frame(page, 'detail')
        page.click('#m-phone [data-goto="settings"]')
        self.wait_frame(page, 'settings')
        page.reload(wait_until='networkidle')
        self.wait_frame(page, 'detail')
        unknown = self.open('/m/?start=no-such-frame')
        self.wait_frame(unknown, 'home')
        self.assertNotEqual(self.frame(unknown), 'settings')
        self.assertEqual(page.errors, [])
        self.assertEqual(unknown.errors, [])

    def test_in_page_back_still_returns_to_the_previous_screen(self):
        page = self.open('/m/')
        self.wait_frame(page, 'home')
        page.click('#m-phone [data-goto="detail"]')
        self.wait_frame(page, 'detail')
        page.click('#m-phone [data-goto="settings"]')
        self.wait_frame(page, 'settings')
        page.go_back()
        self.wait_frame(page, 'detail')
        page.go_back()
        self.wait_frame(page, 'home')
        self.assertEqual(page.errors, [])

    def test_flow_view_reload_keeps_its_frame_and_tile_view_stays_tile(self):
        flow = self.open('/#view=flow&frame=detail', width=1280, height=900)
        flow.wait_for_selector('.frame.flow-current[data-frame-id="detail"]', state='attached')
        flow.reload(wait_until='domcontentloaded')
        flow.wait_for_selector('.frame.flow-current[data-frame-id="detail"]', state='attached')
        self.assertIn('frame=detail', flow.evaluate('location.hash'))
        self.assertTrue(flow.evaluate("document.body.classList.contains('flow-mode')"))
        tile = self.open('/', width=1280, height=900)
        tile.wait_for_selector('#board>.frame', state='attached')
        self.assertFalse(tile.evaluate("document.body.classList.contains('flow-mode')"))
        self.assertNotIn('view=flow', tile.evaluate('location.hash'))
        self.assertEqual(flow.errors, [])
        self.assertEqual(tile.errors, [])


for _name in dir(test_server.ServerTest):
    if _name.startswith('test_'):
        setattr(MobileEntry, _name, None)


if __name__ == '__main__':
    unittest.main(verbosity=2, defaultTest='MobileEntry')
