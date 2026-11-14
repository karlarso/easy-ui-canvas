// SPDX-License-Identifier: Apache-2.0
// node tests for the <export-version> block: the dialog always offers the live canvas first.
// run: node tests/export_version.test.js
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const block=src.match(/\/\/ <export-version>[\s\S]*?\/\/ <\/export-version>/);assert(block,'block missing');
const api=new Function(block[0]+'\n;return{exportVersionRows,exportRequestPath}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};

const data={current_revision:'r2',snapshots:[
 {rev:'r2',name:'Now',created_at:'2026-02-02T00:00:00Z',valid:true},
 {rev:'r1',name:'Then',created_at:'2026-01-01T00:00:00Z',valid:true},
 {rev:'bad',valid:false}
]};

t('latest live row is first even when a snapshot is newer in the list and one is invalid',()=>{
 const rows=api.exportVersionRows(data,'Live name');
 assert.strictEqual(rows[0].kind,'live');
 assert.strictEqual(rows[0].rev,'r2');
 assert.strictEqual(rows[0].name,'Live name');
 assert.strictEqual(rows[1].rev,'r2');
 assert.strictEqual(rows[1].kind,'snapshot');
 assert.strictEqual(rows[2].rev,'r1');
 assert.strictEqual(rows.length,3);
});

t('the default request is the live export; a snapshot row names that rev only',()=>{
 const rows=api.exportVersionRows(data,'Live');
 assert.strictEqual(api.exportRequestPath(rows[0]),'/api/export-ui');
 assert.strictEqual(api.exportRequestPath(rows[2]),'/api/export-ui?rev=r1');
 assert.strictEqual(api.exportRequestPath(null),'/api/export-ui');
});

t('a missing current revision is not a list to export',()=>{
 assert.strictEqual(api.exportVersionRows({snapshots:[{rev:'r1',valid:true}]},'x'),null);
 assert.strictEqual(api.exportVersionRows(null,'x'),null);
});

t('opening again still starts at the live row, not a previously viewed rev',()=>{
 const rows=api.exportVersionRows(data,'Live');
 assert.strictEqual(rows[0].kind,'live');
 assert.notStrictEqual(rows[0].kind,'snapshot');
});

console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
