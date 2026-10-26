#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The list's agent guide: both languages name the same HTTP paths, and the list page links to it.
Run: python3 tests/test_agent_guide.py"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / 'assets' / 'agent.en.md').read_text(encoding='utf-8')
ZH = (ROOT / 'assets' / 'agent.zh.md').read_text(encoding='utf-8')
LIST = (ROOT / 'assets' / 'list.html').read_text(encoding='utf-8')
CJK = re.compile(r'[\u4e00-\u9fff]')

# Paths an agent must be able to find in either language. Keep the two guides in step.
MARKERS = (
    'GET <origin>/healthz',
    'GET <origin>/api/canvases',
    'POST <origin>/api/canvases/<id>/start',
    'POST <origin>/api/canvases/<id>/stop',
    'POST <origin>/api/canvases/<id>/rename',
    'DELETE <origin>/api/canvases/<id>',
    'POST <canvas-origin>/api/rename',
    '/m/',
    'data-ui-id',
    'data-goto',
    'data-keep-scroll',
    'other_revisions',
    'GET <canvas-origin>/api/export-ui',
    'HANDOFF.md',
    '?lang=en',
    '?lang=zh',
    'canvas.json',
    'project.json',
    'trash/',
    '--bind',
)


class AgentGuideTest(unittest.TestCase):
    def test_languages_share_the_api(self):
        self.assertFalse(CJK.search(EN), 'English guide must not contain Chinese')
        self.assertTrue(CJK.search(ZH))
        for marker in MARKERS:
            self.assertIn(marker, EN, marker)
            self.assertIn(marker, ZH, marker)

    def test_list_page_links_to_the_guide(self):
        self.assertIn('href="/agent"', LIST)
        self.assertIn('data-i18n="l.forAgents"', LIST)
        self.assertNotIn("previewControl(c,'for-agents')", LIST)
        handler = (ROOT / 'scripts' / 'canvas.py').read_text(encoding='utf-8')
        self.assertIn("path == '/agent.md'", handler)
        self.assertIn("'/agent'", handler)
        self.assertIn('text/markdown', handler)


if __name__ == '__main__':
    unittest.main(verbosity=2)
