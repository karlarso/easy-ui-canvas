#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional headless-browser test for "Copy frame reference": the icon button in each frame title bar (a sibling of the h2, never a comment target) and the
button next to the frame id in the Flow view copy a short plain-text reference (canvas address and id, snapshot rev, frame id and title, Flow link). The rev is the
newest snapshot (not the live project revision), the history rev while a history version is shown, and is left out when the canvas has no snapshot. The LAN-http
path (no async clipboard) goes through the textarea fallback; the secure-context path uses navigator.clipboard. Comment mode, both languages, small zoom and
/m/ are checked too. The history banner's "Copy link to this version" copies origin/?rev=<snapshot> (Flow also adds the hash); opening that URL stays on that snapshot, read-only, and a rejected id falls back to the live revision. "Back to current version" asks first: Cancel and Escape stay on the snapshot, confirming removes rev. Throw-away canvases in a temporary runtime. Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself
otherwise. Run: python3 tests/browser_frame_ref.py"""
import json
import os
import re
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

F01 = '<div style="padding:16px"><h1 data-ui-id="hello" data-ui-label="Hello">Hello</h1><button data-goto="f02">Next</button></div>'
F02 = '<div style="padding:16px"><p data-ui-id="two" data-ui-label="Two">Two</p></div>'
# Simulate a canvas opened over LAN http (not a secure context: no async clipboard) and record what execCommand('copy') copies.
NO_CLIPBOARD = """
Object.defineProperty(Navigator.prototype, 'clipboard', {get: () => undefined, configurable: true});
window.__copied = [];
document.addEventListener('copy', e => {
  const t = e.target;
  window.__copied.push(t && typeof t.value === 'string' ? t.value.slice(t.selectionStart, t.selectionEnd) : String(getSelection()));
}, true);
"""


def shown_canvas_id(cid):
    """Frame-reference text for a canvas created by new: display_id is # plus the digits."""
    if re.fullmatch(r'[1-9]\d*', cid or ''):
        return '#' + cid
    return cid


def setup_canvas(cli, tmp, name, frames, revs):
    created = json.loads(cli('new', '--name', name))
    cdir = next((Path(tmp) / 'canvases').glob('%d-*' % created['port']))
    project = json.loads((cdir / 'project.json').read_text())
    project['frames'] = frames
    project.pop('groupColumns', None)
    project.pop('notes', None)
    project.pop('flow_start', None)
    shutil.rmtree(cdir / 'frames', ignore_errors=True)
    (cdir / 'frames').mkdir()
    (cdir / 'frames' / 'f01.html').write_text(F01)
    (cdir / 'frames' / 'f02.html').write_text(F02)
    for rev in revs:  # each revision listed is snapshotted; the last one stays live
        project['revision'] = rev
        (cdir / 'project.json').write_text(json.dumps(project, indent=2))
        if rev != revs[-1]:
            cli('snapshot', '--canvas', created['id'])
    return created, cdir


