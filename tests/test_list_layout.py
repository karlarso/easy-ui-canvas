#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Static checks for the list page narrow layout. Live behavior is in browser_list_layout.py.
Run: python3 tests/test_list_layout.py"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'assets' / 'list.html').read_text(encoding='utf-8')


def media_blocks(html):
    blocks = []
    for match in re.finditer(r'@media\s*\(\s*max-width:\s*(\d+px)\s*\)\s*\{', html):
        index = match.end()
        depth = 1
        while index < len(html) and depth:
            if html[index] == '{':
                depth += 1
            elif html[index] == '}':
                depth -= 1
            index += 1
        blocks.append((match.group(1), html[match.end():index - 1]))
    return blocks


class ListLayoutMarkupTest(unittest.TestCase):
    def test_single_narrow_breakpoint(self):
        self.assertEqual([width for width, _ in media_blocks(HTML)], ['700px'])

    def test_narrow_swaps_table_for_cards(self):
        block = re.sub(r'\s+', '', media_blocks(HTML)[0][1])
        self.assertIn('#table{display:none}', block)
        self.assertIn('#cards{display:flex', block)
        wide = re.sub(r'\s+', '', HTML.split('@media', 1)[0])
        self.assertIn('#cards{display:none}', wide)
        self.assertIn('id="table"', HTML)
        self.assertIn('id="cards"', HTML)
        self.assertIn('l.colCreated', HTML)

    def test_touch_targets_more_menu_and_existing_actions(self):
        compact = re.sub(r'\s+', '', HTML)
        self.assertIn('.card-actions .primary{', HTML)
        self.assertIn('min-height:44px', HTML)
        self.assertIn('.menu[hidden]{display:none}', compact)
        self.assertIn("previewControl(c,'primary')", HTML)
        self.assertNotIn("el('a','primary',tr('l.open'))", HTML)
        self.assertIn("tr('l.open'", HTML)
        self.assertIn("tr('l.start'", HTML)
        self.assertIn("tr('l.more'", HTML)
        self.assertIn("renameCanvas(c)", HTML)
        self.assertNotIn('l.renameMissing', HTML)
        self.assertIn("tr('l.cardMeta'", HTML)
        self.assertIn('window.confirm(text)', HTML)
        self.assertIn('window.prompt(', HTML)
        self.assertIn("'/rename'", HTML)
        self.assertNotIn('float:right', compact)
        self.assertIn("'/start'", HTML)
        self.assertIn("'/stop'", HTML)
        self.assertIn("'DELETE'", HTML)
        self.assertIn('class="head-bar"', HTML)
        self.assertIn('data-i18n="l.aboutSecurity"', HTML)
        self.assertIn('class="footer-about"', HTML)


if __name__ == '__main__':
    unittest.main(verbosity=2)
