#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rename changes only the display name, in canvas.json and project.json together.

Empty names are rejected, surrounding whitespace is trimmed, and the directory,
port, canvas id, project id, revision and snapshots stay as they were.
Run: python3 tests/test_rename.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / 'scripts' / 'canvas.py')
os.environ.setdefault('UI_CANVAS_LANG', 'en')
sys.path.insert(0, str(ROOT / 'scripts'))
import canvas as canvas_mod  # noqa: E402


class RenameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='uic-rename-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        canvas_mod.ensure_runtime(self.tmp)

    def make_canvas(self, cid='1', port=4100, name='Old name', scheme='number', project_name=None, broken_project=False):
        entry = self.tmp / 'canvases' / ('%d-%s' % (port, cid))
        entry.mkdir(parents=True)
        meta = {'schema': 1, 'id': cid, 'name': name, 'project_path': '/tmp/design',
                'created_at': '2026-01-02T03:04:05+00:00'}
        if scheme:
            meta['id_scheme'] = scheme
        (entry / 'canvas.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
        project = {
            'id': 'project-%s' % cid,
            'name': name if project_name is None else project_name,
            'revision': 'r7',
            'columns': 3,
            'flow_start': 'home',
            'marker': {'keep': True},
            'frames': [{'id': 'home', 'title': 'Home', 'width': 390, 'height': 844, 'path': 'frames/home.html'}],
        }
        path = entry / 'project.json'
        if broken_project:
            path.write_text('{', encoding='utf-8')
        else:
            path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        snap = entry / 'snapshots' / 'r7'
        snap.mkdir(parents=True)
        (snap / 'project.json').write_text(json.dumps({'id': project['id'], 'name': 'Historical', 'revision': 'r7'}) + '\n', encoding='utf-8')
        (snap / 'frames').mkdir()
        (snap / 'frames' / 'home.html').write_text('<p>old</p>', encoding='utf-8')
        return entry

    def names(self, entry):
        return (json.loads((entry / 'canvas.json').read_text(encoding='utf-8'))['name'],
                json.loads((entry / 'project.json').read_text(encoding='utf-8'))['name'])

    def tree(self, entry):
        found = []
        for path in sorted(entry.rglob('*')):
            rel = path.relative_to(entry).as_posix()
            if path.is_symlink():
                kind = 'symlink'
            elif path.is_dir():
                kind = 'dir'
            else:
                kind = hashlib.sha256(path.read_bytes()).hexdigest()
            found.append((rel, kind))
        return found

    def test_trim_updates_both_files_and_leaves_identity(self):
        entry = self.make_canvas()
        before_tree = self.tree(entry)
        before_canvas = json.loads((entry / 'canvas.json').read_text(encoding='utf-8'))
        before_project = json.loads((entry / 'project.json').read_text(encoding='utf-8'))
        result = canvas_mod.rename_canvas(self.tmp, '  #1  ', '  \n New name \t ')
        self.assertEqual(result['name'], 'New name')
        self.assertEqual(result['id'], '1')
        self.assertEqual(result['display_id'], '#1')
        self.assertEqual(result['port'], 4100)
        self.assertEqual(result['dir'], '4100-1')
        self.assertEqual(result['project_id'], 'project-1')
        self.assertEqual(result['revision'], 'r7')
        self.assertEqual(self.names(entry), ('New name', 'New name'))
        canvas = json.loads((entry / 'canvas.json').read_text(encoding='utf-8'))
        project = json.loads((entry / 'project.json').read_text(encoding='utf-8'))
        self.assertEqual(canvas['id'], before_canvas['id'])
        self.assertEqual(canvas['id_scheme'], 'number')
        self.assertEqual(canvas['created_at'], before_canvas['created_at'])
        self.assertEqual(canvas['project_path'], before_canvas['project_path'])
        self.assertEqual(project['id'], before_project['id'])
        self.assertEqual(project['revision'], before_project['revision'])
        self.assertEqual(project['frames'], before_project['frames'])
        self.assertEqual(project['marker'], before_project['marker'])
        self.assertEqual(project['columns'], 3)
        self.assertEqual(entry.name, '4100-1')
        self.assertTrue(entry.is_dir())
        after = dict(self.tree(entry))
        before = dict(before_tree)
        self.assertEqual(set(after), set(before))
        for rel, kind in before.items():
            if rel in ('canvas.json', 'project.json'):
                continue
            self.assertEqual(after[rel], kind, rel)
        self.assertEqual(json.loads((entry / 'snapshots' / 'r7' / 'project.json').read_text(encoding='utf-8'))['name'], 'Historical')

    def test_empty_and_too_long_are_rejected_without_writes(self):
        entry = self.make_canvas()
        before = self.tree(entry)
        for bad in ('', '   ', '\n\t', None, 12, 'x' * (canvas_mod.NAME_MAX + 1)):
            with self.assertRaises(canvas_mod.CanvasError):
                canvas_mod.rename_canvas(self.tmp, '1', bad)
            self.assertEqual(self.names(entry), ('Old name', 'Old name'))
        self.assertEqual(self.tree(entry), before)
        trimmed = '  ' + ('n' * canvas_mod.NAME_MAX) + '  '
        result = canvas_mod.rename_canvas(self.tmp, '1', trimmed)
        self.assertEqual(result['name'], 'n' * canvas_mod.NAME_MAX)
        self.assertEqual(self.names(entry), ('n' * canvas_mod.NAME_MAX, 'n' * canvas_mod.NAME_MAX))
        self.assertEqual(result['dir'], '4100-1')
        self.assertEqual(result['revision'], 'r7')

    def test_internal_whitespace_is_kept(self):
        entry = self.make_canvas()
        canvas_mod.rename_canvas_files(entry, '  a  b  ')
        self.assertEqual(self.names(entry), ('a  b', 'a  b'))

    def test_broken_project_does_not_change_canvas_json(self):
        entry = self.make_canvas(broken_project=True)
        canvas_bytes = (entry / 'canvas.json').read_bytes()
        with self.assertRaises(canvas_mod.CanvasError) as caught:
            canvas_mod.rename_canvas(self.tmp, '1', 'Nope')
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual((entry / 'canvas.json').read_bytes(), canvas_bytes)
        self.assertEqual((entry / 'project.json').read_text(encoding='utf-8'), '{')
        self.assertFalse((entry / 'snapshots' / 'r8').exists())

    def test_symlink_project_is_refused(self):
        entry = self.make_canvas()
        outside = self.tmp / 'outside.json'
        outside.write_text(json.dumps({'id': 'x', 'name': 'outside', 'revision': 'r0'}) + '\n', encoding='utf-8')
        project = entry / 'project.json'
        project.unlink()
        project.symlink_to(outside)
        canvas_bytes = (entry / 'canvas.json').read_bytes()
        with self.assertRaises(canvas_mod.CanvasError):
            canvas_mod.rename_canvas_files(entry, 'Hijack')
        self.assertEqual((entry / 'canvas.json').read_bytes(), canvas_bytes)
        self.assertEqual(json.loads(outside.read_text(encoding='utf-8'))['name'], 'outside')

    def test_canvas_write_failure_rolls_project_back(self):
        entry = self.make_canvas()
        project_bytes = (entry / 'project.json').read_bytes()
        canvas_bytes = (entry / 'canvas.json').read_bytes()
        real = canvas_mod.write_json_atomic

        def wrapped(path, data):
            if path.name == 'canvas.json':
                raise OSError('disk full')
            return real(path, data)

        with mock.patch.object(canvas_mod, 'write_json_atomic', side_effect=wrapped):
            with self.assertRaises(canvas_mod.CanvasError):
                canvas_mod.rename_canvas_files(entry, 'Half')
        self.assertEqual((entry / 'project.json').read_bytes(), project_bytes)
        self.assertEqual((entry / 'canvas.json').read_bytes(), canvas_bytes)

    def test_mismatched_canvas_id_is_refused(self):
        entry = self.make_canvas()
        meta = json.loads((entry / 'canvas.json').read_text(encoding='utf-8'))
        meta['id'] = '999'
        (entry / 'canvas.json').write_text(json.dumps(meta), encoding='utf-8')
        project_bytes = (entry / 'project.json').read_bytes()
        with self.assertRaises(canvas_mod.CanvasError):
            canvas_mod.rename_canvas_files(entry, 'Nope')
        self.assertEqual((entry / 'project.json').read_bytes(), project_bytes)
        self.assertEqual(json.loads((entry / 'canvas.json').read_text(encoding='utf-8'))['name'], 'Old name')

    def test_legacy_id_and_directory_stay(self):
        entry = self.make_canvas(cid='abc123', port=4200, scheme=None, name='Legacy')
        result = canvas_mod.rename_canvas(self.tmp, 'abc123', 'Legacy renamed')
        self.assertEqual((result['id'], result['display_id'], result['port'], result['dir']),
                         ('abc123', 'abc123', 4200, '4200-abc123'))
        self.assertEqual(self.names(entry), ('Legacy renamed', 'Legacy renamed'))
        self.assertEqual(entry.name, '4200-abc123')

    def test_cli_rename(self):
        entry = self.make_canvas(name='Cli')
        env = dict(os.environ, UI_CANVAS_RUNTIME=str(self.tmp), UI_CANVAS_LANG='en', LC_ALL='C', LANG='C')
        env.pop('UI_CANVAS_BIND', None)
        ok = subprocess.run([sys.executable, SCRIPT, 'rename', '--canvas', '#1', '--name', '  From cli  '],
                            env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        body = json.loads(ok.stdout)
        self.assertEqual(body['name'], 'From cli')
        self.assertEqual(body['dir'], '4100-1')
        self.assertEqual(body['port'], 4100)
        self.assertEqual(body['id'], '1')
        self.assertEqual(body['revision'], 'r7')
        self.assertEqual(self.names(entry), ('From cli', 'From cli'))
        bad = subprocess.run([sys.executable, SCRIPT, 'rename', '--canvas', '1', '--name', '   '],
                             env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn('1–100', bad.stderr)
        self.assertEqual(self.names(entry), ('From cli', 'From cli'))
        listed = json.loads(subprocess.run([sys.executable, SCRIPT, 'list'], env=env, capture_output=True, text=True, timeout=30, check=True).stdout)
        row = listed['canvases'][0]
        self.assertEqual(row['name'], 'From cli')
        self.assertEqual(row['dir'], '4100-1')
        self.assertEqual(row['port'], 4100)
        self.assertEqual(row['id'], '1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
