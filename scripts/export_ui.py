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


def build_export(root, bundle, tr=None, lang='en'):
    """tr(key, **params) localises messages; lang ('zh' | 'en') sets the exported pages' language."""
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
        cards, rows = [], []
        for frame in config['frames']:
            source = sources[frame['path']].decode('utf-8')
            # A handoff must not depend on the running canvas or external resource hosts.
            if re.search(r'(?:src|href)\s*=\s*[\"\']https?://|url\(\s*[\"\']?https?://', source, re.I):
                raise ValueError(tr('x.external'))
            dest = stage / frame['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(sources[frame['path']])
            rendered = source.replace('/project/media/', 'media/').replace('/media/', 'media/')
            fid, title = escape(frame['id'], quote=True), escape(frame['title'])
            width, height = frame['width'], frame['height']
            page = f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><base href="../"><title>{title}</title><link rel="stylesheet" href="assets/canvas.css"><style>body{{display:block;height:auto;overflow:auto;margin:0;background:var(--bg)}}.design-frame{{width:{width}px;margin:0}}.design-frame>.phone{{width:{width}px;height:{height}px;border-radius:0;border:0;cursor:default}}</style></head><body><article class="design-frame" data-frame-id="{fid}"><div class="phone">{rendered}</div></article></body></html>'''
            (stage / 'pages' / (frame['id'] + '.html')).write_text(page)
            cards.append(f'<article><h2>{title}</h2><p>{escape(frame.get("state", ""))}</p><a href="pages/{fid}.html">{tr("x.standalone")}</a> · <a href="previews/{fid}.png">{tr("x.screenshot")}</a><iframe title="{title}" src="pages/{fid}.html" width="{width}" height="{height}"></iframe></article>')
            rows.append(f'| {frame["title"]} | {frame["id"]} | {width} × {height} | {frame.get("state", "")} |')
        index = '<!doctype html><html lang="'+lang+'"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(config['name'])+'</title><style>body{margin:24px;font:14px/1.6 system-ui;background:#eef1f4;color:#2c3a45}h1{font-size:22px}main{display:flex;align-items:flex-start;gap:24px;flex-wrap:wrap}article{background:white;padding:16px;border-radius:12px}h2{font-size:16px;margin:0}iframe{display:block;border:1px solid #ddd;margin-top:12px}a{color:#1385d8}</style></head><body><h1>'+escape(config['name'])+'</h1><p>'+escape(config['id']+' / '+config['revision'])+' · '+escape(tr('x.indexNote'))+'</p><main>'+''.join(cards)+'</main></body></html>'
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
