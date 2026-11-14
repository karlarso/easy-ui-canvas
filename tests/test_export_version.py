#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export of the live canvas and of one snapshot stay separate. A bad rev is an error.
Run: python3 tests/test_export_version.py
"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / 'scripts' / 'canvas.py'


def write_project(root, revision, flow_start, frames):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'frames').mkdir(exist_ok=True)
    (root / 'media').mkdir(exist_ok=True)
    config = {
        'id': 'fixture', 'name': 'Fixture', 'revision': revision, 'columns': 2,
        'flow_start': flow_start,
        'frames': [{'id': fid, 'title': title, 'width': 390, 'height': 700, 'path': 'frames/%s.html' % fid}
                   for fid, title, _body in frames],
    }
    (root / 'project.json').write_text(json.dumps(config), encoding='utf-8')
    for fid, _title, body in frames:
        (root / 'frames' / (fid + '.html')).write_text(body, encoding='utf-8')
    return config


def http(url):
    try:
        with urlopen(url, timeout=60) as response:
            return response.status, response.read(), response.headers.get('Content-Disposition', '')
    except HTTPError as error:
        return error.code, error.read(), ''


def zip_text(blob, name):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return archive.read(name).decode('utf-8'), archive.namelist()


def main():
    tmp = Path(tempfile.mkdtemp(prefix='uic-export-rev-'))
    runtime = tmp / 'runtime'
    runtime.mkdir()
    root = tmp / 'project'
    old = [
        ('home', 'Home', '<div class="screen"><h1>HOME-R1</h1><a data-goto="home" data-ui-id="stay">Stay</a></div>'),
    ]
    write_project(root, 'r1', 'home', old)
    (root / 'media').mkdir(exist_ok=True)
    (root / 'media' / 'dot.png').write_bytes(b'old-media')
    snap = root / 'snapshots' / 'r1'
    shutil.copytree(root / 'frames', snap / 'frames')
    shutil.copytree(root / 'media', snap / 'media')
    shutil.copy(root / 'project.json', snap / 'project.json')
    live = [
        ('home', 'Home', '<div class="screen"><h1>HOME-R2</h1><a data-goto="hub" data-ui-id="to-hub">Hub</a></div>'),
        ('hub', 'Hub', '<div class="screen"><h1>HUB-R2</h1><a data-goto="home" data-ui-id="back">Back</a></div>'),
    ]
    write_project(root, 'r2', 'hub', live)
    (root / 'media' / 'dot.png').write_bytes(b'new-media')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    sock.close()
    env = dict(os.environ, UI_CANVAS_RUNTIME=str(runtime))
    env.pop('UI_CANVAS_BIND', None)
    playwright_mod = Path('/tmp/pw-mod/node_modules/playwright')
    if playwright_mod.is_dir():
        env['UI_CANVAS_PLAYWRIGHT_MODULE'] = str(playwright_mod)
    proc = subprocess.Popen(
        [sys.executable, str(CANVAS), 'serve', '--project-dir', str(root), '--port', str(port),
         '--bind', '127.0.0.1', '--runtime-dir', str(runtime)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline()
        if proc.poll() is not None:
            raise SystemExit(proc.stderr.read() or line)
        base = 'http://127.0.0.1:%d' % port
        status, blob, _disp = http(base + '/api/export-ui')
        if status == 400 and b'Playwright is not installed' in blob:
            print('SKIP: Node Playwright is not installed, so the export cannot render screenshots')
            return
        assert status == 200, (status, blob[:500])
        project, names = zip_text(blob, 'project.json')
        live_project = json.loads(project)
        assert live_project['revision'] == 'r2', live_project['revision']
        assert live_project['flow_start'] == 'hub'
        home, _names = zip_text(blob, 'pages/home.html')
        assert 'HOME-R2' in home and 'HOME-R1' not in home
        assert 'media/dot.png' in names
        media = zipfile.ZipFile(io.BytesIO(blob)).read('media/dot.png')
        assert media == b'new-media'
        status, blob, _disp = http(base + '/api/export-ui?rev=r1')
        assert status == 200, blob[:200]
        project, names = zip_text(blob, 'project.json')
        old_project = json.loads(project)
        assert old_project['revision'] == 'r1'
        assert old_project['flow_start'] == 'home'
        home, _names = zip_text(blob, 'pages/home.html')
        assert 'HOME-R1' in home and 'HOME-R2' not in home and 'HUB-R2' not in ''.join(names)
        assert 'pages/hub.html' not in names
        assert zipfile.ZipFile(io.BytesIO(blob)).read('media/dot.png') == b'old-media'
        mobile, _names = zip_text(blob, 'm/index.html')
        assert 'flow_start' in mobile and 'home' in mobile
        assert 'HOME-R1' in mobile and 'HOME-R2' not in mobile
        for bad in ('nope', '../r1', '.hidden', 'r1/../r2'):
            status, body, _disp = http(base + '/api/export-ui?rev=' + bad.replace('/', '%2F'))
            assert status == 404, (bad, status, body[:120])
        print('API ok')
        browser(base, root)
        print('browser ok')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def browser(base, root):
    chrome = Path('/usr/local/bin/google-chrome')
    if not chrome.is_file():
        print('SKIP browser')
        return
    from playwright.sync_api import sync_playwright
    shots = Path('/opt/cursor/artifacts')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome), args=['--no-sandbox', '--disable-dev-shm-usage'])
        page = browser.new_page(viewport={'width': 1100, 'height': 800}, locale='zh-CN')
        page.goto(base + '/', wait_until='domcontentloaded')
        page.click('#export-ui')
        page.wait_for_selector('#export-dialog[open] #export-versions [role=option]')
        page.wait_for_function("() => !document.querySelector('#export-confirm').disabled")
        selected = page.locator('#export-versions [aria-selected="true"]').inner_text()
        assert 'r2' in selected and '\u6700\u65b0' in selected, selected
        if shots.is_dir():
            page.locator('#export-dialog').screenshot(path=str(shots / 'export-version-latest.png'))
        page.locator('#export-versions [role=option]').nth(1).click()
        picked = page.locator('#export-versions [aria-selected="true"]').inner_text()
        assert 'r1' in picked, picked
        if shots.is_dir():
            page.locator('#export-dialog').screenshot(path=str(shots / 'export-version-history.png'))
        with page.expect_download() as download_info:
            page.click('#export-confirm')
        download = download_info.value
        target = root.parent / 'got.zip'
        download.save_as(str(target))
        blob = target.read_bytes()
        project = json.loads(zipfile.ZipFile(io.BytesIO(blob)).read('project.json'))
        assert project['revision'] == 'r1', project
        assert project['flow_start'] == 'home'
        page.wait_for_selector('#export-dialog', state='hidden')
        assert page.locator('#history-banner').get_attribute('hidden') is not None or not page.locator('body').evaluate('b => b.classList.contains("history-mode")')
        page.click('#export-ui')
        page.wait_for_function("() => !document.querySelector('#export-confirm').disabled")
        again = page.locator('#export-versions [aria-selected="true"]').inner_text()
        assert 'r2' in again and '\u6700\u65b0' in again, again
        page.click('#export-cancel')
        page.wait_for_selector('#export-dialog', state='hidden')
        page.click('#export-ui')
        page.wait_for_selector('#export-dialog[open]')
        page.keyboard.press('Escape')
        page.wait_for_selector('#export-dialog', state='hidden')
        browser.close()


if __name__ == '__main__':
    main()
