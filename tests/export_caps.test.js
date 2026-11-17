// SPDX-License-Identifier: Apache-2.0
// A new toolbar button or a new fetch() must be classified or this fails. Export keeps only the listed controls.
// node tests/export_caps.test.js
const fs = require('fs'), assert = require('assert'), path = require('path');
const root = path.join(__dirname, '..');
const js = fs.readFileSync(path.join(root, 'assets', 'canvas.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'assets', 'canvas.html'), 'utf8');
const caps = js.match(/\/\/ <export-caps>[\s\S]*?\/\/ <\/export-caps>/);
assert(caps, 'export-caps block missing');
const api = new Function(caps[0] + '\n;return{EXPORT_KEEP_IDS,EXPORT_DROP_IDS}')();
const keep = new Set(api.EXPORT_KEEP_IDS), drop = new Set(api.EXPORT_DROP_IDS);
let n = 0, fail = 0;
const t = (name, fn) => { try { fn(); n++; console.log('PASS', name); } catch (e) { fail++; console.log('FAIL', name, e.message); } };

t('toolbar buttons are each kept or dropped', () => {
  const tools = html.split('<div class="tools">')[1].split('</header>')[0];
  const tags = tools.match(/<button\b[^>]*>/g) || [];
  assert(tags.length > 5, 'toolbar buttons');
  tags.forEach(tag => {
    const id = /id="([^"]+)"/.exec(tag);
    assert(id, 'toolbar button needs an id: ' + tag.slice(0, 120));
    assert(keep.has(id[1]) || drop.has(id[1]), id[1]);
  });
});
t('every button id in the shell is classified', () => {
  const tags = html.match(/<button\b[^>]*>/g) || [];
  tags.forEach(tag => {
    const id = /id="([^"]+)"/.exec(tag);
    if (!id) return;
    assert(keep.has(id[1]) || drop.has(id[1]), 'unclassified ' + id[1]);
  });
});
t('kept ids exist and do not overlap the dropped ids', () => {
  keep.forEach(id => assert(html.includes('id="' + id + '"'), id));
  drop.forEach(id => assert(!keep.has(id), id));
});

// Arguments of fetch( that are allowed to exist. A new call must be added here on purpose.
const FETCHES = [
  "fetch(flowFrameUrl(rev,meta.get(id).path),{cache:'no-store'})",
  "fetch('/api/project')",
  "fetch('/api/snapshots',{cache:'no-store'})",
  "fetch(exportRequestPath(row))",
  "fetch('/healthz',{cache:'no-store'})",
  "fetch('/api/comments/'+encodeURIComponent(c.id),{method:deleting?'DELETE':'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,revision,...changes})})",
  "fetch('/api/comments/batch',{method:deleting?'DELETE':'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id,revision,ids,status:$('bulk-status').value})})",
  "fetch('/api/comments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})",
  "fetch('/api/comments?revision='+encodeURIComponent(rev))",
  "fetch('/api/comments?revision='+encodeURIComponent(revision))",
  "fetch(rev?'/api/snapshots/'+encodeURIComponent(rev)+'/design':'/api/design',{cache:'no-store'})",
  "fetch('/api/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})",
  "fetch('/api/project',{cache:'no-store'})",
  "fetch(base+'/project',{cache:'no-store'})",
  "fetch(base+'/comments',{cache:'no-store'})",
  "fetch('/api/preview-hosts',{cache:'no-store'})",
  "fetch(url||('/project/'+path),{cache:'no-store'})"
];

t('every fetch() is already classified', () => {
  const found = [];
  const re = /(?:^|[^A-Za-z0-9_])fetch\(/g;
  let m;
  while ((m = re.exec(js))) {
    const at = m.index + m[0].length - 'fetch('.length;
    const start = at + 'fetch('.length;
    let i = start, depth = 1;
    while (i < js.length && depth) {
      const ch = js[i++];
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
    }
    found.push(js.slice(at, i).replace(/\s+/g, ''));
  }
  const known = new Set(FETCHES.map(s => s.replace(/\s+/g, '')));
  const seen = new Set(found);
  found.forEach(call => assert(known.has(call), 'unclassified ' + call.slice(0, 180)));
  known.forEach(call => assert(seen.has(call), 'listed fetch is gone: ' + call.slice(0, 120)));
});

if (fail) process.exit(1);
console.log(n + ' passed');
