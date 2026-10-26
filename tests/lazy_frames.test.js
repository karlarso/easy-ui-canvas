// SPDX-License-Identifier: Apache-2.0
// node tests for the <lazy-frames> block of assets/canvas.js: start-up camera and which frames are near the visible area (run: node tests/lazy_frames.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const tile=src.match(/\/\/ <tile-layout>[\s\S]*?\/\/ <\/tile-layout>/),lazy=src.match(/\/\/ <lazy-frames>[\s\S]*?\/\/ <\/lazy-frames>/);assert(tile&&lazy,'block missing');
const {tileLayout,initialCamera,framesInView,LAZY,focusFrameCamera}=new Function(tile[0]+'\n'+lazy[0]+'\n;return{tileLayout,initialCamera,framesInView,LAZY,focusFrameCamera}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const close=(a,b,msg)=>assert(Math.abs(a-b)<1e-9,msg+': '+a+' != '+b);

t('constants: 50% floor, 28 px edge, half a viewport of margin, 4-6 parallel loads',()=>{
 assert.strictEqual(LAZY.minScale,.5);assert.strictEqual(LAZY.edge,28);assert.strictEqual(LAZY.margin,.5);assert(LAZY.concurrency>=4&&LAZY.concurrency<=6);
});
t('a board that fits at 50% or more keeps the centred fit (never above 100%)',()=>{
 let c=initialCamera(1000,800,1440,864);close(c.scale,Math.min(1,(1440-56)/1000,(864-56)/800),'scale');close(c.panX,(1440-1000*c.scale)/2,'panX');close(c.panY,(864-800*c.scale)/2,'panY');
 c=initialCamera(400,300,1440,864);assert.strictEqual(c.scale,1);close(c.panX,520,'small board centred');
 c=initialCamera(2*(1440-56),2*(864-56),1440,864);close(c.scale,.5,'exactly 50% is still a fit');close(c.panX,(1440-2*(1440-56)*.5)/2,'centred at exactly 50%');
});
t('a board that would need less than 50% starts at 50% with its top-left corner 28 px from the viewport corner',()=>{
 for(const [bw,bh] of [[2994,5880],[5000,600],[600,9000]]){const c=initialCamera(bw,bh,1440,864);assert.deepStrictEqual(c,{scale:.5,panX:28,panY:28},bw+'x'+bh)}
});
t('degenerate sizes do not throw or produce NaN',()=>{for(const c of [initialCamera(0,0,1440,864),initialCamera(100,100,10,10)])assert(Number.isFinite(c.scale)&&Number.isFinite(c.panX)&&Number.isFinite(c.panY))});
const grid=(cols,rows,w=390,h=888,gx=40,gy=44)=>{const b=[];for(let r=0;r<rows;r++)for(let c=0;c<cols;c++)b.push({x:12+c*(w+gx),y:12+r*(h+gy),w,h});return b};
t('only boxes touching the viewport grown by the margin are returned, nearest to the centre first',()=>{
 const boxes=grid(8,4),cam={scale:.5,panX:28,panY:28};
 const all=framesInView(boxes,cam,1440,864,0),near=framesInView(boxes,cam,1440,864,.5);
 assert(all.length>0&&all.length<boxes.length);assert(near.length>=all.length);all.forEach(i=>assert(near.includes(i)));
 for(const i of near){const b=boxes[i],l=28+b.x*.5,tp=28+b.y*.5;assert(l<1440*1.5&&tp<864*1.5&&l+b.w*.5>-720&&tp+b.h*.5>-432,'box '+i)}
 const d=i=>{const b=boxes[i];return Math.hypot(28+(b.x+b.w/2)*.5-720,28+(b.y+b.h/2)*.5-432)};for(let k=1;k<near.length;k++)assert(d(near[k-1])<=d(near[k]),'sorted by distance');
});
t('with margin 0 the result is exactly the boxes that overlap the viewport',()=>{
 const boxes=grid(8,4),cam={scale:.5,panX:28,panY:28},got=framesInView(boxes,cam,1440,864,0).sort((a,b)=>a-b);
 const want=boxes.map((b,i)=>[b,i]).filter(([b])=>28+b.x*.5<1440&&28+(b.x+b.w)*.5>0&&28+b.y*.5<864&&28+(b.y+b.h)*.5>0).map(([,i])=>i);assert.deepStrictEqual(got,want);
});
t('panning far away selects other boxes; zooming out far enough selects all of them',()=>{
 const boxes=grid(8,4);const a=framesInView(boxes,{scale:.5,panX:28,panY:28},1440,864,0),b=framesInView(boxes,{scale:.5,panX:28-1700,panY:28-1400},1440,864,0);
 assert(b.length&&!b.some(i=>a.includes(i)));assert.strictEqual(framesInView(boxes,{scale:.1,panX:10,panY:10},1440,864,0).length,boxes.length);
});
t('works on the real tile layout (sections and title bars) and on empty input',()=>{
 const frames=Array.from({length:29},(_,i)=>({id:'f'+i,width:390,height:820,group:i<10?'A':i<20?'B':''}));const L=tileLayout({frames,columns:8});
 const got=framesInView(L.boxes,{scale:.5,panX:28,panY:28},1440,864,.5);assert(got.length>0&&got.length<29);assert(got.includes(0));
 assert.deepStrictEqual(framesInView([],{scale:1,panX:0,panY:0},100,100,.5),[]);assert.deepStrictEqual(framesInView(undefined,{scale:1,panX:0,panY:0},100,100,.5),[]);
});
t('focusFrameCamera centres one tile box and does not choose a scale',()=>{
 const box={x:100,y:200,w:390,h:888},cam=focusFrameCamera(box,.5,1440,800);
 close(cam.panX,1440/2-(100+195)*.5,'panX');close(cam.panY,800/2-(200+444)*.5,'panY');
 assert.strictEqual(cam.scale,undefined);
 const L=tileLayout({frames:[{id:'x',width:390,height:820}],columns:3});
 const real=focusFrameCamera(L.boxes[0],.5,1000,700);
 close(real.panX,1000/2-(L.boxes[0].x+L.boxes[0].w/2)*.5,'layout panX');
 close(real.panY,700/2-(L.boxes[0].y+L.boxes[0].h/2)*.5,'layout panY');
});
t('a later frame is a different pan, so the previous frame is not what gets centred',()=>{
 const a=focusFrameCamera({x:12,y:12,w:390,h:888},.5,1440,800);
 const b=focusFrameCamera({x:12,y:12+888+44,w:390,h:888},.5,1440,800);
 assert.strictEqual(a.panX,b.panX);assert.notStrictEqual(a.panY,b.panY);
});
t('no box, a bad scale or an empty viewport returns null so the camera stays put',()=>{
 for(const cam of [focusFrameCamera(null,.5,1440,800),focusFrameCamera(undefined,.5,1440,800),focusFrameCamera({x:0,y:0,w:10,h:10},0,100,100),focusFrameCamera({x:0,y:0,w:10,h:10},-1,100,100),focusFrameCamera({x:0,y:0,w:10,h:10},.5,0,100),focusFrameCamera({x:0,y:0,w:10,h:10},.5,100,-4),focusFrameCamera({x:NaN,y:0,w:10,h:10},.5,100,100),focusFrameCamera({x:0,y:0,w:10},.5,100,100)])assert.strictEqual(cam,null);
});
console.log(`${n} passed, ${fail} failed`);process.exit(fail?1:0);
