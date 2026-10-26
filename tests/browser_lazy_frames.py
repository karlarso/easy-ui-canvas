#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for lazy frames on the desktop canvas: a large board starts at 50% with its top-left corner 28 px from the viewport's
and loads only the frames near the visible area (at most LAZY.concurrency requests at a time, nearest first); panning loads more; a small board keeps the
centred fit; resizing keeps the camera; comments on frames that are not loaded are not shown as removed and locating loads the frame; the Flow view
loads the shown screen first (deep link included) and prefetches its data-goto targets; leaving Flow centres that frame in the tile view once (a later pan stays put, and the next Flow frame is what Tile centres); a history version with a missing frame file still opens;
?load=all loads everything. Throw-away canvases in a temporary runtime. Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome);
skips itself otherwise. Run: python3 tests/browser_lazy_frames.py"""
import json
import os
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_server  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('SKIP: playwright is not installed (optional)')
    sys.exit(0)

N = 30


def frame_html(i):
    nxt = 'f%02d' % (i % N + 1)
    return ('<style>[data-frame-id="f%02d"] .app{height:100%%;padding:16px;font:16px system-ui;background:#eef}</style>'
            '<div class="app"><h1 data-ui-id="head" data-ui-label="Heading">Screen %d</h1>'
            '<button data-ui-id="go" data-ui-label="Next" data-goto="%s">Next</button></div>') % (i, i, nxt)


STATES = "[...document.querySelectorAll('#board>.frame')].map(a=>a.dataset.load)"
BOARD = "(()=>{const b=document.getElementById('board').getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();return [b.left-v.left,b.top-v.top]})()"


class LazyFrames(test_server.ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        created = json.loads(cls.cli('new', '--name', 'Lazy'))
        cls.url = 'http://127.0.0.1:%d' % created['port']
        cls.cdir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % created['port']))
        cls.cid = created['id']
        project = json.loads((cls.cdir / 'project.json').read_text())
        project['frames'] = [{'id': 'f%02d' % i, 'title': 'Screen %d' % i, 'width': 390, 'height': 820, 'path': 'frames/f%02d.html' % i} for i in range(1, N + 1)]
        project['columns'] = 8
        project['revision'] = 'r1'
        project['flow_start'] = 'f01'
        for key in ('groupColumns', 'notes'):
            project.pop(key, None)
        shutil.rmtree(cls.cdir / 'frames', ignore_errors=True)
        (cls.cdir / 'frames').mkdir()
        for i in range(1, N + 1):
            (cls.cdir / 'frames' / ('f%02d.html' % i)).write_text(frame_html(i))
        (cls.cdir / 'project.json').write_text(json.dumps(project, indent=2))
        cls.project = project
        cls.cli('snapshot', '--canvas', cls.cid)   # snapshots/r1
        (cls.cdir / 'snapshots' / 'r1' / 'frames' / 'f02.html').unlink()   # one frame file missing in history
        project['revision'] = 'r2'
        (cls.cdir / 'project.json').write_text(json.dumps(project, indent=2))
        small = json.loads(cls.cli('new', '--name', 'Small'))
        cls.small_url = 'http://127.0.0.1:%d' % small['port']
        sdir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % small['port']))
        sp = json.loads((sdir / 'project.json').read_text())
        sp['frames'] = sp['frames'][:3]
        (sdir / 'project.json').write_text(json.dumps(sp, indent=2))
        cls.small_frames = len(sp['frames'])
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

    def open(self, url=None, width=1440, height=900):
        context = self.browser.new_context(locale='en-US', viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors, page.frame_requests, page.live, page.peak = [], [], set(), [0]

        def started(request):
            if '/frames/' in request.url:
                page.frame_requests.append(request.url.rsplit('/', 1)[-1])
                page.live.add(request)
                page.peak[0] = max(page.peak[0], len(page.live))

        page.on('request', started)
        page.on('requestfinished', lambda r: page.live.discard(r))
        page.on('requestfailed', lambda r: page.live.discard(r))
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' and 'f02.html' not in msg.text else None)
        self.addCleanup(context.close)
        page.goto(url or self.url)
        page.wait_for_selector('#board>.frame .phone', state='attached')
        return page

    def settle(self, page):
        page.wait_for_function("![...document.querySelectorAll('#board>.frame')].some(a=>a.dataset.load==='loading')")
        page.wait_for_timeout(250)
        page.wait_for_function("![...document.querySelectorAll('#board>.frame')].some(a=>a.dataset.load==='loading')")

    def states(self, page):
        return page.evaluate(STATES)

    def post(self, target, frame_id, text, client):
        status, body = test_server.http(self.url + '/api/comments', 'POST', {'client_id': client, 'project_id': self.project['id'],
                                                                           'revision': self.project['revision'], 'target': target, 'text': text})
        self.assertEqual(status, 201, body)
        return json.loads(body)['comment']

    # --- start-up -------------------------------------------------------------------------------------------------------
    def test_large_board_starts_at_50_percent_near_the_top_left(self):
        page = self.open()
        self.settle(page)
        self.assertEqual(page.inner_text('#zoom-value'), '50%')
        left, top = page.evaluate(BOARD)
        self.assertAlmostEqual(left, 28, delta=1)
        self.assertAlmostEqual(top, 28, delta=1)
        self.assertEqual(page.errors, [])

    def test_only_frames_near_the_view_are_loaded_nearest_first(self):
        page = self.open()
        self.settle(page)
        st = self.states(page)
        loaded = [i for i, s in enumerate(st) if s == 'loaded']
        self.assertIn(0, loaded)
        self.assertGreater(len(loaded), 4)
        self.assertLess(len(loaded), N)
        self.assertEqual(set(st), {'loaded', 'idle'})
        self.assertEqual(len(page.frame_requests), len(loaded))   # idle frames were never requested
        first = page.frame_requests[0].split('.')[0]               # nearest to the centre of the view first: a frame on screen, not one in the margin
        self.assertTrue(page.evaluate("""id=>{const r=document.querySelector('#board>.frame[data-frame-id="'+id+'"]').getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();
          return r.left<v.left+v.width/2&&r.right>v.left+v.width/2-500&&r.top<v.bottom&&r.bottom>v.top}""", first), first)
        self.assertLessEqual(page.peak[0], 5)
        far = page.evaluate("document.querySelector('#board>.frame[data-frame-id=\"f30\"]').dataset.load")
        self.assertEqual(far, 'idle')
        self.assertEqual(page.locator('#f30--head').count(), 0)
        self.assertEqual(page.locator('#f30--screen').count(), 1)  # the shell (phone box, title) exists at full size
        box = page.evaluate("(()=>{const p=document.getElementById('f30--screen');return [p.offsetWidth,p.offsetHeight]})()")
        self.assertEqual(box, [390, 820])
        self.assertEqual(page.evaluate("document.getElementById('f30~title').textContent"), 'Screen 30')

    def test_panning_loads_the_frames_that_come_into_view(self):
        page = self.open()
        self.settle(page)
        self.assertEqual(self.states(page)[N - 1], 'idle')
        for _ in range(12):
            page.mouse.move(700, 450)
            page.mouse.wheel(600, 600)
            page.wait_for_timeout(60)
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f30\"]').dataset.load==='loaded'")
        self.assertEqual(page.inner_text('#f30--head'), 'Screen 30')
        self.assertLessEqual(page.peak[0], 5)

    def test_minimap_and_zoom_out_load_the_rest(self):
        page = self.open()
        self.settle(page)
        page.click('#zoom-trigger')
        page.click('#zoom-menu [data-zoom="fit"]')
        page.wait_for_function("[...document.querySelectorAll('#board>.frame')].every(a=>a.dataset.load==='loaded')")
        self.assertEqual(page.locator('#minimap-world .mm-frame').count(), N)
        self.assertLessEqual(page.peak[0], 5)

    def test_small_board_keeps_the_centred_fit(self):
        page = self.open(self.small_url)
        page.wait_for_function("[...document.querySelectorAll('#board>.frame')].every(a=>a.dataset.load==='loaded')")
        zoom = int(page.inner_text('#zoom-value').rstrip('%'))
        self.assertGreaterEqual(zoom, 50)
        self.assertLessEqual(zoom, 100)
        inside = page.evaluate("""(()=>{const b=document.getElementById('board').getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();
          return Math.abs((b.left-v.left)-(v.right-b.right))<2&&b.left>=v.left&&b.right<=v.right+1&&b.top>=v.top-1&&b.bottom<=v.bottom+1})()""")
        self.assertTrue(inside, 'small board: whole board visible and centred')

    def test_resize_keeps_the_camera_and_loads_newly_uncovered_frames(self):
        page = self.open(width=1000, height=700)
        self.settle(page)
        before = (page.inner_text('#zoom-value'), page.evaluate(BOARD))
        loaded_before = self.states(page).count('loaded')
        page.set_viewport_size({'width': 1900, 'height': 1100})
        page.wait_for_timeout(300)
        self.settle(page)
        self.assertEqual((page.inner_text('#zoom-value'), page.evaluate(BOARD)), before)
        self.assertGreater(self.states(page).count('loaded'), loaded_before)

    def test_load_all_switch(self):
        page = self.open(self.url + '/?load=all')
        page.wait_for_function("[...document.querySelectorAll('#board>.frame')].every(a=>a.dataset.load==='loaded')")
        self.assertEqual(page.inner_text('#zoom-value'), '50%')   # the camera is not changed by ?load=all
        self.assertLessEqual(page.peak[0], 5)
        page2 = self.open()
        self.assertTrue(page2.evaluate("window.uicLoadAllFrames().then(r=>r.every(Boolean))"))

    # --- comments -------------------------------------------------------------------------------------------------------
    def test_comments_on_unloaded_frames_are_not_removed_and_locate_loads_them(self):
        live = self.post('f29--head', 'f29', 'far away heading', 'lazy-c1')
        gone = self.post('f28--screen', 'f28', 'whole far screen', 'lazy-c2')
        # make the second one point at an element that does not exist in f28 (as if it was removed from the HTML)
        import sqlite3
        con = sqlite3.connect(str(self.cdir / 'runtime' / 'feedback.sqlite3'))
        try:
            payload = json.loads(con.execute('SELECT payload FROM comments WHERE id=?', (gone['id'],)).fetchone()[0])
            payload['target'] = 'f28--deleted'
            con.execute('UPDATE comments SET payload=? WHERE id=?', (json.dumps(payload), gone['id']))
            con.commit()
        finally:
            con.close()
        try:
            page = self.open()
            self.settle(page)
            page.click('#open-comments')
            cards = page.locator('#comment-list .comment-card')
            texts = cards.locator('.context').all_inner_texts()
            self.assertTrue(texts and not any('removed' in t for t in texts), texts)   # f28/f29 are not loaded: never "removed"
            card = page.locator('#comment-list .comment-card', has_text='far away heading')
            card.locator('.locate').click()
            page.wait_for_function("document.getElementById('f29--head')&&document.getElementById('f29--head').classList.contains('comment-selected')")
            r = page.evaluate("(()=>{const r=document.getElementById('f29--head').getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();return r.left>=v.left&&r.right<=v.right&&r.top>=v.top&&r.bottom<=v.bottom})()")
            self.assertTrue(r, 'located element is on screen')
            page.locator('#comment-list .comment-card', has_text='whole far screen').locator('.locate').click()
            page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f28\"]').dataset.load==='loaded'")
            page.wait_for_function("[...document.querySelectorAll('#comment-list .comment-card')].some(c=>c.textContent.includes('whole far screen')&&c.querySelector('.context').textContent.includes('removed'))")
            self.assertFalse(any('removed' in t for t in page.locator('#comment-list .comment-card', has_text='far away heading').locator('.context').all_inner_texts()))
            self.assertEqual(page.errors, [])
        finally:
            for c in (live, gone):
                test_server.http(self.url + '/api/comments/' + c['id'], 'DELETE', {'project_id': self.project['id'], 'revision': self.project['revision']})

    def test_comment_on_a_placeholder_has_no_placeholder_text(self):
        page = self.open()
        page.evaluate("document.querySelector('#board>.frame[data-frame-id=\"f30\"] .frame-placeholder')")
        excerpt = page.evaluate("document.getElementById('f30--screen').textContent")
        self.assertEqual(excerpt.strip(), '')

    # --- Flow view ------------------------------------------------------------------------------------------------------
    def test_flow_deep_link_loads_that_screen_first_then_its_goto_target(self):
        page = self.open(self.url + '/#view=flow&frame=f20')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f20"]', state='attached')
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f20\"]').dataset.load==='loaded'")
        self.assertEqual(page.frame_requests[0], 'f20.html')
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f21\"]').dataset.load==='loaded'", timeout=5000)  # data-goto prefetch
        page.wait_for_timeout(300)
        self.assertEqual(sorted(page.frame_requests), ['f20.html', 'f21.html'])   # nothing else in the Flow view
        page.click('#f20--go')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f21"]', state='attached')
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f22\"]').dataset.load==='loaded'")
        page.click('#flow-back')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f20"]', state='attached')
        self.assertEqual(page.errors, [])

    def frame_focus(self, page, frame_id):
        """How far the frame's centre is from the centre of the visible canvas, and whether it meets the viewport."""
        return page.evaluate("""(id)=>{const art=document.querySelector('#board>.frame[data-frame-id="'+id+'"]');
          const r=art.getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();
          const aw=v.width-(document.body.classList.contains('panel-open')&&innerWidth>1000?340:0);
          return {dx:r.left+r.width/2-(v.left+aw/2),dy:r.top+r.height/2-(v.top+v.height/2),
                  inView:r.right>v.left&&r.left<v.right&&r.bottom>v.top&&r.top<v.bottom,
                  transform:document.getElementById('board').style.transform,zoom:document.getElementById('zoom-value').textContent}}""", frame_id)

    def test_switching_from_flow_back_to_tile_centres_the_current_frame(self):
        page = self.open(self.url + '/#view=flow&frame=f20')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f20"]', state='attached')
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f20\"]').dataset.load==='loaded'")
        # Still in Flow: the tile camera is the start camera. Jumps do not pre-scroll the tile view.
        start = page.evaluate("document.getElementById('board').style.transform")
        self.assertEqual(start, 'translate(28px, 28px) scale(0.5)')
        page.click('#f20--go')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f21"]', state='attached')
        self.assertEqual(page.evaluate("document.getElementById('board').style.transform"), start)
        page.click('#view-tile')
        page.wait_for_function("!document.body.classList.contains('flow-mode')")
        landed = self.frame_focus(page, 'f21')
        self.assertLess(abs(landed['dx']), 2, landed)
        self.assertLess(abs(landed['dy']), 2, landed)
        self.assertTrue(landed['inView'], landed)
        self.assertEqual(landed['zoom'], '50%')
        self.assertGreater(abs(self.frame_focus(page, 'f20')['dx']), 40)  # the previous Flow frame is not what got centred
        # A manual pan stays put. Nothing pulls the view back to f21.
        cx, cy = page.evaluate("""()=>{const v=document.getElementById('viewport').getBoundingClientRect();return [v.left+v.width/2,v.top+40]}""")
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(400)
        panned = page.evaluate("document.getElementById('board').style.transform")
        self.assertNotEqual(panned, landed['transform'])
        page.wait_for_timeout(500)
        self.assertEqual(page.evaluate("document.getElementById('board').style.transform"), panned)
        # Back to Flow (browse entry), on to another frame, then Tile centres that one.
        page.click('#view-flow')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f01"]', state='attached')
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f01\"]').dataset.load==='loaded'")
        self.assertEqual(page.evaluate("document.getElementById('board').style.transform"), panned)
        page.click('#f01--go')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f02"]', state='attached')
        self.assertEqual(page.evaluate("document.getElementById('board').style.transform"), panned)
        page.click('#view-tile')
        page.wait_for_function("!document.body.classList.contains('flow-mode')")
        again = self.frame_focus(page, 'f02')
        self.assertLess(abs(again['dx']), 2, again)
        self.assertLess(abs(again['dy']), 2, again)
        self.assertTrue(again['inView'], again)
        self.assertGreater(abs(self.frame_focus(page, 'f21')['dy']), 40)
        self.assertEqual(page.errors, [])

    # --- history --------------------------------------------------------------------------------------------------------
    def test_history_with_a_missing_frame_file_still_opens(self):
        page = self.open()
        self.settle(page)
        page.click('#history')
        page.locator('#history-menu .hm-item', has_text='r1').first.click()
        page.wait_for_selector('body.history-mode')
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f02\"]').dataset.load==='error'")
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f01\"]').dataset.load==='loaded'")
        self.assertTrue(page.locator('#history-banner').is_visible())
        self.assertEqual(page.inner_text('#zoom-value'), '50%')
        label = page.evaluate("document.querySelector('#board>.frame[data-frame-id=\"f02\"] .frame-placeholder').dataset.label")
        self.assertIn('f02.html', label)
        page.click('#history-back')
        page.click('#history-leave-ok')
        page.wait_for_function("!document.body.classList.contains('history-mode')")
        page.wait_for_function("document.querySelector('#board>.frame[data-frame-id=\"f02\"]').dataset.load==='loaded'")


if __name__ == '__main__':
    unittest.main(verbosity=2)
