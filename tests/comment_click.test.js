// SPDX-License-Identifier: Apache-2.0
// node tests for commentClickPlan in the <flow-core> block of assets/canvas.js (run: node tests/comment_click.test.js)
// It decides what the board's comment click handler does with a click, in the tile view, in the Flow view and in history.
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const core=src.match(/\/\/ <flow-core>[\s\S]*?\/\/ <\/flow-core>/);assert(core,'block missing');
const {commentClickPlan:plan}=new Function(core[0]+'\n;return{commentClickPlan}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const base={history:false,editorOpen:false,flow:false,commentMode:false,hasTarget:true,onButton:false};
const P=o=>plan({...base,...o});

t('tile view: comment mode on selects, off leaves the click alone, a button shows the design hint',()=>{
 assert.strictEqual(P({commentMode:true}),'select');
 assert.strictEqual(P({}),'ignore');
 assert.strictEqual(P({onButton:true}),'hint');
 assert.strictEqual(P({hasTarget:false}),'ignore');
 assert.strictEqual(P({hasTarget:false,commentMode:true}),'ignore');
});
t('Flow view with comment mode on selects the element, so the jump handler never sees the click',()=>{
 assert.strictEqual(P({flow:true,commentMode:true}),'select');
 assert.strictEqual(P({flow:true,commentMode:true,onButton:true}),'select');
});
t('Flow view with comment mode off lets the jump handler run: no hint, no select',()=>{
 assert.strictEqual(P({flow:true}),'ignore');
 assert.strictEqual(P({flow:true,onButton:true}),'ignore');
});
t('Flow view in comment mode swallows a click that hit nothing commentable instead of jumping',()=>{
 assert.strictEqual(P({flow:true,commentMode:true,hasTarget:false}),'block');
 assert.strictEqual(P({flow:true,hasTarget:false}),'ignore');
});
t('an open comment box blocks every click, in both views (no second selection, no jump)',()=>{
 for(const flow of [false,true])for(const commentMode of [false,true])for(const onButton of [false,true])assert.strictEqual(P({editorOpen:true,flow,commentMode,onButton}),'block');
});
t('history is read-only in both views: nothing is selected, an open box is closed, the Flow jump still works',()=>{
 for(const flow of [false,true])for(const commentMode of [false,true]){
  assert.strictEqual(P({history:true,flow,commentMode}),'ignore');
  assert.strictEqual(P({history:true,flow,commentMode,editorOpen:true}),'close-editor');
  assert.strictEqual(P({history:true,flow,commentMode,onButton:true}),'ignore');
 }
});
console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
