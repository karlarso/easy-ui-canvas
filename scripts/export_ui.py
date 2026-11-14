# SPDX-License-Identifier: Apache-2.0
"""Export all current design frames as an offline development handoff (no comments)."""
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path


MOBILE_STRINGS = ('flow.demoEnd', 'm.err.data', 'm.err.noFrames', 'm.err.page', 'm.err.start', 'm.defaultName', 'h.mobile_preview', 'm.titleRev', 'm.revLabel')

def _js_block(source, name):
    match = re.search(r'// <%s>[\s\S]*?// </%s>' % (name, name), source)
    if not match:
        raise ValueError('canvas.js is missing the <%s> block' % name)
    return match.group(0)

def offline_fragment(source):
    """Frame HTML for a static package. Root-absolute media paths become package-relative."""
    return source.replace('/project/media/', 'media/').replace('/media/', 'media/')

def json_for_script(value):
    blob = json.dumps(value, ensure_ascii=False)
    for raw, safe in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        blob = blob.replace(raw, safe)
    return blob

def document_lang(lang):
    """Match the canvas pages: zh is shown as zh-CN; anything else is en."""
    return 'zh-CN' if lang == 'zh' else 'en'

def mobile_preview_entry(tr):
    """Index link. The label is whatever language `tr` already resolved; the canvas name is not consulted."""
    label = escape(tr('h.mobile_preview'))
    return '<p><a href="m/index.html" aria-label="%s">%s</a></p>' % (label, label)

def write_mobile_preview(stage, config, pages, bundle, tr, lang):
    """Write m/index.html: the same /m/ runner, with every frame inlined so nothing is fetched.

    Start rule matches /m/: ?start= when that frame exists, otherwise flow_start, otherwise the first frame.
    """
    stage, bundle = Path(stage), Path(bundle)
    canvas_js = (bundle / 'assets' / 'canvas.js').read_text(encoding='utf-8')
    runner = _js_block(canvas_js, 'flow-core') + '\n' + _js_block(canvas_js, 'keep-scroll') + '\n' + _js_block(canvas_js, 'm-page')
    dictionary = json.loads((bundle / 'assets' / 'i18n.json').read_text(encoding='utf-8'))
    strings = {}
    for key in MOBILE_STRINGS:
        strings[key] = (dictionary.get(lang) or {}).get(key) or dictionary.get('en', {}).get(key) or key
    frames = []
    for frame in config['frames']:
        frames.append({'id': frame['id'], 'title': frame.get('title') or frame['id'], 'width': frame['width'], 'height': frame['height'], 'path': frame['path']})
    boot = {
        'rev': None,
        'name': config.get('name') if isinstance(config.get('name'), str) else '',
        'revision': config.get('revision') if isinstance(config.get('revision'), str) else '',
        'flow_start': config.get('flow_start') if isinstance(config.get('flow_start'), str) else None,
        'start': None,
        'frames': frames,
        'pages': pages,
    }
    title = escape(boot['name'] or tr('m.defaultName'), quote=True)
    page = '''<!doctype html>
<html lang="%s" class="m-html">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<base href="../">
<title>%s · %s</title>
<link rel="stylesheet" href="assets/canvas.css">
</head>
<body class="m-body">
<div id="m-probe" aria-hidden="true"></div>
<article id="m-frame" class="frame m-frame" aria-label="%s"><div id="m-phone" class="phone"></div></article>
<div id="m-rev" hidden></div>
<div id="m-toast" class="demo-toast" role="status" aria-live="polite"></div>
<script type="application/json" id="m-boot">%s</script>
<script>
window.tr=function(key,params){const dict=%s;let text=Object.prototype.hasOwnProperty.call(dict,key)?dict[key]:key;if(params)text=text.replace(/\\{(\\w+)\\}/g,function(m,n){return n in params?params[n]:m});return text};
%s
mobileMain();
</script>
</body>
</html>
''' % (document_lang(lang), title, escape(tr('h.mobile_preview'), quote=True), escape(tr('h.mobile_preview'), quote=True), json_for_script(boot), json_for_script(strings), runner)
    target = stage / 'm' / 'index.html'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding='utf-8')
    return target

