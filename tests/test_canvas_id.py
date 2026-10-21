#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Canvas ids are monotonic numbers (#1, #2, …) per runtime directory.

Covers the counter file, flock under concurrent processes, no reuse after remove,
legacy 6-character ids (they still open and do not move the counter), and the CLI
forms `1` and `#1`. `#` is display-only and is rejected in a directory name.
Run: python3 tests/test_canvas_id.py
"""
import json
import multiprocessing
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / 'scripts' / 'canvas.py')
os.environ.setdefault('UI_CANVAS_LANG', 'en')
sys.path.insert(0, str(ROOT / 'scripts'))
import canvas as canvas_mod  # noqa: E402

sys.path.insert(0, str(ROOT / 'tests'))
import test_server  # noqa: E402


def _claim(script_and_runtime):
    """Allocate one id in a fresh interpreter. Used by the spawn pool."""
    script, runtime = script_and_runtime
    import importlib.util
    spec = importlib.util.spec_from_file_location('canvas_alloc', script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.allocate_canvas_id(Path(runtime))


def closed_port():
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class CanvasIdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='uic-id-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def runtime(self):
        canvas_mod.ensure_runtime(self.tmp)
        return self.tmp

    def publish(self, cid, port, scheme='number', name='T'):
        entry = self.runtime() / 'canvases' / ('%s-%s' % (port, cid))
        entry.mkdir(parents=True)
        meta = {'schema': 1, 'id': cid, 'name': name}
        if scheme:
            meta['id_scheme'] = scheme
        (entry / 'canvas.json').write_text(json.dumps(meta))
        return entry

    def test_normalize_and_display(self):
        self.assertEqual(canvas_mod.normalize_canvas_id('1'), '1')
        self.assertEqual(canvas_mod.normalize_canvas_id('#1'), '1')
        self.assertEqual(canvas_mod.normalize_canvas_id('  #12  '), '12')
        self.assertEqual(canvas_mod.normalize_canvas_id('abc123'), 'abc123')
        self.assertEqual(canvas_mod.normalize_canvas_id(unquote('%231')), '1')
        self.assertEqual(canvas_mod.display_canvas_id('1', 'number'), '#1')
        self.assertEqual(canvas_mod.display_canvas_id('1'), '#1')
        self.assertEqual(canvas_mod.display_canvas_id('100000', 'number'), '#100000')
        self.assertEqual(canvas_mod.display_canvas_id('234567'), '234567')
        self.assertEqual(canvas_mod.display_canvas_id('234567', 'number'), '#234567')
        self.assertEqual(canvas_mod.display_canvas_id('abc123'), 'abc123')
        for bad in ('', '#', '0', '01', '#01', 'ABC123', 'ab', '#1a', '1.2', '-1', '#abc123', '12-3'):
            with self.assertRaises(canvas_mod.CanvasError):
                canvas_mod.normalize_canvas_id(bad)

    def test_directory_pattern_rejects_hash(self):
        self.assertTrue(canvas_mod.DIR_RE.match('4100-1'))
        self.assertTrue(canvas_mod.DIR_RE.match('4100-100000'))
        self.assertTrue(canvas_mod.DIR_RE.match('4100-abc123'))
        self.assertFalse(canvas_mod.DIR_RE.match('4100-#1'))
        self.assertFalse(canvas_mod.DIR_RE.match('4100-01'))
        self.assertFalse(canvas_mod.DIR_RE.match('9-1'))
        self.assertEqual(canvas_mod.TRASH_CANVAS_RE.match('20261021-105300-4100-12-3').group(2), '12')
        self.assertEqual(canvas_mod.TRASH_CANVAS_RE.match('20261021-105300-4100-1').group(2), '1')
        self.assertEqual(canvas_mod.TRASH_CANVAS_RE.match('20261021-105300-4100-abc123').group(2), 'abc123')
        self.assertIsNone(canvas_mod.TRASH_CANVAS_RE.match('20261021-105300-com.easy-ui-canvas.list.plist'))

    def test_counter_is_monotonic_and_skips_taken_ids(self):
        runtime = self.runtime()
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '1')
        self.publish('1', closed_port())
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '2')
        self.assertEqual((runtime / 'run' / 'canvas.seq').read_text().strip(), '2')
        # A number present on disk but missing from the counter file is not issued again.
        (runtime / 'run' / 'canvas.seq').unlink()
        self.publish('4', closed_port())
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '5')

    def test_remove_does_not_reuse_even_if_trash_is_emptied_while_seq_remains(self):
        runtime = self.runtime()
        self.publish('1', closed_port())
        second = self.publish('2', closed_port())
        (runtime / 'run' / 'canvas.seq').write_text('2\n')
        removed = canvas_mod.remove_canvas(runtime, '#2')
        self.assertEqual(removed['id'], '2')
        self.assertEqual(removed['display_id'], '#2')
        self.assertFalse(second.exists())
        self.assertTrue(canvas_mod.TRASH_CANVAS_RE.match(Path(removed['trash']).name))
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '3')
        shutil.rmtree(runtime / 'trash')
        (runtime / 'trash').mkdir()
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '4')

    def test_lost_counter_file_still_sees_trash(self):
        runtime = self.runtime()
        self.publish('1', closed_port())
        trashed = self.publish('2', closed_port())
        target = runtime / 'trash' / ('20260101-000000-' + trashed.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(trashed, target)
        self.assertFalse((runtime / 'run' / 'canvas.seq').exists())
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '3')

    def test_legacy_ids_still_resolve_and_do_not_move_the_counter(self):
        runtime = self.runtime()
        legacy = self.publish('abc123', closed_port(), scheme=None, name='Legacy')
        digits = self.publish('234567', closed_port(), scheme=None, name='Digits')
        self.assertEqual(canvas_mod.find_canvas(runtime, 'abc123'), legacy)
        self.assertEqual(canvas_mod.find_canvas(runtime, '234567'), digits)
        with self.assertRaises(canvas_mod.CanvasError):
            canvas_mod.find_canvas(runtime, '#abc123')
        numbered = self.publish('7', closed_port())
        self.assertEqual(canvas_mod.find_canvas(runtime, '#7'), numbered)
        self.assertEqual(canvas_mod.find_canvas(runtime, '7'), numbered)
        # Neither legacy id is a sequence number. 234567 must not make the next id 234568.
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '8')
        # A numbered canvas that itself has 6 digits does move the counter.
        self.publish('100000', closed_port(), scheme='number')
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '100001')

    def test_half_created_temp_dir_is_not_reused(self):
        runtime = self.runtime()
        (runtime / 'canvases' / '.tmp-3').mkdir()
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '4')

    def test_counters_are_per_runtime(self):
        one = self.runtime()
        other = Path(tempfile.mkdtemp(prefix='uic-id-b-'))
        self.addCleanup(shutil.rmtree, other, True)
        canvas_mod.ensure_runtime(other)
        self.assertEqual(canvas_mod.allocate_canvas_id(one), '1')
        self.assertEqual(canvas_mod.allocate_canvas_id(other), '1')

    def test_seq_ahead_is_not_rewound(self):
        runtime = self.runtime()
        (runtime / 'run' / 'canvas.seq').write_text('20\n')
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '21')

    def test_corrupt_seq_falls_back_to_directories(self):
        runtime = self.runtime()
        (runtime / 'run' / 'canvas.seq').write_text('not-a-number\n')
        self.publish('4', closed_port())
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '5')

    def test_concurrent_processes_do_not_collide(self):
        runtime = self.runtime()
        ctx = multiprocessing.get_context('spawn')
        with ctx.Pool(8) as pool:
            ids = pool.map(_claim, [(SCRIPT, str(runtime))] * 8)
        self.assertEqual(sorted(ids, key=int), [str(i) for i in range(1, 9)])
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '9')

    def test_serve_rejects_a_hash_in_the_directory_name(self):
        bad = self.runtime() / 'canvases' / '4100-#1'
        bad.mkdir()
        result = subprocess.run([sys.executable, SCRIPT, 'serve', '--canvas-dir', str(bad), '--runtime-dir', str(self.tmp)],
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('#', result.stderr + result.stdout)


class CanvasIdCliTest(unittest.TestCase):
    def test_new_stop_remove_and_legacy_list(self):
        tmp = tempfile.mkdtemp(prefix='uic-id-cli-')
        base = test_server.free_block(6)
        env = dict(os.environ, UI_CANVAS_RUNTIME=tmp, UI_CANVAS_LIST_PORT=str(base),
                   UI_CANVAS_PORT_RANGE='%d-%d' % (base + 1, base + 5), UI_CANVAS_LANG='en',
                   LC_ALL='C', LANG='C')
        env.pop('UI_CANVAS_BIND', None)
        procs = []

        def cli(*args, check=True):
            result = subprocess.run([sys.executable, SCRIPT, *args], env=env, capture_output=True, text=True, timeout=60)
            if check and result.returncode != 0:
                raise AssertionError('canvas.py %s failed (%s): %s %s' % (' '.join(args), result.returncode, result.stdout, result.stderr))
            return result

        try:
            first = json.loads(cli('new', '--name', 'First').stdout)
            second = json.loads(cli('new', '--name', 'Second').stdout)
            procs.extend([first.get('pid'), second.get('pid')])
            self.assertEqual((first['id'], first['display_id']), ('1', '#1'))
            self.assertEqual((second['id'], second['display_id']), ('2', '#2'))
            self.assertNotIn('#', first['dir'])
            self.assertTrue(first['dir'].endswith('-1'))
            health = json.loads(test_server.http('http://127.0.0.1:%d/healthz' % first['port'])[1])
            self.assertEqual(health['id'], '1')
            self.assertEqual(health['display_id'], '#1')
            stopped = json.loads(cli('stop', '--canvas', '#2').stdout)
            self.assertEqual(stopped['id'], '2')
            self.assertTrue(stopped['stopped'])
            removed = json.loads(cli('remove', '--canvas', '#2', '--yes').stdout)
            self.assertEqual(removed['display_id'], '#2')
            third = json.loads(cli('new', '--name', 'Third').stdout)
            procs.append(third.get('pid'))
            self.assertEqual(third['id'], '3')
            self.assertEqual(Path(tmp, 'run', 'canvas.seq').read_text().strip(), '3')
            legacy = Path(tmp) / 'canvases' / '59999-abc123'
            legacy.mkdir()
            (legacy / 'canvas.json').write_text(json.dumps({'schema': 1, 'id': 'abc123', 'name': 'Legacy'}))
            digits = Path(tmp) / 'canvases' / '59998-234567'
            digits.mkdir()
            (digits / 'canvas.json').write_text(json.dumps({'schema': 1, 'id': '234567', 'name': 'Old digits'}))
            listed = {item['id']: item for item in json.loads(cli('list').stdout)['canvases']}
            self.assertEqual(set(listed), {'1', '3', 'abc123', '234567'})
            self.assertEqual(listed['1']['display_id'], '#1')
            self.assertEqual(listed['abc123']['display_id'], 'abc123')
            self.assertEqual(listed['234567']['display_id'], '234567')
            bad = cli('stop', '--canvas', 'nope', check=False)
            self.assertNotEqual(bad.returncode, 0)
            fourth = json.loads(cli('new', '--name', 'Fourth').stdout)
            procs.append(fourth.get('pid'))
            self.assertEqual(fourth['id'], '4')  # 234567 did not jump the counter
        finally:
            try:
                for item in json.loads(cli('list', check=False).stdout or '{"canvases":[]}').get('canvases', []):
                    cli('stop', '--canvas', item['id'], check=False)
            except Exception:
                pass
            for pid in procs:
                if isinstance(pid, int):
                    try:
                        os.kill(pid, 15)
                    except OSError:
                        pass
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
