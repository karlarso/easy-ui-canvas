// SPDX-License-Identifier: Apache-2.0
// node tests for the <scroll-lock> block of assets/canvas.js (run: node tests/wheel_router.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const m=src.match(/\/\/ <scroll-lock>[\s\S]*?\/\/ <\/scroll-lock>/);assert(m,'block missing');
const createWheelRouter=new Function(m[0]+'\n;return createWheelRouter')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
// fake DOM
function el(name,o={},parent=null){const e=Object.assign({name,overflowY:'visible',overflowX:'visible',scrollTop:0,scrollLeft:0,scrollHeight:100,clientHeight:100,scrollWidth:100,clientWidth:100,parentElement:parent,children:[],isFrame:false},o);if(parent)parent.children.push(e);e.contains=x=>{for(;x;x=x.parentElement)if(x===e)return true;return false};return e}
function world(){
 const vp=el('vp');
 const blank=el('blank',{},vp);
 const phoneA=el('phoneA',{isFrame:true,overflowY:'auto',scrollHeight:300,clientHeight:100},vp);   // screen root scrolls itself
 const textA=el('textA',{},phoneA);
 const inner=el('inner',{overflowY:'auto',scrollHeight:400,clientHeight:100},phoneA);               // nested scroller
 const innerText=el('innerText',{},inner);
 const phoneB=el('phoneB',{isFrame:true,overflowY:'auto',scrollHeight:100,clientHeight:100},vp);   // unscrollable
 const textB=el('textB',{},phoneB);
 const phoneC=el('phoneC',{isFrame:true,overflowY:'hidden',scrollHeight:300,clientHeight:100},vp); // overflow hidden: not scrollable
 const textC=el('textC',{},phoneC);
 const phoneH=el('phoneH',{isFrame:true,overflowX:'auto',scrollWidth:300,clientWidth:100},vp);
 const textH=el('textH',{},phoneH);
 return{vp,blank,phoneA,textA,inner,innerText,phoneB,textB,textC,phoneH,textH,phoneC};
}
const mk=()=>createWheelRouter({gap:180,isFrame:e=>e.isFrame,styleOf:e=>e});
const ev=(time,target,dy,extra={})=>Object.assign({t:time,target,dx:0,dy,ctrl:false,space:false},extra);

