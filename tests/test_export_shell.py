#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The exported index is the selected canvas, read-only, and a phone enters /m/ without a loop.
Run: python3 tests/test_export_shell.py
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
import urllib.request
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import canvas as canvas_mod  # noqa: E402

CANVAS = ROOT / 'scripts' / 'canvas.py'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'
IPAD = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15'
ANDROID_TAB = 'Mozilla/5.0 (Linux; Android 14; SM-T870) AppleWebKit/537.36'
DESKTOP = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
BLOCKED = re.compile(r'/(api|healthz|project|tool)(/|$|\?)')


class NoRedirect(Exception):
    pass


def opener():
    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise HTTPError(req.full_url, code, msg, headers, fp)
    return build_opener(Stay)


def get(url, ua=DESKTOP, header=None):
    headers = {'User-Agent': ua}
    if header:
        headers.update(header)
    try:
        with opener().open(Request(url, headers=headers), timeout=120) as response:
            return response.status, response.read(), response.headers
    except HTTPError as error:
        return error.code, error.read(), error.headers


def write_project(root, revision, flow_start, frames, columns, groups, notes, design):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'frames').mkdir(exist_ok=True)
    (root / 'media').mkdir(exist_ok=True)
    config = {
        'id': 'fixture', 'name': 'Fixture', 'revision': revision, 'columns': columns,
        'groupColumns': groups, 'flow_start': flow_start,
        'frames': [{'id': fid, 'title': title, 'group': group, 'width': width, 'height': 700,
                    'path': 'frames/%s.html' % fid} for fid, title, group, width, _body in frames],
        'notes': notes,
    }
    (root / 'project.json').write_text(json.dumps(config), encoding='utf-8')
    for fid, _title, _group, _width, body in frames:
        (root / 'frames' / (fid + '.html')).write_text(body, encoding='utf-8')
    for note in notes:
        (root / note['path']).write_text('<p data-ui-id="note">%s</p>' % note['id'], encoding='utf-8')
    if design is not None:
        (root / 'DESIGN.md').write_text(design, encoding='utf-8')
    elif (root / 'DESIGN.md').exists():
        (root / 'DESIGN.md').unlink()
    return config


def boot_from(html):
    match = re.search(r'window\.UIC_EXPORT=(.*?);</script>', html)
    assert match, 'missing export boot'
    return json.loads(match.group(1))


def mobile_boot(html):
    match = re.search(r'<script type="application/json" id="m-boot">(.*?)</script>', html)
    return json.loads(match.group(1))


def layout_of(project):
    script = r'''
const fs=require('fs');
const src=fs.readFileSync(process.argv[1],'utf8');
const tile=src.match(/\/\/ <tile-layout>[\s\S]*?\/\/ <\/tile-layout>/)[0];
const notes=src.match(/\/\/ <board-notes>[\s\S]*?\/\/ <\/board-notes>/)[0];
const api=new Function(tile+'\n'+notes+'\n;return{tileLayout,noteOrigin,boardNotes}')();
const project=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const L=api.tileLayout(project);
const frames=project.frames.map((f,i)=>({id:f.id,x:L.boxes[i].x+'px',y:L.boxes[i].y+'px'}));
const placed=api.boardNotes(project).map(n=>{const o=api.noteOrigin(n,project,L);return{id:n.id,x:o.x+'px',y:o.y+'px'}});
process.stdout.write(JSON.stringify({frames,notes:placed}));
'''
    blob = Path(tempfile.mkdtemp()) / 'project.json'
    blob.write_text(json.dumps(project), encoding='utf-8')
    out = subprocess.check_output(['node', '-e', script, str(ROOT / 'assets' / 'canvas.js'), str(blob)], text=True)
    return json.loads(out)


