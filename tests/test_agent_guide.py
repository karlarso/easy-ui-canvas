#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The list's agent guide: both languages name the same HTTP paths, and the list page links to it.
List-wide additional instructions append once, and a blank file leaves the guide unchanged.
Run: python3 tests/test_agent_guide.py"""
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('UI_CANVAS_LANG', 'en')
sys.path.insert(0, str(ROOT / 'scripts'))
import canvas as canvas_mod  # noqa: E402

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
    'AGENT.custom.md',
    'POST <origin>/api/agent-custom',
    '## Additional instructions',
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
        self.assertIn("'/api/agent-custom'", LIST)
        self.assertIn('id="agent-custom"', LIST)
        self.assertIn('data-i18n="l.agentCustom"', LIST)
        self.assertIn("AGENT_CUSTOM_HEADING = '## Additional instructions'", handler)
        self.assertIn('AGENT_CUSTOM_LIMIT = 64 * 1024', handler)
        self.assertLess(LIST.index('id="agent-custom-open"'), LIST.index('<main'))
        self.assertEqual(EN.count('\n## Additional instructions\n'), 0)
        self.assertEqual(ZH.count('\n## Additional instructions\n'), 0)

    def test_usage_skill_is_not_installed(self):
        """Everyday use is the live list guide. Deploy must not copy a usage skill into a tool."""
        self.assertFalse((ROOT / 'SKILL.md').exists())
        self.assertIn('Do not install a skill', EN)
        self.assertIn('SKILL.md', EN)
        self.assertIn('\u4e0d\u8981\u5b89\u88c5 skill', ZH)
        self.assertIn('SKILL.md', ZH)
        recipes = (
            'ln -s <INSTALL_DIR> <SKILL_DIR>',
            'cp -R <INSTALL_DIR>/SKILL.md',
            'test -f <SKILL_DIR>/SKILL.md',
            '<SKILL_DIR>',
            '**Q7.',
            '### 7.4',
        )
        for name in ('DEPLOY.md', 'DEPLOY.zh-CN.md', 'README.md', 'README.zh-CN.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            for recipe in recipes:
                self.assertNotIn(recipe, text, '%s still contains %s' % (name, recipe))
        deploy = (ROOT / 'DEPLOY.md').read_text(encoding='utf-8')
        self.assertIn('<list-origin>/agent.md', deploy)
        self.assertIn('id="skill-only-install"', deploy)
        self.assertIn('no longer installs anything', deploy)
        self.assertNotIn('Install the Easy UI Canvas skill', deploy)


class AgentCustomTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='uic-agent-custom-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_blank_custom_leaves_the_guide_unchanged(self):
        guide = 'Built-in guide.\n'
        for custom in (None, '', '   \n\t', ' \n '):
            self.assertEqual(canvas_mod.compose_agent_markdown(guide, custom), guide)
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp), ('missing', None))

    def test_section_is_appended_once_and_the_builtin_stays_a_prefix(self):
        guide = 'Built-in guide.\n'
        text = canvas_mod.compose_agent_markdown(guide, '  Prefer short labels.\n\nKeep the primary action first.  ')
        self.assertTrue(text.startswith(guide))
        self.assertEqual(text.count('\n## Additional instructions\n'), 1)
        self.assertTrue(text.endswith('## Additional instructions\n\nPrefer short labels.\n\nKeep the primary action first.\n'))
        again = canvas_mod.compose_agent_markdown(guide, 'Prefer short labels.\n\nKeep the primary action first.')
        self.assertEqual(text, again)

    def test_write_read_limit_symlink_and_runtime_keep(self):
        stored = canvas_mod.write_agent_custom(self.tmp, '  hello\n')
        self.assertEqual(stored, 'hello')
        self.assertEqual((self.tmp / 'AGENT.custom.md').read_bytes(), b'hello')
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp), ('ok', 'hello'))
        self.assertEqual(canvas_mod.write_agent_custom(self.tmp, ' \n\t'), '')
        self.assertFalse((self.tmp / 'AGENT.custom.md').exists())
        exact = 'y' * canvas_mod.AGENT_CUSTOM_LIMIT
        self.assertEqual(canvas_mod.write_agent_custom(self.tmp, exact), exact)
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp)[0], 'ok')
        with self.assertRaises(canvas_mod.CanvasError) as raised:
            canvas_mod.write_agent_custom(self.tmp, 'x' * (canvas_mod.AGENT_CUSTOM_LIMIT + 1))
        self.assertEqual(raised.exception.status, 413)
        self.assertEqual((self.tmp / 'AGENT.custom.md').read_bytes(), exact.encode())
        (self.tmp / 'AGENT.custom.md').write_bytes(b'z' * (canvas_mod.AGENT_CUSTOM_LIMIT + 1))
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp), ('toobig', None))
        self.assertEqual(canvas_mod.compose_agent_markdown('guide\n', None), 'guide\n')
        target = self.tmp / 'secret.md'
        target.write_text('secret', encoding='utf-8')
        link = self.tmp / 'AGENT.custom.md'
        link.unlink()
        link.symlink_to(target)
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp), ('missing', None))
        self.assertEqual(canvas_mod.write_agent_custom(self.tmp, 'visible'), 'visible')
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(encoding='utf-8'), 'visible')
        self.assertEqual(target.read_text(encoding='utf-8'), 'secret')
        (self.tmp / 'agent.custom.md').write_text('other case', encoding='utf-8')
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp), ('ok', 'visible'))
        canvas_mod.ensure_runtime(self.tmp)
        canvas_mod.sync_app(self.tmp)
        self.assertEqual((self.tmp / 'AGENT.custom.md').read_text(encoding='utf-8'), 'visible')
        self.assertTrue((self.tmp / 'app' / 'scripts' / 'canvas.py').is_file())
        link.unlink()
        (self.tmp / 'AGENT.custom.md').mkdir()
        self.assertEqual(canvas_mod.read_agent_custom(self.tmp)[0], 'missing')


if __name__ == '__main__':
    unittest.main(verbosity=2)
