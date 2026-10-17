// SPDX-License-Identifier: Apache-2.0
// node tests for the <tile-layout> block of assets/canvas.js (run: node tests/tile_layout.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const m=src.match(/\/\/ <tile-layout>[\s\S]*?\/\/ <\/tile-layout>/);assert(m,'block missing');
const {tileLayout,TILE}=new Function(m[0]+'\n;return{tileLayout,TILE}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const fr=(group,w=390,h=800)=>group===undefined?{width:w,height:h}:{group,width:w,height:h};
const run=(group,count,w,h)=>Array.from({length:count},()=>fr(group,w,h));
// The layout before sections existed: one global grid (kept here as the reference for projects without groups).
function legacy(project){
 const cols=Math.min(project.columns||3,project.frames.length),gapX=40,gapY=44,pad=12;
 const widths=Array(cols).fill(0),rowH=Array(Math.ceil(project.frames.length/cols)).fill(0);
 project.frames.forEach((f,i)=>{widths[i%cols]=Math.max(widths[i%cols],f.width);rowH[Math.floor(i/cols)]=Math.max(rowH[Math.floor(i/cols)],f.height+68)});
 const xs=[pad];for(let c=1;c<cols;c++)xs[c]=xs[c-1]+widths[c-1]+gapX;const ys=[pad];for(let r=1;r<rowH.length;r++)ys[r]=ys[r-1]+rowH[r-1]+gapY;
 return{boxes:project.frames.map((f,i)=>({x:xs[i%cols],y:ys[Math.floor(i/cols)],w:f.width,h:f.height+68})),w:widths.reduce((a,b)=>a+b,0)+(cols-1)*40+24,h:rowH.reduce((a,b)=>a+b,0)+(rowH.length-1)*44+24};
}
// small deterministic generator
let seed=12345;const rnd=k=>{seed=(seed*1103515245+12345)&0x7fffffff;return seed%k};

t('no group at all: identical to the old global grid (random projects)',()=>{
 for(let i=0;i<200;i++){
  const frames=Array.from({length:1+rnd(30)},()=>fr(undefined,100+rnd(400),200+rnd(900))),p={frames};
  if(rnd(2))p.columns=1+rnd(6);
  if(rnd(4)===0)p.groupColumns={Whatever:2}; // unused names change nothing
  const a=tileLayout(p),b=legacy(p);
  assert.deepStrictEqual(a.boxes,b.boxes);assert.strictEqual(a.w,b.w);assert.strictEqual(a.h,b.h);
  assert.strictEqual(a.sections.length,1);assert.strictEqual(a.sections[0].bar,null);
 }
});
t('blank, whitespace and non-string groups count as no group',()=>{
 const p={frames:[fr(''),fr('  '),{width:390,height:800,group:null},{width:390,height:800,group:7}]};
 const a=tileLayout(p);assert.strictEqual(a.sections.length,1);assert.strictEqual(a.sections[0].bar,null);assert.deepStrictEqual(a.boxes,legacy(p).boxes);
});
t('default columns is 3; columns is capped by the frame count',()=>{
 assert.strictEqual(tileLayout({frames:run(undefined,7)}).sections[0].cols,3);
 assert.strictEqual(tileLayout({frames:run(undefined,2),columns:5}).sections[0].cols,2);
 assert.strictEqual(tileLayout({frames:run(undefined,7),columns:'x'}).sections[0].cols,3);
});
t('sections are consecutive runs in frame order; each starts on a new row',()=>{
 const frames=[...run('A',4),...run('B',3),...run(undefined,2),...run('A',2)];
 const L=tileLayout({frames});
 assert.deepStrictEqual(L.sections.map(s=>[s.group,s.start,s.count]),[['A',0,4],['B',4,3],['',7,2],['A',9,2]]);
 assert.strictEqual(L.boxes.length,11);
 L.sections.forEach((s,i)=>{if(!i)return;const prev=L.sections[i-1];assert(s.y>=prev.y+prev.h+TILE.sectionGap-0.001,'section '+i+' overlaps the previous one')});
 // the second "A" is its own section (runs are not merged)
 assert.strictEqual(L.sections[3].bar.y,L.sections[3].y);
});
t('grouped section: bar spans the section width and sits above the grid',()=>{
 const L=tileLayout({frames:run('A',5,390,800)}),s=L.sections[0];
 assert.deepStrictEqual(s.bar,{x:12,y:12,w:3*390+2*40,h:TILE.barH});assert.strictEqual(s.w,s.bar.w);
 assert.strictEqual(L.boxes[0].y,12+TILE.barH+TILE.barGap);
 assert.strictEqual(L.boxes[3].y,L.boxes[0].y+868+44);
});
t('ungrouped section has no bar and no bar offset',()=>{
 const L=tileLayout({frames:[...run('A',1),...run(undefined,1)]});
 assert.strictEqual(L.sections[1].bar,null);assert.strictEqual(L.boxes[1].y,L.sections[1].y);
});
t('columns and column widths are per section (widest frame of that section only)',()=>{
 const frames=[fr('A',390),fr('A',600),fr('A',390),fr('B',390),fr('B',390),fr('B',390),fr('B',390)];
 const L=tileLayout({frames,columns:2});
 // A: 2 columns of widths [390,390] and [600] -> col0 = max(390,390)=390, col1 = 600
 assert.strictEqual(L.sections[0].cols,2);assert.strictEqual(L.boxes[1].x,12+390+40);
 // B: all 390 in two columns; unaffected by the 600 wide frame in A
 assert.strictEqual(L.boxes[4].x,12+390+40);assert.strictEqual(L.sections[1].w,390*2+40);
 assert.strictEqual(L.sections[0].w,390+40+600);
 assert.strictEqual(L.w,Math.max(390+40+600,390*2+40)+24);
});
t('groupColumns overrides columns for that group only, capped by the section size',()=>{
 const frames=[...run('A',6),...run('B',6),...run('C',2)];
 const L=tileLayout({frames,columns:3,groupColumns:{A:2,B:10,C:4}});
 assert.deepStrictEqual(L.sections.map(s=>s.cols),[2,6,2]);
 assert.deepStrictEqual(L.sections.map(s=>s.rows),[3,1,1]);
});
t('invalid groupColumns entries fall back to columns; inherited names are ignored',()=>{
 const frames=[...run('A',6),...run('B',6),...run('toString',6),...run('__proto__',6)];
 const gc=JSON.parse('{"A":0,"B":"2","toString":1.5,"__proto__":2}');
 const L=tileLayout({frames,columns:4,groupColumns:gc});
 assert.deepStrictEqual(L.sections.map(s=>s.cols),[4,4,4,2]);
 assert.strictEqual(tileLayout({frames:run('A',6),columns:4,groupColumns:[2,2]}).sections[0].cols,4);
 assert.strictEqual(tileLayout({frames:run('constructor',6),groupColumns:{}}).sections[0].cols,3);
});
t('board size: widest section and bottom of the last section, plus padding',()=>{
 const L=tileLayout({frames:[...run('A',3,390,800),...run('B',1,500,300)]});
 const a=L.sections[0],b=L.sections[1];
 assert.strictEqual(L.w,Math.max(a.w,b.w)+24);assert.strictEqual(L.h,b.y+b.h+12);
 assert.strictEqual(b.y,a.y+a.h+TILE.sectionGap);
});
t('boxes stay inside the board and frames never overlap',()=>{
 for(let i=0;i<100;i++){
  const groups=['A','B','C',undefined],frames=[];for(let k=0;k<1+rnd(25);k++)frames.push(fr(groups[rnd(4)],100+rnd(400),200+rnd(700)));
  const gc={A:1+rnd(4),B:1+rnd(4)},L=tileLayout({frames,columns:1+rnd(5),groupColumns:gc});
  L.boxes.forEach((b,x)=>{assert(b.x>=0&&b.y>=0&&b.x+b.w<=L.w&&b.y+b.h<=L.h,'outside board '+x);
   for(let y=x+1;y<L.boxes.length;y++){const c=L.boxes[y];assert(b.x+b.w<=c.x||c.x+c.w<=b.x||b.y+b.h<=c.y||c.y+c.h<=b.y,'overlap '+x+','+y)}});
  L.sections.forEach(s=>{if(!s.bar)return;assert(s.bar.y+s.bar.h<=L.boxes[s.start].y);assert.strictEqual(s.bar.w,s.w)});
 }
});
t('does not touch or reorder the input',()=>{
 const frames=[...run('A',2),...run('B',2)],copy=JSON.stringify(frames);tileLayout({frames,groupColumns:{A:1}});assert.strictEqual(JSON.stringify(frames),copy);
});
console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