def positions(page):
    return page.evaluate('''() => ({
      frames: [...document.querySelectorAll('#board>.frame')].map(el => ({id: el.dataset.frameId, x: el.style.getPropertyValue('--x'), y: el.style.getPropertyValue('--y')})),
      notes: [...document.querySelectorAll('#board>.board-note')].map(el => ({id: el.dataset.noteId, x: el.style.getPropertyValue('--x'), y: el.style.getPropertyValue('--y')})),
      groups: [...document.querySelectorAll('#board>.group-bar')].map(el => el.textContent)
    })''')


def forbidden(url):
    return bool(BLOCKED.search(url))


def main():
    assert canvas_mod.phone_canvas_redirect(IPHONE, 'rev=r1&start=home') == '/m/?rev=r1&start=home'
    assert canvas_mod.phone_canvas_redirect(IPHONE, '') == '/m/'
    assert canvas_mod.phone_canvas_redirect(IPAD, 'rev=r1') is None
    assert canvas_mod.phone_canvas_redirect(ANDROID_TAB, '') is None
    assert canvas_mod.phone_canvas_redirect(DESKTOP, 'rev=r1&start=home') is None
    assert canvas_mod.uic_device_class('Mozilla/5.0 (Macintosh; Intel Mac OS X)') == 'desktop'
    print('redirect rules ok')

    tmp = Path(tempfile.mkdtemp(prefix='uic-shell-'))
    runtime = tmp / 'runtime'
    runtime.mkdir()
    root = tmp / 'project'
    old_frames = [
        ('home', 'Home', 'Archive', 390, '<div class="screen"><h1>HOME-R1</h1><a data-goto="side" data-ui-id="go">Go</a></div>'),
        ('side', 'Side', 'Archive', 420, '<div class="screen"><h1>SIDE-R1</h1><a data-goto="home" data-ui-id="back">Back</a></div>'),
    ]
    write_project(root, 'r1', 'home', old_frames, 2, {'Archive': 1}, [], None)
    (root / 'media' / 'dot.png').write_bytes(b'old-media')
    snap = root / 'snapshots' / 'r1'
    shutil.copytree(root / 'frames', snap / 'frames')
    shutil.copytree(root / 'media', snap / 'media')
    shutil.copy(root / 'project.json', snap / 'project.json')
    live_frames = [
        ('home', 'Home', 'Now', 390, '<div class="screen"><h1>HOME-R2</h1><a data-goto="hub" data-ui-id="to-hub">Hub</a></div>'),
        ('hub', 'Hub', 'Now', 440, '<div class="screen"><h1>HUB-R2</h1><a data-goto="home" data-ui-id="back">Back</a></div>'),
    ]
    live_notes = [{'id': 'margin', 'title': 'Margin', 'path': 'frames/note-margin.html', 'anchor': 'home', 'x': 20, 'y': 30, 'width': 200}]
    write_project(root, 'r2', 'hub', live_frames, 3, {'Now': 1}, live_notes, 'DESIGN-LIVE')
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
        status, _body, headers = get(base + '/?rev=r1&start=home', IPHONE)
        assert status == 302 and headers.get('Location') == '/m/?rev=r1&start=home', (status, headers.get('Location'))
        status, _body, headers = get(base + '/m/?rev=r1', IPHONE)
        assert status == 200, status
        status, page, _headers = get(base + '/', IPAD)
        assert status == 200 and b'id="view-flow"' in page
        status, page, _headers = get(base + '/', DESKTOP)
        assert status == 200 and b'id="board"' in page
        print('live entry ok')

        status, blob, headers = get(base + '/api/export-ui', header={'X-UIC-Lang': 'en'})
        if status == 400 and b'Playwright is not installed' in blob:
            print('SKIP export render')
            return
        assert status == 200 and headers.get('X-UI-Frame-Count') == '2', (status, headers.get('X-UI-Frame-Count'), blob[:800])
        live_zip = zipfile.ZipFile(io.BytesIO(blob))
        live_index = live_zip.read('index.html').decode('utf-8')
        assert '/tool/' not in live_index
        live_boot = boot_from(live_index)
        assert [f['id'] for f in live_boot['project']['frames']] == ['home', 'hub']
        assert live_boot['project']['flow_start'] == 'hub'
        assert live_boot['project']['columns'] == 3
        assert live_boot['design'] == 'DESIGN-LIVE'
        assert 'DESIGN-LIVE' in live_zip.read('DESIGN.md').decode('utf-8')
        assert live_zip.read('media/dot.png') == b'new-media'
        assert 'comments.json' not in live_zip.namelist()
        assert not any(name.startswith('snapshots/') for name in live_zip.namelist())
        mobile = live_zip.read('m/index.html').decode('utf-8')
        assert [f['id'] for f in mobile_boot(mobile)['frames']] == ['home', 'hub']
        assert mobile_boot(mobile)['flow_start'] == 'hub'
        status, blob, headers = get(base + '/api/export-ui?rev=r1', header={'X-UIC-Lang': 'zh'})
        assert status == 200 and headers.get('X-UI-Frame-Count') == '2'
        old_zip = zipfile.ZipFile(io.BytesIO(blob))
        old_index = old_zip.read('index.html').decode('utf-8')
        old_boot = boot_from(old_index)
        assert [f['id'] for f in old_boot['project']['frames']] == ['home', 'side']
        assert old_boot['project']['flow_start'] == 'home'
        assert old_boot['design'] is None
        assert 'DESIGN.md' not in old_zip.namelist()
        assert 'DESIGN-LIVE' not in old_index
        assert old_zip.read('media/dot.png') == b'old-media'
        assert [f['id'] for f in mobile_boot(old_zip.read('m/index.html').decode('utf-8'))['frames']] == ['home', 'side']
        assert 'window.UIC_LANG="zh"' in old_index
        print('zip ok')
        browser(base, root, live_zip, old_index, live_boot['project'])
        print('browser ok')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def serve(directory):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)
        def log_message(self, fmt, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, 'http://127.0.0.1:%d' % server.server_address[1]


def watch(page, bad):
    page.on('request', lambda req: bad.append(req.url) if forbidden(req.url) else None)


def browser(base, root, live_zip, old_index, live_project):
    chrome = Path('/usr/local/bin/google-chrome')
    if not chrome.is_file():
        print('SKIP browser')
        return
    from playwright.sync_api import sync_playwright
    unpacked = root.parent / 'live-zip'
    if unpacked.exists():
        shutil.rmtree(unpacked)
    unpacked.mkdir()
    live_zip.extractall(unpacked)
    sub = root.parent / 'site' / 'pkg'
    sub.parent.mkdir()
    shutil.copytree(unpacked, sub)
    host, origin = serve(unpacked)
    sub_host, sub_origin = serve(sub.parent)
    shots = Path('/opt/cursor/artifacts')
    if shots.is_dir():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(unpacked.rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(unpacked)))
        (shots / 'export-shell-sample.zip').write_bytes(buf.getvalue())
    expected = layout_of(live_project)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome), args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = browser.new_page(viewport={'width': 1100, 'height': 800}, locale='en-US')
            bad = []
            watch(page, bad)
            page.goto(origin + '/index.html', wait_until='domcontentloaded')
            page.wait_for_selector('#board>.frame')
            assert page.locator('#history').count() == 0
            assert page.locator('#export-ui').count() == 0
            assert page.locator('#annotate').count() == 0
            assert page.locator('#services').count() == 0
            got = positions(page)
            assert got['frames'] == expected['frames'], (got['frames'], expected['frames'])
            assert got['notes'] == expected['notes'], (got['notes'], expected['notes'])
            assert got['groups'] == ['Now']
            assert 'DESIGN-LIVE' not in page.locator('#design-dialog').inner_text()
            page.click('#design-notes')
            page.wait_for_selector('#design-dialog[open]')
            assert 'DESIGN-LIVE' in page.locator('#dn-body').inner_text()
            page.keyboard.press('Escape')
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-shell-tile.png'))
            page.click('#view-flow')
            page.wait_for_selector('body.flow-mode #board>.frame.flow-current')
            page.wait_for_selector('#board>.frame.flow-current[data-frame-id="hub"]')
            assert page.locator('#flow-bar .fb-hint').count() == 0
            page.locator('#board .flow-current [data-ui-id="back"]').click()
            page.wait_for_selector('#board>.frame.flow-current[data-frame-id="home"]')
            page.click('#flow-back')
            page.wait_for_selector('#board>.frame.flow-current[data-frame-id="hub"]')
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-shell-flow.png'))
            page.click('#view-tile')
            sent = len(bad)
            page.evaluate('() => { window.dispatchEvent(new Event("blur")); window.dispatchEvent(new Event("focus")); document.dispatchEvent(new Event("visibilitychange")); }')
            page.wait_for_timeout(400)
            assert bad[sent:] == [], bad[sent:]
            assert bad == [], bad
            page.click('#phone-preview')
            page.wait_for_selector('#phone-preview-dialog[open] #pp-url')
            want = origin + '/m/index.html'
            assert page.locator('#pp-url').input_value() == want
            assert page.locator('#pp-qr svg').count() == 1
            assert page.locator('#phone-preview-dialog').get_by_text('Open preview', exact=True).count() == 0
            if shots.is_dir():
                page.screenshot(path=str(shots / 'export-shell-qr.png'))
            narrow = browser.new_page(viewport={'width': 320, 'height': 700}, locale='en-US')
            narrow.goto(origin + '/index.html', wait_until='domcontentloaded')
            narrow.wait_for_selector('#board>.frame')
            assert 'm/index.html' not in narrow.url
            subpage = browser.new_page(viewport={'width': 1100, 'height': 800})
            sub_bad = []
            watch(subpage, sub_bad)
            subpage.goto(sub_origin + '/pkg/index.html', wait_until='domcontentloaded')
            subpage.wait_for_selector('#phone-preview')
            subpage.click('#phone-preview')
            subpage.wait_for_selector('#pp-url')
            assert subpage.locator('#pp-url').input_value() == sub_origin + '/pkg/m/index.html'
            assert sub_bad == [], sub_bad
            phone = browser.new_context(user_agent=IPHONE, viewport={'width': 390, 'height': 780})
            phone_page = phone.new_page()
            phone_page.goto(origin + '/index.html?start=home', wait_until='domcontentloaded')
            phone_page.wait_for_selector('#m-frame[data-frame-id="home"]')
            assert phone_page.locator('a[href="index.html"], a[href="../index.html"]').count() == 0
            if shots.is_dir():
                phone_page.screenshot(path=str(shots / 'export-shell-phone.png'))
            live = browser.new_page(viewport={'width': 1100, 'height': 800})
            live.goto(base + '/', wait_until='domcontentloaded')
            live.wait_for_selector('#board>.frame')
            assert positions(live)['frames'] == expected['frames']
            file_page = browser.new_page(viewport={'width': 1100, 'height': 800})
            file_bad = []
            file_page.on('request', lambda req: file_bad.append(req.url) if req.url.startswith('http') else None)
            file_page.goto((unpacked / 'index.html').as_uri(), wait_until='domcontentloaded')
            file_page.wait_for_selector('#board>.frame')
            file_page.click('#phone-preview')
            file_page.wait_for_selector('#m-frame')
            assert 'm/index.html' in file_page.url
            assert file_page.locator('#phone-preview-dialog').count() == 0
            assert file_bad == [], file_bad
            old = root.parent / 'old.html'
            old.write_text(old_index, encoding='utf-8')
            # assets are not beside this lone file; the boot text is enough for the missing-design string
            assert '"design":null' in old_index or '"design": null' in old_index
            browser.close()
    finally:
        host.shutdown()
        sub_host.shutdown()


if __name__ == '__main__':
    main()