t('scrollable frame (screen root): whole round scrolls and locks that frame',()=>{const w=world(),r=mk();const a=r.route(ev(0,w.textA,50));assert.equal(a.action,'scroll');assert.equal(a.frame,w.phoneA);assert.equal(a.scroller,w.phoneA);assert(a.newRound)});
t('nested scroll container wins (nearest ancestor)',()=>{const w=world(),r=mk();const a=r.route(ev(0,w.innerText,50));assert.equal(a.scroller,w.inner)});
t('scrollable frame at its edge: same round keeps scrolling (swallowed, no canvas pan)',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));w.phoneA.scrollTop=200;const a=r.route(ev(16,w.textA,50));assert.equal(a.action,'scroll');assert.equal(a.scroller,null);assert(!a.newRound)});
t('inner scroller at its edge: same round chains to the screen root',()=>{const w=world(),r=mk();r.route(ev(0,w.innerText,50));w.inner.scrollTop=300;const a=r.route(ev(16,w.innerText,50));assert.equal(a.scroller,w.phoneA)});
t('after the edge, a pause >180 ms starts a new round: cannot scroll that way, so pan the canvas',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));w.phoneA.scrollTop=200;r.route(ev(16,w.textA,50));const a=r.route(ev(16+181,w.textA,50));assert.equal(a.action,'pan');assert(a.newRound);assert.equal(a.reason,'frame-unscrollable')});
t('a new round in the opposite direction after the edge scrolls the frame',()=>{const w=world(),r=mk();w.phoneA.scrollTop=200;r.route(ev(0,w.textA,50));const a=r.route(ev(300,w.textA,-50));assert.equal(a.action,'scroll');assert.equal(a.scroller,w.phoneA)});
t('unscrollable frame (content fits): whole round pans the canvas',()=>{const w=world(),r=mk();const a=r.route(ev(0,w.textB,50));assert.equal(a.action,'pan');assert.equal(a.reason,'frame-unscrollable');assert.equal(r.route(ev(50,w.textB,50)).action,'pan')});
t('overflow:hidden screens count as unscrollable',()=>{const w=world(),r=mk();assert.equal(r.route(ev(0,w.textC,50)).action,'pan')});
t('starting on blank space: whole round pans the canvas',()=>{const w=world(),r=mk();const a=r.route(ev(0,w.blank,50));assert.equal(a.action,'pan');assert.equal(a.reason,'blank')});
t('starting on blank space, pointer enters a frame mid-round: still pans',()=>{const w=world(),r=mk();r.route(ev(0,w.blank,50));const a=r.route(ev(20,w.textA,50));assert.equal(a.action,'pan');assert(!a.newRound)});
t('starting in a frame, pointer moves to blank/another frame mid-round: stays locked to the first frame',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));let a=r.route(ev(20,w.blank,50));assert.equal(a.action,'scroll');assert.equal(a.frame,w.phoneA);assert.equal(a.scroller,w.phoneA);a=r.route(ev(40,w.textB,50));assert.equal(a.frame,w.phoneA);assert.equal(a.scroller,w.phoneA)});
t('starting unscrollable, direction becomes scrollable mid-round: still pans (no re-decision)',()=>{const w=world(),r=mk();w.phoneA.scrollTop=200;r.route(ev(0,w.textA,50));const a=r.route(ev(20,w.textA,-50));assert.equal(a.action,'pan')});
t('direction reverses mid-round inside a frame: stays locked and re-picks the scroller',()=>{const w=world(),r=mk();w.phoneA.scrollTop=200;w.phoneA.scrollTop=100;let a=r.route(ev(0,w.textA,50));assert.equal(a.action,'scroll');a=r.route(ev(20,w.textA,-50));assert.equal(a.action,'scroll');assert.equal(a.scroller,w.phoneA)});
t('Ctrl+wheel always zooms (in frame, on blank, while locked) and does not affect the lock',()=>{const w=world(),r=mk();assert.equal(r.route(ev(0,w.textA,50,{ctrl:true})).action,'zoom');assert.equal(r.route(ev(1,w.blank,50,{ctrl:true})).action,'zoom');r.route(ev(10,w.textA,50));assert.equal(r.route(ev(20,w.textA,50,{ctrl:true})).action,'zoom');const a=r.route(ev(30,w.textA,50));assert.equal(a.action,'scroll');assert(!a.newRound);assert.equal(r.lock.kind,'frame')});
t('Ctrl events do not extend a round (>180 ms still starts a new one)',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));r.route(ev(150,w.textA,50,{ctrl:true}));const a=r.route(ev(200,w.textA,50));assert(a.newRound)});
t('Space + scrollable frame: whole round pans the canvas',()=>{const w=world(),r=mk();let a=r.route(ev(0,w.textA,50,{space:true}));assert.equal(a.action,'pan');assert.equal(a.reason,'space');a=r.route(ev(20,w.textA,50));assert.equal(a.action,'pan');assert(!a.newRound)});
t('pressing Space mid-round does not change an already locked in-frame round',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));assert.equal(r.route(ev(20,w.textA,50,{space:true})).action,'scroll')});
t('Space + blank space: pans (unaffected)',()=>{const w=world(),r=mk();assert.equal(r.route(ev(0,w.blank,50,{space:true})).action,'pan')});
t('180 ms boundary: gap of exactly 180 is the same round',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));const a=r.route(ev(180,w.blank,50));assert(!a.newRound);assert.equal(a.action,'scroll')});
t('180 ms boundary: gap of 180.01 is a new round (blank space: pan)',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));const a=r.route(ev(180.01,w.blank,50));assert(a.newRound);assert.equal(a.action,'pan')});
t('inertia: gaps grow but stay ≤180 ms, one continuous round (including after the frame edge)',()=>{const w=world(),r=mk();let T=0;r.route(ev(T,w.textA,80));for(const g of [16,16,20,40,80,120,170,179]){T+=g;const a=r.route(ev(T,w.blank,2));assert(!a.newRound);assert.equal(a.action,'scroll')}});
t('canvas pan round: pointer moves into a frame and never switches until a pause >180 ms',()=>{const w=world(),r=mk();r.route(ev(0,w.blank,50));for(let T=16;T<2000;T+=16)assert.equal(r.route(ev(T,w.textA,50)).action,'pan');const a=r.route(ev(2000+300,w.textA,50));assert(a.newRound);assert.equal(a.action,'scroll')});
t('a new round starting in another frame changes the lock target',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));const a=r.route(ev(500,w.textH,0,{dx:40}));assert.equal(a.action,'scroll');assert.equal(a.frame,w.phoneH);assert.equal(a.scroller,w.phoneH)});
t('horizontal: dx dominates; sideways swipe on a vertically-scrollable-only frame pans the canvas',()=>{const w=world(),r=mk();const a=r.route(ev(0,w.textA,1,{dx:40}));assert.equal(a.action,'pan')});
t('diagonal scrolling uses the dominant axis (noisy dy does not lock a frame)',()=>{const w=world(),r=mk();assert.equal(r.route(ev(0,w.textA,2,{dx:-50})).action,'pan')});
t('zero-delta events neither start nor extend a round',()=>{const w=world(),r=mk();assert.equal(r.route(ev(0,w.textA,0)).action,'noop');assert.equal(r.lock,null);r.route(ev(10,w.textA,50));r.route(ev(100,w.textA,0));assert(r.route(ev(195,w.textA,50)).newRound)});
t('reset() ends a round (blur)',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));r.reset();assert(r.route(ev(10,w.blank,50)).newRound)});
t('scrolling up with the frame already at the top: unscrollable, so the canvas pans',()=>{const w=world(),r=mk();assert.equal(r.route(ev(0,w.textA,-50)).action,'pan')});
t('NaN/missing t counts as a new round (safe fallback)',()=>{const w=world(),r=mk();r.route(ev(0,w.textA,50));assert(r.route(ev(NaN,w.textA,50)).newRound)});
console.log(`\n${n} passed, ${fail} failed`);process.exit(fail?1:0);
