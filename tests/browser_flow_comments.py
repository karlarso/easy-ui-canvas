#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for comments in the Flow view: with comment mode on, a click selects the element and opens the comment box
(no jump, no "End of demo"); with it off, clicks jump again; the comment is stored for the frame on screen in the same shape as a tile-view
comment; locating from the panel switches to the comment's frame; history versions stay read-only in the Flow view. Throw-away canvas in a
temporary runtime. Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself otherwise.
Run: python3 tests/browser_flow_comments.py"""
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

F01 = ('<style>[data-frame-id="f01"] .app{height:100%;background:#dde;padding:16px;font:16px system-ui}</style>'
       '<div class="app"><button data-ui-id="go" data-ui-label="Next button" data-goto="f02">Next</button> '
       '<button data-ui-id="end" data-ui-label="Dead end button">Dead end</button></div>')
F02 = ('<style>[data-frame-id="f02"] .app{height:100%;background:#ded;padding:16px;font:16px system-ui}</style>'
       '<div class="app"><button data-ui-id="back" data-ui-label="Back button" data-goto="f01">Back</button> '
       '<p data-ui-id="card" data-ui-label="Card" style="margin-top:900px">Far down the page</p></div>')
CENTER = "id=>{const r=document.getElementById(id).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]}"
CUR = "document.querySelector('.frame.flow-current').dataset.frameId"


class FlowComments(test_server.ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        created = json.loads(cls.cli('new', '--name', 'Flow comments'))
        cls.url = 'http://127.0.0.1:%d' % created['port']
        cls.cdir = next((Path(cls.tmp) / 'canvases').glob('%d-*' % created['port']))
        cls.cid = created['id']
        project = json.loads((cls.cdir / 'project.json').read_text())
        project['frames'] = [
            {'id': 'f01', 'title': 'Screen 1', 'width': 390, 'height': 700, 'path': 'frames/f01.html', 'state': 'Draft'},
            {'id': 'f02', 'title': 'Screen 2', 'width': 390, 'height': 700, 'path': 'frames/f02.html'}]
        project['flow_start'] = 'f01'
        project.pop('groupColumns', None)
        shutil.rmtree(cls.cdir / 'frames', ignore_errors=True)
        (cls.cdir / 'frames').mkdir()
        (cls.cdir / 'frames' / 'f01.html').write_text(F01)
        (cls.cdir / 'frames' / 'f02.html').write_text(F02)
        (cls.cdir / 'project.json').write_text(json.dumps(project, indent=2))
        cls.project = project
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

    def flow(self, frame='f01', extra=''):
        page = self.open(self.url + '/#view=flow&frame=' + frame + extra)
        page.wait_for_selector('.frame.flow-current[data-frame-id="%s"]' % frame, state='attached')
        return page

    def comments(self):
        return json.loads(test_server.http(self.url + '/api/comments')[1])['comments']

    def click(self, page, element_id):
        x, y = page.evaluate(CENTER, element_id)
        page.mouse.click(x, y)

    def save(self, page, text):
        page.focus('#comment-text')
        page.keyboard.type(text)
        page.keyboard.press('Enter')
        page.wait_for_function("!document.getElementById('editor').open")

    def toast_shown(self, page):
        return page.evaluate("document.getElementById('demo-toast').classList.contains('show')")

    def post(self, target, text, client):
        status, body = test_server.http(self.url + '/api/comments', 'POST', {'client_id': client, 'project_id': self.project['id'],
                                                                           'revision': self.project['revision'], 'target': target, 'text': text})
        self.assertEqual(status, 201, body)
        return json.loads(body)['comment']

    # --- comment mode in the Flow view ----------------------------------------------------------------------------------
    def test_comment_mode_selects_instead_of_jumping_and_off_restores_the_jump(self):
        page = self.flow()
        self.assertFalse(page.evaluate("document.getElementById('annotate').disabled"))
        page.keyboard.press('c')
        self.assertTrue(page.evaluate("document.body.classList.contains('comment-mode')"))
        self.click(page, 'f01--go')  # a button with data-goto
        page.wait_for_selector('#editor[open]')
        self.assertEqual(page.evaluate(CUR), 'f01')
        self.assertIn('Next button', page.inner_text('#selection-label'))
        self.assertFalse(self.toast_shown(page))
        page.keyboard.press('Escape')
        self.click(page, 'f01--end')  # a button without data-goto: no "End of demo" in comment mode
        page.wait_for_selector('#editor[open]')
        self.assertFalse(self.toast_shown(page))
        self.assertEqual(page.evaluate(CUR), 'f01')
        page.keyboard.press('Escape')
        self.assertEqual(page.evaluate(CUR), 'f01')
        # comment mode off: clicks behave as before
        page.click('#annotate')
        self.assertFalse(page.evaluate("document.body.classList.contains('comment-mode')"))
        self.click(page, 'f01--end')
        page.wait_for_function("document.getElementById('demo-toast').classList.contains('show')")
        self.assertFalse(page.evaluate("document.getElementById('editor').open"))
        self.click(page, 'f01--go')
        page.wait_for_function(CUR + "==='f02'")
        self.assertFalse(page.evaluate("document.getElementById('editor').open"))
        self.assertEqual(page.errors, [])

    def test_an_open_comment_box_blocks_jumping_and_selecting(self):
        page = self.flow()
        page.keyboard.press('c')
        self.click(page, 'f01--end')
        page.wait_for_selector('#editor[open]')
        label = page.inner_text('#selection-label')
        self.click(page, 'f01--go')
        self.assertEqual(page.evaluate(CUR), 'f01')
        self.assertEqual(page.inner_text('#selection-label'), label)
        self.assertEqual(page.errors, [])

    def test_comment_is_stored_for_the_frame_on_screen_in_the_tile_shape(self):
        tile = self.open(self.url)
        tile.keyboard.press('c')
        self.click(tile, 'f01--go')
        tile.wait_for_selector('#editor[open]')
        self.save(tile, 'tile comment on go')
        page = self.flow()
        page.keyboard.press('c')
        self.click(page, 'f01--go')
        page.wait_for_selector('#editor[open]')
        self.save(page, 'flow comment on go')
        page.click('#annotate')  # off, then jump and comment on the second frame
        self.click(page, 'f01--go')
        page.wait_for_function(CUR + "==='f02'")
        page.click('#annotate')
        self.click(page, 'f02--back')
        page.wait_for_selector('#editor[open]')
        self.assertEqual(page.evaluate(CUR), 'f02')
        self.save(page, 'flow comment on back')
        by = {c['text']: c for c in self.comments()}
        tile_c, flow1, flow2 = by['tile comment on go'], by['flow comment on go'], by['flow comment on back']
        self.assertEqual((flow1['frame_id'], flow1['frame'], flow1['target'], flow1['element']), ('f01', 'Screen 1', 'f01--go', 'Next button'))
        self.assertEqual((flow2['frame_id'], flow2['frame'], flow2['target'], flow2['element']), ('f02', 'Screen 2', 'f02--back', 'Back button'))
        for c in (flow1, flow2):
            self.assertEqual(sorted(c), sorted(tile_c))  # same record shape: no position, no source label, no step
            self.assertNotIn('position', c)
        self.assertEqual(page.errors + tile.errors, [])

    # --- the panel ------------------------------------------------------------------------------------------------------
    def test_locating_in_the_panel_switches_to_the_comments_frame(self):
        self.post('f02--card', 'comment far down on screen 2', 'loc-1')
        self.post('f01--end', 'comment on screen 1', 'loc-2')
        self.post('f02~title', 'comment on a frame title', 'loc-3')
        page = self.flow()
        page.keyboard.press('d')
        page.wait_for_selector('#comments:not([hidden])')
        card = page.locator('.comment-card', has_text='comment far down on screen 2')
        card.locator('.locate').click()
        page.wait_for_function(CUR + "==='f02'")
        page.wait_for_timeout(200)
        self.assertTrue(page.evaluate("document.getElementById('f02--card').classList.contains('comment-selected')"))
        inside = page.evaluate("(()=>{const e=document.getElementById('f02--card').getBoundingClientRect(),p=document.querySelector('.flow-current .phone').getBoundingClientRect();return e.top>=p.top&&e.bottom<=p.bottom})()")
        self.assertTrue(inside, 'the element must be scrolled into view inside the screen')
        # back to the other frame, and the hash follows
        page.locator('.comment-card', has_text='comment on screen 1').locator('.locate').click()
        page.wait_for_function(CUR + "==='f01'")
        self.assertIn('frame=f01', page.evaluate('location.hash'))
        self.assertTrue(page.evaluate("document.getElementById('f01--end').classList.contains('comment-selected')"))
        # a target the Flow view does not show says so and stays on the frame
        page.locator('.comment-card', has_text='comment on a frame title').locator('.locate').click()
        page.wait_for_function("getComputedStyle(document.getElementById('toast')).display!=='none'")
        self.assertEqual(page.evaluate(CUR), 'f02')  # the comment's own frame is shown, its title is hidden in Flow
        self.assertEqual(page.errors, [])

    # --- history ---------------------------------------------------------------------------------------------------------
    def test_history_stays_read_only_in_the_flow_view(self):
        self.cli('snapshot', '--canvas', self.cid)
        rev = self.project['revision']
        page = self.flow('f01', '&rev=' + rev)
        page.wait_for_selector('body.history-mode')
        self.assertTrue(page.evaluate("document.getElementById('annotate').disabled"))
        page.keyboard.press('c')
        self.assertFalse(page.evaluate("document.body.classList.contains('comment-mode')"))
        page.evaluate("document.getElementById('annotate').click()")
        self.assertFalse(page.evaluate("document.body.classList.contains('comment-mode')"))
        self.click(page, 'f01--end')
        self.assertFalse(page.evaluate("document.getElementById('editor').open"))
        self.click(page, 'f01--go')  # the demo itself still works in history
        page.wait_for_function(CUR + "==='f02'")
        self.assertFalse(page.evaluate("document.getElementById('editor').open"))
        self.assertEqual(page.errors, [])

    def test_phone_page_is_still_a_read_only_preview(self):
        context = self.browser.new_context(locale='en-US', viewport={'width': 390, 'height': 800})
        self.addCleanup(context.close)
        m = context.new_page()
        m.goto(self.url + '/m/')
        m.wait_for_selector('#m-phone')
        self.assertEqual(m.locator('[data-comment]').count(), 0)
        self.assertEqual(m.locator('#annotate').count(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
