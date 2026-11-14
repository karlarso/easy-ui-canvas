# SPDX-License-Identifier: Apache-2.0
"""Export all current design frames as an offline development handoff (no comments)."""
import hashlib
import io
import json
import os
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

def read_export_design(root):
    """DESIGN.md in this export root only. Missing, a symlink, or too large is None. Never a different directory."""
    root = Path(root)
    try:
        if 'DESIGN.md' not in os.listdir(str(root)):
            return None
        path = root / 'DESIGN.md'
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            return None
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None

def canvas_shell_html(bundle, project, pages, design, lang):
    """The canvas document, with this snapshot inlined and tool URLs made relative. One visual template."""
    bundle = Path(bundle)
    html = (bundle / 'assets' / 'canvas.html').read_text(encoding='utf-8')
    html = html.replace('href="/tool/canvas.css"', 'href="assets/canvas.css"', 1)
    html = html.replace('src="/tool/canvas.js"', 'src="assets/canvas.js"', 1)
    canvas_js = (bundle / 'assets' / 'canvas.js').read_text(encoding='utf-8')
    dictionary = json.loads((bundle / 'assets' / 'i18n.json').read_text(encoding='utf-8'))
    boot = {'project': project, 'pages': pages, 'design': design if isinstance(design, str) else None}
    chosen = lang if lang in ('zh', 'en') else 'en'
    head = ('<script>window.UIC_EXPORT=%s;</script>'
            '<script>window.UIC_LANG=%s;window.UIC_DICT=%s;</script>'
            '<script src="assets/i18n.js"></script>'
            '<script>%s\nif(uicIsPhone(navigator.userAgent,navigator.maxTouchPoints||0))location.replace(exportMobileHref(location.href));</script>'
            ) % (json_for_script(boot), json.dumps(chosen), json_for_script(dictionary), _js_block(canvas_js, 'device-class'))
    html = html.replace('<!--UIC-I18N-->', head, 1)
    if '/tool/' in html:
        raise ValueError('export shell still points at /tool/')
    return html

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

    Returns (zip bytes, filename, frame count). The count is the length of the project
    read for this export: the same list written into project.json, the handoff table
    and the phone preview. It is not a later read of another directory.
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
        for asset in ('canvas.css', 'canvas.js', 'i18n.js'):
            (stage / 'assets' / asset).write_bytes((bundle / 'assets' / asset).read_bytes())
        media = root / 'media'
        if media.is_dir():
            for path in media.rglob('*'):
                if path.is_file() and not any(part.startswith('.') for part in path.relative_to(media).parts):
                    if not path.resolve().is_relative_to(media.resolve()):
                        raise ValueError(tr('x.mediaPath'))
                    dest = stage / 'media' / path.relative_to(media)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(path.read_bytes())
        rows, pages, by_path = [], {}, {}
        note_paths = []
        for note in config.get('notes') or []:
            if isinstance(note, dict) and isinstance(note.get('path'), str) and note['path'] not in sources:
                note_paths.append(note['path'])
        for rel in note_paths:
            path = (root / rel).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or rel.split('/')[0] != 'frames':
                raise ValueError(tr('x.noSource'))
            sources[rel] = path.read_bytes()
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
            by_path[frame['path']] = rendered
            rows.append(f'| {frame["title"]} | {frame["id"]} | {width} × {height} | {frame.get("state", "")} |')
        for rel, raw in sources.items():
            if rel not in by_path:
                text = raw.decode('utf-8')
                if re.search(r'(?:src|href)\s*=\s*[\"\']https?://|url\(\s*[\"\']?https?://', text, re.I):
                    raise ValueError(tr('x.external'))
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(raw)
                by_path[rel] = offline_fragment(text)
        design = read_export_design(root)
        if design is not None:
            (stage / 'DESIGN.md').write_text(design, encoding='utf-8')
        write_mobile_preview(stage, config, pages, bundle, tr, lang)
        (stage / 'index.html').write_text(canvas_shell_html(bundle, config, by_path, design, lang), encoding='utf-8')
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
        frame_count = len(config['frames'])
        hashes = {str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest() for path in stage.rglob('*') if path.is_file()}
        (stage / 'export-manifest.json').write_text(json.dumps({'project_id': config['id'], 'revision': config['revision'], 'exported_at': stamp, 'files': hashes}, ensure_ascii=False, indent=2))
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(stage)))
        safe = re.sub(r'[^a-zA-Z0-9_-]', '-', config['id']+'-'+config['revision'])
        return output.getvalue(), f'{safe}-ui-{stamp}.zip', frame_count
