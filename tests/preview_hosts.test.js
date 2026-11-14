// SPDX-License-Identifier: Apache-2.0
// node tests for the <preview-hosts> block of assets/canvas.js: which address is selected,
// how its URL is built, and that the QR text, the shown URL and the copied text stay the same string.
// run: node tests/preview_hosts.test.js
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const block=src.match(/\/\/ <preview-hosts>[\s\S]*?\/\/ <\/preview-hosts>/);assert(block,'block missing');
const api=new Function(block[0]+'\n;return{buildPreviewChoices,previewSync,previewHintCode,previewUrlFor,previewIndexFor,unspecifiedHost,loopbackHost}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};

const page={origin:'http://localhost:4100'};
const rows=[
 {address:'192.168.1.20',access:'lan'},
 {address:'100.64.8.8',access:'tailscale'},
 {address:'127.0.0.1',access:'local-only'},
 {address:'0.0.0.0',access:'explicit'},
 {address:'::',access:'explicit'}
];

t('current origin is first and selected, ahead of LAN and Tailscale',()=>{
 const model=api.buildPreviewChoices(page,{port:4100,addresses:rows,discovery:'ok'},'');
 assert.strictEqual(model.selected,0);
 assert.strictEqual(model.choices[0].current,true);
 assert.strictEqual(model.choices[0].url,'http://localhost:4100/m/');
 assert.strictEqual(model.choices[0].loopback,true);
 assert.ok(model.choices.findIndex(c=>c.url.startsWith('http://192.168.1.20:'))>0);
 assert.ok(model.choices.findIndex(c=>c.url.startsWith('http://100.64.8.8:'))>0);
 assert.strictEqual(model.showSelect,true);
 const view=api.previewSync(model.choices, model.selected);
 assert.strictEqual(view.url, view.qr);
 assert.strictEqual(view.url, view.copy);
 assert.strictEqual(view.url,'http://localhost:4100/m/');
 assert.strictEqual(api.previewHintCode(model.choices[0], model.choices),'loop-switch');
});

t('a loopback page is not replaced when the payload lists other addresses first',()=>{
 const reversed=rows.slice().reverse();
 const model=api.buildPreviewChoices(page,{port:4100,addresses:reversed,discovery:'ok'},'');
 assert.strictEqual(model.choices[0].url,'http://localhost:4100/m/');
 assert.strictEqual(api.previewIndexFor(model.choices, model.choices[0].url),0);
});

t('switching keeps the QR, the field and the copy on one URL, including rev',()=>{
 const model=api.buildPreviewChoices(page,{port:4100,addresses:rows,discovery:'ok'},'r3');
 assert.strictEqual(model.choices[0].url,'http://localhost:4100/m/?rev=r3');
 const lan=model.choices.findIndex(c=>c.access==='lan');
 const view=api.previewSync(model.choices, lan);
 assert.strictEqual(view.url,'http://192.168.1.20:4100/m/?rev=r3');
 assert.strictEqual(view.qr, view.url);
 assert.strictEqual(view.copy, view.url);
 assert.notStrictEqual(view.url, api.previewSync(model.choices, 0).url);
 assert.strictEqual(api.previewHintCode(model.choices[lan], model.choices),'unchecked');
 assert.strictEqual(api.previewIndexFor(model.choices, view.url), lan);
});

t('wildcards are not links, and a single real address hides the selector',()=>{
 const model=api.buildPreviewChoices(page,{port:4100,addresses:[{address:'0.0.0.0'},{address:'::'},{address:'127.0.0.1',access:'local-only'}],discovery:'ok'},'');
 assert.ok(model.choices.every(c=>!api.unspecifiedHost(c.host)));
 assert.strictEqual(model.choices.length,2);
 assert.strictEqual(model.showSelect,true);
 const only=api.buildPreviewChoices({origin:'http://127.0.0.1:4100'},{port:4100,addresses:[{address:'127.0.0.1',access:'local-only'}],discovery:'ok'},'');
 assert.strictEqual(only.choices.length,1);
 assert.strictEqual(only.showSelect,false);
 assert.strictEqual(api.previewHintCode(only.choices[0], only.choices),'loop-only');
});

t('IPv6 is bracketed, keeps the port and the rev, and is not the default over the current host',()=>{
 const url=api.previewUrlFor('http','fd7a:115c:a1e0::8',4100,'r 2');
 assert.strictEqual(url,'http://[fd7a:115c:a1e0::8]:4100/m/?rev=r%202');
 const model=api.buildPreviewChoices(
  {origin:'http://[fd7a:115c:a1e0::8]:4100'},
  {port:4100,addresses:[{address:'192.168.1.20',access:'lan'},{address:'fd7a:115c:a1e0::8',access:'tailscale'}],discovery:'ok'},
  '');
 assert.strictEqual(model.choices[0].url,'http://[fd7a:115c:a1e0::8]:4100/m/');
 assert.strictEqual(model.choices[0].current,true);
 assert.strictEqual(model.choices.filter(c=>c.host==='fd7a:115c:a1e0::8').length,1);
 const view=api.previewSync(model.choices, 0);
 assert.strictEqual(view.qr, view.copy);
 assert.strictEqual(view.url, model.choices[0].url);
});

t('an unspecified current host is not offered, and a failed lookup keeps a usable current URL',()=>{
 const wild=api.buildPreviewChoices({origin:'http://0.0.0.0:4100'},{port:4100,addresses:[{address:'192.168.1.20',access:'lan'}],discovery:'ok'},'');
 assert.strictEqual(wild.choices[0].url,'http://192.168.1.20:4100/m/');
 assert.strictEqual(wild.choices[0].current,false);
 assert.ok(wild.choices.every(c=>c.host!=='0.0.0.0'));
 const failed=api.buildPreviewChoices(page,{port:4100,addresses:[],discovery:'failed'},'');
 assert.strictEqual(failed.discoveryFailed,true);
 assert.strictEqual(failed.choices.length,1);
 assert.strictEqual(failed.choices[0].url,'http://localhost:4100/m/');
 assert.strictEqual(failed.showSelect,false);
 const pending=api.buildPreviewChoices(page,null,'');
 assert.strictEqual(pending.discoveryFailed,false);
 assert.strictEqual(pending.choices[0].url,'http://localhost:4100/m/');
 const none=api.buildPreviewChoices({origin:'http://[::]:9'},{port:9,addresses:[],discovery:'failed'},'');
 assert.strictEqual(none.empty,true);
 assert.strictEqual(api.previewSync(none.choices, 0).url,'');
 assert.strictEqual(api.previewSync(none.choices, 0).qr,'');
 assert.strictEqual(api.previewSync(none.choices, 0).copy,'');
});

t('a refresh does not move the selection onto a LAN row unless that row was chosen',()=>{
 const model=api.buildPreviewChoices(page,{port:4100,addresses:rows,discovery:'ok'},'');
 assert.strictEqual(api.previewIndexFor(model.choices, 'http://localhost:4100/m/'),0);
 const lanUrl='http://192.168.1.20:4100/m/';
 const kept=api.previewIndexFor(model.choices, lanUrl);
 assert.strictEqual(model.choices[kept].url, lanUrl);
 const again=api.previewSync(model.choices, kept);
 assert.strictEqual(again.url, again.qr);
 assert.strictEqual(again.copy, lanUrl);
 assert.strictEqual(api.previewIndexFor(model.choices, 'http://10.9.9.9:4100/m/'),0);
});

console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
