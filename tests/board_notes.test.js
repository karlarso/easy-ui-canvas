// SPDX-License-Identifier: Apache-2.0
// node tests for the <board-notes> block of assets/canvas.js (run: node tests/board_notes.test.js)
const fs=require('fs'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'..','assets','canvas.js'),'utf8');
const tile=src.match(/\/\/ <tile-layout>[\s\S]*?\/\/ <\/tile-layout>/),notes=src.match(/\/\/ <board-notes>[\s\S]*?\/\/ <\/board-notes>/);assert(tile&&notes,'block missing');
const {tileLayout,boardNotes,noteOrigin,groupTitleIds,NOTE}=new Function(tile[0]+'\n'+notes[0]+'\n;return{tileLayout,boardNotes,noteOrigin,groupTitleIds,NOTE}')();
let n=0,fail=0;const t=(name,fn)=>{try{fn();n++;console.log('PASS',name)}catch(e){fail++;console.log('FAIL',name,e.message)}};
const frames=[{id:'a',width:390,height:700},{id:'b',width:390,height:700},{id:'c',width:390,height:700}];

t('a project without notes has none (missing, null, not an array)',()=>{
 assert.deepStrictEqual(boardNotes({frames}),[]);assert.deepStrictEqual(boardNotes({frames,notes:null}),[]);assert.deepStrictEqual(boardNotes({frames,notes:{id:'x'}}),[]);assert.deepStrictEqual(boardNotes(null),[]);
});
t('a well-formed note keeps its fields; width defaults to 320; title and anchor default to empty',()=>{
 const [a]=boardNotes({notes:[{id:'n1',path:'frames/n1.html',x:10,y:20}]});
 assert.deepStrictEqual(a,{id:'n1',path:'frames/n1.html',x:10,y:20,width:NOTE.width,title:'',anchor:''});
 assert.strictEqual(NOTE.width,320);
 const [b]=boardNotes({notes:[{id:'n2',path:'frames/n2.html',x:0,y:0,width:200,title:'T',anchor:'a'}]});
 assert.deepStrictEqual([b.width,b.title,b.anchor],[200,'T','a']);
});
t('malformed entries are skipped, never thrown on (hand-edited snapshots)',()=>{
 const bad=[null,7,'x',{},{id:'',path:'p',x:0,y:0},{id:'a b',path:'p',x:0,y:0},{id:'ok',path:5,x:0,y:0},{id:'ok',path:'p',x:-1,y:0},{id:'ok',path:'p',x:0,y:NOTE.max+1},
  {id:'ok',path:'p',x:'1',y:0},{id:'ok',path:'p',x:NaN,y:0},{id:'ok',path:'p',x:0,y:0,width:39},{id:'ok',path:'p',x:0,y:0,width:4001},{id:'ok',path:'p',x:0,y:0,width:1.5},{id:'ok',path:'p',x:0,y:0,width:'9'}];
 assert.deepStrictEqual(boardNotes({notes:bad}),[]);
 assert.strictEqual(boardNotes({notes:[{id:'ok',path:'p',x:0,y:0},...bad]}).length,1);
});
t('duplicate ids: the first one wins',()=>{
 const r=boardNotes({notes:[{id:'d',path:'p1',x:1,y:1},{id:'d',path:'p2',x:2,y:2}]});assert.strictEqual(r.length,1);assert.strictEqual(r[0].path,'p1');
});
t('without anchor x/y are board coordinates',()=>{
 const p={frames,notes:[]},L=tileLayout(p);
 assert.deepStrictEqual(noteOrigin({x:900,y:5,anchor:''},p,L),{x:900,y:5});
});
t('with an anchor x/y are measured from that frame box (title included)',()=>{
 const p={frames},L=tileLayout(p);
 for(let i=0;i<frames.length;i++)assert.deepStrictEqual(noteOrigin({x:7,y:9,anchor:frames[i].id},p,L),{x:L.boxes[i].x+7,y:L.boxes[i].y+9});
});
t('an unknown anchor falls back to board coordinates',()=>{
 const p={frames},L=tileLayout(p);assert.deepStrictEqual(noteOrigin({x:7,y:9,anchor:'zzz'},p,L),{x:7,y:9});
});
t('notes never change the tile layout (frames stay where they were)',()=>{
 const a=tileLayout({frames}),b=tileLayout({frames,notes:[{id:'n',path:'p',x:0,y:0}]});assert.deepStrictEqual(a,b);
});
// Group title bars: the same table as test_group_title_targets_follow_the_sections in tests/test_board_comments.py (scripts/canvas.py must give the same ids).
const gf=groups=>groups.map((g,i)=>({id:'g'+i,width:390,height:600,...(g===undefined?{}:{group:g})}));
const barIds=groups=>{const L=tileLayout({frames:gf(groups)});return groupTitleIds(L.sections).filter(Boolean)};
t('group title ids: one per grouped section, none for blank or non-string groups',()=>{
 assert.deepStrictEqual(barIds([undefined,undefined]),[]);
 assert.deepStrictEqual(barIds(['','  ',undefined,5,['x'],{}]),[]);
 assert.deepStrictEqual(barIds(['A','A','A']),['group~A~title']);
});
t('group title ids: a group that comes back is another section (n = 2, 3, ...)',()=>{
 assert.deepStrictEqual(barIds(['A','B','A']),['group~A~title','group~B~title','group~A~2~title']);
 assert.deepStrictEqual(barIds(['A',undefined,'A','','A']),['group~A~title','group~A~2~title','group~A~3~title']);
});
t('group title ids: names are exact, \'~\' and \'%\' are escaped so ids never collide',()=>{
 assert.deepStrictEqual(barIds([' A','A']),['group~ A~title','group~A~title']);
 assert.deepStrictEqual(barIds(['a','a~2','a','a~2']),['group~a~title','group~a%7E2~title','group~a~2~title','group~a%7E2~2~title']);
 assert.deepStrictEqual(barIds(['100%','100%25']),['group~100%25~title','group~100%2525~title']);
 const ids=barIds(['a','a~2','a','a~2','a%7E2']);assert.strictEqual(new Set(ids).size,ids.length);
});
t('group title ids: positions match the sections (index by section, \'\' without a bar) and do not change the layout',()=>{
 const L=tileLayout({frames:gf([undefined,'A','A','B'])}),ids=groupTitleIds(L.sections);
 assert.deepStrictEqual(ids,['','group~A~title','group~B~title']);
 assert.deepStrictEqual(L.sections.map(s=>!!s.bar),ids.map(Boolean));
 assert.deepStrictEqual(groupTitleIds([]),[]);
});
console.log(n+' passed, '+fail+' failed');process.exit(fail?1:0);
