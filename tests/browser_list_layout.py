#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Headless-browser check for the canvas list: a table when wide, cards at 390 and 320.
Needs `pip install playwright` and a Chromium/Chrome (env UIC_CHROME=/path/to/chrome); skips itself otherwise.
Run: python3 tests/browser_list_layout.py"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_server import ServerTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DICT = json.loads((ROOT / 'assets' / 'i18n.json').read_text(encoding='utf-8'))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('SKIP: playwright is not installed (optional)')
    sys.exit(0)


class ListLayoutBrowser(ServerTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cli('lang', 'en')
        cls.paused = json.loads(cls.cli('new', '--name', 'Paused'))
        cls.cli('stop', '--canvas', cls.paused['id'])
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

    def open_list(self, width, height):
        context = self.browser.new_context(locale='en-US', viewport={'width': width, 'height': height})
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda error: page.errors.append(str(error)))
        page.on('console', lambda msg: page.errors.append(msg.text) if msg.type == 'error' else None)
        self.addCleanup(context.close)
        page.goto(self.list_url + '/', wait_until='networkidle')
        page.wait_for_selector('#rows tr[data-id]', state='attached')
        if width <= 700:
            page.wait_for_selector('.card')
        else:
            page.wait_for_selector('#table')
        return page

    def assert_no_overflow(self, page):
        overflow = page.evaluate('''() => {
          const doc = document.documentElement, body = document.body;
          return doc.scrollWidth <= doc.clientWidth + 1 && body.scrollWidth <= body.clientWidth + 1;
        }''')
        self.assertTrue(overflow, 'page is wider than the viewport')

    def assert_header_clear(self, page):
        overlap = page.evaluate('''() => {
          const h1 = document.querySelector('h1').getBoundingClientRect();
          const lang = document.querySelector('.lang').getBoundingClientRect();
          return !(h1.bottom <= lang.top + 0.5 || lang.bottom <= h1.top + 0.5 || h1.right <= lang.left + 0.5 || lang.right <= h1.left + 0.5);
        }''')
        self.assertFalse(overlap, 'language control overlaps the title')

    def test_wide_table_narrow_cards(self):
        page = self.open_list(1100, 800)
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector("#table")).display'), 'table')
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector("#cards")).display'), 'none')
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector(".head-bar")).flexDirection'), 'row')
        self.assertNotEqual(page.evaluate('() => getComputedStyle(document.querySelector("#table th:nth-child(5)")).display'), 'none')
        self.assertGreater(page.locator('#rows .actions button, #rows .actions .mlink').count(), 0)
        self.assertEqual(page.locator('#rows .actions button', has_text='Rename').count(), 2)
        self.assertEqual(page.locator('#rows .menu').count(), 0)
        self.assertEqual(page.errors, [])

        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_selector('.card')
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector("#table")).display'), 'none')
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector("#cards")).display'), 'flex')
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector(".head-bar")).flexDirection'), 'column')
        self.assertEqual(page.locator('.card').count(), page.locator('#rows tr[data-id]').count())
        self.assert_no_overflow(page)
        self.assert_header_clear(page)
        self.assertTrue(page.evaluate('''() => {
          const s = document.querySelector('#summary');
          return getComputedStyle(s).whiteSpace === 'nowrap' && s.getBoundingClientRect().height < 28;
        }'''))
        self.assertEqual(page.evaluate('() => getComputedStyle(document.querySelector(".footer-full")).display'), 'none')
        self.assertFalse(page.locator('.footer-about p').is_visible())

        running = page.locator('.card', has_text='Smoke')
        stopped = page.locator('.card', has_text='Paused')
        self.assertEqual(running.locator('a.primary').inner_text().strip(), 'Open')
        self.assertIn(str(self.canvas_port), running.locator('a.primary').get_attribute('href'))
        self.assertIn(self.created['display_id'], running.locator('.meta').inner_text())
        self.assertIn(str(self.canvas_port), running.locator('.meta').inner_text())
        self.assertGreaterEqual(running.locator('a.primary').bounding_box()['height'], 44)
        self.assertGreaterEqual(running.locator('.more-btn').bounding_box()['height'], 44)
        self.assertEqual(stopped.locator('button.primary').inner_text().strip(), 'Start')
        self.assertGreaterEqual(stopped.locator('button.primary').bounding_box()['height'], 40)

        running.locator('.more-btn').click()
        self.assertTrue(running.locator('.menu').is_visible())
        self.assertEqual(running.locator('.menu a.item').inner_text().strip(), 'Mobile preview')
        self.assertTrue(running.locator('.menu button', has_text='Stop').is_enabled())
        self.assertTrue(running.locator('.menu button.danger').is_disabled())
        gap = page.evaluate('''() => {
          const card = [...document.querySelectorAll('.card')].find(node => node.textContent.includes('Smoke'));
          const stop = [...card.querySelectorAll('.menu button')].find(node => node.textContent.trim() === 'Stop');
          const remove = card.querySelector('.menu button.danger');
          return remove.getBoundingClientRect().top - stop.getBoundingClientRect().bottom;
        }''')
        self.assertGreaterEqual(gap, 8)
        self.assertGreaterEqual(running.locator('.menu button.danger').bounding_box()['height'], 44)
        self.assert_no_overflow(page)
        page.keyboard.press('Escape')
        self.assertTrue(running.locator('.menu').is_hidden())

        stopped.locator('.more-btn').click()
        self.assertEqual(stopped.locator('.menu .item.off').count(), 1)
        self.assertEqual(stopped.locator('.menu button', has_text='Stop').count(), 0)
        self.assertTrue(stopped.locator('.menu button.danger').is_enabled())
        self.assertGreaterEqual(stopped.locator('.menu button', has_text='Rename').bounding_box()['height'], 44)
        page.once('dialog', lambda dialog: dialog.accept('Held'))
        stopped.locator('.menu button', has_text='Rename').click()
        page.wait_for_function('''() => [...document.querySelectorAll('.card-title')].some(node => node.textContent.trim() === 'Held')''')
        held = page.locator('.card', has_text='Held')
        page.once('dialog', lambda dialog: dialog.accept('Paused'))
        held.locator('.more-btn').click()
        held.locator('.menu button', has_text='Rename').click()
        page.wait_for_function('''() => [...document.querySelectorAll('.card-title')].some(node => node.textContent.trim() === 'Paused')''')
        stopped = page.locator('.card', has_text='Paused')
        stopped.locator('.more-btn').click()
        with page.expect_event('dialog') as dialog_info:
            stopped.locator('.menu button.danger').click()
        dialog = dialog_info.value
        self.assertIn('Paused', dialog.message)
        dialog.dismiss()
        page.wait_for_timeout(300)
        self.assertEqual(stopped.count(), 1)

        page.set_viewport_size({'width': 320, 'height': 700})
        self.assert_no_overflow(page)
        self.assert_header_clear(page)
        self.assertGreaterEqual(page.locator('.card .primary').first.bounding_box()['height'], 44)
        self.assertEqual(page.errors, [])

    def test_start_and_stop_from_the_card(self):
        page = self.open_list(390, 844)
        stopped = page.locator('.card', has_text='Paused')
        stopped.locator('button.primary').click()
        page.wait_for_function('''() => {
          const card = [...document.querySelectorAll('.card')].find(node => node.textContent.includes('Paused'));
          return card && card.querySelector('.badge').textContent === 'Running';
        }''', timeout=20000)
        card = page.locator('.card', has_text='Paused')
        self.assertEqual(card.locator('a.primary').inner_text().strip(), 'Open')
        card.locator('.more-btn').click()
        card.locator('.menu button', has_text='Stop').click()
        page.wait_for_function('''() => {
          const card = [...document.querySelectorAll('.card')].find(node => node.textContent.includes('Paused'));
          return card && card.querySelector('.badge').textContent === 'Stopped';
        }''', timeout=20000)
        self.assertEqual(page.locator('.card', has_text='Paused').locator('button.primary').inner_text().strip(), 'Start')
        self.assertEqual(page.errors, [])

    def test_more_label_follows_language(self):
        self.set_lang('zh')
        try:
            page = self.open_list(390, 844)
            more = DICT['zh']['l.more']
            page.wait_for_function('(text) => document.querySelector(".more-btn").textContent === text', arg=more)
            literal = re.sub(r'\{[^}]+\}', '', DICT['zh']['l.cardMeta']).strip(' ·')
            self.assertIn(literal, page.locator('.card .meta').first.inner_text())
            self.assertEqual(page.errors, [])
        finally:
            self.set_lang('en')


if __name__ == '__main__':
    unittest.main(verbosity=2, defaultTest='ListLayoutBrowser')
