#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""i18n consistency checks: zh/en dictionaries aligned, every used key defined, no dead keys, English fallbacks in HTML match,
and no Chinese text outside the zh dictionary / zh docs / zh example. Pure stdlib; run: python3 tests/test_i18n.py"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DICT = json.loads((ROOT / 'assets' / 'i18n.json').read_text(encoding='utf-8'))
CJK = re.compile(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]')
PLACEHOLDER = re.compile(r'\{(\w+)\}')
SOURCES = ['assets/canvas.js', 'assets/canvas.html', 'assets/list.html', 'assets/mobile.html', 'assets/i18n.js',
           'scripts/canvas.py', 'scripts/export_ui.py']


def used_keys():
    keys = set()
    for name in SOURCES:
        text = (ROOT / name).read_text(encoding='utf-8')
        keys.update(re.findall(r'\btr\(\s*[\'"]([\w.]+)[\'"]', text))
        keys.update(re.findall(r'data-i18n(?:-[\w-]+)?="([\w.]+)"', text))
    return keys


class DictionaryTest(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(sorted(DICT), ['en', 'zh'])

    def test_keys_aligned(self):
        zh, en = set(DICT['zh']), set(DICT['en'])
        self.assertEqual(sorted(zh - en), [], 'keys missing in en')
        self.assertEqual(sorted(en - zh), [], 'keys missing in zh')

    def test_placeholders_aligned(self):
        for key in DICT['zh']:
            self.assertEqual(set(PLACEHOLDER.findall(DICT['zh'][key])), set(PLACEHOLDER.findall(DICT['en'][key])), key)

    def test_values_are_non_empty_strings(self):
        for lang in ('zh', 'en'):
            for key, value in DICT[lang].items():
                self.assertIsInstance(value, str, key)
                self.assertTrue(value.strip(), lang + ':' + key)

    def test_english_has_no_chinese(self):
        for key, value in DICT['en'].items():
            self.assertFalse(CJK.search(value), key + ': ' + value)

    def test_chinese_is_translated(self):
        untranslated = [key for key, value in DICT['zh'].items() if not CJK.search(value) and value == DICT['en'][key]
                        and not re.fullmatch(r'[\W\w]{0,3}', value) and key not in ('h.history', 'h.light', 'h.dark')]
        # a few strings are legitimately identical (product words, symbols); anything long must differ
        self.assertEqual([key for key in untranslated if len(DICT['zh'][key]) > 12], [])

    def test_used_keys_defined(self):
        missing = sorted(used_keys() - set(DICT['en']))
        self.assertEqual(missing, [], 'keys used in code but missing from assets/i18n.json')

    def test_no_dead_keys(self):
        dead = sorted(set(DICT['en']) - used_keys())
        self.assertEqual(dead, [], 'keys in assets/i18n.json that no code uses')

    def test_html_fallback_matches_english(self):
        """The English text baked into the HTML (shown before/without JS) must equal the en dictionary."""
        for name in ('assets/canvas.html', 'assets/list.html'):
            text = (ROOT / name).read_text(encoding='utf-8')
            for match in re.finditer(r'<(\w+)[^>]*?\sdata-i18n="([\w.]+)"[^>]*>([^<]*)</\1>', text):
                value = match.group(3).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                self.assertEqual(value, DICT['en'][match.group(2)], name + ' ' + match.group(2))


class NoStrayChineseTest(unittest.TestCase):
    ALLOWED = ('assets/i18n.json', 'README.zh-CN.md')
    ALLOWED_PREFIX = ('examples/zh/', 'docs/zh-CN/', '.git/')

    def test_chinese_only_where_expected(self):
        offenders = []
        for path in ROOT.rglob('*'):
            if not path.is_file() or path.suffix in ('.png', '.jpg', '.gif', '.zip', '.pyc'):
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in self.ALLOWED or rel.startswith(self.ALLOWED_PREFIX) or '__pycache__' in rel:
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if CJK.search(line):
                    # the language picker labels each language in its own script
                    if rel == 'assets/list.html' and '<option value="zh">' in line:
                        continue
                    if rel == 'README.md' and 'README.zh-CN.md' in line:
                        continue  # link to the Chinese README, labelled in Chinese
                    if rel == 'docs/i18n.md' and 'Auto /' in line:
                        continue  # name of the Chinese option in the language selector
                    offenders.append('%s:%d' % (rel, number))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