def build_export(root, bundle, tr=None, lang='en'):
    """tr(key, **params) localises messages. lang is 'zh' or 'en'.

    The canvas passes the request language: X-UIC-Lang (the language the page is showing),
    otherwise the stored choice, otherwise Accept-Language. English is the fallback.
    The canvas name is not a language signal.
    """
    tr = tr or (lambda key, **params: key)
    root, bundle = Path(root), Path(bundle)
    config_bytes = (root / 'project.json').read_bytes()
    config = json.loads(config_bytes)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    with tempfile.TemporaryDirectory(prefix='ui-handoff-') as folder:
        stage = Path(folder)
        sources = {}
        for frame in config['frames']:
            path = (root / frame['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(tr('x.noSource'))
            sources[frame['path']] = path.read_bytes()
        for name in ('frames', 'pages', 'assets', 'previews'):
            (stage / name).mkdir()
        (stage / 'project.json').write_bytes(config_bytes)
        (stage / 'assets/canvas.css').write_bytes((bundle / 'assets/canvas.css').read_bytes())
        media = root / 'media'
        if media.is_dir():
            for path in media.rglob('*'):
                if path.is_file() and not any(part.startswith('.') for part in path.relative_to(media).parts):
                    if not path.resolve().is_relative_to(media.resolve()):
                        raise ValueError(tr('x.mediaPath'))
                    dest = stage / 'media' / path.relative_to(media)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(path.read_bytes())
        cards, rows, pages = [], [], {}
        for frame in config['frames']:
            source = sources[frame['path']].decode('utf-8')
            # A handoff must not depend on the running canvas or external resource hosts.
            if re.search(r'(?:src|href)\s*=\s*[\"\']https?://|url\(\s*[\"\']?https?://', source, re.I):
                raise ValueError(tr('x.external'))
            dest = stage / frame['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(sources[frame['path']])
            rendered = offline_fragment(source)
            fid, title = escape(frame['id'], quote=True), escape(frame['title'])
            width, height = frame['width'], frame['height']
            page = f'''<!doctype html><html lang="{document_lang(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><base href="../"><title>{title}</title><link rel="stylesheet" href="assets/canvas.css"><style>body{{display:block;height:auto;overflow:auto;margin:0;background:var(--bg)}}.design-frame{{width:{width}px;margin:0}}.design-frame>.phone{{width:{width}px;height:{height}px;border-radius:0;border:0;cursor:default}}</style></head><body><article class="design-frame" data-frame-id="{fid}"><div class="phone">{rendered}</div></article></body></html>'''
            (stage / 'pages' / (frame['id'] + '.html')).write_text(page)
            pages[frame['id']] = rendered
            cards.append(f'<article><h2>{title}</h2><p>{escape(frame.get("state", ""))}</p><a href="pages/{fid}.html">{tr("x.standalone")}</a> · <a href="previews/{fid}.png">{tr("x.screenshot")}</a><iframe title="{title}" src="pages/{fid}.html" width="{width}" height="{height}"></iframe></article>')
            rows.append(f'| {frame["title"]} | {frame["id"]} | {width} × {height} | {frame.get("state", "")} |')
        write_mobile_preview(stage, config, pages, bundle, tr, lang)
        preview = mobile_preview_entry(tr)
        index = '<!doctype html><html lang="'+document_lang(lang)+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(config['name'])+'</title><style>body{margin:24px;font:14px/1.6 system-ui;background:#eef1f4;color:#2c3a45}h1{font-size:22px}main{display:flex;align-items:flex-start;gap:24px;flex-wrap:wrap}article{background:white;padding:16px;border-radius:12px}h2{font-size:16px;margin:0}iframe{display:block;border:1px solid #ddd;margin-top:12px}a{color:#1385d8}</style></head><body><h1>'+escape(config['name'])+'</h1><p>'+escape(config['id']+' / '+config['revision'])+' · '+escape(tr('x.indexNote'))+'</p>'+preview+'<main>'+''.join(cards)+'</main></body></html>'
        (stage / 'index.html').write_text(index)
        handoff = (f"# {config['name']} · " + tr('x.handoffTitle') + "\n\n"
                   + tr('x.meta', id=config['id'], revision=config['revision'], stamp=stamp) + "\n\n"
                   + tr('x.howTo') + "\n\n## " + tr('x.allPages') + "\n\n"
                   + '| ' + tr('x.colPage') + ' | ' + tr('x.colId') + ' | ' + tr('x.colSize') + ' | ' + tr('x.colState') + ' |\n|---|---|---|---|\n'
                   + '\n'.join(rows) + "\n\n## " + tr('x.basisTitle') + "\n\n" + tr('x.basis1') + "\n\n" + tr('x.basis2') + "\n\n" + tr('x.basis3') + "\n")
        # Optional explicit project-authored handoff requirements; never read comment storage.
        authored = root / 'HANDOFF.md'
        if authored.is_file():
            handoff += '\n## ' + tr('x.authored') + '\n\n' + authored.read_text()
        (stage / 'HANDOFF.md').write_text(handoff)
        node = shutil.which('node') or next((str(path) for path in (Path('/opt/homebrew/bin/node'), Path('/usr/local/bin/node'), Path.home() / '.local/share/mise/shims/node') if path.is_file()), None)
        if not node:
            candidates = list((Path.home() / '.local/share/fnm/node-versions').glob('*/installation/bin/node')) + list((Path.home() / '.nvm/versions/node').glob('*/bin/node'))
            node = str(sorted(candidates)[-1]) if candidates else None
        if not node:
            raise ValueError(tr('x.needNode'))
        result = subprocess.run([node, str(bundle / 'scripts/export-ui.cjs'), str(stage)], capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(tr('x.shotFailed', detail=result.stderr[-1500:]))
        if (root / 'project.json').read_bytes() != config_bytes or any((root / path).read_bytes() != value for path, value in sources.items()):
            raise ValueError(tr('x.changed'))
        hashes = {str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest() for path in stage.rglob('*') if path.is_file()}
        (stage / 'export-manifest.json').write_text(json.dumps({'project_id': config['id'], 'revision': config['revision'], 'exported_at': stamp, 'files': hashes}, ensure_ascii=False, indent=2))
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(stage)))
        safe = re.sub(r'[^a-zA-Z0-9_-]', '-', config['id']+'-'+config['revision'])
        return output.getvalue(), f'{safe}-ui-{stamp}.zip'
