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
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
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
        for bad in ('', '#', '0', '01', '#01', 'ABC123', 'ab', '#1a', '1.2', '-1', '#abc123', '12-3', '# 1', '# 12', '#\t1'):
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
        with self.assertRaises(canvas_mod.CanvasError) as hashed:
            canvas_mod.find_canvas(runtime, '#234567')
        self.assertEqual(hashed.exception.status, 400)
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

    def test_missing_hashed_id_keeps_the_hash_in_the_error(self):
        runtime = self.runtime()
        for missing in ('#100000', '#234567'):
            with self.assertRaises(canvas_mod.CanvasError) as caught:
                canvas_mod.find_canvas(runtime, missing)
            self.assertEqual(caught.exception.status, 404)
            self.assertIn(missing, str(caught.exception))

    def test_seq_read_error_does_not_reset_the_counter(self):
        runtime = self.runtime()
        seq = runtime / 'run' / 'canvas.seq'
        seq.write_text('7\n')
        real = Path.read_text

        def boom(self, *args, **kwargs):
            if self == seq:
                raise PermissionError('canvas.seq')
            return real(self, *args, **kwargs)

        with mock.patch.object(Path, 'read_text', boom):
            with self.assertRaises(PermissionError):
                canvas_mod.allocate_canvas_id(runtime)
        self.assertEqual(seq.read_text().strip(), '7')
        seq.write_bytes(b'\xff')
        with self.assertRaises(UnicodeError):
            canvas_mod.allocate_canvas_id(runtime)
        self.assertEqual(seq.read_bytes(), b'\xff')
        self.assertEqual(canvas_mod._read_seq(runtime / 'run' / 'no-such-seq'), 0)

    def test_stale_seq_tmp_is_removed_and_short_writes_finish(self):
        runtime = self.runtime()
        dead = 1 << 22
        while canvas_mod.pid_alive(dead):
            dead += 1
        stale = runtime / 'run' / ('.canvas.seq.tmp-%d' % dead)
        stale.write_text('stale')
        live = runtime / 'run' / '.canvas.seq.tmp-1' if canvas_mod.pid_alive(1) else None
        if live is not None:
            live.write_text('keep')
        real = os.write

        def short(fd, data):
            raw = data.tobytes() if isinstance(data, memoryview) else data
            if isinstance(raw, bytes) and raw.endswith(b'\n') and raw[:-1].isdigit() and len(raw) > 1:
                return real(fd, raw[:1])
            return real(fd, data)

        with mock.patch.object(canvas_mod.os, 'write', short):
            self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '1')
        self.assertFalse(stale.exists())
        self.assertEqual((runtime / 'run' / 'canvas.seq').read_text().strip(), '1')
        if live is not None:
            self.assertTrue(live.is_file())

    def test_zero_length_write_raises_and_drops_the_tmp(self):
        runtime = self.runtime()
        real = os.write

        def zero(fd, data):
            raw = data.tobytes() if isinstance(data, memoryview) else data
            if isinstance(raw, bytes) and raw.endswith(b'\n') and raw[:-1].isdigit():
                return 0
            return real(fd, data)

        with mock.patch.object(canvas_mod.os, 'write', zero):
            with self.assertRaises(OSError):
                canvas_mod.allocate_canvas_id(runtime)
        self.assertFalse(list((runtime / 'run').glob('.canvas.seq.tmp-*')))
        self.assertFalse((runtime / 'run' / 'canvas.seq').exists())

    def test_fullfsync_is_requested_on_darwin(self):
        runtime = self.runtime()
        calls = []

        class Fcntl:
            F_FULLFSYNC = 51

            @staticmethod
            def fcntl(fd, op):
                calls.append(op)

        fd = os.open(str(runtime / 'run' / 'fsync-probe'), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            os.write(fd, b'x')
            with mock.patch.object(canvas_mod.sys, 'platform', 'darwin'), mock.patch.object(canvas_mod, 'fcntl', Fcntl()):
                canvas_mod._fsync_file(fd)
        finally:
            os.close(fd)
        self.assertEqual(calls, [51])

    def test_junk_dir_is_hidden_and_does_not_consume_a_number(self):
        runtime = self.runtime()
        (runtime / 'canvases' / '2024-10').mkdir()
        self.assertEqual(canvas_mod.scan_canvases(runtime), [])
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '1')
        partial = runtime / 'canvases' / '2025-9'
        partial.mkdir()
        (partial / 'project.json').write_text('{}')
        records = canvas_mod.scan_canvases(runtime)
        self.assertEqual([item['id'] for item in records], ['9'])
        self.assertTrue(records[0]['metadata_missing'])
        self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '10')

    def test_scan_orders_by_number_then_legacy_id(self):
        runtime = self.runtime()
        self.publish('2', closed_port())
        self.publish('10', closed_port())
        self.publish('1', closed_port())
        self.publish('abc123', closed_port(), scheme=None)
        self.publish('234567', closed_port(), scheme=None)
        self.assertEqual([item['id'] for item in canvas_mod.scan_canvases(runtime)], ['1', '2', '10', '234567', 'abc123'])

    def test_unreadable_trash_does_not_fail_allocation(self):
        runtime = self.runtime()
        (runtime / 'run' / 'canvas.seq').write_text('5\n')
        real = Path.iterdir

        def boom(self):
            if self.name == 'trash':
                raise OSError('trash unreadable')
            return real(self)

        with mock.patch.object(Path, 'iterdir', boom):
            self.assertEqual(canvas_mod.allocate_canvas_id(runtime), '6')

    def test_missing_seq_does_not_ignore_a_listing_error(self):
        runtime = self.runtime()
        seq = runtime / 'run' / 'canvas.seq'
        if seq.exists():
            seq.unlink()
        real = Path.iterdir

        def boom(self):
            if self.name == 'trash':
                raise OSError('trash unreadable')
            return real(self)

        with mock.patch.object(Path, 'iterdir', boom):
            with self.assertRaises(OSError):
                canvas_mod.allocate_canvas_id(runtime)
        self.assertFalse(seq.exists())

    def test_find_canvas_ignores_a_hand_made_directory(self):
        runtime = self.runtime()
        (runtime / 'canvases' / '2024-10').mkdir()
        with self.assertRaises(canvas_mod.CanvasError) as caught:
            canvas_mod.find_canvas(runtime, '10')
        self.assertEqual(caught.exception.status, 404)
        real = self.publish('10', closed_port())
        self.assertEqual(canvas_mod.find_canvas(runtime, '10'), real)
        self.assertEqual(canvas_mod.find_canvas(runtime, '#10'), real)

    def test_pin_replaces_files_left_by_another_version(self):
        runtime = self.runtime()
        stale = runtime / 'run' / 'app-pin' / 'scripts' / 'obsolete.py'
        stale.parent.mkdir(parents=True)
        stale.write_text('old')
        (runtime / 'run' / 'app-pin' / 'VERSION').write_text('not-this-version\n')
        canvas_mod.pin_app(runtime)
        self.assertFalse(stale.exists())
        self.assertTrue(canvas_mod.script_supports_numbered_ids(runtime / 'run' / 'app-pin' / 'scripts' / 'canvas.py'))

    def test_pin_failure_is_logged_and_does_not_raise(self):
        runtime = self.runtime()
        with mock.patch.object(canvas_mod, 'pin_app', side_effect=OSError('disk full')):
            self.assertIsNone(canvas_mod.try_pin_app(runtime))
        self.assertIn('pin_app failed', (runtime / 'logs' / 'list.log').read_text(encoding='utf-8'))
        self.assertIn('disk full', (runtime / 'logs' / 'list.log').read_text(encoding='utf-8'))

    def test_restart_that_comes_back_without_number_is_an_error(self):
        runtime = self.runtime()
        old = {'service': 'ui-canvas-list', 'pid': 4242, 'runtime': str(runtime), 'version': 'old',
               'port': 9, 'bind': '127.0.0.1'}
        with mock.patch.object(canvas_mod, 'probe_list', return_value=('ok', old)), \
                mock.patch.object(canvas_mod, 'launchd_loaded', return_value=False), \
                mock.patch.object(canvas_mod, 'listening_pid', return_value=4242), \
                mock.patch.object(canvas_mod, 'process_args', return_value='python canvas.py list-serve'), \
                mock.patch.object(canvas_mod, 'terminate_pid', return_value=True) as terminate, \
                mock.patch.object(canvas_mod, 'sync_app', return_value='new'):
            with self.assertRaises(canvas_mod.CanvasError) as caught:
                canvas_mod.ensure_list(runtime, 9, '127.0.0.1', wait=0.4)
        self.assertEqual(caught.exception.code, 'listStillUnnumbered')
        self.assertEqual(caught.exception.status, 409)
        terminate.assert_called()

    def test_marker_is_a_source_literal(self):
        self.assertEqual(canvas_mod.ID_SCHEMES_MARKER, 'ui-canvas-id-schemes:' + ','.join(canvas_mod.ID_SCHEMES))
        self.assertIn(canvas_mod.ID_SCHEMES_MARKER, Path(SCRIPT).read_text(encoding='utf-8'))
        self.assertTrue(canvas_mod.script_supports_numbered_ids(SCRIPT))

    def test_capable_list_is_not_restarted_just_because_the_hash_differs(self):
        runtime = self.runtime()

        def fake_probe(port):
            return 'ok', {'service': 'ui-canvas-list', 'pid': 123, 'runtime': str(runtime), 'version': 'old-hash',
                          'port': port, 'id_schemes': ['legacy', 'number'], 'bind': '127.0.0.1'}

        with mock.patch.object(canvas_mod, 'probe_list', fake_probe), \
                mock.patch.object(canvas_mod, 'bundle_version', lambda base=None: 'new-hash'):
            result = canvas_mod.ensure_list(runtime, 4042, '127.0.0.1', restart_if_outdated=False)
        self.assertFalse(result['restarted'])
        self.assertEqual(result['pid'], 123)
        self.assertEqual(result['bind'], '127.0.0.1')

    def test_numbered_list_check_leaves_other_runtimes_alone(self):
        runtime = self.runtime()
        foreign = {'service': 'ui-canvas-list', 'pid': 5, 'runtime': str(runtime) + '-other', 'version': 'x', 'bind': '0.0.0.0'}
        with mock.patch.object(canvas_mod, 'probe_list', return_value=('ok', foreign)), \
                mock.patch.object(canvas_mod, 'ensure_list') as ensure:
            self.assertIsNone(canvas_mod.ensure_numbered_list(runtime, 4042, '127.0.0.1'))
            ensure.assert_not_called()
        with mock.patch.object(canvas_mod, 'probe_list', return_value=('refused', None)), \
                mock.patch.object(canvas_mod, 'ensure_list') as ensure:
            self.assertIsNone(canvas_mod.ensure_numbered_list(runtime, 4042, '127.0.0.1'))
            ensure.assert_not_called()
        same = {'service': 'ui-canvas-list', 'pid': 5, 'runtime': str(runtime), 'version': 'x', 'bind': '0.0.0.0'}
        with mock.patch.object(canvas_mod, 'probe_list', return_value=('ok', same)), \
                mock.patch.object(canvas_mod, 'ensure_list', return_value={'restarted': True}) as ensure:
            canvas_mod.ensure_numbered_list(runtime, 4042, '127.0.0.1')
            ensure.assert_called_once_with(runtime, 4042, '0.0.0.0', restart_if_outdated=False)


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


