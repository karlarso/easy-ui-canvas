#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for board-wide comments: frame titles and subtitles, notes (project.notes) outside every frame and their
elements can be selected and commented; the layer picker gets a "Canvas" top layer; the frame column of a note comment says "Canvas";
comments show up in the panel, in "Copy for AI" and can be located; comments inside the phone, comments saved before this feature and
history snapshots keep working; Flow view, /m/ and the camera gestures are unaffected. Throw-away canvases in a temporary runtime.
Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself otherwise.
Run: python3 tests/browser_board_comments.py"""
import json
import os
import shutil
import sqlite3
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

FRAME = ('<style>[data-frame-id="%s"] .app{height:100%%;background:#dde;padding:16px;font:16px system-ui}</style>'
         '<div class="app"><button data-ui-id="b" data-ui-label="Button">Frame %s</button></div>')
NOTE_INTRO = '<h3 data-ui-id="heading" data-ui-label="Note heading">Reading order</h3><p data-ui-id="tip">Start at the first screen.</p>'
NOTE_BELOW = '<p data-ui-id="remark" data-ui-label="Remark under the first screen">Check the empty state here.</p>'
NOTES = [{'id': 'intro', 'path': 'frames/note-intro.html', 'x': 900, 'y': 12, 'title': 'Reading notes'},
         {'id': 'below', 'path': 'frames/note-below.html', 'x': 0, 'y': 780, 'anchor': 'f01', 'width': 300}]
OLD_COMMENT = {'id': 'old-1', 'project_id': None, 'revision': None, 'frame_id': 'f01', 'frame': 'Screen 1', 'target': 'f01--b', 'element': 'Button',
               'text': 'older comment inside the phone', 'created_at': '2025-01-01T00:00:00+00:00', 'status': 'pending', 'replies': [],
               'source_hash': 'abc', 'excerpt': 'Frame f01'}

CENTER = "id=>{const r=document.getElementById(id).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}"


class BoardComments(test_server.ServerTest):
    @classmethod
    def make(cls, name, notes=True):
        created = json.loads(cls.cli('new', '--name', name))
        cdir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % created['port']))
        project = json.loads((cdir / 'project.json').read_text())
        project['frames'] = [
            {'id': 'f01', 'title': 'Screen 1', 'width': 390, 'height': 700, 'path': 'frames/f01.html', 'state': 'Draft'},
            {'id': 'f02', 'title': 'Screen 2', 'width': 390, 'height': 700, 'path': 'frames/f02.html'}]
        project['flow_start'] = 'f01'
        project.pop('groupColumns', None)
        if notes:
            project['notes'] = NOTES
        shutil.rmtree(cdir / 'frames', ignore_errors=True)
        (cdir / 'frames').mkdir()
        for fid in ('f01', 'f02'):
            (cdir / 'frames' / (fid + '.html')).write_text(FRAME % (fid, fid))
        if notes:
            (cdir / 'frames' / 'note-intro.html').write_text(NOTE_INTRO)
            (cdir / 'frames' / 'note-below.html').write_text(NOTE_BELOW)
        (cdir / 'project.json').write_text(json.dumps(project, indent=2))
        return 'http://127.0.0.1:%d' % created['port'], cdir, created['id'], project

    @classmethod
    def seed_old_comment(cls, cdir, project):
        old = dict(OLD_COMMENT, project_id=project['id'], revision=project['revision'])
        (cdir / 'runtime').mkdir(exist_ok=True)
        con = sqlite3.connect(str(cdir / 'runtime' / 'feedback.sqlite3'))
        con.execute('CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, project TEXT NOT NULL, revision TEXT NOT NULL, client_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
        with con:
            con.execute('INSERT INTO comments VALUES (?,?,?,?,?)', (old['id'], project['id'], project['revision'], 'old-client', json.dumps(old)))
        con.close()

    @classmethod
    def api_comment(cls, url, project, target, text):
        status, body = test_server.http(url + '/api/comments', 'POST', {'client_id': 'seed-' + target, 'project_id': project['id'], 'revision': project['revision'],
                                                                      'target': target, 'text': text, 'position': {'x': 0.1, 'y': 0.1}})
        assert status == 201, body
        return json.loads(body)['comment']

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.url, cls.cdir, cls.cid, cls.project = cls.make('Board', notes=True)
        cls.seed_old_comment(cls.cdir, cls.project)
        cls.seeded = cls.api_comment(cls.url, cls.project, '~note~intro~tip', 'seeded note comment')
        cls.cli('snapshot', '--canvas', cls.cid)  # history r = current revision, with the two comments above
        cls.removed_url, cls.removed_dir, _, cls.removed_project = cls.make('Removed', notes=True)
        cls.api_comment(cls.removed_url, cls.removed_project, '~note~below~remark', 'comment on a note that goes away')
        cls.removed_project.pop('notes')
        (cls.removed_dir / 'project.json').write_text(json.dumps(cls.removed_project))
        cls.plain_url, _, _, _ = cls.make('Plain', notes=False)
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

    # --- helpers ------------------------------------------------------------------------------------------------------
    def open(self, url, width=1440, height=900):
        context = self.browser.new_context(locale='en-US', viewport={'width': width, 'height': height})
        try:
            context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url)
        except Exception:
            pass
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        self.addCleanup(context.close)
        page.goto(url)
        page.wait_for_selector('#board>.frame .phone', state='attached')
        page.wait_for_timeout(300)
        return page

    def center(self, page, element_id):
        return page.evaluate(CENTER, element_id)

    def comments(self, url=None):
        return json.loads(test_server.http((url or self.url) + '/api/comments')[1])['comments']

    def pick(self, page, element_id, dx=0):
        """Comment mode on, click the middle of the element, wait for the comment box."""
        if not page.evaluate("document.body.classList.contains('comment-mode')"):
            page.click('#annotate')
        x, y = self.center(page, element_id)
        page.mouse.click(x + dx, y)
        page.wait_for_selector('#editor[open]')

    def save(self, page, text):
        page.focus('#comment-text')
        page.keyboard.type(text)
        page.keyboard.press('Enter')
        page.wait_for_function("!document.getElementById('editor').open")

    def comment_on(self, page, element_id, text):
        self.pick(page, element_id)
        self.save(page, text)
        found = [c for c in self.comments() if c['text'] == text]
        self.assertEqual(len(found), 1, text)
        return found[0]

    def picker(self, page):
        return page.evaluate("[...document.querySelectorAll('#layer-picker option')].map(o=>({id:o.value,text:o.textContent.replace(/\\u3000/g,'>'),disabled:o.disabled}))")

    # --- frame title and subtitle ---------------------------------------------------------------------------------------
    def test_frame_title_is_selectable_and_commentable(self):
        page = self.open(self.url)
        self.pick(page, 'f01~title', dx=-60)
        self.assertEqual(page.inner_text('#selection-label'), 'Screen 1 / Title: Screen 1')
        self.save(page, 'about the title')
        c = [c for c in self.comments() if c['text'] == 'about the title'][0]
        self.assertEqual((c['frame_id'], c['frame'], c['target'], c['element']), ('f01', 'Screen 1', 'f01~title', 'Title: Screen 1'))
        self.assertEqual(c['position_ref'], 'frame')
        self.assertTrue(0 <= c['position']['x'] <= 1 and 0 <= c['position']['y'] <= 0.2, c['position'])
        self.assertEqual(page.errors, [])

    def test_frame_subtitle_is_selectable_and_only_exists_when_there_is_one(self):
        page = self.open(self.url)
        c = self.comment_on(page, 'f01~subtitle', 'about the subtitle')
        self.assertEqual((c['frame'], c['element'], c['position_ref']), ('Screen 1', 'Subtitle: Draft', 'frame'))
        self.assertIsNone(page.evaluate("document.getElementById('f02~subtitle')"))
        self.assertEqual(page.evaluate("document.querySelector('[data-frame-id=f02] .frame-title p').hasAttribute('data-comment')"), False)
        c = self.comment_on(page, 'f02~title', 'second title')  # a frame without subtitle still has a title target
        self.assertEqual((c['frame_id'], c['element']), ('f02', 'Title: Screen 2'))

    def test_whole_layout_and_elements_in_the_phone_are_unchanged(self):
        page = self.open(self.url)
        self.pick(page, 'f01--b')
        self.assertEqual(page.inner_text('#selection-label'), 'Screen 1 / Button')
        opts = self.picker(page)
        ids = [o['id'] for o in opts]
        self.assertEqual(ids[0], 'f01--screen')  # the phone itself on top, then everything inside it (automatic targets included), nothing from outside
        self.assertIn('f01--b', ids)
        self.assertTrue(all(i.startswith('f01--') for i in ids), ids)
        self.assertEqual(opts[0]['text'], 'Screen 1 · Whole layout')
        self.assertFalse(any(o['disabled'] for o in opts))
        self.assertFalse(page.evaluate("document.getElementById('layer-parent').disabled"))
        for _ in range(10):  # parent, parent, ... up to the whole layout of the phone (automatic targets sit in between)
            if page.evaluate("document.getElementById('layer-parent').disabled"):
                break
            page.click('#layer-parent')
        self.assertEqual(page.inner_text('#selection-label'), 'Screen 1 / Screen 1 · Whole layout')
        self.assertTrue(page.evaluate("document.getElementById('layer-parent').disabled"))
        page.click('#cancel')
        c = self.comment_on(page, 'f01--b', 'comment inside the phone')
        self.assertEqual(sorted(c), sorted(['id', 'project_id', 'revision', 'frame_id', 'frame', 'target', 'element', 'text', 'created_at', 'status', 'replies', 'source_hash', 'excerpt']))
        self.assertEqual((c['frame'], c['element']), ('Screen 1', 'Button'))

    # --- notes outside every frame ----------------------------------------------------------------------------------------
    def test_note_elements_are_selectable_and_recorded_against_the_canvas(self):
        page = self.open(self.url)
        self.pick(page, '~note~intro~heading')
        self.assertEqual(page.inner_text('#selection-label'), 'Canvas / Note heading')
        board_rel = page.evaluate("""()=>{const r=document.getElementById('~note~intro~heading').getBoundingClientRect(),b=document.getElementById('board').getBoundingClientRect();return [(r.left-b.left)/b.width,(r.top-b.top)/b.height]}""")
        self.save(page, 'about the note heading')
        c = [c for c in self.comments() if c['text'] == 'about the note heading'][0]
        self.assertEqual((c['frame_id'], c['frame'], c['target'], c['element']), ('', 'Canvas', '~note~intro~heading', 'Note heading'))
        self.assertEqual(c['position_ref'], 'board')
        self.assertAlmostEqual(c['position']['x'], board_rel[0], delta=0.002)
        self.assertAlmostEqual(c['position']['y'], board_rel[1], delta=0.002)

    def test_whole_note_and_anchored_note_are_commentable(self):
        page = self.open(self.url)
        page.click('#annotate')
        r = page.evaluate("(()=>{const r=document.getElementById('~note~intro').getBoundingClientRect();return [r.left+4,r.top+4]})()")
        page.mouse.click(r[0], r[1])  # the note's own padding, not one of its elements
        page.wait_for_selector('#editor[open]')
        self.assertEqual(page.inner_text('#selection-label'), 'Canvas / Note: Reading notes')
        self.save(page, 'about the whole note')
        c = [c for c in self.comments() if c['text'] == 'about the whole note'][0]
        self.assertEqual((c['frame'], c['target'], c['element']), ('Canvas', '~note~intro', 'Note: Reading notes'))
        c = self.comment_on(page, '~note~below~remark', 'about the remark')
        self.assertEqual((c['frame'], c['element']), ('Canvas', 'Remark under the first screen'))

    def test_layer_picker_has_a_canvas_top_layer_outside_the_frames(self):
        page = self.open(self.url)
        self.pick(page, '~note~intro~tip')
        opts = self.picker(page)
        self.assertEqual(opts[0], {'id': '', 'text': 'Canvas', 'disabled': True})  # a label, not a target
        texts = [o['text'] for o in opts[1:]]
        for want in ('>Title: Screen 1', '>Subtitle: Draft', '>Title: Screen 2', '>Note: Reading notes', '>>Note heading', '>>Start at the first screen.', '>Note: below', '>>Remark under the first screen'):
            self.assertIn(want, texts)
        self.assertFalse(any(o['id'].startswith('f01--') for o in opts), 'nothing from inside a phone is listed under Canvas')
        self.assertEqual(page.evaluate("document.getElementById('layer-picker').value"), '~note~intro~tip')
        # switching layers through the picker
        page.select_option('#layer-picker', 'f01~title')
        self.assertEqual(page.inner_text('#selection-label'), 'Screen 1 / Title: Screen 1')
        self.assertTrue(page.evaluate("document.getElementById('layer-parent').disabled"))  # a title has no parent layer
        page.select_option('#layer-picker', '~note~intro~heading')
        self.assertFalse(page.evaluate("document.getElementById('layer-parent').disabled"))
        page.click('#layer-parent')  # parent of a note element is the note
        self.assertEqual(page.inner_text('#selection-label'), 'Canvas / Note: Reading notes')
        self.assertTrue(page.evaluate("document.getElementById('layer-parent').disabled"))  # the note is the top of its tree
        self.assertEqual(page.evaluate("document.getElementById('layer-picker').value"), '~note~intro')

    # --- panel, copy, export, locate ---------------------------------------------------------------------------------------------
    def test_panel_copy_and_locate_for_canvas_comments(self):
        page = self.open(self.url)
        self.comment_on(page, '~note~intro~heading', 'panel copy locate')
        page.keyboard.press('Escape')
        page.click('#open-comments')
        card = page.locator('.comment-card', has_text='panel copy locate')
        self.assertRegex(card.locator('.context').inner_text(), r'^\d+\. Canvas / Note heading$')
        card.locator('.comment-check').check()
        page.click('#comment-more summary')
        page.click('#copy-feedback')
        page.wait_for_timeout(300)
        text = page.evaluate("navigator.clipboard.readText().catch(()=> '')")
        self.assertIn('Canvas / Note heading\nElement ID: ~note~intro~heading\nFeedback: panel copy locate', text)
        # export keeps the same record
        self.assertTrue(card.locator('.comment-check').is_checked())
        with page.expect_download() as info:
            page.click('#comment-more summary')
            page.click('#export')
        exported = json.loads(Path(info.value.path()).read_text())
        row = [c for c in exported['comments'] if c['text'] == 'panel copy locate'][0]
        self.assertEqual((row['frame'], row['frame_id'], row['position_ref']), ('Canvas', '', 'board'))
        # locate: pan away first, then the element comes back to the middle of the visible canvas and is highlighted
        page.mouse.move(40, 800)
        page.mouse.wheel(900, 700)
        page.wait_for_timeout(200)
        moved = self.center(page, '~note~intro~heading')
        self.assertNotEqual(moved, None)
        card.locator('.locate').click()
        page.wait_for_timeout(200)
        after = page.evaluate("""()=>{const e=document.getElementById('~note~intro~heading'),r=e.getBoundingClientRect(),v=document.getElementById('viewport').getBoundingClientRect(),aw=v.width-(document.body.classList.contains('panel-open')&&innerWidth>1000?340:0);
          return {dx:r.left+r.width/2-v.left-aw/2,dy:r.top+r.height/2-v.top-v.height/2,mark:e.classList.contains('comment-selected')}}""")
        self.assertLessEqual(abs(after['dx']), 3)
        self.assertLessEqual(abs(after['dy']), 3)
        self.assertTrue(after['mark'])
        # a title comment locates too
        self.comment_on(page, 'f02~title', 'locate the title')
        page.mouse.wheel(-900, -700)
        page.locator('.comment-card', has_text='locate the title').locator('.locate').click()
        page.wait_for_timeout(200)
        self.assertTrue(page.evaluate("document.getElementById('f02~title').classList.contains('comment-selected')"))
        self.assertEqual(page.errors, [])

    def test_old_comments_still_show_and_locate(self):
        page = self.open(self.url)
        page.click('#open-comments')
        card = page.locator('.comment-card', has_text='older comment inside the phone')
        self.assertRegex(card.locator('.context').inner_text(), r'^\d+\. Screen 1 / Button$')
        self.assertNotIn('removed', card.inner_text())
        card.locator('.locate').click()
        page.wait_for_timeout(200)
        self.assertTrue(page.evaluate("document.getElementById('f01--b').classList.contains('comment-selected')"))

    def test_note_gone_shows_element_removed_and_locate_says_so(self):
        page = self.open(self.removed_url)
        page.click('#open-comments')
        card = page.locator('.comment-card', has_text='comment on a note that goes away')
        self.assertRegex(card.locator('.context').inner_text(), r'^\d+\. Canvas / Remark under the first screen\(original element removed\)$')
        self.assertEqual(page.locator('.board-note').count(), 0)
        card.locator('.locate').click()
        page.wait_for_function("document.getElementById('toast').textContent.includes('no longer in the current version')")

    # --- history ----------------------------------------------------------------------------------------------------------
    def test_history_shows_notes_and_their_comments_read_only(self):
        page = self.open(self.url)
        page.click('#history')
        page.click('#history-menu .hm-item')
        page.wait_for_selector('body.history-mode')
        page.wait_for_function("document.querySelectorAll('#board>.board-note').length===2")
        page.click('#open-comments')
        card = page.locator('.comment-card', has_text='seeded note comment')
        self.assertRegex(card.locator('.context').inner_text(), r'^\d+\. Canvas / tip$')
        self.assertEqual(page.locator('.comment-card', has_text='older comment inside the phone').count(), 1)
        card.locator('.locate').click()
        page.wait_for_timeout(200)
        self.assertTrue(page.evaluate("document.getElementById('~note~intro~tip').classList.contains('comment-selected')"))
        # read-only: comment mode refuses and a click on a note or a title opens nothing
        self.assertTrue(page.evaluate("document.getElementById('annotate').disabled"))
        for element_id in ('~note~intro~tip', 'f01~title'):
            x, y = self.center(page, element_id)
            page.mouse.click(x, y)
            self.assertFalse(page.evaluate("document.getElementById('editor').open"))
        page.click('#history-back')
        page.wait_for_function("!document.body.classList.contains('history-mode')")
        self.assertEqual(page.locator('#board>.board-note').count(), 2)
        self.assertEqual(page.errors, [])

    # --- the rest of the page ----------------------------------------------------------------------------------------------
    def test_flow_view_and_phone_page_do_not_show_or_comment_on_notes(self):
        page = self.open(self.url + '/#view=flow&frame=f01')
        page.wait_for_selector('.frame.flow-current[data-frame-id="f01"]', state='attached')
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#board>.board-note')].filter(e=>getComputedStyle(e).display!=='none').length"), 0)
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.flow-current .frame-title')).display"), 'none')
        page.keyboard.press('c')
        self.assertFalse(page.evaluate("document.body.classList.contains('comment-mode')"))  # flow view has no comments
        m = self.open_plain_m(self.url)
        self.assertEqual(m.locator('.board-note').count(), 0)
        self.assertEqual(m.locator('[data-comment]').count(), 0)
        self.assertEqual(m.locator('#m-phone').count(), 1)
        self.assertEqual(m.errors, [])
        self.assertEqual(page.errors, [])

    def open_plain_m(self, url):
        context = self.browser.new_context(locale='en-US', viewport={'width': 390, 'height': 800})
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        self.addCleanup(context.close)
        page.goto(url + '/m/')
        page.wait_for_selector('#m-phone .app')
        return page

    def test_camera_gestures_and_keys_are_unaffected(self):
        page = self.open(self.url)
        transform = "document.getElementById('board').style.transform"
        # wheel over a title and over a note pans the canvas (they are not scrollable screens)
        for element_id in ('f01~title', '~note~intro~tip'):
            x, y = self.center(page, element_id)
            page.mouse.move(x, y)
            before = page.evaluate(transform)
            page.mouse.wheel(0, -120)  # up, so the next element (near the top) stays on screen
            page.wait_for_timeout(300)
            self.assertNotEqual(page.evaluate(transform), before, element_id)
        # a drag that starts on a title or a note pans and never opens the comment box, even in comment mode
        page.click('#annotate')
        for element_id in ('f02~title', '~note~intro~heading'):
            x, y = self.center(page, element_id)
            before = page.evaluate(transform)
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 40, y + 30, steps=5)
            page.mouse.up()
            page.wait_for_timeout(500)
            self.assertNotEqual(page.evaluate(transform), before, element_id)
            self.assertFalse(page.evaluate("document.getElementById('editor').open"), element_id)
        # Space types in the comment box of a canvas comment, and still holds the hand elsewhere
        self.pick(page, '~note~intro~heading')
        x, y = self.center(page, '~note~intro~tip')
        page.mouse.move(x, y)
        page.focus('#comment-text')
        page.keyboard.type('a b')
        self.assertEqual(page.input_value('#comment-text'), 'a b')
        self.assertFalse(page.evaluate("document.body.classList.contains('canvas-hand')"))
        page.evaluate("document.activeElement.blur()")
        page.keyboard.down('Space')
        self.assertTrue(page.evaluate("document.body.classList.contains('canvas-hand')"))
        page.keyboard.up('Space')
        page.click('#cancel')
        # C toggles comment mode, D the panel
        page.keyboard.press('c')
        self.assertFalse(page.evaluate("document.body.classList.contains('comment-mode')"))
        page.keyboard.press('d')
        self.assertTrue(page.evaluate("document.body.classList.contains('panel-open')"))
        page.keyboard.press('d')
        self.assertFalse(page.evaluate("document.body.classList.contains('panel-open')"))
        self.assertEqual(page.errors, [])

    def test_board_and_minimap_cover_the_notes(self):
        page = self.open(self.url)
        g = page.evaluate("""()=>{const b=document.getElementById('board'),br=b.getBoundingClientRect(),s=br.width/b.offsetWidth,rel=id=>{const r=document.getElementById(id).getBoundingClientRect();return [(r.left-br.left)/s,(r.top-br.top)/s,r.width/s,r.height/s]};
          return {board:[b.offsetWidth,b.offsetHeight],intro:rel('~note~intro'),below:rel('~note~below'),f01:rel('f01--screen'),title:rel('f01~title'),
                  mmNotes:document.querySelectorAll('#minimap-world .mm-note').length,mmFrames:document.querySelectorAll('#minimap-world .mm-frame').length}}""")
        self.assertEqual(g['mmFrames'], 2)
        self.assertEqual(g['mmNotes'], 2)
        self.assertAlmostEqual(g['intro'][0], 900, delta=1)
        self.assertAlmostEqual(g['intro'][1], 12, delta=1)
        self.assertAlmostEqual(g['intro'][2], 320, delta=1)
        # anchored: measured from the top-left of the frame box (title included), width as given
        self.assertAlmostEqual(g['below'][0], g['title'][0], delta=1)
        self.assertAlmostEqual(g['below'][1], g['title'][1] + 780, delta=1)
        self.assertAlmostEqual(g['below'][2], 300, delta=1)
        self.assertGreaterEqual(g['board'][0], 900 + 320 + 12 - 1)
        self.assertGreaterEqual(g['board'][1], g['below'][1] + g['below'][3] + 12 - 1)

    def test_a_project_without_notes_looks_exactly_as_before(self):
        page = self.open(self.plain_url)
        g = page.evaluate("({board:[document.getElementById('board').offsetWidth,document.getElementById('board').offsetHeight],notes:document.querySelectorAll('.board-note').length,mm:document.querySelectorAll('#minimap-world .mm-note').length})")
        self.assertEqual(g, {'board': [844, 792], 'notes': 0, 'mm': 0})  # two 390x700 frames in the old grid: 2*390+40+24 by 768+24
        self.pick(page, 'f01--b')
        self.assertEqual(page.inner_text('#selection-label'), 'Screen 1 / Button')
        self.assertEqual(page.errors, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
