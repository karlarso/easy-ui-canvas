// SPDX-License-Identifier: Apache-2.0
// node tests for the <history-link> block of assets/canvas.js: the URL copied from a history version,
// and which rev a canvas URL opens (run: node tests/history_link.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const block=src.match(/\/\/ <history-link>[\s\S]*?\/\/ <\/history-link>/);assert(block,'block missing');
const api=new Function(block[0]+'\n;return{historyRevOk,historyQueryRev,historyQueryRejected,historyHashRev,historyBootRev,historySearch,historyShareUrl}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};

t('tile history link is origin plus ?rev and opens that rev',()=>{
 const url=api.historyShareUrl({origin:'http://192.168.1.20:4846',rev:'r3'});
 assert.strictEqual(url,'http://192.168.1.20:4846/?rev=r3');
 const u=new URL(url);
 assert.strictEqual(api.historyBootRev(u.search,u.hash),'r3');
 assert.strictEqual(u.hash,'');
});
t('a v3-style snapshot id is kept',()=>{
 assert.strictEqual(api.historyShareUrl({origin:'http://100.64.0.2:4100/',rev:'v3'}),'http://100.64.0.2:4100/?rev=v3');
 assert.strictEqual(api.historyBootRev('?rev=v3',''),'v3');
});
t('flow history link keeps the frame and the same rev in the hash',()=>{
 const url=api.historyShareUrl({origin:'http://127.0.0.1:9',rev:'r1',flow:true,frame:'f02'});
 assert.strictEqual(url,'http://127.0.0.1:9/?rev=r1#view=flow&frame=f02&rev=r1');
 const u=new URL(url);
 assert.strictEqual(api.historyBootRev(u.search,u.hash),'r1');
 assert.strictEqual(api.historyHashRev(u.hash),'r1');
});
t('odd frame ids round-trip through the flow hash',()=>{
 const url=api.historyShareUrl({origin:'http://h:1',rev:'r7',flow:true,frame:'a b&c=d/#'});
 const u=new URL(url);
 assert.strictEqual(u.search,'?rev=r7');
 const p=new URLSearchParams(u.hash.replace(/^#/,''));
 assert.strictEqual(p.get('view'),'flow');
 assert.strictEqual(p.get('frame'),'a b&c=d/#');
 assert.strictEqual(p.get('rev'),'r7');
 assert.strictEqual(api.historyBootRev(u.search,u.hash),'r7');
});
t('?rev wins over a different flow-hash rev; hash is used only when the query has no usable rev',()=>{
 assert.strictEqual(api.historyBootRev('?rev=r1','#view=flow&frame=f02&rev=r2'),'r1');
 assert.strictEqual(api.historyBootRev('','#view=flow&frame=f02&rev=r2'),'r2');
 assert.strictEqual(api.historyBootRev('?rev=','#view=flow&frame=f02&rev=r2'),'r2');
 assert.strictEqual(api.historyBootRev('?rev=.hidden','#view=flow&rev=r2'),'r2');
});
t('a hash rev without view=flow is not a pin, and a bare canvas URL opens the current version',()=>{
 assert.strictEqual(api.historyBootRev('','#rev=r2'),'');
 assert.strictEqual(api.historyHashRev('#rev=r2'),'');
 assert.strictEqual(api.historyBootRev('',''),'');
 assert.strictEqual(api.historyQueryRev(''),'');
});
t('ids the server would reject are not pins',()=>{
 for(const rev of ['','.hidden','../r1','a/b','bad rev','r1?x','.','a'.repeat(121)]){
  assert.strictEqual(api.historyRevOk(rev),false,rev);
  assert.strictEqual(api.historyQueryRev('?rev='+encodeURIComponent(rev)),'');
 }
 assert.strictEqual(api.historyRevOk('r_1.2-a'),true);
 assert.strictEqual(api.historyQueryRev('?rev=r_1.2-a'),'r_1.2-a');
 assert.strictEqual(api.historyShareUrl({origin:'http://h:1',rev:'../r1'}),'http://h:1/');
 assert.strictEqual(api.historyQueryRejected('?rev=.hidden'),true);
 assert.strictEqual(api.historyQueryRejected('?rev='),true);
 assert.strictEqual(api.historyQueryRejected('?rev=r1'),false);
 assert.strictEqual(api.historyQueryRejected(''),false);
});
t('writing the address keeps other query flags and drops rev when leaving history',()=>{
 assert.strictEqual(api.historySearch('?load=all','r1'),'?load=all&rev=r1');
 assert.strictEqual(api.historySearch('?load=all&rev=r9','r1'),'?load=all&rev=r1');
 assert.strictEqual(api.historySearch('?load=all&rev=r1',''),'?load=all');
 assert.strictEqual(api.historySearch('?rev=r1',''),'');
 assert.strictEqual(api.historySearch('','v3'),'?rev=v3');
});

console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
