#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Easy UI Canvas: a local, multi-frame web canvas for UI exploration. Python standard library only (Python 3.9+).

Fixed runtime directory (~/ui-canvas-runtime or $UI_CANVAS_RUNTIME):
  canvases/<port>-<id>/   one canvas per directory (canvas.json + project data).
                          New ids are 1, 2, 3, … (shown to people as #1, #2, #3). The '#' is display-only.
                          Older canvases keep their 6-character id.
  app/                    synced copy of this skill's code, used by background processes
  run/ logs/ trash/ config/
  run/canvas.seq          last canvas number issued in this runtime (not reused after remove)
  run/app-pin/            copy of the code this list service started with; serve falls back to it
                          if an older skill overwrites app/
A single list service (default port 4042) scans canvases/ and shows their status.
Its /healthz advertises id_schemes. A list that does not is still the pre-numbering
process: ensure-list (and new, before it allocates) restarts it once.
Servers listen on 127.0.0.1 only unless --bind/--host or $UI_CANVAS_BIND says otherwise (there is no authentication).
"""
import argparse
import errno
import gzip
import hashlib
import http.client
import ipaddress
import json
import os
import plistlib
import random
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial
from html import escape
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from xml.sax.saxutils import escape as xml_escape

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms are not supported for locking
    fcntl = None


def now():
    return datetime.now(timezone.utc).isoformat()

def inside(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(tr('s.pathOutside'))
    return path

def cgnat_address(value):
    """100.64.0.0/10 is the shared range Tailscale hands out, never a normal LAN."""
    try:
        return ipaddress.IPv4Address(value) in ipaddress.ip_network('100.64.0.0/10')
    except ipaddress.AddressValueError:
        return False

def lan_address(value):
    try:
        address = ipaddress.IPv4Address(value)
        return address.is_private and not address.is_loopback and not address.is_link_local and not address.is_unspecified and not cgnat_address(value)
    except ipaddress.AddressValueError:
        return False

def tailscale_addresses():
    """Actual IPv4 addresses of an online Tailscale interface, in reported order."""
    found = []
    executable = shutil.which('tailscale')
    if executable:
        try:
            result = subprocess.run([executable, 'status', '--json'], capture_output=True, text=True, timeout=3, check=True)
            status = json.loads(result.stdout)
            if status.get('BackendState') == 'Running' and status.get('Self', {}).get('Online'):
                for value in status.get('TailscaleIPs', []):
                    try:
                        if isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address):
                            found.append(value)
                    except ValueError:
                        continue
        except (OSError, ValueError, subprocess.SubprocessError):
            found = []
    if found:
        return dedupe(found)
    # CLI missing from PATH (e.g. a launchd job) or Tailscale not running: any
    # 100.64.0.0/10 address bound to an interface is this node's Tailscale IP.
    return dedupe([value for _, value in interface_addresses() if cgnat_address(value)])

# Interfaces that carry tunnels, overlays or host-only plumbing, never a LAN the user browses.
NON_LAN_PREFIXES = ('lo', 'gif', 'stf', 'awdl', 'llw', 'utun', 'tun', 'tap', 'wg', 'docker', 'veth', 'br-', 'bridge', 'ap', 'anpi')

def interface_addresses():
    """(interface, IPv4) pairs from up interfaces, cross-platform."""
    pairs = []
    executable = shutil.which('ip')
    if executable:
        try:
            result = subprocess.run([executable, '-j', '-4', 'address', 'show', 'up'], capture_output=True, text=True, timeout=2)
            for interface in json.loads(result.stdout):
                name = interface.get('ifname', '')
                for item in interface.get('addr_info', []):
                    if item.get('local'):
                        pairs.append((name, item['local']))
            if pairs:
                return pairs
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    executable = shutil.which('ifconfig')
    if not executable:
        return pairs
    try:
        result = subprocess.run([executable, '-a'], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return pairs
    name = ''
    for line in result.stdout.splitlines():
        if line and not line[0].isspace():
            name = line.split(':', 1)[0].strip()
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[0] == 'inet':
            pairs.append((name, fields[1]))
    return pairs

def dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result

def lan_addresses():
    """LAN IPv4 addresses on non-tunnel interfaces, with a route-probe fallback."""
    usable = [
        value
        for name, value in interface_addresses()
        if not name.startswith(NON_LAN_PREFIXES) and lan_address(value)
    ]
    if usable:
        return dedupe(usable)
    # No interface enumeration available: fall back to the default route and hostname.
    candidates = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # Route lookup only; no UDP payload is sent.
            probe.connect(('8.8.8.8', 80))
            candidates.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return dedupe([value for value in candidates if lan_address(value)])

def _access_addresses_uncached():
    """Online Tailscale IPv4 addresses first, then actual LAN addresses; deduplicated."""
    ordered = [(value, 'tailscale') for value in tailscale_addresses()]
    ordered.extend((value, 'lan') for value in lan_addresses())
    seen = set()
    result = []
    for value, kind in ordered:
        if value in seen:
            continue
        seen.add(value)
        result.append((value, kind))
    return result

class Targets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = attrs.get('data-ui-id')
        if key:
            if key == 'screen' or key in self.items or not key.replace('-', '').replace('_', '').isalnum():
                raise ValueError(tr('s.dupElement', key=key))
            self.items[key] = attrs.get('data-ui-label', key)

class AutoTargets(HTMLParser):
    """Inject targets into served fragments; never rewrite the design source."""
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.digest = hashlib.sha256(source.encode()).hexdigest()
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.inserts = []
        self.index = 0

    def handle_starttag(self, tag, attrs):
        self.index += 1
        attrs = dict(attrs)
        if tag in ('style', 'script', 'link', 'meta', 'title', 'template') or attrs.get('data-ui-id'):
            return
        key = '__auto-' + self.digest[:24] + '-' + str(self.index)
        label = tag + ''.join('.' + value for value in attrs.get('class', '').split())
        line, column = self.getpos()
        start = self.offsets[line - 1] + column
        raw = self.get_starttag_text()
        end = start + len(raw) - (2 if raw.endswith('/>') else 1)
        self.inserts.append((end, ' data-ui-id="' + key + '" data-ui-label="' + escape(label, quote=True) + '"'))

    handle_startendtag = handle_starttag

    def annotated(self):
        self.feed(self.source)
        self.close()
        result = self.source
        for offset, value in reversed(self.inserts):
            result = result[:offset] + value + result[offset:]
        return result

def annotated_html(source):
    return AutoTargets(source).annotated()

NOTE_ORIGIN_MAX = 20000
NOTE_DEFAULT_WIDTH = 320

def frame_subtitle(frame):
    """The text under a frame title on the canvas (group / state); mirrors buildFrames() in canvas.js."""
    return ' / '.join(str(value) for value in (frame.get('group'), frame.get('state')) if value)

def frame_group(frame):
    """The group of a frame as the tile layout sees it: a non-blank string, else '' (mirrors tileGroupOf() in canvas.js)."""
    group = frame.get('group') if isinstance(frame, dict) else None
    return group if isinstance(group, str) and group.strip() else ''

def group_title_targets(frames):
    """[(target id, group name)] for every group title bar of the tile view: one per run of consecutive frames with the same group.
    A group has no id of its own, its name is the identifier: 'group~<name>~title', '~' and '%' in the name percent-escaped; a name that starts a later section again gets
    'group~<name>~<n>~title' (n = 2, 3, ...). Mirrors groupTitleIds() in canvas.js."""
    result = []
    seen = {}
    previous = ''
    for frame in frames:
        group = frame_group(frame)
        if group and group != previous:
            seen[group] = seen.get(group, 0) + 1
            escaped = group.replace('%', '%25').replace('~', '%7E')
            result.append(('group~' + escaped + ('~%d' % seen[group] if seen[group] > 1 else '') + '~title', group))
        previous = group
    return result

def number_in_range(value, high):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= high

def board_notes(root, config, frame_ids):
    """Validated project.notes: free-standing HTML blocks on the board, outside every frame. Returns [(note, source path)]."""
    raw = config.get('notes', [])
    if not isinstance(raw, list):
        raise ValueError(tr('s.notesFormat'))
    seen = set()
    result = []
    for note in raw:
        if (not isinstance(note, dict) or not valid_frame_id(note.get('id')) or note['id'] in seen or not isinstance(note.get('path'), str)
                or not number_in_range(note.get('x'), NOTE_ORIGIN_MAX) or not number_in_range(note.get('y'), NOTE_ORIGIN_MAX)
                or not (note.get('title') is None or isinstance(note['title'], str))):
            raise ValueError(tr('s.notesFormat'))
        width = note.get('width', NOTE_DEFAULT_WIDTH)
        if not isinstance(width, int) or isinstance(width, bool) or not 40 <= width <= 4000:
            raise ValueError(tr('s.notesFormat'))
        if note.get('anchor') is not None and note['anchor'] not in frame_ids:
            raise ValueError(tr('s.noteAnchor', id=note['id']))
        seen.add(note['id'])
        source = inside(root, note['path'])
        if note['path'].split('/')[0] != 'frames' or source.suffix != '.html' or not source.is_file():
            raise ValueError(tr('s.noteEntry', id=note['id']))
        result.append((note, source))
    return result

def fragment_paths(project):
    """Every HTML fragment a project serves with automatic targets: frames and notes (tolerant of odd snapshot data)."""
    paths = set()
    if isinstance(project, dict):
        for key in ('frames', 'notes'):
            items = project.get(key)
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict) and isinstance(item.get('path'), str):
                    paths.add(item['path'])
    return paths

def manifest(root):
    config = json.loads((root / 'project.json').read_text())
    for key in ('id', 'name', 'revision'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(tr('s.cfgMissing', key=key))
    if not isinstance(config.get('columns', 3), int) or config.get('columns', 3) < 1:
        raise ValueError(tr('s.columns'))
    group_columns = config.get('groupColumns', {})
    if not isinstance(group_columns, dict) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in group_columns.values()):
        raise ValueError(tr('s.groupColumns'))
    frames = config.get('frames', [])
    if not frames:
        raise ValueError(tr('s.oneFrame'))
    ids = set()
    targets = {}
    for frame in frames:
        fid = frame['id']
        if not isinstance(fid, str) or not fid.replace('-', '').replace('_', '').isalnum() or fid in ids:
            raise ValueError(tr('s.frameId'))
        ids.add(fid)
        for dim in ('width', 'height'):
            if not isinstance(frame[dim], int) or not 100 <= frame[dim] <= 4000:
                raise ValueError(tr('s.frameSize'))
        source = inside(root, frame['path'])
        if frame['path'].split('/')[0] != 'frames' or source.suffix != '.html' or not source.is_file():
            raise ValueError(tr('s.frameEntry'))
        html = source.read_text()
        parser = Targets()
        parser.feed(annotated_html(html))
        digest = hashlib.sha256(html.encode()).hexdigest()
        # targets[id] = (frame or None, label, source hash, position reference); the reference is only set for targets outside the phone
        targets[fid + '--screen'] = (frame, tr('c.wholeLayout', title=frame['title']), digest, None)
        # '~' cannot occur in frame or element ids, so these never collide with <frame id>--<element id>
        targets[fid + '~title'] = (frame, tr('c.frameTitle', title=frame['title']), digest, 'frame')
        subtitle = frame_subtitle(frame)
        if subtitle:
            targets[fid + '~subtitle'] = (frame, tr('c.frameSubtitle', text=subtitle), digest, 'frame')
        for key, label in parser.items.items():
            targets[fid + '--' + key] = (frame, label, digest, None)
    # Group title bars belong to the canvas, like notes: no frame, position relative to the board. A group is not a file, so the hash is that of its name.
    for target, group in group_title_targets(frames):
        targets[target] = (None, tr('c.groupTitle', title=group), hashlib.sha256(group.encode()).hexdigest(), 'board')
    for note, source in board_notes(root, config, ids):
        html = source.read_text()
        parser = Targets()
        parser.feed(annotated_html(html))
        digest = hashlib.sha256(html.encode()).hexdigest()
        base = '~note~' + note['id']
        targets[base] = (None, tr('c.noteWhole', title=note.get('title') or note['id']), digest, 'board')
        for key, label in parser.items.items():
            targets[base + '~' + key] = (None, label, digest, 'board')
    return config, targets

def database(root):
    runtime = root / 'runtime'
    runtime.mkdir(exist_ok=True)
    con = sqlite3.connect(runtime / 'feedback.sqlite3', timeout=5)
    con.execute('CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, project TEXT NOT NULL, revision TEXT NOT NULL, client_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
    return con

def read_comments(root, revision=None):
    con = database(root)
    try:
        query = 'SELECT payload FROM comments'
        params = ()
        if revision is not None:
            query += ' WHERE revision=?'
            params = (revision,)
        return [item for row in con.execute(query + ' ORDER BY rowid', params) if not (item := json.loads(row[0])).get('deleted_at')]
    finally:
        con.close()

# ---------------------------------------------------------------------------
# Read-only access to version snapshots (snapshots/<rev>/)
# ---------------------------------------------------------------------------
SNAPSHOT_REV_RE = re.compile(r'[A-Za-z0-9._-]+')
SNAPSHOT_JSON_LIMIT = 8 * 1024 * 1024

def snapshot_dir(root, rev):
    """Directory of snapshot `rev`, or None. Only a real (non-symlink) direct child of snapshots/ qualifies."""
    if not isinstance(rev, str) or not 0 < len(rev) <= 120 or rev.startswith('.') or not SNAPSHOT_REV_RE.fullmatch(rev):
        return None
    base = Path(root) / 'snapshots'
    if base.is_symlink() or not base.is_dir():
        return None
    snap = base / rev
    if snap.is_symlink() or not snap.is_dir() or snap.resolve().parent != base.resolve():
        return None
    try:
        if rev not in os.listdir(str(base)):  # exact name only: case-insensitive filesystems (macOS) would alias R9 to r9
            return None
    except OSError:
        return None
    return snap

def snapshot_json(snap, name):
    """Parsed snapshots/<rev>/<name>; None when missing, a symlink, oversized or not valid JSON."""
    path = snap / name
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > SNAPSHOT_JSON_LIMIT:
            return None
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None

def snapshot_file(snap, relative):
    """A regular file inside snap/frames or snap/media (no '..', no symlink anywhere on the way), else None."""
    parts = relative.split('/')
    if len(parts) < 2 or parts[0] not in ('frames', 'media') or any(part in ('', '.', '..') for part in parts) or '\x00' in relative or '\\' in relative:
        return None
    folder = snap / parts[0]
    if folder.is_symlink() or not folder.is_dir():
        return None
    current = folder
    for part in parts[1:]:
        current = current / part
        if current.is_symlink():
            return None
    target = current.resolve()
    if not target.is_relative_to(folder.resolve()) or not target.is_file():
        return None
    return target

DESIGN_NAME = 'DESIGN.md'
DESIGN_LIMIT = 1024 * 1024

def read_design(folder):
    """DESIGN.md of a canvas root or a snapshot directory, by this fixed name only (never a caller-supplied path).
    Returns (status, text): ('ok', str), ('missing', None) or ('toobig', None). A symlink or non-regular file counts as missing."""
    folder = Path(folder)
    try:
        if DESIGN_NAME not in os.listdir(str(folder)):  # exact name only (case-insensitive filesystems would alias design.md)
            return 'missing', None
        path = folder / DESIGN_NAME
        if path.is_symlink() or not path.is_file():
            return 'missing', None
        if path.stat().st_size > DESIGN_LIMIT:
            return 'toobig', None
        return 'ok', path.read_bytes().decode('utf-8', errors='replace')
    except OSError:
        return 'missing', None

def snapshot_sort_key(rev):
    return [(1, int(piece), '') if piece.isdigit() else (0, 0, piece.lower()) for piece in re.split(r'(\d+)', rev) if piece]

def snapshot_comments(snap):
    data = snapshot_json(snap, 'comments.json')
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

# ---------------------------------------------------------------------------
# Phone preview (/m/): read-only, one frame at a time. Start frame resolution lives here so it is
# decided on the server (and is testable with curl); navigation (data-goto) is client side.
# ---------------------------------------------------------------------------
def is_mobile_path(path):
    return path == '/m' or path.startswith('/m/')

def valid_frame_id(value):
    return isinstance(value, str) and bool(value) and len(value) <= 120 and value.replace('-', '').replace('_', '').isalnum()

def pick_flow_start(ids, flow_start, want):
    """?start= wins, then project.flow_start, then the first frame; unknown ids fall through to the next choice."""
    for candidate in (want, flow_start):
        if isinstance(candidate, str) and candidate in ids:
            return candidate
    return ids[0]

def mobile_boot(root, config, rev, want):
    """Everything /m/ needs to start, as a JSON-able dict. CanvasError(404) for an unknown or unreadable rev."""
    root = Path(root)
    if rev:
        snap = snapshot_dir(root, rev)  # same rev rules as /api/snapshots
        project = snapshot_json(snap, 'project.json') if snap is not None else None
        if not isinstance(project, dict) or not isinstance(project.get('frames'), list):
            raise CanvasError(tr('s.noHistory'), 404)
        def read(path):
            target = snapshot_file(snap, path)
            return target.read_text(encoding='utf-8') if target is not None and target.suffix == '.html' else None
    else:
        project = config
        def read(path):
            target = inside(root, path)
            return target.read_text(encoding='utf-8') if path.split('/')[0] == 'frames' and target.suffix == '.html' and target.is_file() else None
    frames = []
    seen = set()
    for item in project['frames']:
        if not isinstance(item, dict) or not valid_frame_id(item.get('id')) or item['id'] in seen or not isinstance(item.get('path'), str):
            continue
        seen.add(item['id'])
        size = [item.get(key) if isinstance(item.get(key), int) and 100 <= item[key] <= 4000 else default for key, default in (('width', 390), ('height', 820))]
        frames.append({'id': item['id'], 'title': str(item.get('title') or item['id']), 'width': size[0], 'height': size[1], 'path': item['path']})
    if not frames:
        raise CanvasError(tr('s.noHistoryFrames'), 404)
    flow_start = project.get('flow_start') if isinstance(project.get('flow_start'), str) else None
    start = pick_flow_start([frame['id'] for frame in frames], flow_start, want)
    html = None
    try:
        text = read(next(frame['path'] for frame in frames if frame['id'] == start))
        html = annotated_html(text) if text is not None else None
    except (ValueError, OSError):
        html = None
    return {'rev': rev or None, 'name': project.get('name') if isinstance(project.get('name'), str) else '',
            'revision': project.get('revision') if isinstance(project.get('revision'), str) else '',
            'flow_start': flow_start, 'start': start, 'frames': frames, 'html': html}

def render_mobile_page(boot, runtime=None):
    template = (BUNDLE / 'assets' / 'mobile.html').read_text(encoding='utf-8')
    blob = json.dumps(boot, ensure_ascii=False)
    for raw, safe in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        blob = blob.replace(raw, safe)  # keeps the JSON inert inside <script type="application/json">
    title = escape(boot['name'] or tr('m.defaultName'), quote=True)
    page = template.replace('<!--M-TITLE-->', title)
    page = page.replace('<!--M-BOOT-->', '<script type="application/json" id="m-boot">' + blob + '</script>')
    return inject_i18n(page, runtime) if runtime is not None else page

def mobile_missing_page():
    return ('<!doctype html><html lang="' + current_lang() + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<title>' + escape(tr('s.mobileMissingTitle')) + '</title></head><body style="font:15px/1.6 -apple-system,sans-serif;padding:32px 24px;color:#2c3a45">'
            '<p>' + escape(tr('s.mobileMissingBody')) + '</p><p><a href="/m/">' + escape(tr('s.mobileOpenLatest')) + '</a></p></body></html>')

def list_snapshots(root, current_revision=None):
    """Cheap summaries (two small JSON reads per snapshot), newest version number first."""
    base = Path(root) / 'snapshots'
    if base.is_symlink() or not base.is_dir():
        return []
    items = []
    for entry in base.iterdir():
        snap = snapshot_dir(root, entry.name)
        if snap is None:
            continue
        project = snapshot_json(snap, 'project.json')
        comments = snapshot_json(snap, 'comments.json')
        valid = isinstance(project, dict) and isinstance(project.get('frames'), list)
        try:
            marker = snap / 'comments.json'
            stamp = (marker if marker.is_file() and not marker.is_symlink() else snap).stat().st_mtime
            created = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except OSError:
            created = None
        items.append({'rev': entry.name, 'revision': project.get('revision') if valid else None,
                      'name': project.get('name') if valid else None, 'created_at': created, 'valid': valid,
                      'frames': len(project['frames']) if valid else None,
                      'comments': len([c for c in comments if isinstance(c, dict)]) if isinstance(comments, list) else 0,
                      'current': entry.name == current_revision})
    items.sort(key=lambda item: snapshot_sort_key(item['rev']), reverse=True)
    return items

_ADDRESS_CACHE = {'at': 0.0, 'value': None}

def access_addresses():
    """Cached for 30 s: the Tailscale CLI probe can be slow when tailscaled is down."""
    if _ADDRESS_CACHE['value'] is None or time.time() - _ADDRESS_CACHE['at'] > 30:
        _ADDRESS_CACHE['value'] = _access_addresses_uncached()
        _ADDRESS_CACHE['at'] = time.time()
    return list(_ADDRESS_CACHE['value'])

# ---------------------------------------------------------------------------
# i18n (zh / en). One dictionary, assets/i18n.json, shared with the browser code.
# The language is stored once per runtime directory (config/lang.json), so every
# canvas process, the list service and the CLI agree. Unset: follow the browser/locale.
# ---------------------------------------------------------------------------
LANGS = ('zh', 'en')
_I18N = {'data': None, 'cli': None}
_REQUEST = threading.local()
LOOPBACK_HOSTS = ('127.0.0.1', '::1', 'localhost')

def i18n_dict():
    if _I18N['data'] is None:
        try:
            _I18N['data'] = json.loads((BUNDLE / 'assets' / 'i18n.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            _I18N['data'] = {'zh': {}, 'en': {}}
    return _I18N['data']

def lang_from_locale(value):
    """'zh-CN,zh;q=0.9' / 'zh_CN.UTF-8' -> 'zh'; anything else -> 'en'."""
    first = re.split(r'[,;]', value or '')[0].strip().lower()
    return 'zh' if first.startswith('zh') else 'en'

def lang_config_path(runtime):
    return Path(runtime) / 'config' / 'lang.json'

def stored_lang(runtime):
    """'zh' | 'en' | None (never chosen: follow the browser)."""
    try:
        value = json.loads(lang_config_path(runtime).read_text(encoding='utf-8')).get('lang')
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in LANGS else None

def save_lang(runtime, value):
    if value not in LANGS and value is not None:
        raise CanvasError(tr('s.badLang'), 400)
    path = lang_config_path(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {'lang': value})

def lang_state(runtime, accept=None):
    stored = stored_lang(runtime)
    return {'lang': stored, 'effective': stored or lang_from_locale(accept), 'supported': list(LANGS)}

def request_lang(headers, runtime):
    """Per request: X-UIC-Lang (what the page shows) > stored choice > Accept-Language."""
    explicit = (headers.get('X-UIC-Lang') or '').strip().lower()
    if explicit in LANGS:
        return explicit
    return stored_lang(runtime) or lang_from_locale(headers.get('Accept-Language'))

def _argv_runtime():
    argv = sys.argv[1:]
    for index, item in enumerate(argv):
        if item == '--runtime-dir' and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith('--runtime-dir='):
            return item.split('=', 1)[1]
    return None

def cli_lang():
    """Command line: $UI_CANVAS_LANG > stored choice > locale ($LC_ALL, $LC_MESSAGES, $LANG) > en."""
    forced = os.environ.get('UI_CANVAS_LANG', '').strip().lower()
    if forced in LANGS:
        return forced
    stored = stored_lang(runtime_dir(_argv_runtime()))
    if stored:
        return stored
    for name in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        if os.environ.get(name):
            return lang_from_locale(os.environ[name])
    return 'en'

def current_lang():
    lang = getattr(_REQUEST, 'lang', None)
    if lang:
        return lang
    if _I18N['cli'] is None:
        _I18N['cli'] = cli_lang()
    return _I18N['cli']

def tr(key, **params):
    table = i18n_dict()
    text = table.get(current_lang(), {}).get(key)
    if text is None:
        text = table.get('en', {}).get(key, key)
    return re.sub(r'\{(\w+)\}', lambda m: str(params.get(m.group(1), m.group(0))), text)

def inject_i18n(page, runtime):
    """Put the dictionary and the stored language choice into an HTML page (<!--UIC-I18N--> placeholder)."""
    blob = json.dumps(i18n_dict(), ensure_ascii=False, separators=(',', ':'))
    for raw, safe in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        blob = blob.replace(raw, safe)
    script = '<script>window.UIC_LANG=%s;window.UIC_DICT=%s;</script><script src="/tool/i18n.js"></script>' % (json.dumps(stored_lang(runtime)), blob)
    return page.replace('<!--UIC-I18N-->', script, 1)

def default_bind():
    """Loopback unless the user opts in (--bind/--host or $UI_CANVAS_BIND). There is no authentication."""
    return os.environ.get('UI_CANVAS_BIND', '').strip() or '127.0.0.1'

def bind_is_loopback(bind):
    values = [value.strip() for value in (bind or '').split(',') if value.strip()]
    return bool(values) and all(value in LOOPBACK_HOSTS for value in values)

# gzip for text responses (HTML, CSS, JS, JSON) when the client accepts it. Nothing is cached: Cache-Control stays as each caller sets it.
GZIP_TYPES = ('text/html', 'text/css', 'text/javascript', 'application/javascript', 'application/json')
GZIP_MIN = 512

def accepts_gzip(header):
    """True when an Accept-Encoding header allows gzip (explicitly, or through '*'), honouring q=0."""
    codings = {}
    for part in (header or '').split(','):
        name, _, params = part.partition(';')
        name = name.strip().lower()
        if not name:
            continue
        q = 1.0
        for param in params.split(';'):
            key, _, value = param.partition('=')
            if key.strip().lower() == 'q':
                try:
                    q = float(value.strip())
                except ValueError:
                    q = 0.0
        codings[name] = q
    if 'gzip' in codings:
        return codings['gzip'] > 0
    return codings.get('*', 0) > 0

class RequestMixin:
    """Per-request language and, for loopback-only servers, a Host header allowlist (DNS-rebinding guard)."""
    def lang_runtime(self):
        raise NotImplementedError
    def parse_request(self):
        if not super().parse_request():
            return False
        _REQUEST.lang = request_lang(self.headers, self.lang_runtime())
        if self.ctx.get('loopback_only'):
            try:
                name = urlparse('//' + (self.headers.get('Host') or '')).hostname
            except ValueError:
                name = None
            if name not in LOOPBACK_HOSTS:
                self.send_error(403, 'Host header not allowed')
                return False
        return True
    def send_body(self, status, data, content_type, *headers):
        """Send a complete response. Text types are gzip-compressed when the request accepts it (Content-Length is the
        compressed size; Vary: Accept-Encoding on every compressible response). Extra headers are (name, value) pairs."""
        compressible = content_type.split(';')[0].strip().lower() in GZIP_TYPES
        encoded = compressible and len(data) >= GZIP_MIN and accepts_gzip(self.headers.get('Accept-Encoding'))
        if encoded:
            data = gzip.compress(data, compresslevel=6, mtime=0)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if encoded:
            self.send_header('Content-Encoding', 'gzip')
        if compressible:
            self.send_header('Vary', 'Accept-Encoding')
        self.send_header('Content-Length', str(len(data)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)
    def lang_get(self):
        return self.reply_json(200, lang_state(self.lang_runtime(), self.headers.get('Accept-Language')))
    def lang_post(self):
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.reply_json(403, {'error': tr('s.originMismatch')})
        site = self.headers.get('Sec-Fetch-Site')
        if site and site not in ('same-origin', 'none'):
            return self.reply_json(403, {'error': tr('s.originMismatch')})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2000:
                raise ValueError(tr('s.badSize'))
            body = json.loads(self.rfile.read(length))
            value = body.get('lang') if isinstance(body, dict) else None
            if value in ('auto', ''):
                value = None
            if value is not None and value not in LANGS:
                raise ValueError(tr('s.badLang'))
        except (ValueError, TypeError) as error:
            return self.reply_json(400, {'error': str(error)})
        save_lang(self.lang_runtime(), value)
        _REQUEST.lang = request_lang(self.headers, self.lang_runtime())
        if hasattr(self, 'lang_changed'):
            self.lang_changed()
        return self.reply_json(200, lang_state(self.lang_runtime(), self.headers.get('Accept-Language')))

# ---------------------------------------------------------------------------
# Runtime layout, configuration
# ---------------------------------------------------------------------------
BUNDLE = Path(__file__).resolve().parent.parent
STATES = ('pending', 'changed', 'discussion')
SERVE_MARKER = 'ui-canvas-serve'
DEFAULT_LIST_PORT = 4042
DEFAULT_PORT_RANGE = (4100, 4899)
# New canvases are numbered 1, 2, 3, … like GitHub pull requests. The stored id is the decimal
# text ("1"), never "#1": '#' is a URL fragment and a shell comment, so it stays out of directory
# names, canvas.json, healthz.id and API paths. People see display_id ("#1") instead.
# Canvases created before numbering keep a legacy id of exactly 6 lowercase letters or digits.
# A legacy id can be 6 digits (the old alphabet included 2-9). Those are not sequence numbers;
# canvas.json id_scheme "number" marks a numbered canvas so a 6-digit legacy id cannot move the counter.
NUMERIC_ID_RE = re.compile(r'^[1-9]\d*$')
CANVAS_ID_RE = re.compile(r'^(?:[1-9]\d*|[a-z0-9]{6})$')
# A hand-made name such as canvases/2024-10 matches this pattern (port 2024, id 10) but is not a
# canvas. scan_canvases and the counter ignore it unless canvas.json or project.json is present.
DIR_RE = re.compile(r'^(\d{2,5})-([1-9]\d*|[a-z0-9]{6})$')
TRASH_CANVAS_RE = re.compile(r'^\d{8}-\d{6}-(\d{2,5})-([1-9]\d*|[a-z0-9]{6})(?:-\d+)?$')
TMP_CANVAS_RE = re.compile(r'^\.tmp-([1-9]\d*|[a-z0-9]{6})$')
SEQ_FILE = 'canvas.seq'
SEQ_LOCK = 'canvas.seq.lock'
# Capability advertised by list /healthz. The marker is a source literal so a downgraded
# canvas.py (an older skill's sync_app overwrote runtime/app) can be told apart from this one.
# Keep this exact line in every future version that can serve numbered canvases.
# script_supports_numbered_ids reads the file text; it does not import the module.
# Do not build the string by concatenation, and do not delete the line when adding a scheme:
# extend this literal and ID_SCHEMES together.
ID_SCHEMES = ('legacy', 'number')
ID_SCHEMES_MARKER = 'ui-canvas-id-schemes:legacy,number'
APP_PIN = 'app-pin'
MAX_CANVAS_NUMBER = 10**15 - 1  # 15 digits; keeps directory names short even if the counter file is corrupt
EXIT_PORT_IN_USE = 98
LAUNCH_LABEL = 'com.easy-ui-canvas.list'
APP_FILES = ('scripts/canvas.py', 'scripts/export_ui.py', 'scripts/export-ui.cjs', 'scripts/ui-canvas-list.plist.template')
APP_DIRS = ('assets', 'examples')


class CanvasError(Exception):
    """Expected failure with an HTTP-like status (404 missing, 409 conflict, 400 bad input ...)."""
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


def runtime_dir(value=None):
    raw = value or os.environ.get('UI_CANVAS_RUNTIME') or '~/ui-canvas-runtime'
    return Path(raw).expanduser().resolve()

def list_port_value(value=None):
    raw = value if value else os.environ.get('UI_CANVAS_LIST_PORT')
    try:
        port = int(raw) if raw else DEFAULT_LIST_PORT
    except ValueError:
        raise CanvasError(tr('s.listPortInt'))
    if not 1 <= port <= 65535:
        raise CanvasError(tr('s.listPortBad'))
    return port

def port_range_value():
    raw = os.environ.get('UI_CANVAS_PORT_RANGE')
    if not raw:
        return DEFAULT_PORT_RANGE
    match = re.match(r'^\s*(\d+)\s*-\s*(\d+)\s*$', raw)
    if not match or not 1024 <= int(match.group(1)) <= int(match.group(2)) <= 65535:
        raise CanvasError(tr('s.portRangeFmt'))
    return int(match.group(1)), int(match.group(2))

def canvases_dir(runtime):
    return runtime / 'canvases'

def ensure_runtime(runtime):
    for name in ('canvases', 'run', 'logs', 'trash'):
        (runtime / name).mkdir(parents=True, exist_ok=True)

def display_canvas_id(cid, scheme=None):
    """Human form. Numbered canvases gain a leading '#'; legacy ids are unchanged.

    Six digits are ambiguous (a legacy random id can be all digits). Only id_scheme "number"
    earns a '#' in that case. Shorter and longer numbers are unambiguous.
    """
    if not isinstance(cid, str) or not NUMERIC_ID_RE.fullmatch(cid):
        return cid if isinstance(cid, str) else ''
    if len(cid) == 6 and scheme != 'number':
        return cid
    return '#' + cid

def normalize_canvas_id(value):
    """Accept '1', '#1' and a legacy 6-character id. Return the stored form (no '#').

    The whole token is stripped, then a leading '#' must be followed immediately by the digits.
    '# 1' is rejected. '  #12  ' is still '#12'.
    """
    if not isinstance(value, str):
        raise CanvasError(tr('s.idInvalid'), 400)
    text = value.strip()
    if text.startswith('#'):
        body = text[1:]
        if not NUMERIC_ID_RE.fullmatch(body):
            raise CanvasError(tr('s.idInvalid'), 400)
        return body
    if CANVAS_ID_RE.fullmatch(text):
        return text
    raise CanvasError(tr('s.idInvalid'), 400)

def _read_seq(path):
    """Last issued number, or 0 when the file is missing or not a plausible counter.

    Only a missing file is an empty counter. Permission errors and other IO or decode
    failures propagate: treating them as 0 would reissue a number (for example after
    trash was emptied and the counter file could not be read).
    """
    try:
        text = path.read_text(encoding='ascii')
    except FileNotFoundError:
        return 0
    text = text.strip()
    if re.fullmatch(r'0|[1-9]\d{0,14}', text):
        return int(text)
    return 0

def _fsync_file(fd):
    """Flush a file (or directory) fd. On macOS, also ask the disk to flush its cache."""
    os.fsync(fd)
    if sys.platform != 'darwin' or fcntl is None:
        return
    full = getattr(fcntl, 'F_FULLFSYNC', None)
    if full is None:
        return
    try:
        fcntl.fcntl(fd, full)
    except OSError:
        pass

def _write_all(fd, payload):
    view = memoryview(payload)
    while len(view):
        written = os.write(fd, view)
        if not written:
            raise OSError(errno.EIO, 'short write to ' + SEQ_FILE)
        view = view[written:]

def _cleanup_stale_seq_tmps(directory):
    """Drop .canvas.seq.tmp-<pid> left by a crash. Leave a tmp whose pid is still running."""
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    prefix = '.' + SEQ_FILE + '.tmp-'
    me = os.getpid()
    for entry in entries:
        if not entry.name.startswith(prefix):
            continue
        tail = entry.name[len(prefix):]
        if not tail.isdigit():
            continue
        pid = int(tail)
        if pid != me and pid_alive(pid):
            continue
        try:
            entry.unlink()
        except OSError:
            pass

def _write_seq(path, number):
    """Atomically publish the last issued number and flush it before returning."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_seq_tmps(path.parent)
    payload = (str(number) + '\n').encode('ascii')
    tmp = path.with_name('.' + SEQ_FILE + '.tmp-' + str(os.getpid()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        _write_all(fd, payload)
        _fsync_file(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    os.close(fd)
    os.replace(tmp, path)
    dirfd = os.open(str(path.parent), os.O_RDONLY)
    try:
        _fsync_file(dirfd)
    finally:
        os.close(dirfd)

def _sequence_value(cid, entry):
    """How far this id pushes the counter. Legacy ids, including 6-digit ones, push it by 0."""
    if not isinstance(cid, str) or not NUMERIC_ID_RE.fullmatch(cid) or len(cid) > 15:
        return 0
    if len(cid) == 6:
        meta = read_canvas_json(entry)
        if not isinstance(meta, dict) or meta.get('id_scheme') != 'number':
            return 0
    return int(cid)

def _is_canvas_dir(entry):
    """True when this directory is a canvas, or when we cannot tell (do not reuse its number).

    An empty name that merely matches DIR_RE, such as canvases/2024-10, is not a canvas.
    canvas.json or project.json makes it one (project.json alone is metadata_missing).
    """
    try:
        return (entry / 'canvas.json').is_file() or (entry / 'project.json').is_file()
    except OSError:
        return True

def iter_issued_ids(runtime, strict=False):
    """(stored id, directory) for live canvases, half-created temps and trashed canvases.

    A directory listing that fails is skipped when the counter file is the high-water mark.
    strict is set when canvas.seq is missing: swallowing the error then would look like an
    empty runtime and reuse a number that is still on disk.
    """
    root = canvases_dir(runtime)
    try:
        entries = list(root.iterdir()) if root.is_dir() else []
    except OSError:
        if strict:
            raise
        entries = []
    for entry in entries:
        match = DIR_RE.match(entry.name)
        if match:
            if _is_canvas_dir(entry):
                yield match.group(2), entry
            continue
        match = TMP_CANVAS_RE.match(entry.name)
        if match:
            yield match.group(1), entry
    trash = runtime / 'trash'
    try:
        trashed = list(trash.iterdir()) if trash.is_dir() else []
    except OSError:
        if strict:
            raise
        trashed = []
    for entry in trashed:
        match = TRASH_CANVAS_RE.match(entry.name)
        if match:
            yield match.group(2), entry

def allocate_canvas_id(runtime):
    """Next canvas number for this runtime. Monotonic: remove never hands a number out again.

    Serialized with flock on run/canvas.seq.lock, so two processes creating canvases at once
    cannot take the same number. The counter is one runtime directory (the workspace), not one
    design project and not one machine. The number is synced to disk before the lock is released,
    which is before the canvas directory is published, so a crash skips a number instead of
    repeating it. Caller may also hold run/create.lock; this lock is the one that protects the counter.
    """
    ensure_runtime(runtime)
    with file_lock(runtime / 'run' / SEQ_LOCK, 180):
        seq_path = runtime / 'run' / SEQ_FILE
        known = set()
        # Missing counter file: a failed directory listing must not look like "nothing issued".
        strict = not seq_path.is_file()
        floor = _read_seq(seq_path)
        for cid, entry in iter_issued_ids(runtime, strict=strict):
            known.add(cid)
            floor = max(floor, _sequence_value(cid, entry))
        nxt = floor + 1
        while str(nxt) in known:
            nxt += 1
            if nxt > MAX_CANVAS_NUMBER:
                raise CanvasError(tr('s.idExhausted'), 503)
        if nxt > MAX_CANVAS_NUMBER:
            raise CanvasError(tr('s.idExhausted'), 503)
        _write_seq(seq_path, nxt)
        return str(nxt)

def timestamp():
    return datetime.now().strftime('%Y%m%d-%H%M%S')

def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)

def fail(message, code=1, **extra):
    data = {'error': message}
    data.update(extra)
    print(json.dumps(data, ensure_ascii=False), file=sys.stderr, flush=True)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------
@contextmanager
def file_lock(path, timeout):
    """flock(2) based lock; the kernel releases it when the process exits (no stale locks)."""
    if fcntl is None:
        raise CanvasError(tr('s.noFlock'), 500)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.time() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                    raise
                if time.time() > deadline:
                    raise CanvasError(tr('s.lockTimeout', name=path.name), 503)
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)

def create_lock(runtime, timeout=180):
    return file_lock(runtime / 'run' / 'create.lock', timeout)


# ---------------------------------------------------------------------------
# App sync (code copy that background processes run from)
# ---------------------------------------------------------------------------
def _bundle_files(base):
    found = []
    for rel in APP_FILES:
        if (base / rel).is_file():
            found.append(rel)
    for folder in APP_DIRS:
        root = base / folder
        if root.is_dir():
            for path in sorted(root.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts and not path.name.startswith('.'):
                    found.append(path.relative_to(base).as_posix())
    return sorted(found)

def bundle_version(base=None):
    """Content hash of the app files. An app copy carries it in VERSION."""
    base = Path(base) if base else BUNDLE
    marker = base / 'VERSION'
    if marker.is_file():
        try:
            return marker.read_text().strip()
        except OSError:
            pass
    digest = hashlib.sha256()
    for rel in _bundle_files(base):
        digest.update(rel.encode() + b'\0')
        digest.update((base / rel).read_bytes() + b'\0')
    return digest.hexdigest()[:12]

def sync_app(runtime):
    """Copy this skill's code into runtime/app (atomic per file, VERSION last). Returns the version."""
    dest = runtime / 'app'
    if dest.resolve() == BUNDLE.resolve():
        return bundle_version()
    version = bundle_version(BUNDLE)
    files = _bundle_files(BUNDLE)
    marker = dest / 'VERSION'
    try:
        current = marker.read_text().strip()
    except OSError:
        current = None
    if current == version and all((dest / rel).is_file() for rel in files):
        return version
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name('.' + target.name + '.tmp-' + str(os.getpid()) + '-' + secrets.token_hex(3))
        shutil.copy2(BUNDLE / rel, tmp)
        os.replace(tmp, target)
    tmp = marker.with_name('.VERSION.tmp-' + str(os.getpid()) + '-' + secrets.token_hex(3))
    tmp.write_text(version + '\n')
    os.replace(tmp, marker)
    return version

def script_supports_numbered_ids(path):
    """True when this canvas.py advertises numbered ids (the source contains the marker)."""
    try:
        text = Path(path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    return ID_SCHEMES_MARKER in text

def _pin_is_current(dest, version, files):
    """True when dest is exactly this bundle: right VERSION, no files left from another version."""
    script = dest / 'scripts' / 'canvas.py'
    try:
        current = (dest / 'VERSION').read_text().strip()
    except OSError:
        return False
    if current != version or not script.is_file() or not script_supports_numbered_ids(script):
        return False
    if not all((dest / rel).is_file() for rel in files):
        return False
    expected = set(files)
    expected.add('VERSION')
    try:
        found = {path.relative_to(dest).as_posix() for path in dest.rglob('*') if path.is_file() and not path.name.startswith('.')}
    except OSError:
        return False
    return found == expected

def _replace_tree(staging, dest):
    """Publish staging as dest. A previous dest is removed only after the new tree is in place."""
    if not dest.exists():
        os.rename(staging, dest)
        return
    backup = dest.with_name('.' + dest.name + '.old-' + str(os.getpid()) + '-' + secrets.token_hex(3))
    os.rename(dest, backup)
    try:
        os.rename(staging, dest)
    except OSError:
        os.rename(backup, dest)
        raise
    shutil.rmtree(backup, ignore_errors=True)

def pin_app(runtime):
    """Copy the running bundle to runtime/run/app-pin.

    An older skill's sync_app overwrites runtime/app only. The pin lives under run/, which
    that sync does not touch, so a list that already speaks numbered ids can still spawn
    `serve` after a downgrade. The copy replaces the whole tree, so two versions starting
    at once cannot leave a mix of files. No-op when this process is already running from the pin.
    """
    dest = runtime / 'run' / APP_PIN
    with file_lock(runtime / 'run' / 'app-pin.lock', 30):
        try:
            if dest.exists() and dest.resolve() == BUNDLE.resolve():
                return dest
        except OSError:
            pass
        version = bundle_version(BUNDLE)
        files = _bundle_files(BUNDLE)
        if _pin_is_current(dest, version, files):
            return dest
        staging = runtime / 'run' / ('.' + APP_PIN + '.tmp-' + str(os.getpid()) + '-' + secrets.token_hex(3))
        shutil.rmtree(staging, ignore_errors=True)
        try:
            for rel in files:
                target = staging / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(BUNDLE / rel, target)
            (staging / 'VERSION').parent.mkdir(parents=True, exist_ok=True)
            (staging / 'VERSION').write_text(version + '\n')
            _replace_tree(staging, dest)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return dest

def try_pin_app(runtime):
    """Pin the running bundle. A failure is logged and ignored: list-serve must still start."""
    try:
        return pin_app(runtime)
    except (OSError, CanvasError) as error:
        line = '%s pin_app failed: %s\n' % (now(), error)
        try:
            log = runtime / 'logs' / 'list.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open('a', encoding='utf-8') as handle:
                handle.write(line)
        except OSError:
            print(line, file=sys.stderr, flush=True)
        return None

def app_script(runtime):
    """Script used to spawn serve and list-serve.

    Prefer runtime/app while it still understands numbered ids. After an older skill
    overwrites that file, use run/app-pin. Last resort is this file.
    """
    for script in (runtime / 'app' / 'scripts' / 'canvas.py',
                   runtime / 'run' / APP_PIN / 'scripts' / 'canvas.py'):
        if script.is_file() and script_supports_numbered_ids(script):
            return script
    return Path(__file__).resolve()


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------
def url_for(address, port):
    host = '[' + address + ']' if ':' in address else address
    return f'http://{host}:{port}/'

def advertised_for(bind):
    """[(address, kind)] a service started with this bind setting can be reached on (loopback is always bound)."""
    bind = bind or default_bind()
    values = [value.strip() for value in bind.split(',') if value.strip()]
    wildcard = any(value in ('0.0.0.0', '::') for value in values)
    discovered = access_addresses() if bind == 'auto' or wildcard or not bind_is_loopback(bind) else []
    known = dict(discovered)
    if bind == 'auto' or wildcard:
        items = list(discovered)
    else:
        items = [(value, known.get(value, 'local-only' if value in LOOPBACK_HOSTS else 'explicit')) for value in values]
    if '127.0.0.1' not in [value for value, _ in items]:
        items.append(('127.0.0.1', 'local-only'))
    return items

def advertised_urls(port, bind=None):
    """Concrete URLs for a service bound with `bind` (default: loopback only)."""
    return [{'url': url_for(value, port), 'access': kind, 'bind': value} for value, kind in advertised_for(bind)]

def probe_json(port, path='/healthz', timeout=1.5, host='127.0.0.1'):
    """('ok', data) | ('refused', None) | ('bad', reason)."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request('GET', path)
        response = conn.getresponse()
        body = response.read(65536)
        if response.status != 200:
            return 'bad', 'HTTP ' + str(response.status)
        try:
            data = json.loads(body.decode('utf-8'))
        except ValueError:
            return 'bad', tr('s.notJson')
        if not isinstance(data, dict):
            return 'bad', tr('s.notObject')
        return 'ok', data
    except ConnectionRefusedError:
        return 'refused', None
    except socket.timeout:
        return 'bad', tr('s.timeout')
    except (OSError, http.client.HTTPException) as error:
        return 'bad', error.__class__.__name__
    finally:
        conn.close()

def classify_canvas(port, cid):
    """running / stopped / unresponsive (+ reason)."""
    state, data = probe_json(port)
    if state == 'refused':
        return 'stopped', None
    if state == 'bad':
        return 'unresponsive', data
    if data.get('service') != 'ui-canvas':
        return 'unresponsive', tr('s.portOther')
    if data.get('id') != cid:
        return 'unresponsive', tr('s.idMismatch')
    return 'running', None

def bind_targets(bind):
    """Addresses a canvas with this --bind would listen on (loopback always included)."""
    if bind == 'auto':
        values = [value for value, _ in access_addresses()]
    else:
        values = [value.strip() for value in bind.split(',') if value.strip()]
    if '0.0.0.0' in values or '::' in values:
        return ['0.0.0.0' if '0.0.0.0' in values else '::']
    if '127.0.0.1' not in values:
        values.append('127.0.0.1')
    return values

def port_free(port, addresses):
    """True when every address can bind the port and nothing answers on loopback."""
    for address in addresses:
        family = socket.AF_INET6 if ':' in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((address, port))
        except OSError as error:
            if error.errno in (errno.EADDRINUSE, errno.EACCES):
                return False
        finally:
            sock.close()
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(('127.0.0.1', port))
        return False
    except ConnectionRefusedError:
        return True
    except OSError:
        return False
    finally:
        probe.close()

def dir_ports(runtime):
    """Ports reserved by canvas directory names (stopped canvases keep theirs)."""
    ports = set()
    root = canvases_dir(runtime)
    if root.is_dir():
        for entry in root.iterdir():
            match = DIR_RE.match(entry.name)
            if match and _is_canvas_dir(entry):
                ports.add(int(match.group(1)))
    return ports

def pick_free_port(runtime, bind, exclude=()):
    low, high = port_range_value()
    taken = dir_ports(runtime) | set(exclude) | {list_port_value()}
    addresses = bind_targets(bind)
    span = high - low + 1
    start = random.randrange(span)
    for offset in range(span):
        port = low + (start + offset) % span
        if port in taken:
            continue
        if port_free(port, addresses):
            return port
    raise CanvasError(tr('s.noFreePort', low=low, high=high), 503)


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------
def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def process_args(pid):
    if sys.platform == 'darwin':
        try:
            out = subprocess.run(['ps', '-p', str(pid), '-o', 'args='], capture_output=True, text=True, timeout=3, check=False)
            return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ''
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00', b' ').decode(errors='replace').strip()
    except OSError:
        return ''

def _proc_listening_pid(port):
    inodes = set()
    for name in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            lines = Path(name).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) > 9 and parts[3] == '0A' and int(parts[1].rsplit(':', 1)[1], 16) == port:
                inodes.add(parts[9])
    if not inodes:
        return None
    targets = {'socket:[' + inode + ']' for inode in inodes}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for fd in (entry / 'fd').iterdir():
                try:
                    if os.readlink(str(fd)) in targets:
                        return int(entry.name)
                except OSError:
                    continue
        except OSError:
            continue
    return None

def listening_pid(port):
    """pid owning a LISTEN socket on this port (lsof, /proc, ss), or None."""
    lsof = shutil.which('lsof')
    if lsof:
        try:
            out = subprocess.run([lsof, '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'], capture_output=True, text=True, timeout=5, check=False)
            for line in out.stdout.split():
                if line.isdigit():
                    return int(line)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if sys.platform.startswith('linux'):
        found = _proc_listening_pid(port)
        if found:
            return found
        ss = shutil.which('ss')
        if ss:
            try:
                out = subprocess.run([ss, '-ltnp'], capture_output=True, text=True, timeout=5, check=False)
                for line in out.stdout.splitlines():
                    fields = line.split()
                    if len(fields) < 5 or not fields[3].endswith(':' + str(port)) or 'pid=' not in line:
                        continue
                    match = re.search(r'pid=(\d+)', line)
                    if match:
                        return int(match.group(1))
            except (OSError, subprocess.SubprocessError):
                pass
    return None

def terminate_pid(pid, grace=5.0):
    """SIGTERM, then SIGKILL after the grace period. True when the process is gone."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.time() + grace
    while time.time() < deadline:
        if not pid_alive(pid) or _is_zombie(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    time.sleep(0.2)
    return not pid_alive(pid) or _is_zombie(pid)

def _is_zombie(pid):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
        return text.rsplit(')', 1)[1].split()[0] == 'Z'
    except (OSError, IndexError):
        return False

def tail_text(path, limit=1200):
    try:
        data = Path(path).read_bytes()[-limit:]
        return data.decode('utf-8', errors='replace')
    except OSError:
        return ''


# ---------------------------------------------------------------------------
# Canvas directories
# ---------------------------------------------------------------------------
def read_canvas_json(path):
    try:
        data = json.loads((path / 'canvas.json').read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None

def write_json_atomic(path, data):
    tmp = path.with_name('.' + path.name + '.tmp-' + str(os.getpid()) + '-' + secrets.token_hex(3))
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    os.replace(tmp, path)

def find_canvas(runtime, cid):
    """Resolve a canvas id to its directory (direct child of canvases/, never a symlink).

    Accepts the stored form ('1', 'abc123') and the human form ('#1'). A leading '#'
    requires id_scheme "number", so '#234567' does not open a legacy 6-digit id.
    """
    raw = cid.strip() if isinstance(cid, str) else ''
    hashed = raw.startswith('#')
    cid = normalize_canvas_id(cid)
    label = display_canvas_id(cid, 'number' if hashed else None)
    root = canvases_dir(runtime)
    if not root.is_dir():
        raise CanvasError(tr('s.noCanvas', id=label), 404)
    for entry in root.iterdir():
        match = DIR_RE.match(entry.name)
        if not match or match.group(2) != cid or not _is_canvas_dir(entry):
            continue
        if entry.is_symlink() or not entry.is_dir() or entry.parent.resolve() != root.resolve():
            raise CanvasError(tr('s.badCanvasDir', name=entry.name), 400)
        if hashed:
            meta = read_canvas_json(entry)
            scheme = meta.get('id_scheme') if isinstance(meta, dict) else None
            if scheme != 'number':
                raise CanvasError(tr('s.idInvalid'), 400)
        return entry
    raise CanvasError(tr('s.noCanvas', id=label), 404)

def canvas_record(entry):
    """Cheap description of one canvas dir (no network)."""
    match = DIR_RE.match(entry.name)
    port, cid = int(match.group(1)), match.group(2)
    meta = read_canvas_json(entry)
    scheme = meta.get('id_scheme') if isinstance(meta, dict) else None
    record = {'id': cid, 'display_id': display_canvas_id(cid, scheme), 'port': port, 'dir': entry.name,
              'path': str(entry), 'name': None, 'created_at': None, 'project_path': None, 'metadata_missing': False}
    if meta is None or meta.get('id') != cid:
        record['metadata_missing'] = True
        record['name'] = tr('s.metaMissingName')
    else:
        record['name'] = str(meta.get('name') or display_canvas_id(cid, scheme))
        record['created_at'] = meta.get('created_at')
        record['project_path'] = meta.get('project_path') or None
    return record

def scan_canvases(runtime):
    root = canvases_dir(runtime)
    records = []
    if root.is_dir():
        try:
            entries = sorted(root.iterdir(), key=lambda item: item.name)
        except OSError:
            entries = []
        for entry in entries:
            if not DIR_RE.match(entry.name):
                continue
            try:
                if entry.is_symlink() or not entry.is_dir() or not _is_canvas_dir(entry):
                    continue
                records.append(canvas_record(entry))
            except OSError:
                continue  # renamed/removed while scanning
    def check(record):
        if record['metadata_missing']:
            record['status'], record['status_note'] = 'unresponsive', tr('s.metaMissing')
            return record
        record['status'], record['status_note'] = classify_canvas(record['port'], record['id'])
        return record
    if records:
        with ThreadPoolExecutor(max_workers=min(16, len(records))) as pool:
            records = list(pool.map(check, records))
    records.sort(key=_canvas_sort_key)
    return records

def _canvas_sort_key(item):
    """Numbered canvases by numeric id (1, 2, 10), then legacy ids by stored id.

    Directory order is lexicographic ('1', '10', '2'). Six digits without a leading '#'
    on display_id stay with the legacy ids.
    """
    cid = item.get('id') or ''
    display = item.get('display_id') or ''
    if not isinstance(cid, str) or not NUMERIC_ID_RE.fullmatch(cid):
        return (1, cid)
    numbered = (isinstance(display, str) and display.startswith('#')) or len(cid) != 6
    if numbered:
        return (0, int(cid))
    return (1, cid)

def canvas_stats(entry):
    """Numbers shown in the removal confirmation."""
    stats = {'comments_total': 0, 'comments_active': 0, 'snapshots': 0, 'size_bytes': 0}
    db = entry / 'runtime' / 'feedback.sqlite3'
    if db.is_file():
        try:
            con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
            try:
                for (payload,) in con.execute('SELECT payload FROM comments'):
                    stats['comments_total'] += 1
                    try:
                        if not json.loads(payload).get('deleted_at'):
                            stats['comments_active'] += 1
                    except ValueError:
                        stats['comments_active'] += 1
            finally:
                con.close()
        except sqlite3.Error:
            pass
    snaps = entry / 'snapshots'
    if snaps.is_dir():
        stats['snapshots'] = sum(1 for item in snaps.iterdir() if item.is_dir() and not item.is_symlink())
    total = 0
    for base, dirs, files in os.walk(str(entry), followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    stats['size_bytes'] = total
    return stats

def rename_port(cdir, port):
    match = DIR_RE.match(cdir.name)
    target = cdir.with_name('%d-%s' % (port, match.group(2)))
    if target.exists():
        raise CanvasError(tr('s.targetExists', name=target.name), 409)
    os.rename(str(cdir), str(target))
    return target


# ---------------------------------------------------------------------------
# Spawning canvases / list service
# ---------------------------------------------------------------------------
def spawn_detached(command, log_path, cwd):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(str(log_path), 'ab')
    try:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True, close_fds=True, cwd=str(cwd))
    finally:
        log.close()

def keep_reaping(proc):
    """Long-lived callers (the list service) must wait() children or they linger as zombies."""
    threading.Thread(target=proc.wait, daemon=True).start()

def wait_canvas_ready(proc, port, cid, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            return 'exited', code
        state, data = probe_json(port)
        if state == 'ok' and data.get('service') == 'ui-canvas' and data.get('id') == cid and data.get('pid') == proc.pid:
            return 'ok', 0
        time.sleep(0.1)
    try:
        proc.terminate()
    except OSError:
        pass
    return 'timeout', None

def launch_canvas(runtime, cdir, bind, list_port, attempts=5):
    """Start `serve` for cdir; on EADDRINUSE rename to another port and retry. Returns (cdir, pid)."""
    tried = set()
    for _ in range(attempts):
        match = DIR_RE.match(cdir.name)
        port, cid = int(match.group(1)), match.group(2)
        tried.add(port)
        command = [sys.executable, str(app_script(runtime)), 'serve', '--canvas-dir', str(cdir), '--bind', bind,
                   '--list-port', str(list_port), '--runtime-dir', str(runtime)]
        log = cdir / 'logs' / 'serve.log'
        proc = spawn_detached(command, log, runtime)
        state, code = wait_canvas_ready(proc, port, cid)
        if state == 'ok':
            keep_reaping(proc)
            return cdir, proc.pid
        if state == 'exited' and code == EXIT_PORT_IN_USE:
            cdir = rename_port(cdir, pick_free_port(runtime, bind, exclude=tried))
            continue
        detail = tail_text(log)
        raise CanvasError(tr('s.startFailed', state=state, code='' if code is None else tr('s.exitCode', code=code), detail=detail.strip()[-600:]), 500)
    raise CanvasError(tr('s.portConflicts'), 503)

def canvas_result(cdir, pid=None, bind=None, **extra):
    match = DIR_RE.match(cdir.name)
    port, cid = int(match.group(1)), match.group(2)
    meta = read_canvas_json(cdir) or {}
    urls = advertised_urls(port, bind)
    result = {'id': cid, 'display_id': display_canvas_id(cid, meta.get('id_scheme')), 'name': meta.get('name'),
              'port': port, 'dir': str(cdir), 'pid': pid, 'url': urls[0]['url'], 'urls': urls,
              'log': str(cdir / 'logs' / 'serve.log')}
    if any(item['access'] != 'local-only' for item in urls):
        result['warning'] = tr('s.lanWarning')
    result.update(extra)
    return result

def copy_design_source(source, dest, name):
    """Populate dest (an empty temp dir) from the bundled example or an existing project directory."""
    if source in (None, '', 'example', 'sample', 'default', 'example-en', 'example-zh'):
        variant = source[len('example-'):] if source in ('example-en', 'example-zh') else current_lang()
        shutil.copytree(BUNDLE / 'examples' / variant, dest, dirs_exist_ok=True)
        config_path = dest / 'project.json'
        config = json.loads(config_path.read_text())
        config['name'] = name
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
        return
    origin = Path(source).expanduser().resolve()
    if not (origin / 'project.json').is_file():
        raise CanvasError(tr('s.fromBad'))
    for item in ('project.json', 'DESIGN.md', 'README.md'):
        if (origin / item).is_file():
            shutil.copy2(origin / item, dest / item)
    for folder in ('frames', 'media'):
        if (origin / folder).is_dir():
            shutil.copytree(origin / folder, dest / folder, symlinks=False)

def new_canvas(runtime, name, project_path=None, source=None, created_by=None, bind=None, list_port=None):
    bind = bind or default_bind()
    name = (name or '').strip()
    if not name or len(name) > 100:
        raise CanvasError(tr('s.nameLen'))
    if project_path is not None and len(str(project_path)) > 1000:
        raise CanvasError(tr('s.pathLong'))
    list_port = list_port or list_port_value()
    ensure_runtime(runtime)
    sync_app(runtime)
    # Before a number is reserved: an old list still running on this port cannot see canvases/<port>-1.
    upgraded = ensure_numbered_list(runtime, list_port, bind)
    with create_lock(runtime):
        # The number is reserved (and synced) before the directory exists, so a crash cannot reuse it.
        cid = allocate_canvas_id(runtime)
        port = pick_free_port(runtime, bind)
        tmp = canvases_dir(runtime) / ('.tmp-' + cid)
        tmp.mkdir()  # atomic reservation; hidden from scans until renamed
        try:
            copy_design_source(source, tmp, name)
            manifest(tmp)
            write_json_atomic(tmp / 'canvas.json', {
                'schema': 1, 'id': cid, 'id_scheme': 'number', 'name': name, 'project_path': project_path or None,
                'created_at': now(), 'created_by': created_by or None})
            (tmp / 'logs').mkdir(exist_ok=True)
        except Exception:
            shutil.rmtree(str(tmp), ignore_errors=True)
            raise
        cdir = canvases_dir(runtime) / ('%d-%s' % (port, cid))
        os.rename(str(tmp), str(cdir))
        cdir, pid = launch_canvas(runtime, cdir, bind, list_port)
    extra = {}
    if isinstance(upgraded, dict) and upgraded.get('restarted_reason'):
        extra['restarted_reason'] = upgraded['restarted_reason']
        if upgraded.get('note'):
            extra['note'] = upgraded['note']
    return canvas_result(cdir, pid, bind, created=True, **extra)

def start_canvas(runtime, cid, bind=None, list_port=None):
    bind = bind or default_bind()
    list_port = list_port or list_port_value()
    ensure_runtime(runtime)
    sync_app(runtime)
    already = False
    with create_lock(runtime):
        cdir = find_canvas(runtime, cid)
        record = canvas_record(cdir)
        cid = record['id']  # stored form, so '#1' and '1' classify against healthz the same way
        state, note = classify_canvas(record['port'], cid)
        if record['metadata_missing']:
            raise CanvasError(tr('s.metaCannotStart'), 409)
        if state == 'unresponsive':
            raise CanvasError(tr('s.portNotCanvas', port=record['port'], note=note), 409)
        if state == 'running':
            already = True
            health = probe_json(record['port'])[1]
            pid = health.get('pid') if isinstance(health, dict) else None
        else:
            port = record['port']
            if not port_free(port, bind_targets(bind)):
                cdir = rename_port(cdir, pick_free_port(runtime, bind, exclude={port}))
            cdir, pid = launch_canvas(runtime, cdir, bind, list_port)
    # URLs may probe Tailscale (slow when it is down): build them outside the lock
    if already:
        return canvas_result(cdir, pid, bind, already_running=True)
    return canvas_result(cdir, pid, bind, port_changed=(cdir.name != record['dir']))

def serve_process_matches(pid, cdir_name):
    args = process_args(pid)
    return bool(args) and 'canvas.py' in args and re.search(r'(^|\s)serve(\s|$)', args) is not None and cdir_name in args

def stop_canvas(runtime, cid):
    cdir = find_canvas(runtime, cid)
    match = DIR_RE.match(cdir.name)
    port, cid = int(match.group(1)), match.group(2)
    label = display_canvas_id(cid, (read_canvas_json(cdir) or {}).get('id_scheme'))
    pid = listening_pid(port)
    if pid is None:
        state, _ = classify_canvas(port, cid)
        if state == 'stopped':
            return {'id': cid, 'display_id': label, 'port': port, 'stopped': False, 'already_stopped': True}
        raise CanvasError(tr('s.noOwner', port=port), 409)
    if not serve_process_matches(pid, cdir.name):
        raise CanvasError(tr('s.notServe', port=port, pid=pid), 409)
    if not terminate_pid(pid):
        raise CanvasError(tr('s.stopFailed', pid=pid), 500)
    return {'id': cid, 'display_id': label, 'port': port, 'pid': pid, 'stopped': True}

def remove_canvas(runtime, cid):
    """Move the canvas directory into trash/<time>-<dirname>/ (never deletes). Not allowed while running."""
    ensure_runtime(runtime)
    with create_lock(runtime):
        cdir = find_canvas(runtime, cid)
        match = DIR_RE.match(cdir.name)
        port, cid = int(match.group(1)), match.group(2)
        state, _ = classify_canvas(port, cid)
        if state == 'running':
            raise CanvasError(tr('s.removeRunning'), 409)
        owner = listening_pid(port)
        if owner is not None and serve_process_matches(owner, cdir.name):
            raise CanvasError(tr('s.removeRunningPid', pid=owner), 409)
        stats = canvas_stats(cdir)
        trash = runtime / 'trash'
        trash.mkdir(parents=True, exist_ok=True)
        target = trash / (timestamp() + '-' + cdir.name)
        suffix = 1
        while target.exists():
            suffix += 1
            target = trash / (timestamp() + '-' + cdir.name + '-' + str(suffix))
        os.rename(str(cdir), str(target))
    return {'id': cid, 'display_id': display_canvas_id(cid, (read_canvas_json(target) or {}).get('id_scheme')),
            'removed': True, 'trash': str(target), 'stats': stats}

class Handler(RequestMixin, SimpleHTTPRequestHandler):
    def __init__(self, *args, root, ctx=None, **kwargs):
        self.root = root
        self.ctx = ctx or {}
        super().__init__(*args, directory=str(BUNDLE / 'assets'), **kwargs)
    def lang_runtime(self):
        return canvas_runtime_of(self.root)
    def reply_json(self, status, value):
        return self.response(status, value)
    def send_page(self, path):
        if not path.is_file():
            self.send_error(404)
            return
        data = inject_i18n(path.read_text(encoding='utf-8'), self.lang_runtime()).encode('utf-8')
        self.send_body(200, data, 'text/html; charset=utf-8', ('Cache-Control', 'no-store'))
    def log_message(self, format, *args):
        # The list service polls /healthz for every canvas every few seconds; keep it out of the log.
        if getattr(self, 'path', '').startswith('/healthz'):
            return
        super().log_message(format, *args)
    def healthz(self):
        ctx = self.ctx
        meta = read_canvas_json(self.root) or {}
        cid = ctx.get('id')
        return {'service': 'ui-canvas', 'id': cid,
                'display_id': display_canvas_id(cid, meta.get('id_scheme')) if cid else None,
                'name': meta.get('name') or ctx.get('name'),
                'port': ctx.get('port'), 'pid': os.getpid(), 'started_at': ctx.get('started_at'),
                'version': ctx.get('version'), 'list_port': ctx.get('list_port'), 'bind': ctx.get('bind')}
    def response(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_body(status, data, 'application/json; charset=utf-8', ('Cache-Control', 'no-store'))
    def send_file(self, path):
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_body(200, data, self.guess_type(str(path)), ('Cache-Control', 'no-store'))
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/healthz':
            # Answered before manifest(): a broken project.json must not hide a live process.
            return self.response(200, self.healthz())
        if path == '/api/lang':
            return self.lang_get()
        try:
            config, _ = manifest(self.root)
            if path == '/api/project':
                return self.response(200, config)
            if path == '/api/export-ui':
                import importlib.util
                spec = importlib.util.spec_from_file_location('ui_export', BUNDLE / 'scripts/export_ui.py')
                exporter = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(exporter)
                body, filename = exporter.build_export(self.root, BUNDLE, tr, current_lang())
                self.send_body(200, body, 'application/zip', ('Content-Disposition', 'attachment; filename="' + filename + '"'), ('X-UI-Frame-Count', str(len(config['frames']))), ('Cache-Control', 'no-store'))
                return
            if path == '/api/comments':
                return self.response(200, {'comments': read_comments(self.root, config['revision'])})
            if path == '/api/design':
                return self.design_response(self.root)
            if path == '/api/snapshots' or path.startswith('/api/snapshots/'):
                return self.snapshot_get(path, config)
            if path == '/':
                return self.send_page(BUNDLE / 'assets/canvas.html')
            if is_mobile_path(path):
                return self.mobile_get(path, config)
            if path.startswith('/tool/'):
                name = path.removeprefix('/tool/')
                if name not in ('canvas.js', 'canvas.css', 'i18n.js'):
                    return self.send_error(404)
                return self.send_file(BUNDLE / 'assets' / name)
            if path.startswith('/project/'):
                from urllib.parse import unquote
                relative = unquote(path.removeprefix('/project/'))
                target = inside(self.root, relative)
                # Only design content directories are published, never runtime or snapshots.
                if relative.split('/')[0] not in ('frames', 'media'):
                    return self.send_error(403)
                if relative in fragment_paths(config):
                    body = annotated_html(target.read_text()).encode('utf-8')
                    self.send_body(200, body, 'text/html; charset=utf-8', ('Cache-Control', 'no-store'))
                    return
                return self.send_file(target)
            self.send_error(404)
        except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
            self.response(400, {'error': str(error)})
    def mobile_get(self, path, config):
        """GET /m/ : read-only phone preview. Only the exact path /m/ is served (/m redirects); anything else under /m/ is 404."""
        query = urlparse(self.path).query
        if path == '/m':
            self.send_response(301)
            self.send_header('Location', '/m/' + ('?' + query if query else ''))
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if path != '/m/':
            return self.send_error(404)
        params = parse_qs(query, keep_blank_values=True)
        rev = (params.get('rev') or [''])[0]
        want = (params.get('start') or [''])[0]
        try:
            body = render_mobile_page(mobile_boot(self.root, config, rev, want), self.lang_runtime()).encode('utf-8')
            status = 200
        except CanvasError as error:
            body, status = mobile_missing_page().encode('utf-8'), error.status
        self.send_body(status, body, 'text/html; charset=utf-8', ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'))

    def reject_mobile_write(self):
        """The phone preview is read-only: every non-GET request on /m and /m/* is 405."""
        path = urlparse(self.path).path
        if not is_mobile_path(path):
            return False
        data = json.dumps({'error': tr('s.mobileReadonly')}, ensure_ascii=False).encode()
        self.send_body(405, data, 'application/json; charset=utf-8', ('Allow', 'GET'), ('Cache-Control', 'no-store'))
        return True

    def do_HEAD(self):
        if self.reject_mobile_write():
            return
        super().do_HEAD()

    def design_response(self, folder):
        """GET /api/design and /api/snapshots/<rev>/design: {markdown: <text>}, or {markdown: null} when there is no DESIGN.md
        (200, so a canvas without one does not log a failed request in the browser). Read-only, fixed file name."""
        status, text = read_design(folder)
        if status == 'toobig':
            return self.response(413, {'error': tr('s.designTooBig')})
        return self.response(200, {'markdown': text})

    def snapshot_get(self, path, config):
        """Read-only snapshot API: list, project, comments, frames/<file>, media/<file>."""
        rest = path[len('/api/snapshots'):].strip('/')
        if not rest:
            return self.response(200, {'snapshots': list_snapshots(self.root, config['revision']), 'current_revision': config['revision']})
        head, _, tail = rest.partition('/')
        snap = snapshot_dir(self.root, unquote(head))
        if snap is None:
            return self.response(404, {'error': tr('s.noSnapshot')})
        sub = unquote(tail)
        if sub == 'project':
            project = snapshot_json(snap, 'project.json')
            if not isinstance(project, dict):
                return self.response(404, {'error': tr('s.snapNoProject')})
            return self.response(200, project)
        if sub == 'comments':
            return self.response(200, {'comments': snapshot_comments(snap)})
        if sub == 'design':
            return self.design_response(snap)
        target = snapshot_file(snap, sub)
        if target is None:
            return self.response(404, {'error': tr('s.noFile')})
        project = snapshot_json(snap, 'project.json')
        frame_paths = fragment_paths(project)
        if sub in frame_paths and target.suffix == '.html':
            body = annotated_html(target.read_text(encoding='utf-8')).encode('utf-8')
            self.send_body(200, body, 'text/html; charset=utf-8', ('Cache-Control', 'no-store'))
            return
        return self.send_file(target)

    def reject_snapshot_write(self):
        """Snapshots are history: every non-GET request on /api/snapshots* is refused."""
        path = urlparse(self.path).path
        if path != '/api/snapshots' and not path.startswith('/api/snapshots/'):
            return False
        data = json.dumps({'error': tr('s.snapReadonly')}, ensure_ascii=False).encode()
        self.send_body(405, data, 'application/json; charset=utf-8', ('Allow', 'GET'), ('Cache-Control', 'no-store'))
        return True

    def do_PATCH(self):
        if self.reject_mobile_write() or self.reject_snapshot_write():
            return
        self.manage_comment(False)

    def do_DELETE(self):
        if self.reject_mobile_write() or self.reject_snapshot_write():
            return
        self.manage_comment(True)

    def do_PUT(self):
        if not (self.reject_mobile_write() or self.reject_snapshot_write()):
            self.send_error(501)

    def manage_comment(self, deleting):
        path = urlparse(self.path).path
        if path == '/api/comments/batch':
            return self.manage_batch(deleting)
        if not path.startswith('/api/comments/'):
            return self.response(404, {'error': tr('s.noEndpoint')})
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.response(403, {'error': tr('s.originMismatch')})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 24000:
                raise ValueError(tr('s.badSize'))
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError(tr('s.bodyObject'))
            config, _ = manifest(self.root)
            if data.get('project_id') != config['id'] or data.get('revision') != config['revision']:
                raise ValueError(tr('s.projectMismatch'))
            cid = path.removeprefix('/api/comments/')
            con = database(self.root)
            try:
                with con:
                    row = con.execute('SELECT payload FROM comments WHERE id=? AND project=? AND revision=?', (cid, config['id'], config['revision'])).fetchone()
                    if row is None:
                        return self.response(404, {'error': tr('s.noComment')})
                    comment = json.loads(row[0])
                    if deleting:
                        # Keep a recovery record, but exclude it from all normal lists/exports.
                        comment['deleted_at'] = now()
                    else:
                        if comment.get('deleted_at'):
                            return self.response(404, {'error': tr('s.commentDeleted')})
                        if 'text' in data:
                            text = data['text']
                            if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
                                raise ValueError(tr('s.commentLen'))
                            comment['text'] = text.strip()
                        if 'status' in data:
                            if data['status'] not in STATES:
                                raise ValueError(tr('s.badStatus'))
                            comment['status'] = data['status']
                        if not any(key in data for key in ('text', 'status')):
                            raise ValueError(tr('s.nothingToUpdate'))
                        comment['updated_at'] = now()
                    con.execute('UPDATE comments SET payload=? WHERE id=?', (json.dumps(comment, ensure_ascii=False), cid))
            finally:
                con.close()
            self.response(200, {'comment': comment})
        except (ValueError, TypeError, KeyError, OSError) as error:
            self.response(400, {'error': str(error)})

    def manage_batch(self, deleting):
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.response(403, {'error': tr('s.originMismatch')})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 24000:
                raise ValueError(tr('s.badSize'))
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError(tr('s.bodyObject'))
            config, _ = manifest(self.root)
            if data.get('project_id') != config['id'] or data.get('revision') != config['revision']:
                raise ValueError(tr('s.projectMismatch'))
            ids = data.get('ids')
            if not isinstance(ids, list) or not 0 < len(ids) <= 300 or any(not isinstance(cid, str) for cid in ids) or len(set(ids)) != len(ids):
                raise ValueError(tr('s.pickCount'))
            if not deleting and data.get('status') not in STATES:
                raise ValueError(tr('s.badStatus'))
            updated = []
            con = database(self.root)
            try:
                with con:
                    for cid in ids:
                        row = con.execute('SELECT payload FROM comments WHERE id=? AND project=? AND revision=?', (cid, config['id'], config['revision'])).fetchone()
                        if row is None:
                            raise ValueError(tr('s.someMissing'))
                        comment = json.loads(row[0])
                        if comment.get('deleted_at'):
                            raise ValueError(tr('s.someDeleted'))
                        if deleting:
                            comment['deleted_at'] = now()
                        else:
                            comment['status'] = data['status']
                            comment['updated_at'] = now()
                        con.execute('UPDATE comments SET payload=? WHERE id=?', (json.dumps(comment, ensure_ascii=False), cid))
                        updated.append(comment)
            finally:
                con.close()
            self.response(200, {'comments': updated})
        except (ValueError, TypeError, KeyError, OSError) as error:
            self.response(400, {'error': str(error)})

    def do_POST(self):
        if self.reject_mobile_write() or self.reject_snapshot_write():
            return
        if urlparse(self.path).path == '/api/lang':
            return self.lang_post()
        if self.path != '/api/comments':
            return self.response(404, {'error': tr('s.noEndpoint')})
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc != self.headers.get('Host'):
            return self.response(403, {'error': tr('s.originMismatch')})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 24000:
                raise ValueError(tr('s.badSize'))
            data = json.loads(self.rfile.read(length))
            config, targets = manifest(self.root)
            if data.get('project_id') != config['id'] or data.get('revision') != config['revision']:
                raise ValueError(tr('s.projectMismatch'))
            target = data.get('target')
            if target not in targets:
                raise ValueError(tr('s.noElement'))
            text = data.get('text')
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
                raise ValueError(tr('s.commentLen'))
            cid = data.get('client_id')
            if not isinstance(cid, str) or not 1 <= len(cid) <= 100:
                raise ValueError(tr('s.badClientId'))
            frame, label, digest, ref = targets[target]
            # Targets outside every frame belong to the canvas: no frame id, and the frame column says "Canvas".
            comment = {'id': str(uuid.uuid4()), 'project_id': config['id'], 'revision': config['revision'], 'frame_id': frame['id'] if frame else '', 'frame': frame['title'] if frame else tr('c.canvas'), 'target': target, 'element': label, 'text': text.strip(), 'created_at': now(), 'status': 'pending', 'replies': [], 'source_hash': digest, 'excerpt': str(data.get('excerpt', label))[:500]}
            # Targets outside the phone also keep the click position, relative to the frame (title, subtitle) or the board (notes). Targets inside the phone are stored exactly as before.
            position = data.get('position')
            if ref and isinstance(position, dict) and all(isinstance(position.get(axis), (int, float)) and not isinstance(position.get(axis), bool) and abs(position[axis]) <= 1000 for axis in ('x', 'y')):
                comment['position'] = {'x': round(float(position['x']), 6), 'y': round(float(position['y']), 6)}
                comment['position_ref'] = ref
            con = database(self.root)
            try:
                with con:
                    con.execute('INSERT OR IGNORE INTO comments VALUES (?,?,?,?,?)', (comment['id'], config['id'], config['revision'], cid, json.dumps(comment, ensure_ascii=False)))
                    saved = json.loads(con.execute('SELECT payload FROM comments WHERE client_id=?', (cid,)).fetchone()[0])
            finally:
                con.close()
            self.response(201, {'comment': saved})
        except (ValueError, TypeError, KeyError) as error:
            self.response(400, {'error': str(error)})


def canvas_runtime_of(root):
    root = Path(root)
    return root.parent.parent if root.parent.name == 'canvases' else runtime_dir()

def bind_servers(bind, port, handler, always_local=True):
    """Bind one handler on every requested address. Returns (servers, advertised, errors, port).

    Loopback is always added (unless a wildcard covers it) and is required: if it cannot be bound
    everything is released and OSError is raised, so callers can retry on another port."""
    discovered = access_addresses() if bind == 'auto' or not bind_is_loopback(bind) else []
    known = {value: kind for value, kind in discovered}
    local_covered = False
    if bind == 'auto':
        advertised = list(discovered)
        listeners = [value for value, _ in advertised]
    else:
        listeners = [value.strip() for value in bind.split(',') if value.strip()]
        if not listeners:
            raise ValueError(tr('s.bindNeedsOne'))
        if '0.0.0.0' in listeners or '::' in listeners:
            # A wildcard already covers every interface (loopback too); advertise the concrete ones.
            wildcard = '0.0.0.0' if '0.0.0.0' in listeners else '::'
            listeners = [wildcard]
            advertised = discovered + [('127.0.0.1', 'local-only')]
            local_covered = True
        else:
            advertised = [(value, known.get(value, 'local-only' if value in LOOPBACK_HOSTS else 'explicit')) for value in listeners]
    if always_local and not local_covered and '127.0.0.1' not in listeners:
        listeners.append('127.0.0.1')
        advertised = list(advertised) + [('127.0.0.1', 'local-only')]
    servers = []
    errors = []
    for address in listeners:
        try:
            server = ThreadingHTTPServer((address, port), handler)
        except OSError as error:
            errors.append({'bind': address, 'error': str(error), 'errno': error.errno})
            continue
        servers.append((address, server))
        if port == 0:
            port = server.server_port
    if not servers:
        raise OSError(errors[0]['errno'] if errors else errno.EADDRNOTAVAIL,
                      tr('s.bindNone') + '; '.join(f"{item['bind']}: {item['error']}" for item in errors))
    if always_local and not local_covered:
        failed = [item for item in errors if item['bind'] == '127.0.0.1']
        if failed:
            for _, server in servers:
                server.server_close()
            raise OSError(failed[0]['errno'] or errno.EADDRINUSE, tr('s.bindLoopback') + failed[0]['error'])
    # Drop advertised entries that failed to bind
    failed_binds = {item['bind'] for item in errors}
    advertised = [item for item in advertised if item[0] not in failed_binds]
    return servers, advertised, errors, port

def serve_all(servers, advertised, port, on_ready):
    """Serve servers[0] on this thread, the rest in daemons. Calls on_ready(urls, port) first."""
    workers = []
    for _, server in servers[1:]:
        worker = threading.Thread(target=server.serve_forever, name=SERVE_MARKER, daemon=True)
        worker.start()
        workers.append(worker)
    urls = [{'url': url_for(address, port), 'access': kind, 'bind': address} for address, kind in advertised]
    on_ready(urls, port)
    def _stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _stop)
    try:
        servers[0][1].serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for (_, server), worker in zip(servers[1:], workers):
            if worker.is_alive():
                server.shutdown()
        for _, server in servers:
            server.server_close()


# ---------------------------------------------------------------------------
# List service
# ---------------------------------------------------------------------------
def same_origin(handler):
    """Writes accept only same-origin browser requests (Origin == Host; cross-site Sec-Fetch-Site refused)."""
    origin = handler.headers.get('Origin')
    if origin and urlparse(origin).netloc != handler.headers.get('Host'):
        return False
    site = handler.headers.get('Sec-Fetch-Site')
    if site and site not in ('same-origin', 'none'):
        return False
    return True

class ScanCache:
    def __init__(self, runtime, ttl=2.0):
        self.runtime = runtime
        self.ttl = ttl
        self.lock = threading.Lock()
        self.at = 0.0
        self.value = []
    def get(self):
        with self.lock:
            if time.time() - self.at > self.ttl:
                self.value = scan_canvases(self.runtime)
                self.at = time.time()
            return list(self.value)
    def invalidate(self):
        with self.lock:
            self.at = 0.0

def public_record(record):
    keep = ('id', 'display_id', 'name', 'port', 'status', 'status_note', 'dir', 'created_at', 'project_path', 'metadata_missing')
    return {key: record.get(key) for key in keep}

class ListHandler(RequestMixin, SimpleHTTPRequestHandler):
    """Canvas list page + API. Reads canvases/ from disk on every (cached) request: no registry."""
    def __init__(self, *args, ctx, **kwargs):
        self.ctx = ctx
        super().__init__(*args, directory=str(BUNDLE / 'assets'), **kwargs)
    def lang_runtime(self):
        return self.ctx['runtime']
    def lang_changed(self):
        self.ctx['cache'].invalidate()
    def reply_json(self, status, value):
        return self.reply(status, value)
    def log_message(self, format, *args):
        if getattr(self, 'path', '').startswith('/healthz'):
            return
        super().log_message(format, *args)
    def do_HEAD(self):
        self.send_error(405)
    def reply(self, status, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_body(status, data, 'application/json; charset=utf-8', ('Cache-Control', 'no-store'))
    def page(self):
        target = BUNDLE / 'assets' / 'list.html'
        if not target.is_file():
            return self.send_error(404)
        data = inject_i18n(target.read_text(encoding='utf-8'), self.ctx['runtime']).encode('utf-8')
        self.send_body(200, data, 'text/html; charset=utf-8', ('Cache-Control', 'no-store'))
    def healthz(self):
        ctx = self.ctx
        return {'service': 'ui-canvas-list', 'pid': os.getpid(), 'runtime': str(ctx['runtime']), 'version': ctx['version'],
                'port': ctx['port'], 'started_at': ctx['started_at'], 'bind': ctx.get('bind'),
                'id_schemes': list(ID_SCHEMES)}
    def route(self):
        path = urlparse(self.path).path
        match = re.match(r'^/api/canvases/([^/]+)(?:/(start|stop))?/?$', path)
        if not match:
            return path, None, None
        return path, unquote(match.group(1)), match.group(2)
    def do_GET(self):
        path, cid, action = self.route()
        try:
            if path == '/healthz':
                return self.reply(200, self.healthz())
            if path in ('/', '/index.html'):
                return self.page()
            if path == '/api/lang':
                return self.lang_get()
            if path == '/tool/i18n.js':
                return self.tool_file('i18n.js')
            if path == '/api/canvases':
                items = [public_record(item) for item in self.ctx['cache'].get()]
                return self.reply(200, {'canvases': items, 'list_port': self.ctx['port'], 'version': self.ctx['version']})
            if cid is not None and action is None:
                entry = find_canvas(self.ctx['runtime'], cid)
                record = public_record(canvas_record(entry))
                cid = DIR_RE.match(entry.name).group(2)
                state, note = classify_canvas(int(DIR_RE.match(entry.name).group(1)), cid)
                record['status'], record['status_note'] = ('unresponsive', tr('s.metaMissing')) if record['metadata_missing'] else (state, note)
                record['stats'] = canvas_stats(entry)
                return self.reply(200, record)
            self.send_error(404)
        except CanvasError as error:
            self.reply(error.status, {'error': str(error)})
    def mutate(self, method):
        path, cid, action = self.route()
        if cid is None:
            return self.reply(404, {'error': tr('s.noEndpoint')})
        if not same_origin(self):
            return self.reply(403, {'error': tr('s.originMismatch')})
        runtime = self.ctx['runtime']
        try:
            if method == 'POST' and action == 'start':
                result = start_canvas(runtime, cid, self.ctx['bind'], self.ctx['port'])
            elif method == 'POST' and action == 'stop':
                result = stop_canvas(runtime, cid)
            elif method == 'DELETE' and action is None:
                result = remove_canvas(runtime, cid)
            else:
                return self.reply(405, {'error': tr('s.methodNotAllowed')})
        except CanvasError as error:
            return self.reply(error.status, {'error': str(error)})
        finally:
            self.ctx['cache'].invalidate()
        self.reply(200, result)
    def tool_file(self, name):
        target = BUNDLE / 'assets' / name
        data = target.read_bytes()
        self.send_body(200, data, 'text/javascript; charset=utf-8', ('Cache-Control', 'no-store'))
    def do_POST(self):
        if urlparse(self.path).path == '/api/lang':
            return self.lang_post()
        self.mutate('POST')
    def do_DELETE(self):
        self.mutate('DELETE')

def probe_list(port):
    state, data = probe_json(port)
    if state == 'ok' and data.get('service') == 'ui-canvas-list':
        return 'ok', data
    if state == 'refused':
        return 'refused', None
    return 'foreign', data

def run_list_serve(args):
    runtime = runtime_dir(args.runtime_dir)
    ensure_runtime(runtime)
    try_pin_app(runtime)
    port = list_port_value(args.list_port)
    ctx = {'runtime': runtime, 'version': bundle_version(), 'port': port, 'started_at': now(), 'bind': args.bind,
           'loopback_only': bind_is_loopback(args.bind), 'cache': ScanCache(runtime)}
    try:
        servers, advertised, bind_errors, port = bind_servers(args.bind, port, partial(ListHandler, ctx=ctx))
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, 48, 98):
            state, data = probe_list(port)
            if state == 'ok':
                print(json.dumps({'note': tr('s.listRunning'), 'pid': data.get('pid')}, ensure_ascii=False), flush=True)
                sys.exit(0)
            print(json.dumps({'error': tr('s.portBusy', port=port)}, ensure_ascii=False), file=sys.stderr, flush=True)
            sys.exit(EXIT_PORT_IN_USE)
        raise
    binds = [value for value, _ in servers]
    def _ready(urls, port):
        print(json.dumps({'service': 'ui-canvas-list', 'url': urls[0]['url'], 'urls': urls, 'binds': binds, 'port': port,
                          'bind_errors': bind_errors, 'pid': os.getpid(), 'runtime': str(runtime),
                          'version': ctx['version']}, ensure_ascii=False), flush=True)
    serve_all(servers, advertised, port, _ready)

def launchctl_target(label):
    return 'gui/%d/%s' % (os.getuid(), label)

def launchd_loaded(label):
    launchctl = shutil.which('launchctl')
    if not launchctl:
        return False
    try:
        return subprocess.run([launchctl, 'print', launchctl_target(label)], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def kickstart_and_wait(port, wait):
    """Ask launchd to start the (loaded) list-service job and wait for its /healthz. False when it did not come up."""
    label = os.environ.get('UI_CANVAS_LAUNCH_LABEL', LAUNCH_LABEL)
    try:
        subprocess.run([shutil.which('launchctl'), 'kickstart', launchctl_target(label)], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError, TypeError):
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        if probe_list(port)[0] == 'ok':
            return True
        time.sleep(0.2)
    return False

def list_has_numbered_ids(data):
    """True when this list process can see canvases/<port>-1, not only 6-character ids."""
    schemes = data.get('id_schemes') if isinstance(data, dict) else None
    return isinstance(schemes, (list, tuple)) and 'number' in schemes

def _describe_list(runtime, port, bind, data, started, restarted, for_ids):
    """ensure-list JSON. URLs are built by the caller, outside list.lock (Tailscale can be slow)."""
    urls = advertised_urls(port, data.get('bind') or bind)
    result = {'ok': True, 'started': started, 'restarted': restarted, 'url': urls[0]['url'], 'urls': urls,
              'local_url': url_for('127.0.0.1', port), 'port': port, 'pid': data.get('pid'), 'bind': data.get('bind') or bind,
              'runtime': data.get('runtime'), 'version': data.get('version'), 'id_schemes': data.get('id_schemes'),
              'log': str(runtime / 'logs' / 'list.log')}
    # On stdout, not stderr: a stderr line is easy to treat as a failure when the restart worked.
    if restarted and for_ids:
        result['restarted_reason'] = 'id_schemes'
        result['note'] = tr('s.listRestartedForIds')
    return result

def ensure_list(runtime, port, bind=None, restart_if_outdated=False, wait=15.0):
    bind = bind or default_bind()
    ensure_runtime(runtime)

    def check_runtime(data):
        if data.get('runtime') and str(data['runtime']) != str(runtime):
            raise CanvasError(tr('s.listOtherRuntime', port=port, runtime=data['runtime']), 409)

    def already_good(data):
        # A version-hash mismatch restarts only with --restart-if-outdated (an older skill must
        # not be able to downgrade a newer list). Missing id_schemes is different: that process
        # still has the pre-numbering directory pattern in memory and cannot see or stop canvas 1.
        if not list_has_numbered_ids(data):
            return False
        if restart_if_outdated and data.get('version') != bundle_version(BUNDLE):
            return False
        return True

    state, data = probe_list(port)
    if state == 'foreign':
        raise CanvasError(tr('s.portForeign', port=port), 409)
    if state == 'ok':
        check_runtime(data)
        if already_good(data):
            return _describe_list(runtime, port, bind, data, False, False, False)

    started = False
    restarted = False
    for_ids = False
    # Probe, decide and terminate under one lock. Two `new`s must not both try to kill the old list.
    with file_lock(runtime / 'run' / 'list.lock', max(30.0, float(wait) + 20.0)):
        state, data = probe_list(port)
        if state == 'foreign':
            raise CanvasError(tr('s.portBusy', port=port), 409)
        if state == 'ok':
            check_runtime(data)
            if already_good(data):
                state = 'ok'  # the process ahead of us already restarted it
            else:
                for_ids = not list_has_numbered_ids(data)
                sync_app(runtime)
                want = bundle_version(runtime / 'app')
                label = os.environ.get('UI_CANVAS_LAUNCH_LABEL', LAUNCH_LABEL)
                managed = launchd_loaded(label)
                if managed:
                    subprocess.run([shutil.which('launchctl'), 'kickstart', '-k', launchctl_target(label)], capture_output=True, timeout=30)
                else:
                    pid = data.get('pid')
                    owner = listening_pid(port)
                    if not (isinstance(pid, int) and owner == pid and 'canvas.py' in process_args(pid) and 'list-serve' in process_args(pid)):
                        raise CanvasError(tr('s.listOldUnknown'), 409, code='listOldUnknown')
                    if not terminate_pid(pid):
                        raise CanvasError(tr('s.listOldStop'), 500)
                restarted = True
                deadline = time.time() + wait
                while time.time() < deadline:
                    state, data = probe_list(port)
                    if state == 'ok' and data.get('version') == want and (not for_ids or list_has_numbered_ids(data)):
                        break
                    if state == 'refused' and not managed:
                        break
                    time.sleep(0.2)
                # launchd (or anything else) brought the old binary back. Do not report success
                # and do not let the next `new` spend another 15s repeating it in silence.
                if state == 'ok' and for_ids and not list_has_numbered_ids(data):
                    raise CanvasError(tr('s.listStillUnnumbered'), 409, code='listStillUnnumbered')
        if state != 'ok':
            sync_app(runtime)
            if launchd_loaded(os.environ.get('UI_CANVAS_LAUNCH_LABEL', LAUNCH_LABEL)) and kickstart_and_wait(port, min(wait, 8.0)):
                # a loaded LaunchAgent owns the list service: let launchd start it (stays supervised) instead of a stray Popen
                state, data = probe_list(port)
                started = True
            else:
                command = [sys.executable, str(app_script(runtime)), 'list-serve', '--runtime-dir', str(runtime), '--list-port', str(port), '--bind', bind]
                log = runtime / 'logs' / 'list.log'
                proc = spawn_detached(command, log, runtime)
                deadline = time.time() + wait
                data = None
                while time.time() < deadline:
                    code = proc.poll()
                    state, found = probe_list(port)
                    if state == 'ok' and found.get('pid') == proc.pid:
                        keep_reaping(proc)
                        data, started = found, True
                        break
                    if code is not None:
                        if state == 'ok':  # another instance won the race
                            data = found
                            break
                        raise CanvasError(tr('s.listStartFailed', code=code, detail=tail_text(log).strip()[-600:]), 500)
                    time.sleep(0.1)
                if data is None:
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    raise CanvasError(tr('s.listStartTimeout', detail=tail_text(log).strip()[-600:]), 500)
            if for_ids and not list_has_numbered_ids(data):
                raise CanvasError(tr('s.listStillUnnumbered'), 409, code='listStillUnnumbered')
    # URLs may probe Tailscale (slow when it is down): build them outside the lock
    return _describe_list(runtime, port, bind, data, started, restarted, for_ids)

def ensure_numbered_list(runtime, port, bind=None):
    """Restart this runtime's list when it cannot see numbered canvases.

    Called by `new` before a number is allocated, and the same check lives in ensure-list
    so the usual first step does it too. A list that is down, foreign, or bound to another
    runtime is left alone: `new` must still work when the list port belongs to someone else.
    The restart keeps the bind the running list reported. listOldUnknown is retried once:
    another `new` may have finished the restart while this one was deciding.
    """
    state, data = probe_list(port)
    if state != 'ok' or not isinstance(data, dict):
        return None
    reported = data.get('runtime')
    if reported and str(reported) != str(runtime):
        return None
    if list_has_numbered_ids(data):
        return None
    try:
        return ensure_list(runtime, port, data.get('bind') or bind, restart_if_outdated=False)
    except CanvasError as error:
        if error.code != 'listOldUnknown':
            raise
        state, again = probe_list(port)
        if (state == 'ok' and isinstance(again, dict) and list_has_numbered_ids(again)
                and (not again.get('runtime') or str(again.get('runtime')) == str(runtime))):
            return ensure_list(runtime, port, again.get('bind') or data.get('bind') or bind, restart_if_outdated=False)
        raise

def render_plist(label, python, script, runtime, port, log_dir):
    template = (BUNDLE / 'scripts' / 'ui-canvas-list.plist.template').read_text()
    values = {'@LABEL@': label, '@PYTHON@': python, '@SCRIPT@': script, '@RUNTIME@': str(runtime), '@PORT@': str(port),
              '@LOG@': str(log_dir / 'list.log'), '@HOME@': str(Path.home())}
    for key, value in values.items():
        template = template.replace(key, xml_escape(value))
    plistlib.loads(template.encode('utf-8'))  # must be valid
    return template

def plist_path_for(label, plist_dir=None):
    base = Path(plist_dir).expanduser() if plist_dir else Path.home() / 'Library' / 'LaunchAgents'
    return base / (label + '.plist')

def run_install_list_agent(args):
    runtime = runtime_dir(args.runtime_dir)
    port = list_port_value(args.list_port)
    label = args.label
    target = plist_path_for(label, args.plist_dir)
    plan = {'label': label, 'plist': str(target), 'runtime': str(runtime), 'port': port, 'load': not args.no_load}
    if not args.yes:
        plan['dry_run'] = True
        plan['note'] = tr('s.planNoYes1')
        plan['plist_content'] = render_plist(label, sys.executable, str(runtime / 'app' / 'scripts' / 'canvas.py'), runtime, port, runtime / 'logs')
        return emit(plan)
    if not args.no_load and not shutil.which('launchctl'):
        fail(tr('s.noLaunchctl'), 2)
    ensure_runtime(runtime)
    sync_app(runtime)
    content = render_plist(label, sys.executable, str(runtime / 'app' / 'scripts' / 'canvas.py'), runtime, port, runtime / 'logs')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    plan['written'] = True
    if not args.no_load:
        launchctl = shutil.which('launchctl')
        subprocess.run([launchctl, 'bootout', launchctl_target(label)], capture_output=True, timeout=30)
        result = subprocess.run([launchctl, 'bootstrap', 'gui/%d' % os.getuid(), str(target)], capture_output=True, text=True, timeout=30)
        plan['bootstrap_returncode'] = result.returncode
        if result.returncode != 0:
            plan['bootstrap_error'] = result.stderr.strip()
    emit(plan)

def run_uninstall_list_agent(args):
    runtime = runtime_dir(args.runtime_dir)
    label = args.label
    target = plist_path_for(label, args.plist_dir)
    plan = {'label': label, 'plist': str(target), 'exists': target.is_file(), 'unload': not args.no_load}
    if not args.yes:
        plan['dry_run'] = True
        plan['note'] = tr('s.planNoYes2')
        return emit(plan)
    if not args.no_load:
        launchctl = shutil.which('launchctl')
        if launchctl:
            subprocess.run([launchctl, 'bootout', launchctl_target(label)], capture_output=True, timeout=30)
    if target.is_file():
        trash = runtime / 'trash'
        trash.mkdir(parents=True, exist_ok=True)
        moved = trash / (timestamp() + '-' + target.name)
        shutil.move(str(target), str(moved))  # keep a copy; never delete
        plan['moved_to'] = str(moved)
    emit(plan)


def resolve_root(args, parser):
    if getattr(args, 'canvas', None):
        return find_canvas(runtime_dir(args.runtime_dir), args.canvas)
    if getattr(args, 'project_dir', None):
        return args.project_dir.expanduser().resolve()
    parser.error(tr('s.needCanvas'))

def run_serve(args, parser):
    cdir_arg = args.canvas_dir
    list_port = list_port_value(args.list_port)
    if cdir_arg:
        root = cdir_arg.expanduser().resolve()
        match = DIR_RE.match(root.name)
        if not match:
            parser.error(tr('s.canvasDirName'))
        port, cid = int(match.group(1)), match.group(2)
        if args.port is not None and args.port != port:
            parser.error(tr('s.portDirMismatch'))
        meta = read_canvas_json(root)
        if not meta or meta.get('id') != cid:
            print(json.dumps({'error': tr('s.canvasJsonBad')}, ensure_ascii=False), file=sys.stderr)
            sys.exit(2)
        name = meta.get('name')
    else:
        # Compatibility mode: serve any project directory on --port (no id/healthz identity).
        root = args.project_dir.expanduser().resolve()
        port, cid, name, meta = args.port or 8765, None, None, None
    try:
        manifest(root)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'warning': tr('s.projectUnavailable', error=error)}, ensure_ascii=False), file=sys.stderr, flush=True)
    ctx = {'id': cid, 'name': name, 'port': port, 'started_at': now(), 'version': bundle_version(), 'list_port': list_port,
           'bind': args.bind, 'loopback_only': bind_is_loopback(args.bind)}
    try:
        servers, advertised, bind_errors, port = bind_servers(args.bind, port, partial(Handler, root=root, ctx=ctx))
    except ValueError as error:
        parser.error(str(error))
    except OSError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr, flush=True)
        sys.exit(EXIT_PORT_IN_USE if error.errno in (errno.EADDRINUSE, 48, 98) else 1)
    ctx['port'] = port
    binds = [address for address, _ in servers]
    def _ready(urls, port):
        print(json.dumps({'service': 'ui-canvas', 'id': cid, 'display_id': display_canvas_id(cid, (meta or {}).get('id_scheme')) if cid else None,
                          'url': urls[0]['url'], 'urls': urls, 'bind': binds[0], 'binds': binds,
                          'port': port, 'bind_errors': bind_errors, 'project_dir': str(root), 'pid': os.getpid(),
                          'version': ctx['version'], 'serve_marker': SERVE_MARKER}, ensure_ascii=False), flush=True)
    serve_all(servers, advertised, port, _ready)

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--runtime-dir', help=tr('cli.runtimeDir'))
    common.add_argument('--list-port', type=int, default=None, help=tr('cli.listPort'))
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest='command', required=True)
    def add(name, help_text, **kwargs):
        return sub.add_parser(name, parents=[common], help=help_text, **kwargs)
    def canvas_arg(p, required=False):
        p.add_argument('--canvas', help=tr('cli.canvasId'), required=required)
    def bind_arg(p):
        p.add_argument('--bind', '--host', dest='bind', default=default_bind(), help=tr('cli.bind'))
    p = add('ensure-list', tr('cli.ensureList'))
    bind_arg(p)
    p.add_argument('--restart-if-outdated', action='store_true', help=tr('cli.restartOutdated'))
    p = add('list-serve', tr('cli.listServe'))
    bind_arg(p)
    p = add('new', tr('cli.new'))
    p.add_argument('--name', required=True)
    p.add_argument('--project-path', help=tr('cli.projectPath'))
    p.add_argument('--from', dest='source', help=tr('cli.from'))
    p.add_argument('--created-by')
    bind_arg(p)
    p = add('serve', tr('cli.serve'))
    p.add_argument('--canvas-dir', type=Path)
    p.add_argument('--project-dir', type=Path, help=tr('cli.projectDir'))
    p.add_argument('--port', type=int, default=None)
    bind_arg(p)
    p = add('start', tr('cli.start'))
    canvas_arg(p, True)
    bind_arg(p)
    p = add('stop', tr('cli.stop'))
    canvas_arg(p, True)
    p = add('list', tr('cli.list'))
    p = add('services', tr('cli.services'))
    p = add('remove', tr('cli.remove'))
    canvas_arg(p, True)
    p.add_argument('--yes', action='store_true')
    p = add('install-list-agent', tr('cli.installAgent'))
    p.add_argument('--label', default=LAUNCH_LABEL)
    p.add_argument('--plist-dir', help=tr('cli.plistDir'))
    p.add_argument('--no-load', action='store_true', help=tr('cli.noLoad'))
    p.add_argument('--yes', action='store_true')
    p = add('uninstall-list-agent', tr('cli.uninstallAgent'))
    p.add_argument('--label', default=LAUNCH_LABEL)
    p.add_argument('--plist-dir')
    p.add_argument('--no-load', action='store_true')
    p.add_argument('--yes', action='store_true')
    p = add('lang', tr('cli.lang'))
    p.add_argument('value', nargs='?', choices=['zh', 'en', 'auto'], help=tr('cli.langValue'))
    p = add('init', tr('cli.init'))
    p.add_argument('--project-dir', type=Path, required=True)
    for name, help_text in (('comments', tr('cli.comments')), ('reply', tr('cli.reply')), ('snapshot', tr('cli.snapshot'))):
        p = add(name, help_text)
        canvas_arg(p)
        p.add_argument('--project-dir', type=Path)
        if name == 'comments':
            p.add_argument('--all', action='store_true')
        if name == 'reply':
            p.add_argument('--comment-id')
            p.add_argument('--text')
            p.add_argument('--status', choices=STATES, default='changed')
    return root

def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args, parser)
    except CanvasError as error:
        fail(str(error), 3 if error.status == 409 else 1, status=error.status)

def dispatch(args, parser):
    command = args.command
    if command == 'list-serve':
        return run_list_serve(args)
    if command == 'serve':
        if not args.canvas_dir and not args.project_dir:
            parser.error(tr('s.serveNeeds'))
        return run_serve(args, parser)
    if command == 'install-list-agent':
        return run_install_list_agent(args)
    if command == 'uninstall-list-agent':
        return run_uninstall_list_agent(args)
    runtime = runtime_dir(args.runtime_dir)
    list_port = list_port_value(args.list_port)
    if command == 'lang':
        if args.value:
            save_lang(runtime, None if args.value == 'auto' else args.value)
        state = lang_state(runtime)
        state['effective'] = cli_lang()
        return emit(state)
    if command == 'ensure-list':
        return emit(ensure_list(runtime, list_port, args.bind, args.restart_if_outdated))
    if command == 'new':
        return emit(new_canvas(runtime, args.name, args.project_path, args.source, args.created_by, args.bind, list_port))
    if command == 'start':
        return emit(start_canvas(runtime, args.canvas, args.bind, list_port))
    if command == 'stop':
        return emit(stop_canvas(runtime, args.canvas))
    if command in ('list', 'services'):
        items = scan_canvases(runtime)
        return emit({'runtime': str(runtime), 'list_port': list_port, 'canvases': items})
    if command == 'remove':
        if not args.yes:
            parser.error(tr('s.removeNeedsYes'))
        return emit(remove_canvas(runtime, args.canvas))
    if command == 'init':
        root = args.project_dir.expanduser().resolve()
        if (root / 'project.json').exists():
            parser.error(tr('s.projectExists'))
        shutil.copytree(BUNDLE / 'examples' / current_lang(), root, dirs_exist_ok=True)
        config, _ = manifest(root)
        return print(json.dumps({'project_dir': str(root), 'project_id': config['id']}, ensure_ascii=False))
    root = resolve_root(args, parser)
    config, _ = manifest(root)
    if command == 'comments':
        print(json.dumps({'project_id': config['id'], 'comments': read_comments(root, None if args.all else config['revision'])}, ensure_ascii=False, indent=2))
    elif command == 'reply':
        if not args.comment_id or not args.text:
            parser.error(tr('s.replyNeeds'))
        con = database(root)
        try:
            with con:
                row = con.execute('SELECT payload FROM comments WHERE id=?', (args.comment_id,)).fetchone()
                if not row:
                    parser.error(tr('s.noComment'))
                comment = json.loads(row[0])
                comment['replies'].append({'text': args.text, 'created_at': now(), 'status': args.status})
                comment['status'] = args.status
                con.execute('UPDATE comments SET payload=? WHERE id=?', (json.dumps(comment, ensure_ascii=False), args.comment_id))
            print(json.dumps(comment, ensure_ascii=False))
        finally:
            con.close()
    elif command == 'snapshot':
        dest = inside(root / 'snapshots', config['revision'])
        if dest.exists():
            parser.error(tr('s.snapExists'))
        dest.mkdir(parents=True)
        shutil.copy2(root / 'project.json', dest / 'project.json')
        for folder in ('frames', 'media'):
            if (root / folder).exists():
                shutil.copytree(root / folder, dest / folder)
        if read_design(root)[0] != 'missing':  # keep the design notes of this revision (shown read-only in history)
            shutil.copy2(root / DESIGN_NAME, dest / DESIGN_NAME)
        (dest / 'comments.json').write_text(json.dumps(read_comments(root, config['revision']), ensure_ascii=False, indent=2))
        print(json.dumps({'snapshot': str(dest)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
