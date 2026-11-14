#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Phone-preview addresses follow the sockets that were actually bound.

Wildcards (0.0.0.0, ::) are listen scope, never shareable links. A specific bind
does not pick up other interfaces. Discovery is injected here, so the unit cases
do not scan the network. One live server checks GET /api/preview-hosts.
Run: python3 tests/test_preview_hosts.py
"""
import importlib.util
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / 'scripts' / 'canvas.py'


def load_canvas():
    spec = importlib.util.spec_from_file_location('ui_canvas_preview', CANVAS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


canvas = load_canvas()


def addresses(payload):
    return [item['address'] for item in payload['addresses']]


class PreviewAddressTest(unittest.TestCase):
    def test_wildcard_v4_expands_only_concrete_local_rows(self):
        rows = canvas.concrete_preview_addresses(
            [{'address': '0.0.0.0', 'covers_v4': True}],
            [('100.64.0.8', 'tailscale'), ('192.168.1.20', 'lan'), ('0.0.0.0', 'explicit')],
            [('fd7a:115c:a1e0::8', 'tailscale'), ('fe80::1', 'lan')])
        self.assertEqual(addresses({'addresses': rows}), ['100.64.0.8', '192.168.1.20', '127.0.0.1'])
        self.assertEqual([item['access'] for item in rows], ['tailscale', 'lan', 'local-only'])
        self.assertNotIn('0.0.0.0', addresses({'addresses': rows}))
        self.assertNotIn('::', addresses({'addresses': rows}))

    def test_specific_bind_does_not_gain_other_interfaces(self):
        rows = canvas.concrete_preview_addresses(
            [{'address': '192.168.1.20', 'covers_v4': False}, {'address': '127.0.0.1', 'covers_v4': False}],
            [('192.168.1.20', 'lan'), ('10.0.0.5', 'lan'), ('100.64.0.2', 'tailscale')],
            [('fd7a:115c:a1e0::8', 'tailscale')])
        self.assertEqual(addresses({'addresses': rows}), ['192.168.1.20', '127.0.0.1'])
        self.assertEqual(rows[0]['access'], 'lan')
        self.assertEqual(rows[1]['access'], 'local-only')

    def test_ipv6_wildcard_scope_and_brackets_source(self):
        v6_only = canvas.concrete_preview_addresses(
            [{'address': '::', 'covers_v4': False}],
            [('192.168.1.5', 'lan')],
            [('fd7a:115c:a1e0::2', 'tailscale'), ('fe80::abcd', 'lan'), ('::', 'explicit')])
        self.assertEqual(addresses({'addresses': v6_only}), ['fd7a:115c:a1e0::2', '::1'])
        self.assertEqual([item['access'] for item in v6_only], ['tailscale', 'local-only'])
        dual = canvas.concrete_preview_addresses(
            [{'address': '::', 'covers_v4': True}],
            [('192.168.1.5', 'lan'), ('0.0.0.0', 'explicit')],
            [('2001:db8::5', 'explicit')])
        self.assertEqual(addresses({'addresses': dual}), ['192.168.1.5', '2001:db8::5', '127.0.0.1', '::1'])
        self.assertNotIn('::', addresses({'addresses': dual}))
        self.assertNotIn('0.0.0.0', addresses({'addresses': dual}))

    def test_specific_ipv6_bind_is_that_address_only(self):
        rows = canvas.concrete_preview_addresses(
            [{'address': 'fd7a:115c:a1e0::9', 'covers_v4': False}],
            [('192.168.1.5', 'lan')],
            [('fd7a:115c:a1e0::9', 'tailscale'), ('2001:db8::1', 'explicit')])
        self.assertEqual(rows, [{'address': 'fd7a:115c:a1e0::9', 'access': 'tailscale'}])

    def test_discovery_failure_on_wildcard_keeps_loopback_and_says_so(self):
        def boom(_listeners):
            raise OSError('lookup failed')
        payload = canvas.preview_hosts_payload([{'address': '0.0.0.0', 'covers_v4': True}], 4100, discover=boom)
        self.assertEqual(payload['discovery'], 'failed')
        self.assertEqual(payload['listeners'][0]['address'], '0.0.0.0')
        self.assertEqual(payload['addresses'], [{'address': '127.0.0.1', 'access': 'local-only'}])
        self.assertNotIn('0.0.0.0', addresses(payload))

    def test_failed_lookup_still_returns_the_specific_binds(self):
        def boom(_listeners):
            raise OSError('lookup failed')
        payload = canvas.preview_hosts_payload(
            [{'address': '10.1.2.3', 'covers_v4': False}, {'address': '127.0.0.1', 'covers_v4': False}],
            9, discover=boom)
        self.assertEqual(payload['discovery'], 'failed')
        self.assertEqual(addresses(payload), ['10.1.2.3', '127.0.0.1'])
        self.assertNotIn('0.0.0.0', addresses(payload))

    def test_specific_scope_does_not_enumerate_interfaces(self):
        calls = []
        originals = (canvas.lan_addresses, canvas.interface_ipv6_addresses, canvas._tailscale_status_ips)
        canvas.lan_addresses = lambda: calls.append('lan') or []
        canvas.interface_ipv6_addresses = lambda: calls.append('v6') or []
        canvas._tailscale_status_ips = lambda: calls.append('ts') or None
        try:
            self.assertEqual(canvas.discover_for_preview([{'address': '127.0.0.1'}]), ([], []))
        finally:
            canvas.lan_addresses, canvas.interface_ipv6_addresses, canvas._tailscale_status_ips = originals
        self.assertEqual(calls, [])

    def test_wildcard_payload_uses_only_the_injected_rows(self):
        def discover(_listeners):
            return [('192.168.1.20', 'lan')], []
        payload = canvas.preview_hosts_payload([{'address': '0.0.0.0', 'covers_v4': True}], 4100, discover=discover)
        self.assertEqual(payload['discovery'], 'ok')
        self.assertEqual(addresses(payload), ['192.168.1.20', '127.0.0.1'])
        self.assertNotIn('0.0.0.0', addresses(payload))

    def test_url_for_brackets_ipv6(self):
        self.assertEqual(canvas.url_for('fd7a:115c:a1e0::8', 4100), 'http://[fd7a:115c:a1e0::8]:4100/')
        self.assertEqual(canvas.url_for('192.168.1.20', 4100), 'http://192.168.1.20:4100/')
        self.assertNotIn('0.0.0.0', canvas.url_for('192.168.1.20', 4100))


class PreviewEndpointTest(unittest.TestCase):
    def test_loopback_server_lists_only_loopback(self):
        port = self._free_port()
        proc = subprocess.Popen(
            [sys.executable, str(CANVAS), 'serve', '--project-dir', str(ROOT / 'examples' / 'en'),
             '--port', str(port), '--bind', '127.0.0.1'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._stop, proc)
        ready = json.loads(proc.stdout.readline())
        self.assertEqual(ready['service'], 'ui-canvas')
        self.assertNotIn('0.0.0.0', [item['bind'] for item in ready['urls']])
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:%d/api/preview-hosts' % port, timeout=10) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode())
        self.assertEqual(payload['discovery'], 'ok')
        self.assertEqual(addresses(payload), ['127.0.0.1'])
        self.assertTrue(all(item['address'] not in ('0.0.0.0', '::') for item in payload['addresses']))
        self.assertEqual(payload['listeners'], [{'address': '127.0.0.1', 'covers_v4': False}])

    def test_wildcard_listener_is_not_a_shareable_address(self):
        port = self._free_port()
        proc = subprocess.Popen(
            [sys.executable, str(CANVAS), 'serve', '--project-dir', str(ROOT / 'examples' / 'en'),
             '--port', str(port), '--bind', '0.0.0.0'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._stop, proc)
        line = proc.stdout.readline()
        if proc.poll() is not None:
            self.skipTest('cannot bind 0.0.0.0 here: ' + (proc.stderr.read() or line))
        ready = json.loads(line)
        self.assertIn('0.0.0.0', ready['binds'])
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:%d/api/preview-hosts' % port, timeout=15) as response:
            payload = json.loads(response.read().decode())
        self.assertEqual(payload['discovery'], 'ok')
        self.assertEqual(payload['listeners'][0]['address'], '0.0.0.0')
        self.assertNotIn('0.0.0.0', addresses(payload))
        self.assertNotIn('::', addresses(payload))
        self.assertIn('127.0.0.1', addresses(payload))
        for item in payload['addresses']:
            ip = canvas.parse_host_ip(item['address'])
            self.assertIsNotNone(ip)
            self.assertFalse(ip.is_unspecified)
            self.assertFalse(ip.is_link_local)

    def _free_port(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _stop(self, proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            if stream:
                stream.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