class FrameRef(test_server.ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frames = [{'id': 'f01', 'title': '01 Start', 'width': 390, 'height': 700, 'path': 'frames/f01.html'},
                  {'id': 'f02', 'title': '02 Next', 'width': 390, 'height': 700, 'path': 'frames/f02.html'},
                  {'id': 'f03', 'title': '03 A very long frame title that needs more than one line in the title bar', 'width': 390, 'height': 700, 'path': 'frames/f02.html'}]
        created, cls.cdir = setup_canvas(cls.cli, cls.tmp, 'Frame ref', frames, ['r1', 'r2', 'r3'])  # snapshots r1, r2; live r3
        cls.cid, cls.url = created['id'], 'http://127.0.0.1:%d' % created['port']
        bare, _ = setup_canvas(cls.cli, cls.tmp, 'No snapshots', frames, ['r1'])
        cls.bare_id, cls.bare_url = bare['id'], 'http://127.0.0.1:%d' % bare['port']
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

    def open(self, url=None, width=1440, height=900, locale='en-US', lan=True, **options):
        context = self.browser.new_context(locale=locale, viewport={'width': width, 'height': height}, **options)
        if lan:
            context.add_init_script(NO_CLIPBOARD)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        self.addCleanup(context.close)
        page.goto(url or self.url)
        page.wait_for_selector('#board>.frame .frame-ref', state='attached')
        page.wait_for_function("fetch('/api/snapshots').then(()=>true)")
        page.wait_for_timeout(400)  # /healthz and /api/snapshots answered
        return page

    def copied(self, page, count=1):
        page.wait_for_function('window.__copied.length >= %d' % count)
        return page.evaluate('window.__copied[%d]' % (count - 1))

    def expected(self, url, cid, rev, frame, title, history=False):
        # the snapshot line is always there when there is a snapshot; the link carries &rev only for a history version
        lines = ['UI Canvas frame reference', 'Canvas: %s/ (canvas id: %s)' % (url, shown_canvas_id(cid))]
        if rev:
            lines.append('Snapshot: %s' % rev)
        lines += ['Frame: %s (%s)' % (frame, title), 'Link: %s/#view=flow&frame=%s%s' % (url, frame, '&rev=' + rev if rev and history else '')]
        return '\n'.join(lines)

    def title_button(self, page, frame):
        return page.locator('#board>.frame[data-frame-id="%s"] > header.frame-title > button.frame-ref' % frame)

    # --- tile view -----------------------------------------------------------------------------------------------------
    def test_title_bar_button_copies_the_reference_with_the_newest_snapshot(self):
        page = self.open()
        self.assertEqual(page.locator('#board>.frame header.frame-title > button.frame-ref').count(), 3)
        self.assertEqual(page.locator('[data-comment] .frame-ref, .frame-ref[data-comment]').count(), 0)  # never inside a comment target
        button = self.title_button(page, 'f02')
        self.assertEqual(button.get_attribute('title'), 'Copy frame reference')
        self.assertEqual(button.get_attribute('aria-label'), 'Copy frame reference')
        button.click()
        self.assertEqual(self.copied(page), self.expected(self.url, self.cid, 'r2', 'f02', '02 Next'))  # r2 = newest snapshot, not the live r3
        self.assertEqual(page.inner_text('#toast'), 'Frame reference copied')
        self.assertEqual(page.locator('textarea:not(#comment-text)').count(), 0)  # helper textarea removed
        self.assertEqual(page.errors, [])

    def test_comment_mode_ignores_the_button(self):
        page = self.open()
        page.click('#annotate')
        self.assertTrue(page.evaluate("document.body.classList.contains('comment-mode')"))
        self.title_button(page, 'f01').click()
        self.assertIn('Frame: f01 (01 Start)', self.copied(page))
        self.assertFalse(page.evaluate("document.getElementById('editor').open"))
        self.assertEqual(page.locator('.comment-selected').count(), 0)
        self.assertEqual(page.inner_text('#toast'), 'Frame reference copied')
        page.click('#annotate')  # comment mode off: the button still copies instead of showing the demo hint
        self.title_button(page, 'f01').click()
        self.copied(page, 2)
        self.assertEqual(page.inner_text('#toast'), 'Frame reference copied')

    def test_button_stays_inside_the_title_bar_at_any_zoom(self):
        page = self.open()
        seen = set()
        for zoom in ('actual', 'out', 'out', 'out', 'out', 'out', 'out'):  # 100% down to the smallest zoom
            page.evaluate("(z)=>document.querySelector('#zoom-menu [data-zoom=\"'+z+'\"]').click()", zoom)
            page.wait_for_timeout(100)
            seen.add(page.inner_text('#zoom-value'))
            inside = page.evaluate("""() => [...document.querySelectorAll('#board>.frame>header.frame-title')].every(h => {
              const b = h.querySelector('.frame-ref').getBoundingClientRect(), r = h.getBoundingClientRect(), range = document.createRange();
              range.selectNodeContents(h.querySelector('h2'));
              const text = [...range.getClientRects()].every(t => t.right <= b.left + .5);  // the title (also a long, wrapped one) never runs under the button
              return b.width > 0 && b.left >= r.left - .5 && b.right <= r.right + .5 && b.top >= r.top - .5 && b.bottom <= r.bottom + .5 && text;
            })""")
            self.assertTrue(inside, page.inner_text('#zoom-value'))
        self.assertGreaterEqual(len(seen), 4, seen)

    def opacity(self, page, frame):
        return page.evaluate("(id)=>getComputedStyle(document.querySelector('#board>.frame[data-frame-id=\"'+id+'\"] .frame-ref')).opacity", frame)

    def test_button_shows_on_hover_and_keyboard_focus(self):
        page = self.open()
        page.mouse.move(2, 120)  # blank canvas
        self.assertEqual([self.opacity(page, f) for f in ('f01', 'f02')], ['0', '0'])
        for part in ('.phone', 'header.frame-title h2'):  # the frame tile or its title bar
            box = page.locator('#board>.frame[data-frame-id="f02"] %s' % part).bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + min(box['height'] / 2, 10))
            self.assertEqual(self.opacity(page, 'f02'), '1', part)
            self.assertEqual(self.opacity(page, 'f01'), '0', part)  # only the frame under the pointer
        page.mouse.move(2, 120)
        self.assertEqual(self.opacity(page, 'f02'), '0')
        page.keyboard.press('Shift')  # keyboard modality, then focus the button
        self.title_button(page, 'f01').evaluate('b => b.focus()')
        self.assertTrue(self.title_button(page, 'f01').evaluate("b => b.matches(':focus-visible')"))
        self.assertEqual(self.opacity(page, 'f01'), '1')
        self.assertEqual(page.inner_text('#flow-copy-ref'), 'Copy frame reference')  # the Flow view button is not hover-only

    def test_button_is_always_shown_without_hover(self):
        page = self.open(width=1024, height=768, is_mobile=True, has_touch=True)  # a touch tablet: (hover: none)
        self.assertTrue(page.evaluate("matchMedia('(hover: none)').matches"))
        self.assertEqual([self.opacity(page, f) for f in ('f01', 'f02', 'f03')], ['1', '1', '1'])

    def test_a_snapshot_taken_after_opening_is_picked_up(self):
        page = self.open()
        project = json.loads((self.cdir / 'project.json').read_text())
        try:
            self.cli('snapshot', '--canvas', self.cid)  # snapshots/r3
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_timeout(500)
            self.title_button(page, 'f01').click()
            self.assertIn('Snapshot: r3', self.copied(page))
        finally:
            shutil.rmtree(self.cdir / 'snapshots' / 'r3', ignore_errors=True)
            (self.cdir / 'project.json').write_text(json.dumps(project, indent=2))

    # --- history and Flow view -----------------------------------------------------------------------------------------
    def test_history_uses_the_rev_being_viewed(self):
        page = self.open()
        page.click('#history')
        page.locator('#history-menu .hm-item', has_text='r1').first.click()
        page.wait_for_function("document.body.classList.contains('history-mode')")
        self.title_button(page, 'f01').click()
        self.assertEqual(self.copied(page), self.expected(self.url, self.cid, 'r1', 'f01', '01 Start', history=True))
        page.click('#history-back')
        page.click('#history-leave-ok')
        page.wait_for_function("!document.body.classList.contains('history-mode')")
        self.title_button(page, 'f01').click()
        self.assertEqual(self.copied(page, 2), self.expected(self.url, self.cid, 'r2', 'f01', '01 Start'))  # back on the latest: no &rev
        self.assertEqual(page.errors, [])

    def test_flow_view_button_copies_the_screen_on_show(self):
        page = self.open()
        page.click('#view-flow')
        page.wait_for_function("document.getElementById('flow-frame-id').textContent==='f01'")
        self.assertTrue(page.locator('#flow-copy-ref').is_visible())
        self.assertEqual(page.inner_text('#flow-copy-ref'), 'Copy frame reference')
        page.click('#flow-copy-ref')
        self.assertEqual(self.copied(page), self.expected(self.url, self.cid, 'r2', 'f01', '01 Start'))
        page.locator('#board>.frame.flow-current .phone [data-goto="f02"]').click()
        page.wait_for_function("document.getElementById('flow-frame-id').textContent==='f02'")
        page.click('#flow-copy-ref')
        self.assertIn('Frame: f02 (02 Next)', self.copied(page, 2))
        self.assertEqual(page.errors, [])

    def test_flow_deep_link_into_history(self):
        page = self.open(self.url + '/#view=flow&frame=f02&rev=r1')
        page.wait_for_function("document.body.classList.contains('history-mode')&&document.getElementById('flow-frame-id').textContent==='f02'")
        page.click('#flow-copy-ref')
        self.assertEqual(self.copied(page), self.expected(self.url, self.cid, 'r1', 'f02', '02 Next', history=True))

    # --- no snapshot, secure context, language, phone page -------------------------------------------------------------
    def test_canvas_without_snapshots_has_no_rev(self):
        page = self.open(self.bare_url)
        self.title_button(page, 'f01').click()
        self.assertEqual(self.copied(page), self.expected(self.bare_url, self.bare_id, '', 'f01', '01 Start'))

    def test_secure_context_uses_the_async_clipboard(self):
        page = self.open(lan=False)
        page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=self.url)
        self.title_button(page, 'f02').click()
        page.wait_for_function("document.getElementById('toast').style.display==='block'")
        self.assertEqual(page.evaluate('navigator.clipboard.readText()'), self.expected(self.url, self.cid, 'r2', 'f02', '02 Next'))

    def test_chinese_text(self):
        self.cli('lang', 'auto')
        page = self.open(locale='zh-CN')
        self.assertEqual(self.title_button(page, 'f01').get_attribute('title'), '\u590d\u5236\u753b\u9762\u5f15\u7528')
        self.title_button(page, 'f01').click()
        self.assertEqual(self.copied(page), '\n'.join([
            'UI Canvas \u753b\u9762\u5f15\u7528',
            '\u753b\u5e03\uff1a%s/\uff08canvas id: %s\uff09' % (self.url, shown_canvas_id(self.cid)),
            '\u5feb\u7167\uff1ar2',
            '\u753b\u9762\uff1af01\uff0801 Start\uff09',
            '\u94fe\u63a5\uff1a%s/#view=flow&frame=f01' % self.url]))
        self.assertEqual(page.inner_text('#toast'), '\u5df2\u590d\u5236\u753b\u9762\u5f15\u7528')
        page.click('#history')
        page.locator('#history-menu .hm-item', has_text='r1').first.click()
        page.wait_for_function("document.body.classList.contains('history-mode')")
        page.click('#history-back')
        page.wait_for_selector('#history-leave[open]')
        self.assertEqual(page.inner_text('#history-leave-title'), '\u79bb\u5f00\u8fd9\u4e2a\u5386\u53f2\u7248\u672c\uff1f')
        label = page.inner_text('#history-leave-label')
        self.assertIn('r1', label)
        self.assertIn('\u4e0d\u4f1a\u5220\u9664', label)
        self.assertEqual(page.inner_text('#history-leave-cancel'), '\u53d6\u6d88')
        self.assertEqual(page.inner_text('#history-leave-ok'), '\u8fd4\u56de\u5f53\u524d\u7248\u672c')
        page.click('#history-leave-cancel')
        self.assertTrue(page.evaluate("document.body.classList.contains('history-mode')"))
        self.assertIn('rev=r1', page.evaluate('location.search'))

    def test_history_copy_link_opens_that_revision(self):
        self.cli('lang', 'en')
        try:
            page = self.open()
            self.assertTrue(page.locator('#history-banner').is_hidden())
            page.click('#history')
            page.locator('#history-menu .hm-item', has_text='r1').first.click()
            page.wait_for_function("document.body.classList.contains('history-mode')")
            self.assertEqual(page.inner_text('#history-banner-rev').strip(), 'r1')
            self.assertEqual(page.inner_text('#history-copy'), 'Copy link to this version')
            self.assertIn('r1 (history, read-only)', page.evaluate("document.querySelector('.brand p').textContent"))
            self.assertTrue(page.locator('#annotate').is_disabled())
            self.assertEqual(page.evaluate('location.href'), self.url + '/?rev=r1')
            self.assertTrue(page.evaluate("performance.getEntriesByType('resource').some(e=>e.name.includes('/api/snapshots/r1/project'))"))
            live = page.evaluate("fetch('/api/project').then(r=>r.json()).then(p=>p.revision)")
            self.assertEqual(live, 'r3')  # the page is showing r1, not the live revision
            page.click('#history-copy')
            page.wait_for_function("document.getElementById('history-copy').textContent==='Copied'")
            link = self.copied(page)
            self.assertEqual(link, self.url + '/?rev=r1')
            opened = self.open(link)
            opened.wait_for_function("document.body.classList.contains('history-mode')&&document.getElementById('history-banner-rev').textContent==='r1'")
            self.assertIn('r1 (history, read-only)', opened.evaluate("document.querySelector('.brand p').textContent"))
            self.assertNotIn('r3', opened.evaluate("document.querySelector('.brand p').textContent"))
            self.assertTrue(opened.locator('#annotate').is_disabled())
            opened.reload()
            opened.wait_for_selector('#board>.frame .frame-ref', state='attached')
            opened.wait_for_function("document.body.classList.contains('history-mode')&&document.getElementById('history-banner-rev').textContent==='r1'")
            opened.click('#history-back')
            opened.wait_for_selector('#history-leave[open]')
            self.assertEqual(opened.inner_text('#history-leave-title'), 'Leave this history version?')
            self.assertIn('r1', opened.inner_text('#history-leave-label'))
            self.assertIn('nothing is deleted', opened.inner_text('#history-leave-label'))
            self.assertTrue(opened.evaluate("document.body.classList.contains('history-mode')"))
            self.assertIn('rev=r1', opened.evaluate('location.search'))
            opened.click('#history-leave-cancel')
            opened.wait_for_function("!document.getElementById('history-leave').open")
            self.assertTrue(opened.evaluate("document.body.classList.contains('history-mode')"))
            self.assertIn('rev=r1', opened.evaluate('location.search'))
            opened.click('#history-back')
            opened.keyboard.press('Escape')
            opened.wait_for_function("!document.getElementById('history-leave').open")
            self.assertTrue(opened.evaluate("document.body.classList.contains('history-mode')"))
            self.assertEqual(opened.evaluate('location.search'), '?rev=r1')
            opened.click('#history-back')
            opened.click('#history-leave-ok')
            opened.wait_for_function("!document.body.classList.contains('history-mode')")
            self.assertEqual(opened.evaluate('location.search'), '')
            self.assertIn('r3', opened.evaluate("document.querySelector('.brand p').textContent"))
            # Flow: the copied link names the frame on screen and still pins r1.
            page.click('#view-flow')
            page.wait_for_function("document.getElementById('flow-frame-id').textContent==='f01'")
            page.click('#history-copy')
            page.wait_for_function("window.__copied.length>=2")
            flow_link = self.url + '/?rev=r1#view=flow&frame=f01&rev=r1'
            self.assertEqual(self.copied(page, 2), flow_link)
            self.assertEqual(page.evaluate('location.href'), flow_link)
            flow = self.open(flow_link)
            flow.wait_for_function("document.body.classList.contains('history-mode')&&document.body.classList.contains('flow-mode')&&document.getElementById('flow-frame-id').textContent==='f01'")
            self.assertEqual(flow.inner_text('#history-banner-rev').strip(), 'r1')
            self.assertEqual(flow.errors, [])
            self.assertEqual(page.errors, [])
        finally:
            self.cli('lang', 'auto')

    def test_rev_query_wins_and_a_bad_id_opens_the_current_version(self):
        self.cli('lang', 'en')
        try:
            pinned = self.open(self.url + '/?rev=r1#view=flow&frame=f02&rev=r2')
            pinned.wait_for_function("document.body.classList.contains('history-mode')&&document.getElementById('flow-frame-id').textContent==='f02'")
            self.assertEqual(pinned.inner_text('#history-banner-rev').strip(), 'r1')
            self.assertIn('rev=r1', pinned.evaluate('location.search'))
            self.assertIn('rev=r1', pinned.evaluate('location.hash'))
            bad = self.open(self.url + '/?rev=.hidden')
            bad.wait_for_function("!location.search.includes('rev=')")
            self.assertFalse(bad.evaluate("document.body.classList.contains('history-mode')"))
            self.assertIn('r3', bad.evaluate("document.querySelector('.brand p').textContent"))
            self.assertNotIn('history', bad.evaluate("document.querySelector('.brand p').textContent"))
            self.assertEqual(pinned.errors, [])
        finally:
            self.cli('lang', 'auto')

    def test_phone_page_is_unchanged(self):
        context = self.browser.new_context(locale='en-US', viewport={'width': 390, 'height': 800})
        self.addCleanup(context.close)
        m = context.new_page()
        m.goto(self.url + '/m/')
        m.wait_for_selector('#m-phone')
        self.assertEqual(m.locator('.frame-ref, #flow-copy-ref').count(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