def _http(url, method='GET', body=None, headers=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8', 'replace')
    except urllib.error.URLError as error:
        return 0, str(error.reason)


def _wait_list(port, timeout=20):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, body = _http('http://127.0.0.1:%d/healthz' % port, timeout=2)
        last = (status, body)
        if status == 200:
            try:
                data = json.loads(body)
            except ValueError:
                data = None
            if isinstance(data, dict) and data.get('service') == 'ui-canvas-list':
                return data
        time.sleep(0.1)
    raise AssertionError('list healthz did not come up: %r' % (last,))


def _kill(pid):
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def _old_skill(dest):
    """A base-revision skill tree: main's canvas.py plus this tree's assets."""
    script = dest / 'scripts' / 'canvas.py'
    script.parent.mkdir(parents=True)
    script.write_bytes(subprocess.check_output(['git', '-C', str(ROOT), 'show', 'main:scripts/canvas.py']))
    (dest / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
    return script


class OldListUpgradeTest(unittest.TestCase):
    """The reviewer's upgrade repro: a base list service, then this tree's `new`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='uic-upgrade-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pids = []
        self.procs = []
        self.addCleanup(self._stop_pids)
        self.runtime = self.tmp / 'runtime'
        self.runtime.mkdir()
        self.list_port = test_server.free_block(14)
        self.old_script = _old_skill(self.tmp / 'old-skill')
        self.assertNotIn(canvas_mod.ID_SCHEMES_MARKER, self.old_script.read_text(encoding='utf-8'))

    def _stop_pids(self):
        for pid in self.pids:
            _kill(pid)
        for proc in self.procs:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)

    def _env(self):
        env = dict(os.environ, UI_CANVAS_RUNTIME=str(self.runtime), UI_CANVAS_LIST_PORT=str(self.list_port),
                   UI_CANVAS_PORT_RANGE='%d-%d' % (self.list_port + 1, self.list_port + 6),
                   UI_CANVAS_LANG='en', LC_ALL='C', LANG='C')
        env.pop('UI_CANVAS_BIND', None)
        return env

    def _start_old_list(self):
        log_path = self.tmp / 'old-list.log'
        log = open(log_path, 'ab')
        self.addCleanup(log.close)
        proc = subprocess.Popen(
            [sys.executable, str(self.old_script), 'list-serve', '--runtime-dir', str(self.runtime),
             '--list-port', str(self.list_port), '--bind', '127.0.0.1'],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            env=dict(os.environ, UI_CANVAS_LANG='en', LC_ALL='C', LANG='C'))
        self.pids.append(proc.pid)
        self.procs.append(proc)
        try:
            return _wait_list(self.list_port)
        except AssertionError:
            raise AssertionError(log_path.read_text(encoding='utf-8', errors='replace')[-2000:])

    def _place(self, port, cid, scheme=None, name='Old'):
        entry = self.runtime / 'canvases' / ('%s-%s' % (port, cid))
        entry.mkdir(parents=True)
        meta = {'schema': 1, 'id': cid, 'name': name}
        if scheme:
            meta['id_scheme'] = scheme
        (entry / 'canvas.json').write_text(json.dumps(meta))
        return entry

    def _ids(self):
        status, body = _http('http://127.0.0.1:%d/api/canvases' % self.list_port)
        self.assertEqual(status, 200, body)
        return {item['id'] for item in json.loads(body)['canvases']}

    def _stop(self, cid):
        return _http('http://127.0.0.1:%d/api/canvases/%s/stop' % (self.list_port, cid), 'POST', {},
                     {'Origin': 'http://127.0.0.1:%d' % self.list_port})

    def test_new_restarts_an_old_list_that_cannot_see_numbered_canvases(self):
        self._place(19990, 'abc123', name='Legacy')
        self._place(19991, '1', scheme='number', name='Already numbered')
        before = self._start_old_list()
        self.pids.append(before['pid'])
        self.assertNotIn('id_schemes', before)
        self.assertEqual(self._ids(), {'abc123'})
        status, body = self._stop('1')
        self.assertEqual(status, 400, body)
        self.assertIn('Invalid canvas id', body)

        result = subprocess.run(
            [sys.executable, SCRIPT, 'new', '--name', 'Upgrade', '--runtime-dir', str(self.runtime),
             '--list-port', str(self.list_port)],
            env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        created = json.loads(result.stdout)
        self.pids.append(created.get('pid'))
        self.assertEqual(created['id'], '2')  # 1 was already on disk
        self.assertEqual(created.get('restarted_reason'), 'id_schemes')
        self.assertNotIn('Restarted the list service', result.stderr)

        after = _wait_list(self.list_port)
        self.pids.append(after['pid'])
        self.assertNotEqual(after['pid'], before['pid'])
        self.assertIn('number', after.get('id_schemes') or [])
        self.assertEqual(self._ids(), {'abc123', '1', '2'})
        status, body = self._stop('1')
        self.assertEqual(status, 200, body)
        stopped = json.loads(body)
        self.assertEqual(stopped['id'], '1')
        self.assertTrue(stopped.get('already_stopped'))

    def test_ensure_list_restarts_without_the_outdated_flag(self):
        self._place(19991, '1', scheme='number', name='Numbered')
        before = self._start_old_list()
        self.pids.append(before['pid'])
        result = subprocess.run(
            [sys.executable, SCRIPT, 'ensure-list', '--runtime-dir', str(self.runtime),
             '--list-port', str(self.list_port)],
            env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        reported = json.loads(result.stdout)
        self.assertTrue(reported['restarted'])
        self.assertEqual(reported.get('restarted_reason'), 'id_schemes')
        self.assertIn('number', reported.get('id_schemes') or [])
        self.assertNotIn('Restarted the list service', result.stderr)
        after = _wait_list(self.list_port)
        self.pids.append(after['pid'])
        self.assertNotEqual(after['pid'], before['pid'])
        self.assertIn('1', self._ids())
        status, body = self._stop('1')
        self.assertEqual(status, 200, body)

    def test_downgraded_app_still_serves_numbered_canvases_from_the_pin(self):
        ensured = subprocess.run(
            [sys.executable, SCRIPT, 'ensure-list', '--runtime-dir', str(self.runtime),
             '--list-port', str(self.list_port)],
            env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(ensured.returncode, 0, ensured.stdout + ensured.stderr)
        self.pids.append(json.loads(ensured.stdout).get('pid'))
        created_run = subprocess.run(
            [sys.executable, SCRIPT, 'new', '--name', 'Pinned', '--runtime-dir', str(self.runtime),
             '--list-port', str(self.list_port)],
            env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(created_run.returncode, 0, created_run.stdout + created_run.stderr)
        created = json.loads(created_run.stdout)
        self.pids.append(created.get('pid'))
        self.assertEqual((created['id'], created['display_id']), ('1', '#1'))
        status, body = self._stop('1')
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body).get('stopped'))

        app_script = self.runtime / 'app' / 'scripts' / 'canvas.py'
        pin_script = self.runtime / 'run' / 'app-pin' / 'scripts' / 'canvas.py'
        self.assertTrue(canvas_mod.script_supports_numbered_ids(pin_script))
        app_script.write_bytes(self.old_script.read_bytes())
        self.assertFalse(canvas_mod.script_supports_numbered_ids(app_script))
        self.assertTrue(canvas_mod.script_supports_numbered_ids(pin_script))

        status, body = _http('http://127.0.0.1:%d/api/canvases/1/start' % self.list_port, 'POST', {},
                             {'Origin': 'http://127.0.0.1:%d' % self.list_port}, timeout=40)
        self.assertEqual(status, 200, body)
        started = json.loads(body)
        health = json.loads(_http('http://127.0.0.1:%d/healthz' % started['port'])[1])
        self.pids.append(health.get('pid'))
        self.assertEqual(health.get('display_id'), '#1')
        self.assertIn('app-pin/scripts/canvas.py', canvas_mod.process_args(health.get('pid')))

    def test_concurrent_new_against_an_old_list_all_succeed(self):
        before = self._start_old_list()
        self.pids.append(before['pid'])
        low, high = self.list_port + 1, self.list_port + 12

        def one(name):
            env = self._env()
            env['UI_CANVAS_PORT_RANGE'] = '%d-%d' % (low, high)
            result = subprocess.run(
                [sys.executable, SCRIPT, 'new', '--name', name, '--runtime-dir', str(self.runtime),
                 '--list-port', str(self.list_port)],
                env=env, capture_output=True, text=True, timeout=90)
            return result.returncode, result.stdout, result.stderr

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(one, ['N%d' % i for i in range(6)]))
        ids = []
        for code, out, err in results:
            self.assertEqual(code, 0, out + err)
            self.assertNotIn('listOldUnknown', out + err)
            created = json.loads(out)
            self.pids.append(created.get('pid'))
            ids.append(created['id'])
        self.assertEqual(sorted(ids, key=int), [str(i) for i in range(1, 7)])
        after = _wait_list(self.list_port)
        self.pids.append(after['pid'])
        self.assertIn('number', after.get('id_schemes') or [])

    def test_concurrent_ensure_list_against_an_old_list(self):
        before = self._start_old_list()
        self.pids.append(before['pid'])

        def one(_index):
            result = subprocess.run(
                [sys.executable, SCRIPT, 'ensure-list', '--runtime-dir', str(self.runtime),
                 '--list-port', str(self.list_port)],
                env=self._env(), capture_output=True, text=True, timeout=60)
            return result.returncode, result.stdout, result.stderr

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(one, range(6)))
        restarted = 0
        for code, out, err in results:
            self.assertEqual(code, 0, out + err)
            self.assertNotIn('listOldUnknown', out + err)
            reported = json.loads(out)
            self.pids.append(reported.get('pid'))
            self.assertIn('number', reported.get('id_schemes') or [])
            if reported.get('restarted'):
                restarted += 1
                self.assertEqual(reported.get('restarted_reason'), 'id_schemes')
        self.assertGreaterEqual(restarted, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
