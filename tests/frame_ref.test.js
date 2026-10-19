// SPDX-License-Identifier: Apache-2.0
// node tests for the <frame-ref> block of assets/canvas.js: the text behind "Copy frame reference" (run: node tests/frame_ref.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const block=src.match(/\/\/ <frame-ref>[\s\S]*?\/\/ <\/frame-ref>/);assert(block,'block missing');
const {frameRefText,frameRefLink,latestSnapshotRev}=new Function(block[0]+'\n;return{frameRefText,frameRefLink,latestSnapshotRev}')();
const dict=JSON.parse(fs.readFileSync(path.join(__dirname,'..','assets','i18n.json'),'utf8'));
// Same substitution as assets/i18n.js
const trFor=lang=>(key,params)=>{let text=dict[lang][key];assert(typeof text==='string','missing key '+key);return params?text.replace(/\{(\w+)\}/g,(m,n)=>(n in params?params[n]:m)):text};
const zh=trFor('zh'),en=trFor('en');
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const frame={id:'goal-select',title:'01 \u00b7 \u9009\u62e9\u884c\u52a8\u76ee\u6807'};

t('Chinese text: exactly the agreed five lines',()=>{
 assert.strictEqual(frameRefText({origin:'http://192.168.69.214:4846',canvasId:'xdbtqx',rev:'r61',frame},zh),[
  'UI Canvas \u753b\u9762\u5f15\u7528',
  '\u753b\u5e03\uff1ahttp://192.168.69.214:4846/\uff08canvas id: xdbtqx\uff09',
  '\u5feb\u7167\uff1ar61',
  '\u753b\u9762\uff1agoal-select\uff0801 \u00b7 \u9009\u62e9\u884c\u52a8\u76ee\u6807\uff09',
  '\u94fe\u63a5\uff1ahttp://192.168.69.214:4846/#view=flow&frame=goal-select&rev=r61'].join('\n'));
});
t('English text has the same lines',()=>{
 assert.strictEqual(frameRefText({origin:'http://192.168.69.214:4846',canvasId:'xdbtqx',rev:'r61',frame:{id:'home',title:'Home'}},en),[
  'UI Canvas frame reference','Canvas: http://192.168.69.214:4846/ (canvas id: xdbtqx)','Snapshot: r61','Frame: home (Home)',
  'Link: http://192.168.69.214:4846/#view=flow&frame=home&rev=r61'].join('\n'));
});
t('no snapshot yet: no rev line and no &rev in the link',()=>{
 const text=frameRefText({origin:'http://10.0.0.2:8876',canvasId:'abc123',rev:'',frame},en);
 assert(!/Snapshot/.test(text),text);assert(!/rev=/.test(text),text);
 assert(text.endsWith('Link: http://10.0.0.2:8876/#view=flow&frame=goal-select'),text);
 assert.strictEqual(text.split('\n').length,4);
});
t('canvas id unknown: canvas line without the parenthesis; title missing or equal to the id: id only',()=>{
 const text=frameRefText({origin:'http://h:1/',canvasId:'',rev:'r2',frame:{id:'x',title:''}},en).split('\n');
 assert.strictEqual(text[1],'Canvas: http://h:1/');assert.strictEqual(text[3],'Frame: x');
 assert.strictEqual(frameRefText({origin:'http://h:1',rev:'r2',frame:{id:'x',title:'x'}},en).split('\n')[3],'Frame: x');
});
t('the link round-trips through the view hash parser (odd ids are encoded)',()=>{
 const link=frameRefLink('http://h:1','a b&c=d/#','r7');
 assert(link.startsWith('http://h:1/#'));
 const p=new URLSearchParams(link.split('#').slice(1).join('#'));
 assert.strictEqual(p.get('view'),'flow');assert.strictEqual(p.get('frame'),'a b&c=d/#');assert.strictEqual(p.get('rev'),'r7');
});
t('never contains a file path or a server endpoint',()=>{
 const text=frameRefText({origin:'http://192.168.69.214:4846',canvasId:'xdbtqx',rev:'r61',frame:{...frame,path:'frames/goal-select.html'}},zh);
 assert(!/frames\/|\.html|\/api\/|\/Users\/|ui-canvas-runtime/.test(text),text);
});
t('latest snapshot: first usable entry of the newest-first list, else empty',()=>{
 assert.strictEqual(latestSnapshotRev([{rev:'r62',valid:true},{rev:'r61',valid:true}]),'r62');
 assert.strictEqual(latestSnapshotRev([{rev:'r9',valid:false},{rev:'r8',valid:true}]),'r8');
 assert.strictEqual(latestSnapshotRev([]),'');assert.strictEqual(latestSnapshotRev(null),'');assert.strictEqual(latestSnapshotRev([{rev:''},null,{}]),'');
});
console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
