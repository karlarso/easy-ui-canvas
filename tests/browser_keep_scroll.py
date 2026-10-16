#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for `data-keep-scroll` (scroll position carried between frames, Flow view and /m/).
Builds a small throw-away canvas (generic frames) in a temporary runtime and drives the real pages: scroll down, click a card that jumps to
another frame of the same group, and check the inner scroll position is kept. Also checks the unchanged defaults (no attribute / other group
-> back to the top), "Back to start", the .phone fallback, content that grows after the jump, resizing, the URL hash and /m/.
Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself otherwise. Run: python3 tests/browser_keep_scroll.py"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402  (throw-away runtime helpers; imported as a module so its own tests are not collected here)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('SKIP: playwright is not installed (optional)')
    sys.exit(0)

TOL = 2  # px; scroll positions are fractional under the Flow view scale


def screen_css(fid):
    s = '[data-frame-id="%s"]' % fid
    return ('<style>%s .app{height:820px;display:flex;flex-direction:column;background:#fff;color:#222;font:15px system-ui}'
            '%s header{flex:0 0 56px;padding:16px}%s .sc{flex:1;min-height:0;overflow:auto;padding:0 16px}'
            '%s .card{display:block;width:100%%;height:70px;margin:0 0 10px;text-align:left}'
            '%s .grow{height:600px;animation:g%s .4s .1s forwards}@keyframes g%s{to{height:2400px}}</style>' % (s, s, s, s, s, fid.replace('-', ''), fid.replace('-', '')))


def cards(count, links):
    out = []
    for i in range(count):
        target = links.get(i)
        goto = ' data-goto="%s"' % target if target else ''
        out.append('<button class="card" data-ui-id="card-%d" data-ui-label="Card %d"%s>Card %d%s</button>' % (i, i, goto, i, ' &rarr; ' + target if target else ''))
    return ''.join(out)


def frame(fid, title, links, keep=None, count=24, body_extra='', phone_scroll=False, tag='main'):
    attr = ' data-keep-scroll="%s"' % keep if keep is not None else ''
    if phone_scroll:  # the .phone itself scrolls: content is taller than the frame, the attribute sits on an inner, non-scrolling element
        return screen_css(fid).replace('height:820px', 'height:auto') + '<div class="app"><header>%s</header><div%s>%s</div></div>' % (title, attr, cards(count, links))
    return screen_css(fid) + '<div class="app"><header>%s</header><%s class="sc"%s>%s%s</%s></div>' % (title, tag, attr, cards(count, links), body_extra, tag)


FRAMES = {
    # group "list": a long list page and two "selected" states that point at each other
    'list': ('List', {5: 'late', 8: 'sel-a', 9: 'sel-b', 10: 'plain-a', 11: 'other-group', 22: 'sel-b'}, 'list'),
    'sel-a': ('List, A selected', {8: 'sel-b', 9: 'list'}, 'list'),
    'sel-b': ('List, B selected', {8: 'sel-a', 9: 'list'}, 'list'),
    # no attribute at all
    'plain-a': ('Plain A', {8: 'plain-b'}, None),
    'plain-b': ('Plain B', {8: 'plain-a'}, None),
    # another group name
    'other-group': ('Other group', {8: 'list'}, 'settings'),
    # keep on a non-scrolling element: falls back to the scrolling .phone
    'pad-a': ('Padding A', {8: 'pad-b'}, 'page'),
    'pad-b': ('Padding B', {8: 'pad-a'}, 'page'),
    # content that only becomes tall after the jump
    'late': ('Late', {}, 'list'),
}


