#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export of the live canvas and of one snapshot stay separate. A bad rev is an error.
Run: python3 tests/test_export_version.py
"""
import io
import json
import os
import re
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
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def zip_frame_facts(blob):
    """Frame counts already inside one export: project.json, the handoff table, and the phone preview."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        project = json.loads(archive.read('project.json'))
        handoff = archive.read('HANDOFF.md').decode('utf-8')
        mobile = archive.read('m/index.html').decode('utf-8')
        names = archive.namelist()
    rows = [line for line in handoff.splitlines() if line.startswith('| ') and not line.startswith('|---')]
    boot = json.loads(re.search(r'<script type="application/json" id="m-boot">(.*?)</script>', mobile).group(1))
    pages = [name for name in names if name.startswith('pages/') and name.endswith('.html')]
    previews = [name for name in names if name.startswith('previews/') and name.endswith('.png')]
    return {
        'revision': project.get('revision'),
        'project': len(project['frames']),
        'meta': len(rows) - 1,
        'mobile': len(boot['frames']),
        'mobile_pages': len(boot['pages']),
        'page_files': len(pages),
        'previews': len(previews),
    }


def assert_frame_header(headers, blob, revision, count):
    facts = zip_frame_facts(blob)
    got = headers.get('X-UI-Frame-Count')
    assert got == str(count), (got, facts)
    assert facts['revision'] == revision, facts
    assert facts['project'] == facts['meta'] == facts['mobile'] == facts['mobile_pages'] == facts['page_files'] == facts['previews'] == count, facts
    return facts


def zip_text(blob, name):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return archive.read(name).decode('utf-8'), archive.namelist()


