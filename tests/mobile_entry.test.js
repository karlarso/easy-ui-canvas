// SPDX-License-Identifier: Apache-2.0
// node tests for the phone-preview browse entry in the <flow-core> block of assets/canvas.js
// (run: node tests/mobile_entry.test.js)
// A load or refresh of /m/ opens the browse entry (?start=, else flow_start, else the first frame)
// and does not resume a hash frame or history.state frame. The canvas Flow view still does.
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const core=src.match(/\/\/ <flow-core>[\s\S]*?\/\/ <\/flow-core>/);assert(core,'block missing');
const api=new Function(core[0]+'\n;return{mobileLoadFrame,mobileHashFrame,mobileReplayFrame,mobilePopTarget,flowBootFrame,flowPickStart}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const ids=['settings','home','detail']; // first frame is not the browse entry

t('browse entry is ?start=, then flow_start, then the first frame',()=>{
 assert.strictEqual(api.flowPickStart(ids,'home',null),'home');
 assert.strictEqual(api.flowPickStart(ids,'home','detail'),'detail');
 assert.strictEqual(api.flowPickStart(ids,'missing','nope'),'settings');
 assert.strictEqual(api.flowPickStart(ids,null,null),'settings');
});
t('phone preview load ignores the hash frame and the history frame',()=>{
 const entry=api.mobileLoadFrame({ids,flowStart:'home',want:null,hashFrame:'detail',historyFrame:'settings'});
 assert.strictEqual(entry,'home');
 assert.strictEqual(api.mobileLoadFrame({ids,flowStart:'home',want:'detail',hashFrame:'settings',historyFrame:'settings'}),'detail');
 assert.strictEqual(api.mobileLoadFrame({ids,flowStart:'nope',want:'',hashFrame:'detail',historyFrame:'detail'}),'settings');
});
t('a frame hash is parsed and then not used as the phone entry',()=>{
 assert.strictEqual(api.mobileHashFrame('#view=flow&frame=detail'),'detail');
 assert.strictEqual(api.mobileHashFrame('#frame=settings'),'settings');
 assert.strictEqual(api.mobileHashFrame('#view=flow'),'');
 assert.strictEqual(api.mobileHashFrame(''),'');
 const hash=api.mobileHashFrame('#view=flow&frame=detail');
 assert.strictEqual(api.mobileLoadFrame({ids,flowStart:'home',want:null,hashFrame:hash,historyFrame:hash}),'home');
});
t('a popstate that replays the pre-refresh frame is ignored; any other frame is kept',()=>{
 assert.strictEqual(api.mobileReplayFrame('detail','home'),'detail');
 assert.strictEqual(api.mobileReplayFrame('home','home'),'');
 assert.strictEqual(api.mobileReplayFrame('','home'),'');
 assert.strictEqual(api.mobilePopTarget('detail','detail','home',ids),null);
 assert.strictEqual(api.mobilePopTarget('detail','settings','home',ids),'settings');
 assert.strictEqual(api.mobilePopTarget('','detail','home',ids),'detail');
 assert.strictEqual(api.mobilePopTarget('detail','nope','home',ids),'home');
 assert.strictEqual(api.mobilePopTarget('detail',null,'home',ids),'home');
});
t('Flow view reload still opens the hashed frame; an unknown hash falls through to the browse entry',()=>{
 assert.strictEqual(api.flowBootFrame(ids,'home','detail'),'detail');
 assert.strictEqual(api.flowBootFrame(ids,'home','settings'),'settings');
 assert.strictEqual(api.flowBootFrame(ids,'home','nope'),'home');
 assert.strictEqual(api.flowBootFrame(ids,'home',null),'home');
 assert.strictEqual(api.flowBootFrame(ids,'missing',undefined),'settings');
});

if(fail){console.log(fail+' failed');process.exit(1)}
console.log(n+' passed');