class KeepScroll(test_server.ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        root = Path(cls.tmp) / 'canvases'
        cdir = next(root.iterdir())
        project = json.loads((cdir / 'project.json').read_text())
        project['frames'] = []
        project['flow_start'] = 'list'
        (cdir / 'frames').mkdir(exist_ok=True)
        for fid, (title, links, keep) in FRAMES.items():
            phone_scroll = fid.startswith('pad-')
            extra = '<div class="grow"></div>' if fid == 'late' else ''
            html = frame(fid, title, links, keep, count=4 if fid == 'late' else 24, body_extra=extra, phone_scroll=phone_scroll)
            (cdir / 'frames' / (fid + '.html')).write_text(html)
            project['frames'].append({'id': fid, 'title': title, 'width': 390, 'height': 820, 'path': 'frames/%s.html' % fid, 'group': 'Test', 'state': 'Draft'})
        (cdir / 'project.json').write_text(json.dumps(project, indent=2))
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

    def open(self, url, width=1280, height=900):
        context = self.browser.new_context(locale='en-US', viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        self.addCleanup(context.close)
        page.goto(url)
        return page

    def flow(self, frame_id='list', **size):
        page = self.open(self.canvas_url + '/#view=flow&frame=' + frame_id, **size)
        page.wait_for_selector('.frame.flow-current[data-frame-id="%s"]' % frame_id, state='attached')
        page.wait_for_timeout(300)
        return page

    # --- helpers --------------------------------------------------------------------------------------------------
    SCROLLER = "(()=>{const a=document.querySelector('.frame.flow-current')||document.getElementById('m-frame');const p=a.querySelector('.phone')||a;return a.querySelector('.sc')||p})()"

    def cur(self, page):
        return page.evaluate("document.querySelector('.frame.flow-current')?.dataset.frameId||document.getElementById('m-frame').dataset.frameId")

    def top(self, page):
        return page.evaluate('(()=>{const s=%s;return s.scrollTop})()' % self.SCROLLER)

    def phone_top(self, page):
        return page.evaluate("(()=>{const a=document.querySelector('.frame.flow-current')||document.getElementById('m-frame');return a.querySelector('.phone').scrollTop})()")

    def scroll_to(self, page, value, phone=False):
        sel = "a.querySelector('.phone')" if phone else 'S'
        page.evaluate("(()=>{const a=document.querySelector('.frame.flow-current')||document.getElementById('m-frame');const S=%s;const e=%s;e.scrollTop=%d})()" % (self.SCROLLER, sel, value))
        page.wait_for_timeout(100)

    def click_card(self, page, index, wait=250):
        """Real mouse click on the card's centre (after checking it is visible, so the browser does not scroll first)."""
        box = page.evaluate("""(i=>{const a=document.querySelector('.frame.flow-current')||document.getElementById('m-frame');
          const e=a.querySelector('[data-ui-id="card-'+i+'"]'),r=e.getBoundingClientRect(),p=a.querySelector('.phone').getBoundingClientRect();
          return {x:r.left+r.width/2,y:r.top+r.height/2,inView:r.top>p.top+60&&r.bottom<p.bottom-1&&r.top>0&&r.bottom<innerHeight}})""", index)
        self.assertTrue(box['inView'], 'card %d is not on screen: %r' % (index, box))
        page.mouse.click(box['x'], box['y'])
        page.wait_for_timeout(wait)

    def assertNear(self, got, want, msg=''):
        self.assertLessEqual(abs(got - want), TOL, '%s: got %s, want %s' % (msg, got, want))

    # --- Flow view ------------------------------------------------------------------------------------------------
    def test_same_group_keeps_scroll_across_frames_and_back(self):
        page = self.flow()
        self.scroll_to(page, 300)
        start = self.top(page)
        self.assertNear(start, 300, 'scrolled')
        self.click_card(page, 9)  # list -> sel-b
        self.assertEqual(self.cur(page), 'sel-b')
        self.assertNear(self.top(page), start, 'after jump')
        self.assertIn('frame=sel-b', page.evaluate('location.hash'))
        self.click_card(page, 8)  # sel-b -> sel-a (also the same group)
        self.assertEqual(self.cur(page), 'sel-a')
        self.assertNear(self.top(page), start, 'second jump')
        page.click('#flow-back')
        page.wait_for_timeout(200)
        self.assertEqual(self.cur(page), 'sel-b')
        self.assertNear(self.top(page), start, 'back')
        self.assertEqual(page.errors, [])

    def test_scrolled_to_the_bottom_is_kept(self):
        page = self.flow()
        self.scroll_to(page, 100000)
        bottom = self.top(page)
        self.assertGreater(bottom, 500)
        self.click_card(page, 22)  # a card near the end of the list
        self.assertEqual(self.cur(page), 'sel-b')
        self.assertNear(self.top(page), bottom, 'bottom of the page')

    def test_without_attribute_a_new_frame_starts_at_the_top(self):
        page = self.flow('plain-a')
        self.scroll_to(page, 300)
        self.assertNear(self.top(page), 300)
        self.click_card(page, 8)
        self.assertEqual(self.cur(page), 'plain-b')
        self.assertNear(self.top(page), 0, 'no data-keep-scroll')

    def test_different_group_names_do_not_carry_over(self):
        page = self.flow()
        self.scroll_to(page, 300)
        self.click_card(page, 11)  # group "list" -> group "settings"
        self.assertEqual(self.cur(page), 'other-group')
        self.assertNear(self.top(page), 0, 'other group')

    def test_revisited_frame_takes_the_position_it_is_left_at(self):
        page = self.flow()
        self.scroll_to(page, 300)
        self.click_card(page, 9)  # list -> sel-b
        self.scroll_to(page, 120)
        self.click_card(page, 9)  # sel-b -> list (shown before, at 300): now follows the page being left
        self.assertEqual(self.cur(page), 'list')
        self.assertNear(self.top(page), 120, 'revisit')

    def test_back_to_start_does_not_carry_over(self):
        page = self.flow('sel-a')  # "list" (the start frame) was never scrolled in this page
        self.scroll_to(page, 300)
        self.assertNear(self.top(page), 300)
        page.click('#flow-home')
        page.wait_for_timeout(250)
        self.assertEqual(self.cur(page), 'list')
        self.assertNear(self.top(page), 0, 'Back to start')

    def test_phone_scroll_fallback(self):
        page = self.flow('pad-a')
        self.scroll_to(page, 250, phone=True)
        self.assertNear(self.phone_top(page), 250)
        self.click_card(page, 8)
        self.assertEqual(self.cur(page), 'pad-b')
        self.assertNear(self.phone_top(page), 250, '.phone scroller')

    def test_content_that_grows_after_the_jump(self):
        page = self.flow()
        self.scroll_to(page, 300)
        self.click_card(page, 5)  # -> "late": too short to scroll 300 px at first, a tall block grows 100-500 ms after it is shown
        self.assertEqual(self.cur(page), 'late')
        page.wait_for_timeout(900)
        self.assertNear(self.top(page), 300, 'late layout')

    def test_user_scroll_wins_over_pending_restore(self):
        page = self.flow()
        self.scroll_to(page, 300)
        self.click_card(page, 5, wait=0)
        self.scroll_to(page, 40)
        page.wait_for_timeout(700)
        self.assertNear(self.top(page), 40, 'user scrolled during the restore window')

    def test_resize_and_reload(self):
        page = self.flow()
        self.scroll_to(page, 300)
        self.click_card(page, 9)
        for w, h in ((700, 600), (1600, 1000), (1280, 900)):
            page.set_viewport_size({'width': w, 'height': h})
            page.wait_for_timeout(250)
        self.assertEqual(self.cur(page), 'sel-b')
        self.assertNear(self.top(page), 300, 'after resizes')
        page.reload()
        page.wait_for_selector('.frame.flow-current[data-frame-id="sel-b"]', state='attached')
        page.wait_for_timeout(300)
        self.assertEqual(self.cur(page), 'sel-b')
        self.assertNear(self.top(page), 0, 'reload does not restore scroll')
        self.assertEqual(page.errors, [])

    # --- phone page /m/ -------------------------------------------------------------------------------------------
    def test_mobile_page_keeps_scroll(self):
        page = self.open(self.canvas_url + '/m/?start=list', 390, 844)
        page.wait_for_selector('#m-phone .card')
        page.wait_for_timeout(300)
        self.scroll_to(page, 300)
        self.assertNear(self.top(page), 300)
        self.click_card(page, 9)
        self.assertEqual(self.cur(page), 'sel-b')
        self.assertNear(self.top(page), 300, '/m/ jump')
        page.go_back()
        page.wait_for_timeout(300)
        self.assertEqual(self.cur(page), 'list')
        self.assertNear(self.top(page), 300, '/m/ back')
        self.click_card(page, 10)  # -> plain-a (no attribute)
        self.assertEqual(self.cur(page), 'plain-a')
        self.assertNear(self.top(page), 0, '/m/ without attribute')
        self.assertEqual(page.errors, [])


for _name in dir(test_server.ServerTest):  # the inherited server tests are not ours to repeat
    if _name.startswith('test_'):
        setattr(KeepScroll, _name, None)


if __name__ == '__main__':
    unittest.main(verbosity=2, defaultTest='KeepScroll')