def main():
    tmp = Path(tempfile.mkdtemp(prefix='uic-export-rev-'))
    runtime = tmp / 'runtime'
    runtime.mkdir()
    root = tmp / 'project'
    # The snapshot has more frames than the live canvas, so a header taken from the live project cannot match this zip.
    old = [
        ('home', 'Home', '<div class="screen"><h1>HOME-R1</h1><a data-goto="home" data-ui-id="stay">Stay</a></div>'),
        ('side', 'Side', '<div class="screen"><h1>SIDE-R1</h1></div>'),
        ('note', 'Note', '<div class="screen"><h1>NOTE-R1</h1></div>'),
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
        status, blob, headers = http(base + '/api/export-ui')
        if status == 400 and b'Playwright is not installed' in blob:
            print('SKIP: Node Playwright is not installed, so the export cannot render screenshots')
            return
        assert status == 200, (status, blob[:500])
        assert_frame_header(headers, blob, 'r2', 2)
        index, _names = zip_text(blob, 'index.html')
        assert 'id="entry-flow" href="m/index.html?present=flow"' in index
        assert 'id="entry-phone" href="m/index.html"' in index
        assert 'pages/hub.html' in index and 'pages/side.html' not in index
        project, names = zip_text(blob, 'project.json')
        live_project = json.loads(project)
        assert live_project['revision'] == 'r2', live_project['revision']
        assert live_project['flow_start'] == 'hub'
        assert [frame['id'] for frame in live_project['frames']] == ['home', 'hub']
        home, _names = zip_text(blob, 'pages/home.html')
        assert 'HOME-R2' in home and 'HOME-R1' not in home
        assert 'media/dot.png' in names
        media = zipfile.ZipFile(io.BytesIO(blob)).read('media/dot.png')
        assert media == b'new-media'
        live_mobile, _names = zip_text(blob, 'm/index.html')
        live_boot = json.loads(re.search(r'<script type="application/json" id="m-boot">(.*?)</script>', live_mobile).group(1))
        assert [frame['id'] for frame in live_boot['frames']] == ['home', 'hub']
        assert 'HOME-R2' in live_mobile and 'SIDE-R1' not in live_mobile
        status, blob, headers = http(base + '/api/export-ui?rev=r1')
        assert status == 200, blob[:200]
        assert_frame_header(headers, blob, 'r1', 3)
        index, _names = zip_text(blob, 'index.html')
        assert 'id="entry-flow" href="m/index.html?present=flow"' in index
        assert 'id="entry-phone" href="m/index.html"' in index
        assert 'pages/side.html' in index and 'pages/note.html' in index and 'pages/hub.html' not in index
        project, names = zip_text(blob, 'project.json')
        old_project = json.loads(project)
        assert old_project['revision'] == 'r1'
        assert old_project['flow_start'] == 'home'
        assert [frame['id'] for frame in old_project['frames']] == ['home', 'side', 'note']
        home, _names = zip_text(blob, 'pages/home.html')
        assert 'HOME-R1' in home and 'HOME-R2' not in home and 'HUB-R2' not in ''.join(names)
        assert 'pages/hub.html' not in names
        assert zipfile.ZipFile(io.BytesIO(blob)).read('media/dot.png') == b'old-media'
        mobile, _names = zip_text(blob, 'm/index.html')
        assert 'flow_start' in mobile and 'home' in mobile
        assert 'HOME-R1' in mobile and 'HOME-R2' not in mobile and 'SIDE-R1' in mobile
        boot = json.loads(re.search(r'<script type="application/json" id="m-boot">(.*?)</script>', mobile).group(1))
        assert [frame['id'] for frame in boot['frames']] == ['home', 'side', 'note']
        assert mobile.count('function mobileMain') == 1
        for bad in ('nope', '../r1', '.hidden', 'r1/../r2'):
            status, body, headers = http(base + '/api/export-ui?rev=' + bad.replace('/', '%2F'))
            assert status == 404, (bad, status, body[:120])
            assert not headers.get('X-UI-Frame-Count'), (bad, headers.get('X-UI-Frame-Count'))
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


def history_export_keeps_the_open_snapshot(page, root, shots):
    """Viewing a snapshot, Export still offers and downloads the live canvas, and leaves the snapshot on screen."""
    exports = []
    page.on('request', lambda req: exports.append(req.url) if '/api/export-ui' in req.url else None)
    page.click('#history')
    page.wait_for_selector('#history-menu .hm-item')
    page.locator('#history-menu .hm-item').filter(has_text='r1').click()
    page.wait_for_selector('body.history-mode')
    page.wait_for_function("() => document.getElementById('board').innerText.includes('HOME-R1')")

    def still_on_r1():
        assert 'history-mode' in (page.locator('body').get_attribute('class') or '')
        assert 'rev=r1' in page.url
        board = page.locator('#board').inner_text()
        assert 'HOME-R1' in board and 'HOME-R2' not in board

    still_on_r1()
    page.click('#export-ui')
    page.wait_for_function("() => !document.querySelector('#export-confirm').disabled")
    selected = page.locator('#export-versions [aria-selected="true"]').inner_text()
    assert 'r2' in selected and '\u6700\u65b0' in selected, selected
    assert 'r1' not in page.locator('#export-versions [aria-selected="true"]').inner_text().split('\n')[0]
    if shots.is_dir():
        page.screenshot(path=str(shots / 'export-while-history-default.png'))
    with page.expect_download() as download_info:
        page.click('#export-confirm')
    target = root.parent / 'latest-while-history.zip'
    download_info.value.save_as(str(target))
    project = json.loads(zipfile.ZipFile(target).read('project.json'))
    assert project['revision'] == 'r2', project
    assert project['flow_start'] == 'hub'
    assert 'HOME-R2' in zipfile.ZipFile(target).read('pages/home.html').decode('utf-8')
    assert exports and exports[-1].rstrip('/').endswith('/api/export-ui'), exports
    assert 'rev=' not in exports[-1]
    page.wait_for_selector('#export-dialog', state='hidden')
    still_on_r1()
    if shots.is_dir():
        page.screenshot(path=str(shots / 'export-while-history-stays.png'))
    sent = len(exports)
    page.click('#export-ui')
    page.wait_for_function("() => !document.querySelector('#export-confirm').disabled")
    page.click('#export-cancel')
    page.wait_for_selector('#export-dialog', state='hidden')
    assert len(exports) == sent
    still_on_r1()
    page.click('#export-ui')
    page.wait_for_selector('#export-dialog[open]')
    page.keyboard.press('Escape')
    page.wait_for_selector('#export-dialog', state='hidden')
    assert len(exports) == sent
    still_on_r1()


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
        history_export_keeps_the_open_snapshot(page, root, shots)
        browser.close()


if __name__ == '__main__':
    main()
