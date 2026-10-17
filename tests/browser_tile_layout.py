#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for the tile view layout (group sections, per-section columns, minimap, Flow view, history, /m/).
Builds throw-away canvases in a temporary runtime and checks the real page: where every frame ends up on the board, that sections start on new
rows, that a project without `group` keeps the old global grid exactly, that the minimap shows the same boxes, and that Flow view, history
snapshots, comment mode and the phone page still work. Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome);
skips itself otherwise. Run: python3 tests/browser_tile_layout.py"""
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

BAR, BAR_GAP, SECTION_GAP, PAD, GAP_X, GAP_Y, TITLE = 36, 20, 72, 12, 40, 44, 68


def legacy(frames, columns=3):
    """The old single global grid: [(x, y, w, h)] per frame and the board size."""
    cols = min(columns, len(frames))
    widths = [0] * cols
    rows = [0] * ((len(frames) + cols - 1) // cols)
    for i, f in enumerate(frames):
        widths[i % cols] = max(widths[i % cols], f['width'])
        rows[i // cols] = max(rows[i // cols], f['height'] + TITLE)
    xs = [PAD]
    for c in range(1, cols):
        xs.append(xs[-1] + widths[c - 1] + GAP_X)
    ys = [PAD]
    for r in range(1, len(rows)):
        ys.append(ys[-1] + rows[r - 1] + GAP_Y)
    boxes = [(xs[i % cols], ys[i // cols], f['width'], f['height'] + TITLE) for i, f in enumerate(frames)]
    return boxes, (sum(widths) + (cols - 1) * GAP_X + 2 * PAD, sum(rows) + (len(rows) - 1) * GAP_Y + 2 * PAD)


def html(fid):
    return ('<style>[data-frame-id="%s"] .app{height:100%%;background:#dde;padding:16px;font:16px system-ui}</style>'
            '<div class="app"><button data-ui-id="b" data-ui-label="Button">Frame %s</button></div>' % (fid, fid))


def spec(groups):
    """groups: list of (group or None, count, width, height)."""
    frames = []
    for group, count, width, height in groups:
        for _ in range(count):
            fid = 'f%02d' % (len(frames) + 1)
            frame = {'id': fid, 'title': 'Screen %d' % (len(frames) + 1), 'width': width, 'height': height, 'path': 'frames/%s.html' % fid, 'state': 'Draft'}
            if group:
                frame['group'] = group
            frames.append(frame)
    return frames


class TileLayout(test_server.ServerTest):
    @classmethod
    def make(cls, name, frames, **extra):
        created = json.loads(cls.cli('new', '--name', name))
        cdir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % created['port']))
        project = json.loads((cdir / 'project.json').read_text())
        project['frames'] = frames
        project['flow_start'] = frames[0]['id']
        project.update(extra)
        shutil.rmtree(cdir / 'frames', ignore_errors=True)
        (cdir / 'frames').mkdir()
        for f in frames:
            (cdir / 'frames' / (f['id'] + '.html')).write_text(html(f['id']))
        (cdir / 'project.json').write_text(json.dumps(project, indent=2))
        return 'http://127.0.0.1:%d' % created['port'], cdir

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.grouped_frames = spec([('Onboarding', 4, 390, 700), ('Home', 5, 390, 760), ('Settings', 3, 430, 640)])
        cls.grouped_url, cls.grouped_dir = cls.make('Grouped', cls.grouped_frames, groupColumns={'Onboarding': 2, 'Settings': 5})
        cls.plain_frames = spec([(None, 7, 390, 700)])
        cls.plain_url, _ = cls.make('Plain', cls.plain_frames)
        cls.plain4_frames = spec([(None, 9, 390, 700)])
        cls.plain4_url, _ = cls.make('Plain4', cls.plain4_frames, columns=4)
        cls.mixed_frames = spec([(None, 2, 390, 700), ('Alpha', 3, 390, 700), (None, 2, 390, 700), ('Beta', 2, 390, 700)])
        cls.mixed_url, _ = cls.make('Mixed', cls.mixed_frames)
        # a snapshot of the grouped canvas with a different grouping (history view uses the snapshot's own project.json)
        snap = cls.grouped_dir / 'snapshots' / 'r0'
        shutil.copytree(cls.grouped_dir / 'frames', snap / 'frames')
        old = json.loads((cls.grouped_dir / 'project.json').read_text())
        cls.snap_frames = [dict(f) for f in old['frames'][:5]]
        for f in cls.snap_frames:
            f['group'] = 'Old'
        old.update(revision='r0', frames=cls.snap_frames)
        old.pop('groupColumns')
        (snap / 'project.json').write_text(json.dumps(old))
        (snap / 'comments.json').write_text('[]')
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

    def open(self, url, width=1440, height=900):
        context = self.browser.new_context(locale='en-US', viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        self.addCleanup(context.close)
        page.goto(url)
        page.wait_for_selector('#board>.frame .phone', state='attached')
        page.wait_for_timeout(300)
        return page

    GEOMETRY = """()=>{const b=document.getElementById('board'),br=b.getBoundingClientRect(),s=br.width/b.offsetWidth;
      const rel=e=>{const r=e.getBoundingClientRect();return [(r.left-br.left)/s,(r.top-br.top)/s,r.width/s,r.height/s]};
      return {board:[b.offsetWidth,b.offsetHeight],frames:[...b.querySelectorAll(':scope>.frame')].map(rel),bars:[...b.querySelectorAll(':scope>.group-bar')].map(e=>({text:e.textContent,box:rel(e),vis:getComputedStyle(e).display}))}}"""

    def geometry(self, page):
        return page.evaluate(self.GEOMETRY)

    def assertBox(self, got, want, msg=''):
        for a, b in zip(got, want):
            self.assertLessEqual(abs(a - b), 0.6, '%s: got %s want %s' % (msg, got, want))

    def check_legacy(self, url, frames, columns=3):
        page = self.open(url)
        geo = self.geometry(page)
        boxes, size = legacy(frames, columns)
        self.assertEqual(geo['bars'], [])
        self.assertEqual(tuple(geo['board']), size)
        for i, (got, want) in enumerate(zip(geo['frames'], boxes)):
            self.assertBox(got, want, 'frame %d' % i)
        self.assertEqual(page.errors, [])
        return page

    # --- projects without groups look exactly as before ----------------------------------------------------------------
    def test_no_group_is_the_old_grid(self):
        self.check_legacy(self.plain_url, self.plain_frames)

    def test_no_group_custom_columns_is_the_old_grid(self):
        self.check_legacy(self.plain4_url, self.plain4_frames, columns=4)

    # --- sections --------------------------------------------------------------------------------------------------------
    def test_grouped_sections_layout_matches_dom(self):
        page = self.open(self.grouped_url)
        geo = self.geometry(page)
        self.assertEqual([b['text'] for b in geo['bars']], ['Onboarding', 'Home', 'Settings'])
        # Onboarding: groupColumns 2 -> 2x2; Home: default 3 -> 3+2; Settings: groupColumns 5 capped to 3 frames
        frames, bars = geo['frames'], geo['bars']
        ys = [round(f[1]) for f in frames]
        self.assertEqual(ys[0], ys[1])
        self.assertEqual(frames[0][0] < frames[1][0], True)
        self.assertEqual(round(frames[2][0]), round(frames[0][0]))  # Onboarding: third frame wraps to the next row
        self.assertGreater(ys[2], ys[0])
        home = frames[4:9]
        self.assertEqual([round(f[1]) for f in home[:3]], [round(home[0][1])] * 3)
        self.assertGreater(home[3][1], home[0][1])
        self.assertEqual(round(home[3][0]), round(home[0][0]))
        settings = frames[9:]
        self.assertEqual(len({round(f[1]) for f in settings}), 1)
        self.assertEqual(len({round(f[0]) for f in settings}), 3)
        # sections never share a row: every frame of a section is below the previous section's last frame, and below its own bar
        sections = [frames[0:4], frames[4:9], frames[9:12]]
        for i, section in enumerate(sections):
            self.assertGreaterEqual(min(f[1] for f in section), bars[i]['box'][1] + BAR + BAR_GAP - 0.6)
            if i:
                self.assertGreaterEqual(bars[i]['box'][1], max(f[1] + f[3] for f in sections[i - 1]) + SECTION_GAP - 0.6)
        # a bar spans its section's width
        for bar, section in zip(bars, sections):
            self.assertBox((bar['box'][0], bar['box'][2]), (min(f[0] for f in section), max(f[0] + f[2] for f in section) - min(f[0] for f in section)), 'bar span')
        # nothing overlaps and everything is inside the board
        for i, a in enumerate(frames):
            self.assertLessEqual(a[0] + a[2], geo['board'][0] + 0.6)
            self.assertLessEqual(a[1] + a[3], geo['board'][1] + 0.6)
            for b in frames[i + 1:]:
                self.assertTrue(a[0] + a[2] <= b[0] + 0.6 or b[0] + b[2] <= a[0] + 0.6 or a[1] + a[3] <= b[1] + 0.6 or b[1] + b[3] <= a[1] + 0.6)
        self.assertEqual(page.errors, [])

    def test_ungrouped_sections_have_no_bar(self):
        page = self.open(self.mixed_url)
        geo = self.geometry(page)
        self.assertEqual([b['text'] for b in geo['bars']], ['Alpha', 'Beta'])
        self.assertEqual(len(geo['frames']), 9)
        ys = [f[1] for f in geo['frames']]
        # ungrouped run (2 frames) on its own row, Alpha starts below it
        self.assertLess(ys[0] + 700 + TITLE, geo['bars'][0]['box'][1])
        self.assertEqual(page.errors, [])

    def test_frame_order_is_kept_in_dom(self):
        page = self.open(self.mixed_url)
        ids = page.evaluate("[...document.querySelectorAll('#board>.frame')].map(e=>e.dataset.frameId)")
        self.assertEqual(ids, [f['id'] for f in self.mixed_frames])

    def test_dark_theme_bar_is_visible(self):
        page = self.open(self.grouped_url)
        page.click('#theme')
        bg = page.evaluate("getComputedStyle(document.querySelector('.group-bar')).backgroundColor")
        self.assertNotIn(bg, ('rgba(0, 0, 0, 0)', 'transparent'))

    # --- minimap -------------------------------------------------------------------------------------------------------
    def test_minimap_mirrors_the_layout(self):
        page = self.open(self.grouped_url)
        mm = page.evaluate("""()=>{const w=document.getElementById('minimap-world');const f=[...w.querySelectorAll('.mm-frame')].map(e=>[e.offsetLeft,e.offsetTop,e.offsetWidth,e.offsetHeight]);
          return {frames:f,bars:w.querySelectorAll('.mm-bar').length}}""")
        geo = self.geometry(page)
        self.assertEqual(len(mm['frames']), 12)
        self.assertEqual(mm['bars'], 3)
        # same relative placement as the board: scale and offset are common to all boxes
        s = mm['frames'][0][2] / geo['frames'][0][2]
        ox, oy = mm['frames'][0][0] - geo['frames'][0][0] * s, mm['frames'][0][1] - geo['frames'][0][1] * s
        for m, f in zip(mm['frames'], geo['frames']):
            self.assertLessEqual(abs(m[0] - (ox + f[0] * s)), 2.5)
            self.assertLessEqual(abs(m[1] - (oy + f[1] * s)), 2.5)

    # --- camera ---------------------------------------------------------------------------------------------------------
    def test_fit_shows_whole_board_and_zoom_pan_work(self):
        page = self.open(self.grouped_url)
        fit = page.evaluate("""()=>{const b=document.getElementById('board').getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();
          return b.left>=v.left-1&&b.top>=v.top-1&&b.right<=v.right+1&&b.bottom<=v.bottom+1}""")
        self.assertTrue(fit, 'fit-to-view must show the whole board')
        before = page.evaluate("document.getElementById('board').getBoundingClientRect().toJSON()")
        page.click('#zoom-in')
        after = page.evaluate("document.getElementById('board').getBoundingClientRect().toJSON()")
        self.assertGreater(after['width'], before['width'])
        page.mouse.move(700, 400)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(300)
        moved = page.evaluate("document.getElementById('board').getBoundingClientRect().toJSON()")
        self.assertNotEqual(round(moved['top']), round(after['top']))

    # --- Flow view ------------------------------------------------------------------------------------------------------
    def test_flow_view_shows_one_frame_without_bars_and_returns_to_tile(self):
        page = self.open(self.grouped_url)
        before = self.geometry(page)
        page.click('#view-flow')
        page.wait_for_timeout(300)
        state = page.evaluate("""()=>{const fr=[...document.querySelectorAll('#board>.frame')].filter(e=>getComputedStyle(e).display!=='none');
          const cur=fr[0],r=cur.getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect();
          return {visible:fr.length,pos:getComputedStyle(cur).position,cur:cur.dataset.frameId,inside:r.left>=v.left-1&&r.top>=v.top-1&&r.right<=v.right+1&&r.bottom<=v.bottom+1,
                  bars:[...document.querySelectorAll('#board>.group-bar')].map(e=>getComputedStyle(e).display)}}""")
        self.assertEqual(state['visible'], 1)
        self.assertEqual(state['pos'], 'static')
        self.assertEqual(state['cur'], 'f01')
        self.assertTrue(state['inside'], 'the current frame must be fully inside the canvas in Flow view')
        self.assertEqual(set(state['bars']), {'none'})
        page.click('#view-tile')
        page.wait_for_timeout(300)
        after = self.geometry(page)
        self.assertEqual(before['board'], after['board'])
        for a, b in zip(before['frames'], after['frames']):
            self.assertBox(a, b, 'after Flow')
        self.assertEqual(page.errors, [])

    def test_flow_view_boot_from_hash(self):
        page = self.open(self.grouped_url + '/#view=flow&frame=f06')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f06"]', state='attached')
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#board>.frame')].filter(e=>getComputedStyle(e).display!=='none').length"), 1)

    # --- comments -------------------------------------------------------------------------------------------------------
    def test_comment_mode_targets_frame_in_a_later_section(self):
        page = self.open(self.grouped_url)
        page.click('#annotate')
        box = page.evaluate("(()=>{const r=document.getElementById('f10--b').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
        page.mouse.click(box[0], box[1])
        page.wait_for_selector('#editor[open]')
        self.assertIn('Screen 10', page.inner_text('#selection-label'))

    # --- history --------------------------------------------------------------------------------------------------------
    def test_history_view_uses_the_snapshot_project_and_back_restores(self):
        page = self.open(self.grouped_url)
        live = self.geometry(page)
        page.click('#history')
        page.click('#history-menu .hm-item:has-text("r0")')
        page.wait_for_selector('#history-banner:not([hidden])')
        page.wait_for_timeout(400)
        snap = self.geometry(page)
        self.assertEqual([b['text'] for b in snap['bars']], ['Old'])
        self.assertEqual(len(snap['frames']), 5)
        self.assertEqual(round(snap['frames'][0][1]), PAD + BAR + BAR_GAP)
        self.assertEqual(round(snap['frames'][3][0]), round(snap['frames'][0][0]))  # no groupColumns in the snapshot: 3 columns, row 2 starts at column 1
        self.assertEqual(page.evaluate("document.querySelectorAll('#minimap-world .mm-frame').length"), 5)
        page.click('#history-back')
        page.wait_for_timeout(500)
        back = self.geometry(page)
        self.assertEqual(back['board'], live['board'])
        self.assertEqual([b['text'] for b in back['bars']], ['Onboarding', 'Home', 'Settings'])
        self.assertEqual(page.evaluate("document.querySelectorAll('#minimap-world .mm-frame').length"), 12)
        self.assertEqual(page.errors, [])

    # --- phone page -----------------------------------------------------------------------------------------------------
    def test_mobile_page_is_unaffected(self):
        page = self.browser.new_context(locale='en-US', viewport={'width': 390, 'height': 800}).new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(self.grouped_url + '/m/')
        page.wait_for_selector('#m-phone button')
        self.assertEqual(page.evaluate("document.querySelectorAll('.group-bar').length"), 0)
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('m-frame')).position"), 'absolute')
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
